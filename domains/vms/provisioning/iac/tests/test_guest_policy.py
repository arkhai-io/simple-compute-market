"""The VM guest network policy host preparation installs.

The rules template is rendered with Jinja2 as Ansible renders it, block
trimming included, and its chains read rule by rule. The installer,
`files/guest_policy.sh`, runs as its real shell against the stateful fake
`iptables` and `iptables-restore` of `host_fakes`, over chains already holding
the jumps UFW and libvirt install, so the order it leaves behind is read back
from the fake's rules. The removal of per-port guest rules from a host runs as
its real shell the same way. Where ansible-core 2.17 to 2.19 is
installed, as in the native Ansible gate, the preconditions run through
ansible-playbook against fake `virsh`, `virt-install` and `ebtables`, so
Ansible's own version test decides what a host lacks. The rest is the role's
structure: what host preparation refuses before it writes, what keeps the
policy first, and the order of the includes.

None of this runs against a real host's netfilter, libvirt or UFW: whether the
rules stop a guest's packets is the real-host proof's.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import jinja2
import yaml

from host_fakes import FakeHost
from shell_harness import fake_binaries


ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "ansible/roles/vm-setup"
TASKS = SETUP / "tasks"
GUEST_POLICY = TASKS / "guest-policy.yml"
SECURITY = TASKS / "security-hardening.yml"
MAIN = TASKS / "main.yml"
RULES_TEMPLATE = SETUP / "templates/guest-policy.rules.j2"
INSTALLER = SETUP / "files/guest_policy.sh"
UNIT = SETUP / "files/arkhai-guest-policy.service"

GUEST_IN = [
    "-A ARKHAI-GUEST-IN -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT",
    "-A ARKHAI-GUEST-IN -p udp --dport 67 -j ACCEPT",
    "-A ARKHAI-GUEST-IN -d 192.168.122.1 -p udp --dport 53 -j ACCEPT",
    "-A ARKHAI-GUEST-IN -d 192.168.122.1 -p tcp --dport 53 -j ACCEPT",
    "-A ARKHAI-GUEST-IN -m comment --comment arkhai-guest-isolation -j DROP",
]
HAIRPIN = "-A ARKHAI-GUEST-FWD -o virbr0 -m comment --comment arkhai-guest-isolation -j DROP"
FORWARDED_REPLIES = "-A ARKHAI-GUEST-FWD -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT"
PRIVATE_DROPS = [
    "-A ARKHAI-GUEST-FWD -d 169.254.0.0/16 -j DROP",
    "-A ARKHAI-GUEST-FWD -d 10.0.0.0/8 -j DROP",
    "-A ARKHAI-GUEST-FWD -d 172.16.0.0/12 -j DROP",
    "-A ARKHAI-GUEST-FWD -d 192.168.0.0/16 -j DROP",
    "-A ARKHAI-GUEST-FWD -d 100.64.0.0/10 -j DROP",
]
INPUT_JUMP = "-A INPUT -i virbr0 -j ARKHAI-GUEST-IN"
FORWARD_JUMP = "-A FORWARD -i virbr0 -j ARKHAI-GUEST-FWD"

# The jumps a prepared host's built-in chains already hold: UFW's on INPUT and
# libvirt's on both, which accept a guest's packets once reached.
UFW_AND_LIBVIRT = [
    "-A INPUT -j LIBVIRT_INP",
    "-A INPUT -j ufw-before-logging-input",
    "-A INPUT -j ufw-before-input",
    "-A FORWARD -j LIBVIRT_FWX",
    "-A FORWARD -j LIBVIRT_FWI",
    "-A FORWARD -j LIBVIRT_FWO",
    "-A FORWARD -j ufw-before-forward",
]


def _render(destinations: list[str]) -> str:
    environment = jinja2.Environment(
        trim_blocks=True, keep_trailing_newline=True, undefined=jinja2.StrictUndefined
    )
    template = environment.from_string(RULES_TEMPLATE.read_text(encoding="utf-8"))
    return template.render(guest_allowed_private_destinations=destinations)


def _chain(rules: list[str], chain: str) -> list[str]:
    return [rule for rule in rules if shlex.split(rule)[1] == chain]


def _tasks(path: Path) -> list[dict]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _run_sh(command: str, host: FakeHost, scripts: dict[str, str]) -> subprocess.CompletedProcess:
    """COMMAND run by `sh`, as the shell module and the unit run it, with the
    host's fake commands first on PATH."""
    with fake_binaries(scripts) as bin_dir:
        env = host.environment({"PATH": f"{bin_dir}:{os.environ['PATH']}"})
        return subprocess.run(
            ["sh", "-c", command], capture_output=True, text=True, env=env, timeout=30
        )


class TestTheRenderedRules(unittest.TestCase):
    """The chains rule by rule, in order."""

    def _lines(self, destinations: list[str]) -> list[str]:
        return [
            line for line in _render(destinations).splitlines()
            if line and not line.startswith("#")
        ]

    def test_the_input_chain_admits_only_dhcp_and_dns_from_a_guest(self) -> None:
        lines = self._lines([])

        self.assertEqual(lines[0], ":ARKHAI-GUEST-IN - [0:0]")
        self.assertEqual(_chain(lines[1:], "ARKHAI-GUEST-IN"), GUEST_IN)

    def test_the_forward_chain_drops_the_hairpin_first_and_private_ranges_last(self) -> None:
        lines = self._lines([])

        self.assertIn(":ARKHAI-GUEST-FWD - [0:0]", lines)
        self.assertEqual(
            _chain([line for line in lines if not line.startswith(":")], "ARKHAI-GUEST-FWD"),
            [HAIRPIN, FORWARDED_REPLIES, *PRIVATE_DROPS],
        )

    def test_each_listed_destination_is_accepted_ahead_of_the_drops(self) -> None:
        lines = self._lines(["10.0.5.20", "192.168.40.0/24"])

        self.assertEqual(
            _chain([line for line in lines if not line.startswith(":")], "ARKHAI-GUEST-FWD"),
            [
                HAIRPIN,
                FORWARDED_REPLIES,
                "-A ARKHAI-GUEST-FWD -d 10.0.5.20 -j ACCEPT",
                "-A ARKHAI-GUEST-FWD -d 192.168.40.0/24 -j ACCEPT",
                *PRIVATE_DROPS,
            ],
        )

    def test_the_list_is_empty_by_default(self) -> None:
        defaults = yaml.safe_load((SETUP / "defaults/main.yml").read_text(encoding="utf-8"))
        self.assertEqual(defaults["guest_allowed_private_destinations"], [])


class TestTheInstaller(unittest.TestCase):
    """The installer leaves its chains filled and each jump first, once."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="guest-policy-")
        self.root = Path(self._tmp.name)
        self.host = FakeHost(self.root / "host")
        self.rules = self.root / "guest-policy.rules"
        self.rules.write_text(_render(["10.0.5.20"]), encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _install(self, rules: Path | None = None) -> subprocess.CompletedProcess:
        command = shlex.join(["sh", str(INSTALLER), str(rules or self.rules)])
        return _run_sh(command, self.host, self.host.binaries())

    def test_the_script_parses(self) -> None:
        result = subprocess.run(["sh", "-n", str(INSTALLER)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_the_jumps_lead_ufw_and_libvirt_and_the_chains_hold_the_rules(self) -> None:
        self.host.set_rules("filter", UFW_AND_LIBVIRT)

        result = self._install()

        self.assertEqual(result.returncode, 0, result.stderr)
        rules = self.host.rules("filter")
        self.assertEqual(_chain(rules, "INPUT")[0], INPUT_JUMP)
        self.assertEqual(_chain(rules, "FORWARD")[0], FORWARD_JUMP)
        self.assertEqual(_chain(rules, "INPUT")[1:], _chain(UFW_AND_LIBVIRT, "INPUT"))
        self.assertEqual(_chain(rules, "FORWARD")[1:], _chain(UFW_AND_LIBVIRT, "FORWARD"))
        self.assertEqual(_chain(rules, "ARKHAI-GUEST-IN"), GUEST_IN)
        self.assertEqual(
            _chain(rules, "ARKHAI-GUEST-FWD"),
            [HAIRPIN, FORWARDED_REPLIES, "-A ARKHAI-GUEST-FWD -d 10.0.5.20 -j ACCEPT",
             *PRIVATE_DROPS],
        )

    def test_after_libvirt_and_ufw_re_add_theirs_ahead_the_jumps_are_first_again(self) -> None:
        """libvirt's restart and UFW's reload insert their jumps at the top."""
        self.host.set_rules("filter", UFW_AND_LIBVIRT)
        self.assertEqual(self._install().returncode, 0)
        rules = self.host.rules("filter")
        self.host.set_rules("filter", [
            "-A INPUT -j ufw-before-input", "-A FORWARD -j LIBVIRT_FWO", *rules,
        ])

        result = self._install()

        self.assertEqual(result.returncode, 0, result.stderr)
        rules = self.host.rules("filter")
        self.assertEqual(_chain(rules, "INPUT")[0], INPUT_JUMP)
        self.assertEqual(_chain(rules, "FORWARD")[0], FORWARD_JUMP)
        self.assertEqual(rules.count(INPUT_JUMP), 1)
        self.assertEqual(rules.count(FORWARD_JUMP), 1)

    def test_a_second_run_changes_nothing(self) -> None:
        self.host.set_rules("filter", UFW_AND_LIBVIRT)
        self.assertEqual(self._install().returncode, 0)
        first = self.host.rules("filter")

        self.assertEqual(self._install().returncode, 0)

        self.assertEqual(self.host.rules("filter"), first)

    def test_a_refilled_chain_holds_the_rules_rendered_now(self) -> None:
        """A seller's list changed between preparations: the chain is refilled
        rather than appended to."""
        self.assertEqual(self._install().returncode, 0)
        self.rules.write_text(_render([]), encoding="utf-8")

        self.assertEqual(self._install().returncode, 0)

        self.assertEqual(
            _chain(self.host.rules("filter"), "ARKHAI-GUEST-FWD"),
            [HAIRPIN, FORWARDED_REPLIES, *PRIVATE_DROPS],
        )

    def test_without_its_rules_it_fails_naming_them_and_touches_nothing(self) -> None:
        self.host.set_rules("filter", UFW_AND_LIBVIRT)

        result = self._install(self.root / "absent.rules")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("absent.rules", result.stderr)
        self.assertEqual(self.host.rules("filter"), UFW_AND_LIBVIRT)
        self.assertFalse(any(c.startswith("iptables") for c in self.host.calls()))


class TestHostPreparationInstallsThePolicy(unittest.TestCase):
    """What host preparation refuses, writes, and runs to keep the policy first."""

    def _modules(self, task: dict) -> set[str]:
        return set(task) - {
            "name", "register", "changed_when", "failed_when", "when", "tags", "vars",
        }

    def test_a_host_that_cannot_isolate_its_guests_is_refused_before_the_policy_writes_anything(self) -> None:
        tasks = _tasks(GUEST_POLICY)
        refusal = next(i for i, t in enumerate(tasks) if "fail" in t)
        self.assertEqual(tasks[refusal]["when"], "guest_policy_missing | length > 0")
        for task in tasks[:refusal]:
            self.assertTrue(
                self._modules(task) <= {"shell", "command", "set_fact"}, task["name"]
            )
            if "shell" in task or "command" in task:
                self.assertIs(task["changed_when"], False, task["name"])
                self.assertIs(task["failed_when"], False, task["name"])
        missing = tasks[refusal - 1]["set_fact"]["guest_policy_missing"]
        for requirement in (
            "version('6.1.0', '>=')", "guest_policy_nwfilter.rc == 0",
            "version('3.0.0', '>=')", "guest_policy_ebtables.rc == 0",
        ):
            self.assertIn(requirement, missing)
        reads = " ".join(str(t.get("shell") or t.get("command")) for t in tasks[:refusal])
        for read in ("virsh version --daemon", "virsh nwfilter-dumpxml clean-traffic",
                     "virt-install --version", "command -v ebtables"):
            self.assertIn(read, reads)

    def test_the_rules_installer_and_unit_are_written_where_each_reads_the_other(self) -> None:
        tasks = {t["name"]: t for t in _tasks(GUEST_POLICY)}
        rendered = tasks["Render the guest policy's rules"]["template"]
        installer = tasks["Install the guest policy's installer"]["copy"]
        unit = tasks["Install the unit that keeps the guest policy first at boot and after libvirt starts"]["copy"]
        self.assertEqual(rendered["src"], RULES_TEMPLATE.name)
        self.assertEqual(rendered["dest"], "/etc/arkhai/guest-policy.rules")
        self.assertIn(
            '"${1:-/etc/arkhai/guest-policy.rules}"', INSTALLER.read_text(encoding="utf-8")
        )
        self.assertEqual((installer["src"], installer["mode"]), (INSTALLER.name, "0755"))
        self.assertEqual(unit["src"], UNIT.name)
        self.assertIn(f"ExecStart={installer['dest']}\n", UNIT.read_text(encoding="utf-8"))
        started = tasks["Install the guest policy now and at every boot and libvirt start"]["systemd"]
        self.assertEqual(
            (started["name"], started["enabled"], started["state"]),
            ("arkhai-guest-policy.service", True, "restarted"),
        )

    def test_the_unit_runs_after_libvirt_and_ufw_and_again_whenever_libvirt_starts(self) -> None:
        directives = {}
        for line in UNIT.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                directives[key] = value.split()
        self.assertTrue({"libvirtd.service", "ufw.service", "iptables-restore.service",
                         "netfilter-persistent.service"} <= set(directives["After"]))
        self.assertEqual(set(directives["WantedBy"]), {"multi-user.target", "libvirtd.service"})
        self.assertEqual(directives["Type"], ["oneshot"])
        # Active once run, it would not run again when libvirtd next started.
        self.assertNotIn("RemainAfterExit", directives)

    def test_ufw_re_runs_the_installer_each_time_it_starts_or_reloads(self) -> None:
        tasks = {t["name"]: t for t in _tasks(GUEST_POLICY)}
        hook = tasks["Re-install the guest policy each time UFW starts or reloads"]["blockinfile"]
        self.assertEqual(hook["path"], "/etc/ufw/after.init")
        self.assertEqual(hook["mode"], "0755")
        self.assertEqual(hook["insertafter"], "^#!")
        self.assertIn('if [ "$1" = start ]; then\n    /usr/local/sbin/arkhai-guest-policy\n',
                      hook["block"])
        created = tasks["Ensure UFW's after.init hook exists"]["copy"]
        self.assertEqual((created["content"], created["force"]), ("#!/bin/sh\n", False))

    def test_the_policy_is_installed_after_libvirt_and_before_hardening_saves_the_rules(self) -> None:
        included = [
            (t.get("include_tasks") or {}).get("file") for t in _tasks(MAIN)
            if isinstance(t.get("include_tasks"), dict)
        ]
        self.assertLess(included.index("kvm-setup.yml"), included.index("guest-policy.yml"))
        self.assertLess(included.index("kvm-network.yml"), included.index("guest-policy.yml"))
        self.assertLess(included.index("guest-policy.yml"), included.index("security-hardening.yml"))
        saved = [t["name"] for t in _tasks(SECURITY)
                 if "iptables-save" in str(t.get("shell", ""))]
        self.assertEqual(saved, ["Save iptables rules persistently"])

    def test_host_preparation_installs_ebtables(self) -> None:
        tasks = {t["name"]: t for t in _tasks(TASKS / "system-packages.yml")}
        line = tasks["Add KVM virtualization packages to script"]["lineinfile"]["line"]
        self.assertIn("ebtables", line.split())


def _ansible() -> tuple[str | None, str]:
    binary = shutil.which("ansible-playbook")
    if binary is None:
        return None, "native tests require ansible-core 2.17 to 2.19"
    version = subprocess.run([binary, "--version"], capture_output=True, text=True, check=False)
    if not re.search(r"core 2\.(1[7-9])\.", version.stdout):
        return None, "native tests require ansible-core 2.17 to 2.19"
    return binary, ""


ANSIBLE_PLAYBOOK, UNAVAILABLE = _ansible()


@unittest.skipIf(ANSIBLE_PLAYBOOK is None, UNAVAILABLE)
class TestThePreconditionsNatively(unittest.TestCase):
    """The shipped preconditions, every task up to the refusal, run by
    ansible-playbook against localhost with fake `virsh`, `virt-install` and
    `ebtables`, so Ansible's own version test decides what is missing."""

    def _run(self, *, libvirt: str, nwfilter: bool, virt_install: str, ebtables: bool):
        tasks = _tasks(GUEST_POLICY)
        refusal = next(i for i, t in enumerate(tasks) if "fail" in t)
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            bin_dir = work / "bin"
            bin_dir.mkdir()
            fakes = {
                "virsh": (
                    "#!/bin/sh\n"
                    f'[ "$*" = "version --daemon" ] && printf \'%s\\n\' '
                    f'"Compiled against library: libvirt {libvirt}" '
                    f'"Running against daemon: {libvirt}" && exit 0\n'
                    f'[ "$*" = "nwfilter-dumpxml clean-traffic" ] && exit {0 if nwfilter else 1}\n'
                    "exit 2\n"
                ),
                "virt-install": f"#!/bin/sh\necho {virt_install}\n",
            }
            if ebtables:
                fakes["ebtables"] = "#!/bin/sh\nexit 0\n"
            for name, content in fakes.items():
                (bin_dir / name).write_text(content, encoding="utf-8")
                (bin_dir / name).chmod(0o755)
            output = work / "missing.json"
            play = [{
                "hosts": "localhost", "connection": "local", "gather_facts": False,
                "environment": {"PATH": f"{bin_dir}:/usr/bin:/bin"},
                "tasks": tasks[:refusal + 1] + [{"name": "Export what is missing", "copy": {
                    "content": "{{ guest_policy_missing | to_json }}", "dest": str(output),
                    "mode": "0600"}}],
            }]
            path = work / "play.yml"
            path.write_text(yaml.safe_dump(play, sort_keys=False), encoding="utf-8")
            environment = {k: v for k, v in os.environ.items() if not k.startswith("ANSIBLE_")}
            environment.update(ANSIBLE_NOCOLOR="true", ANSIBLE_LOG_PATH="/dev/null")
            run = subprocess.run([ANSIBLE_PLAYBOOK, "-i", "localhost,", str(path)], cwd=work,
                                 env=environment, capture_output=True, text=True, timeout=90,
                                 check=False)
            missing = json.loads(output.read_text(encoding="utf-8")) if output.exists() else None
            return run, missing

    def test_a_host_with_everything_isolation_needs_passes(self) -> None:
        run, missing = self._run(libvirt="8.0.0", nwfilter=True, virt_install="4.0.0", ebtables=True)

        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual(missing, [])

    def _refusal(self, run: subprocess.CompletedProcess) -> str:
        """What the refusal says a host lacks, from the failed task's message
        alone, not the task names ansible-playbook also prints."""
        self.assertNotEqual(run.returncode, 0)
        match = re.search(r"It lacks: (.*?)\.\"", run.stdout + run.stderr)
        self.assertIsNotNone(match, run.stdout + run.stderr)
        return match.group(1)

    def test_a_host_lacking_each_is_refused_naming_all_of_them(self) -> None:
        run, missing = self._run(libvirt="6.0.0", nwfilter=False, virt_install="2.2.1", ebtables=False)

        self.assertIsNone(missing)
        refusal = self._refusal(run)
        for named in ("libvirt 6.1 or later", "the daemon reports 6.0.0",
                      "nwfilter driver with its clean-traffic filter",
                      "virt-install 3.0 or later", "found 2.2.1",
                      "ebtables, which the nwfilter driver runs"):
            self.assertIn(named, refusal)

    def test_a_host_lacking_one_is_refused_naming_that_one_alone(self) -> None:
        run, missing = self._run(libvirt="8.0.0", nwfilter=True, virt_install="4.0.0", ebtables=False)

        self.assertIsNone(missing)
        self.assertEqual(self._refusal(run), "ebtables, which the nwfilter driver runs")

    def test_libvirt_6_1_itself_passes(self) -> None:
        run, missing = self._run(libvirt="6.1.0", nwfilter=True, virt_install="3.0.0", ebtables=True)

        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual(missing, [])


@unittest.skipIf(ANSIBLE_PLAYBOOK is None, UNAVAILABLE)
class TestTheListedDestinationsNatively(unittest.TestCase):
    """The role's check of the list, run by ansible-playbook as Ansible
    evaluates its regular expression and tests."""

    def _check(self, destinations) -> subprocess.CompletedProcess:
        (task,) = [t for t in _tasks(MAIN) if "assert" in t
                   and "guest_allowed_private_destinations" in str(t["assert"]["that"])]
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            play = [{"hosts": "localhost", "connection": "local", "gather_facts": False,
                     "tasks": [task]}]
            path = work / "play.yml"
            path.write_text(yaml.safe_dump(play, sort_keys=False), encoding="utf-8")
            environment = {k: v for k, v in os.environ.items() if not k.startswith("ANSIBLE_")}
            environment.update(ANSIBLE_NOCOLOR="true", ANSIBLE_LOG_PATH="/dev/null")
            return subprocess.run(
                [ANSIBLE_PLAYBOOK, "-i", "localhost,", str(path), "--extra-vars",
                 json.dumps({"guest_allowed_private_destinations": destinations})],
                cwd=work, env=environment, capture_output=True, text=True, timeout=90,
                check=False,
            )

    def test_addresses_and_blocks_pass(self) -> None:
        for destinations in ([], ["10.0.5.20", "192.168.40.0/24", "100.64.0.0/10"]):
            with self.subTest(destinations=destinations):
                run = self._check(destinations)
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    def test_anything_else_is_refused_naming_the_variable(self) -> None:
        for destinations in (["10.0.5.20 -j ACCEPT"], ["10.0.5.256"], ["10.0.5.20\n"],
                             ["fd00::1"], "10.0.5.20", {"10.0.5.20": True}):
            with self.subTest(destinations=destinations):
                run = self._check(destinations)
                self.assertNotEqual(run.returncode, 0)
                self.assertIn("must be a list of IPv4 addresses or CIDR blocks", run.stdout)


class TestTheListedDestinationsAreChecked(unittest.TestCase):
    """Each entry is written into a rule, so only an IPv4 address or CIDR block
    passes, before anything on the host changes."""

    def _validation(self) -> dict:
        tasks = _tasks(MAIN)
        (task,) = [t for t in tasks if "assert" in t
                   and "guest_allowed_private_destinations" in str(t["assert"]["that"])]
        self.assertLess(tasks.index(task), next(i for i, t in enumerate(tasks) if "include_tasks" in t))
        self.assertIn("always", task["tags"])
        return task["assert"]

    def _pattern(self) -> re.Pattern:
        (expression,) = [c for c in self._validation()["that"] if "reject('match'" in c]
        return re.compile(re.search(r"reject\('match', '([^']+)'\)", expression).group(1))

    def test_addresses_and_blocks_pass(self) -> None:
        for entry in ("10.0.5.20", "192.168.40.0/24", "100.64.0.0/10", "172.16.0.1/32"):
            with self.subTest(entry=entry):
                self.assertIsNotNone(self._pattern().match(entry))

    def test_anything_else_is_refused(self) -> None:
        for entry in ("10.0.5.20 -j ACCEPT", "10.0.5.256", "10.0.5.0/33", "fd00::1",
                      "mirror.example", "", "10.0.5.20\n-A INPUT -j ACCEPT", "10.0.5.20\n"):
            with self.subTest(entry=entry):
                self.assertIsNone(self._pattern().match(entry))

    def test_a_mapping_or_a_string_is_refused(self) -> None:
        that = self._validation()["that"]
        self.assertIn("guest_allowed_private_destinations is not string", that)
        self.assertIn("guest_allowed_private_destinations is not mapping", that)


# A `ufw` deleting a rule by its specification, as `ufw --force delete <rule>`
# does, from the rules a test stored.
_UFW_BY_SPEC = f"""#!{sys.executable}
import json, os, sys
from pathlib import Path
path = Path(os.environ["FAKE_HOST_STATE"]) / "ufw-specs.json"
rules = json.loads(path.read_text(encoding="utf-8"))
args = sys.argv[1:]
if args[:2] != ["--force", "delete"]:
    sys.exit(2)
spec = " ".join(args[2:])
if spec in rules:
    rules.remove(spec)
    path.write_text(json.dumps(rules), encoding="utf-8")
    print("Rule deleted")
else:
    print("Could not delete non-existent rule")
"""

# Per-port guest rules a host may hold, as `iptables -S` prints them: the
# port-22 drops and logs from the guest subnets and bridges.
REPLACED_RULES = [
    "-A INPUT -s 192.168.122.0/24 -p tcp -m tcp --dport 22 -j LOG --log-prefix \"BLOCKED-VM-SSH: \"",
    "-A INPUT -i br0 -p tcp -m tcp --dport 22 -j LOG --log-prefix \"BLOCKED-BRIDGE-SSH: \"",
    "-A INPUT -i br0 -p tcp -m tcp --dport 22 -j DROP",
    "-A INPUT -i virbr0 -p tcp -m tcp --dport 22 -j DROP",
    "-A INPUT -i virbr+ -p tcp -m tcp --dport 22 -j DROP",
    "-A INPUT -s 192.168.0.0/16 -p tcp -m tcp --dport 22 -j DROP",
    "-A INPUT -s 192.168.122.0/24 -p tcp -m tcp --dport 22 -j DROP",
]
REPLACED_UFW = [
    "deny from 192.168.122.0/24 to any port 22",
    "deny from 192.168.100.0/16 to any port 22",
    "allow in on virbr0 from 192.168.122.0/24",
]


class TestNoPerPortGuestRuleRemains(unittest.TestCase):
    """No per-port guest rule is installed, a host holding one has it removed,
    and nothing accepts all of a guest's traffic to its host."""

    REMOVAL = "Remove per-port guest rules from the host"

    def _directives(self) -> str:
        return "\n".join(
            line for line in SECURITY.read_text(encoding="utf-8").splitlines()
            if not line.lstrip().startswith("#")
        )

    def test_hardening_installs_none_of_them(self) -> None:
        tasks = _tasks(SECURITY)
        writes = " ".join(
            str(t.get("shell", "")) for t in tasks if t["name"] != self.REMOVAL
        )
        for removed in ("ufw --force allow in on virbr0", "ufw --force deny",
                        "iptables -I INPUT", "iptables -A INPUT", "vm-network-isolation"):
            self.assertNotIn(removed, writes)
        for task in tasks:
            for module in ("copy", "systemd", "template", "file"):
                spec = task.get(module) or {}
                self.assertNotIn("vm-network-isolation", str(spec), task["name"])
        self.assertIn("ufw --force allow out on virbr0 to 192.168.122.0/24", writes)

    def test_a_host_holding_them_is_left_with_the_policy_and_its_operators_rules(self) -> None:
        (task,) = [t for t in _tasks(SECURITY) if t["name"] == self.REMOVAL]
        with tempfile.TemporaryDirectory(prefix="replaced-rules-") as directory:
            host = FakeHost(Path(directory) / "host")
            # An operator's own: a drop from elsewhere, and port-22 accepts from
            # the forms a removed rule takes, a bridged uplink and a LAN.
            kept = [INPUT_JUMP, "-A INPUT -s 203.0.113.0/24 -p tcp -m tcp --dport 22 -j DROP",
                    "-A INPUT -p tcp -m tcp --dport 22 -j ACCEPT",
                    "-A INPUT -i br0 -p tcp -m tcp --dport 22 -j ACCEPT",
                    "-A INPUT -s 192.168.0.0/16 -p tcp -m tcp --dport 22 -j ACCEPT",
                    "-A INPUT -i virbr0 -p tcp -m tcp --dport 22 -j ACCEPT"]
            host.set_rules("filter", [kept[0], *REPLACED_RULES, *kept[1:]])
            (host.state / "ufw-specs.json").write_text(
                json.dumps([*REPLACED_UFW, "allow out on virbr0 to 192.168.122.0/24"]),
                encoding="utf-8",
            )

            result = _run_sh(task["shell"], host, {**host.binaries(), "ufw": _UFW_BY_SPEC})

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(host.rules("filter"), kept)
            self.assertEqual(
                json.loads((host.state / "ufw-specs.json").read_text(encoding="utf-8")),
                ["allow out on virbr0 to 192.168.122.0/24"],
            )
            self.assertEqual(result.stdout.count("removed:"), len(REPLACED_RULES) + len(REPLACED_UFW))

    def test_a_host_without_them_reports_no_change(self) -> None:
        (task,) = [t for t in _tasks(SECURITY) if t["name"] == self.REMOVAL]
        self.assertEqual(task["changed_when"], "'removed:' in guest_rules_replaced.stdout")
        with tempfile.TemporaryDirectory(prefix="replaced-rules-") as directory:
            host = FakeHost(Path(directory) / "host")
            host.set_rules("filter", [INPUT_JUMP])
            (host.state / "ufw-specs.json").write_text("[]", encoding="utf-8")

            result = _run_sh(task["shell"], host, {**host.binaries(), "ufw": _UFW_BY_SPEC})

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("removed:", result.stdout)

    def test_the_printed_summaries_name_the_guest_policy_chains(self) -> None:
        for path, name in ((SECURITY, "Display security hardening summary"),
                           (SECURITY, "Display post-installation notes"),
                           (MAIN, "Display post-installation notes")):
            with self.subTest(path=path.name, task=name):
                (task,) = [t for t in _tasks(path) if t.get("name") == name]
                printed = "\n".join(task["debug"]["msg"])
                self.assertIn("ARKHAI-GUEST-IN", printed)
                self.assertIn("ARKHAI-GUEST-FWD", printed)
                for claim in ("isolation service", "BLOCKED-VM-SSH", "BLOCKED-BRIDGE-SSH",
                              "grep 192.168.122"):
                    self.assertNotIn(claim, printed)


if __name__ == "__main__":
    unittest.main()
