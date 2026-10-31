"""A VM teardown removes only what its own guest created.

Behaviour first, through `shell_harness`: the cleanup script a create writes,
vm_remove's teardown of a guest with no such script, and vm_undefine's rule
removal each run as their real shell, with the shared `files/guest_teardown.sh`
included as the role includes it, against `host_fakes`' stateful `iptables`,
`virsh`, and `ufw`. Paths under `/etc`, `/var`, and `/usr/local` are rewritten
into a temporary tree, the way the relay teardown test rewrites `/etc/frp`.

Two guests share a prefix in both name and address (`guest-1` at `192.0.2.1`,
`guest-12` at `192.0.2.12`) and in forwarded port (4000 and 40001), so a match on
a prefix of any of them removes the other guest's effects and fails here.

Then the role's structure: every rule a create adds for a guest carries its
marker, the subnet-wide masquerade carries none, every teardown path includes
the one implementation, and none keeps a prefix match.

None of this runs a playbook against a host; a real partial create's teardown
is the live VM lane's evidence.
"""

from __future__ import annotations

import os
import re
import tempfile
import unittest
from pathlib import Path

import yaml

from host_fakes import FakeHost, quoted
from shell_harness import assert_bash_syntax_valid, fake_binaries, run_bash


ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "ansible/roles/vm-management"
LIBRARY = (ROLE / "files/guest_teardown.sh").read_text(encoding="utf-8")
VM_CREATE = ROLE / "tasks/vm-create.yml"
VM_REMOVE = ROLE / "tasks/vm-remove.yml"
VM_UNDEFINE = ROLE / "tasks/vm-undefine.yml"
VARS = ROLE / "vars/main.yml"

INCLUDE = "{{ lookup('file', 'guest_teardown.sh') }}"

A, A_IP, A_PORT, A_MAC = "guest-1", "192.0.2.1", "4000", "52:54:00:00:00:01"
B, B_IP, B_PORT, B_MAC = "guest-12", "192.0.2.12", "40001", "52:54:00:00:00:12"
SUBNET_MASQUERADE = "-A POSTROUTING -s 192.168.122.0/24 -o eth0 -j MASQUERADE"
MANAGEMENT_SSH = "-A INPUT -p tcp -m tcp --dport 22 -j ACCEPT"


def marker(name: str) -> str:
    return f"arkhai-vm:{name}"


def _task(path: Path, name: str) -> dict:
    for task in yaml.safe_load(path.read_text(encoding="utf-8")):
        if task.get("name") == name:
            return task
    raise AssertionError(f"no task named {name!r} in {path.name}")


def _render(text: str, name: str) -> str:
    """Resolve the Jinja the teardown shell carries, refusing any it does not
    know, so a new template expression fails here rather than reaching bash."""
    values = {
        "lookup('file', 'guest_teardown.sh')": LIBRARY,
        "vm_name": name,
        "vm_guest_rule_marker": marker(name),
        "vm_image_type": "scratch",
        "target_host": "kvm-test",
        "vm_root_ssh_filename": f"{name}_root_ed25519",
        "frp_admin_port | default(7400)": "7400",
    }

    def resolve(match: re.Match) -> str:
        expression = match.group(1).strip()
        if expression not in values:
            raise AssertionError(f"unexpected template expression: {expression}")
        return values[expression]

    return re.sub(r"\{\{(.*?)\}\}", resolve, text, flags=re.S)


def _a_rules() -> dict[str, list[str]]:
    """Guest A's rules: some marked, some written before markers existed."""
    return {
        "nat": [
            quoted(f"-A PREROUTING -p tcp -m tcp --dport {A_PORT} -m comment --comment {marker(A)} -j DNAT --to-destination {A_IP}:22"),
            f"-A POSTROUTING -d {A_IP}/32 -p tcp -m tcp --dport 22 -j MASQUERADE",
        ],
        "filter": [
            quoted(f"-A FORWARD -d {A_IP}/32 -p tcp -m tcp --dport 22 -m comment --comment {marker(A)} -j ACCEPT"),
            f"-A FORWARD -s {A_IP}/32 -p tcp -m tcp --sport 22 -j ACCEPT",
            f"-A INPUT -p tcp -m tcp --dport {A_PORT} -j ACCEPT",
        ],
    }


def _others_rules() -> dict[str, list[str]]:
    """Guest B's rules, marked and not, and the host's own, which stay."""
    return {
        "nat": [
            f"-A PREROUTING -p tcp -m tcp --dport {B_PORT} -j DNAT --to-destination {B_IP}:22",
            quoted(f"-A POSTROUTING -d {B_IP}/32 -p tcp -m tcp --dport 22 -m comment --comment {marker(B)} -j MASQUERADE"),
            SUBNET_MASQUERADE,
        ],
        "filter": [
            f"-A FORWARD -d {B_IP}/32 -p tcp -m tcp --dport 22 -j ACCEPT",
            quoted(f"-A FORWARD -s {B_IP}/32 -p tcp -m tcp --sport 22 -m comment --comment {marker(B)} -j ACCEPT"),
            f"-A INPUT -p tcp -m tcp --dport {B_PORT} -j ACCEPT",
            # Another rule naming A's address, under a comment that is not A's.
            f'-A FORWARD -d {A_IP}/32 -m comment --comment "operator: keep" -j ACCEPT',
            MANAGEMENT_SSH,
        ],
    }


def _proxy_block(name: str, port: int) -> str:
    return (
        f"# BEGIN ANSIBLE MANAGED BLOCK FOR VM {name}\n"
        f'[[proxies]]\nname = "vm-{name}"\nremotePort = {port}\n'
        f"# END ANSIBLE MANAGED BLOCK FOR VM {name}\n"
    )


class _Teardown(unittest.TestCase):
    """A fake host with guest B fully present, and A's effects as a case sets."""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="guest-teardown-"))
        self.host = FakeHost(self.root)
        for directory in ("etc/frp", "var/lib/libvirt/images", "var/lib/libvirt/qemu/nvram",
                          "usr/local/bin", "var/log", "tmp", "home/.ssh"):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        self.images = self.root / "var/lib/libvirt/images"
        self.nvram = self.root / "var/lib/libvirt/qemu/nvram"
        self.config = self.root / "etc/frp/frpc-vms.toml"
        self.b_files = [self.images / f"{B}.qcow2", self.images / f"{B}-init.iso",
                        self.nvram / f"{B}_VARS.fd", self.root / f"home/.ssh/{B}_root_ed25519"]
        for path in self.b_files:
            path.write_text("guest B\n", encoding="utf-8")
        self.b_domain = {"state": "running", "address": B_IP, "mac": B_MAC,
                         "storage": [str(self.images / f"{B}.qcow2")]}
        self.b_reservation = {"mac": B_MAC, "name": B, "ip": B_IP}

    def _host(self, *, a_rules: bool, a_domain: dict | None, a_reservation: bool,
              a_proxy: bool, unmarked_extra: list[str] = ()) -> None:
        rules = _others_rules()
        if a_rules:
            for table, extra in _a_rules().items():
                rules[table] = extra + rules[table]
        rules["nat"] = list(unmarked_extra) + rules["nat"]
        self.host.set_rules("nat", rules["nat"])
        self.host.set_rules("filter", rules["filter"])
        domains = {B: self.b_domain}
        if a_domain is not None:
            domains[A] = a_domain
        hosts = [self.b_reservation]
        if a_reservation:
            hosts.insert(0, {"mac": A_MAC, "name": A, "ip": A_IP})
        self.host.set_virsh(domains=domains, hosts=hosts)
        self.config.write_text(
            'serverAddr = "203.0.113.9"\n'
            + (_proxy_block(A, 6001) if a_proxy else "")
            + _proxy_block(B, 6012),
            encoding="utf-8",
        )

    def _run(self, script: str, binaries: dict[str, str] | None = None):
        for prefix in ("/etc/frp/", "/var/lib/libvirt/", "/usr/local/bin/", "/var/log/",
                       "/etc/iptables", "/etc/sysconfig", "/tmp/cloudinit_", "find /tmp "):
            rooted = f"find {self.root}/tmp " if prefix == "find /tmp " else f"{self.root}{prefix}"
            script = script.replace(prefix, rooted)
        assert_bash_syntax_valid(script)
        environment = self.host.environment(dict(os.environ, HOME=str(self.root / "home")))
        with fake_binaries(binaries or self.host.binaries()) as fake_bin:
            return run_bash(script, fake_bin_dir=fake_bin, env=environment, timeout=60)

    def assert_others_untouched(self) -> None:
        others = _others_rules()
        self.assertEqual(self.host.rules("nat"), others["nat"])
        self.assertEqual(self.host.rules("filter"), others["filter"])
        state = self.host.virsh()
        self.assertEqual(state["domains"][B], self.b_domain)
        self.assertIn(self.b_reservation, state["hosts"])
        self.assertIn(_proxy_block(B, 6012), self.config.read_text(encoding="utf-8"))
        for path in self.b_files:
            self.assertTrue(path.exists(), path)

    def a_removed(self) -> None:
        state = self.host.virsh()
        self.assertNotIn(A, state["domains"])
        self.assertNotIn(A, [h["name"] for h in state["hosts"]])
        self.assertNotIn(f"FOR VM {A}\n", self.config.read_text(encoding="utf-8"))

    def reloads(self) -> int:
        """How many times the VM tunnel client was asked to reload."""
        return sum(1 for call in self.host.calls()
                   if call.startswith("curl ") and "/api/reload" in call)

    def assert_relay_settled(self) -> None:
        """The VM tunnel client's directory holds its configuration and nothing
        a teardown left behind."""
        self.assertEqual(sorted(p.name for p in self.config.parent.iterdir()),
                         [self.config.name])


class _ReloadFailures:
    """The VM tunnel client refusing or not answering the reload that applies a
    guest's proxy removal, then recovering. A teardown fails while the running
    client may still hold the proxy, and a retry reloads before it succeeds,
    though the configuration no longer names the guest."""

    def test_a_refused_reload_fails_and_a_retry_reloads_before_succeeding(self) -> None:
        self._failing_then_recovering([22])

    def test_an_unreachable_client_fails_every_retry_until_a_reload_succeeds(self) -> None:
        self._failing_then_recovering([7, 22])


class TheCleanupScriptACreateWrites(_ReloadFailures, _Teardown):
    """The whole script, as a create renders it for guest A."""

    def _script(self) -> str:
        content = _task(VM_CREATE, "Create VM cleanup script on target host")["copy"]["content"]
        return _render(content, A)

    def _failing_then_recovering(self, failures: list[int]) -> None:
        self._host(a_rules=True, a_proxy=True, a_reservation=True,
                   a_domain={"state": "running", "address": A_IP, "mac": A_MAC,
                             "storage": [str(self.images / f"{A}.qcow2")]})
        (self.images / f"{A}.qcow2").write_text("guest A\n", encoding="utf-8")
        # The script as the create installed it: a successful run removes it.
        installed = self.root / f"usr/local/bin/cleanup_vm_{A}.sh"
        installed.write_text(self._script(), encoding="utf-8")
        self.host.set_curl_exits(failures)

        for attempt in range(1, len(failures) + 1):
            result = self._run(self._script())

            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertEqual(self.reloads(), attempt)
            self.assertIn("STEP_STATUS|remove_relay_proxy|failed", result.stdout)
            self.assertTrue(installed.exists(), "the script is kept for the retry")
            self.assertIn(A, self.host.virsh()["domains"])
            self.assertIn(_proxy_block(B, 6012), self.config.read_text(encoding="utf-8"))
            self.assertEqual(self.host.virsh()["domains"][B], self.b_domain)

        result = self._run(self._script())

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.reloads(), len(failures) + 1)
        self.assertIn("STEP_STATUS|remove_relay_proxy|success", result.stdout)
        self.a_removed()
        self.assert_others_untouched()
        self.assertFalse(installed.exists())
        self.assert_relay_settled()

    def test_a_host_with_no_vm_tunnel_client_is_torn_down_without_a_reload(self) -> None:
        """A direct-forwarding host has no VM tunnel client to reload."""
        self._host(a_rules=True, a_proxy=False, a_reservation=True,
                   a_domain={"state": "running", "address": A_IP, "mac": A_MAC})
        self.config.unlink()

        result = self._run(self._script())

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("STEP_STATUS|remove_relay_proxy|skipped", result.stdout)
        self.assertEqual(self.reloads(), 0)
        self.assertNotIn(A, self.host.virsh()["domains"])

    def test_it_removes_only_the_first_guests_rules_files_proxy_and_lease(self) -> None:
        self._host(a_rules=True, a_proxy=True, a_reservation=True,
                   a_domain={"state": "running", "address": A_IP, "mac": A_MAC,
                             "storage": [str(self.images / f"{A}.qcow2")]})
        for path in (self.images / f"{A}.qcow2", self.images / f"{A}-init.iso"):
            path.write_text("guest A\n", encoding="utf-8")
        self.host.set_ufw(active=True, rules=[
            {"to": f"{A_PORT}/tcp", "comment": marker(A)},
            {"to": f"{A_PORT}/tcp (v6)"},
            {"to": f"{B_PORT}/tcp"},
            {"to": f"{B_PORT}/tcp (v6)", "comment": marker(B)},
            {"to": "22/tcp"},
        ])

        result = self._run(self._script())

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_others_untouched()
        self.a_removed()
        self.assertFalse((self.images / f"{A}.qcow2").exists())
        self.assertFalse((self.images / f"{A}-init.iso").exists())
        self.assertEqual(
            self.host.ufw_rules(),
            [{"to": f"{B_PORT}/tcp"}, {"to": f"{B_PORT}/tcp (v6)", "comment": marker(B)},
             {"to": "22/tcp"}],
        )
        self.assertIn("STEP_STATUS|cleanup_iptables|success", result.stdout)
        self.assertIn("STEP_STATUS|remove_relay_proxy|success", result.stdout)
        self.assertEqual(self.reloads(), 1)
        self.assert_relay_settled()

    def test_a_refused_rule_removal_fails_the_script(self) -> None:
        """A rule the host will not delete is not reported as removed."""
        self._host(a_rules=True, a_proxy=False, a_reservation=True,
                   a_domain={"state": "running", "address": A_IP, "mac": A_MAC})
        refusing = dict(self.host.binaries())
        refusing["iptables"] = refusing["iptables"].replace(
            'if op == "-D":', 'if op == "-D":\n    sys.exit(1)'
        )
        result = self._run(self._script(), refusing)

        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("STEP_STATUS|cleanup_iptables|success", result.stdout)
        self.assertIn(A, self.host.virsh()["domains"])


class ARemoveWithNoCleanupScript(_ReloadFailures, _Teardown):
    """vm_remove's branch for a guest whose create wrote no cleanup script."""

    def _script(self) -> str:
        task = _task(VM_REMOVE, "Remove what the guest left without a cleanup script")
        return _render(task["shell"], A)

    def _failing_then_recovering(self, failures: list[int]) -> None:
        self._host(a_rules=True, a_proxy=True, a_reservation=True,
                   a_domain={"state": "shut off", "mac": A_MAC,
                             "storage": [str(self.images / f"{A}.qcow2")]})
        self.host.set_curl_exits(failures)

        for attempt in range(1, len(failures) + 1):
            result = self._run(self._script())

            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertEqual(self.reloads(), attempt)
            self.assertNotIn("GUEST_PRESENT=", result.stdout)
            self.assertIn(_proxy_block(B, 6012), self.config.read_text(encoding="utf-8"))
            self.assertEqual(self.host.virsh()["domains"][B], self.b_domain)

        result = self._run(self._script())

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.reloads(), len(failures) + 1)
        self.assertIn("GUEST_PRESENT=true", result.stdout)
        self.a_removed()
        self.assert_others_untouched()
        self.assert_relay_settled()

        # Once the reload has applied the removal, nothing of the guest is left.
        result = self._run(self._script())

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("GUEST_PRESENT=false", result.stdout)
        self.assertEqual(self.reloads(), len(failures) + 1)

    def test_a_proxy_whose_removal_was_not_applied_is_still_the_guests(self) -> None:
        """A create that failed after writing only its proxy block: the block is
        gone after the first attempt, and the guest is present until a reload
        applies its removal."""
        self._host(a_rules=False, a_proxy=True, a_reservation=False, a_domain=None)
        self.host.set_curl_exits([22])

        failed = self._run(self._script())
        result = self._run(self._script())

        self.assertNotEqual(failed.returncode, 0)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("GUEST_PRESENT=true", result.stdout)
        self.assertIn("Removed: relay proxy block", result.stdout)
        self.assertEqual(self.reloads(), 2)
        self.assert_others_untouched()
        self.assert_relay_settled()

    def test_a_host_with_no_vm_tunnel_client_is_torn_down_without_a_reload(self) -> None:
        self._host(a_rules=True, a_proxy=False, a_reservation=True,
                   a_domain={"state": "shut off", "mac": A_MAC})
        self.config.unlink()

        result = self._run(self._script())

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("GUEST_PRESENT=true", result.stdout)
        self.assertEqual(self.reloads(), 0)
        self.assertNotIn(A, self.host.virsh()["domains"])

    def test_a_partial_create_is_removed_by_the_guests_name_and_marker(self) -> None:
        self._host(a_rules=True, a_proxy=True, a_reservation=True,
                   a_domain={"state": "shut off", "mac": A_MAC,
                             "storage": [str(self.images / f"{A}.qcow2")]})
        a_files = [self.images / f"{A}.qcow2", self.images / f"{A}-init.iso",
                   self.nvram / f"{A}_VARS.fd",
                   self.root / f"home/.ssh/{A}_root_ed25519",
                   self.root / f"home/.ssh/{A}_tenant_ed25519.pub"]
        for path in a_files:
            path.write_text("guest A\n", encoding="utf-8")
        cloudinit = self.root / f"tmp/cloudinit_{A}_abcd1234"
        cloudinit.mkdir()
        b_cloudinit = self.root / f"tmp/cloudinit_{B}_abcd1234"
        b_cloudinit.mkdir()

        result = self._run(self._script())

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("GUEST_PRESENT=true", result.stdout)
        self.assert_others_untouched()
        self.a_removed()
        for path in a_files + [cloudinit]:
            self.assertFalse(path.exists(), path)
        self.assertTrue(b_cloudinit.exists())
        self.assertIn(f"Guest address: {A_IP}", result.stdout)
        self.assertEqual(self.reloads(), 1)
        self.assert_relay_settled()

    def test_a_domain_and_disk_left_by_a_create_are_removed_and_it_succeeds(self) -> None:
        self._host(a_rules=False, a_proxy=False, a_reservation=False,
                   a_domain={"state": "running", "address": A_IP, "mac": A_MAC,
                             "storage": [str(self.images / f"{A}.qcow2")]})
        (self.images / f"{A}.qcow2").write_text("guest A\n", encoding="utf-8")

        result = self._run(self._script())

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("GUEST_PRESENT=true", result.stdout)
        self.assertNotIn(A, self.host.virsh()["domains"])
        self.assertFalse((self.images / f"{A}.qcow2").exists())
        self.assert_others_untouched()

    def test_nothing_of_the_guest_is_reported_absent_and_nothing_is_changed(self) -> None:
        self._host(a_rules=False, a_proxy=False, a_reservation=False, a_domain=None)

        result = self._run(self._script())

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("GUEST_PRESENT=false", result.stdout)
        self.assert_others_untouched()
        changes = [c for c in self.host.calls()
                   if " -D " in c or c.startswith(("virsh undefine", "virsh destroy",
                                                   "virsh net-update", "ufw --force"))]
        self.assertEqual(changes, [])
        self.assertEqual(self.reloads(), 0)

    def test_only_marked_rules_left_with_no_address_known_are_still_the_guests(self) -> None:
        """A create that failed after adding its marked rules and before any
        reservation: the marker attributes them without an address."""
        self._host(a_rules=False, a_proxy=False, a_reservation=False, a_domain=None)
        marked = quoted(f"-A PREROUTING -p tcp -m tcp --dport {A_PORT} -m comment --comment {marker(A)} -j DNAT --to-destination {A_IP}:22")
        self.host.set_rules("nat", [marked] + _others_rules()["nat"])

        result = self._run(self._script())

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("GUEST_PRESENT=true", result.stdout)
        self.assert_others_untouched()

    def test_an_unattributable_rule_fails_naming_it_and_removes_nothing(self) -> None:
        """The guest's address is unknown, and an unmarked rule of a create's
        shape names an address no guest has reserved: it may be this guest's."""
        orphan = "-A PREROUTING -p tcp -m tcp --dport 4100 -j DNAT --to-destination 192.0.2.50:22"
        self._host(a_rules=False, a_proxy=True, a_reservation=False,
                   a_domain={"state": "shut off", "mac": A_MAC}, unmarked_extra=[orphan])
        (self.images / f"{A}.qcow2").write_text("guest A\n", encoding="utf-8")

        result = self._run(self._script())

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--to-destination 192.0.2.50:22", result.stderr)
        self.assertIn("nothing was removed", result.stderr)
        self.assertIn(A, self.host.virsh()["domains"])
        self.assertTrue((self.images / f"{A}.qcow2").exists())
        self.assertIn(f"FOR VM {A}\n", self.config.read_text(encoding="utf-8"))
        self.assertEqual(self.host.rules("nat")[0], orphan)
        self.assertEqual([c for c in self.host.calls() if " -D " in c], [])

    def test_an_unmarked_rule_reserved_for_another_guest_is_not_a_doubt(self) -> None:
        """With the address unknown, a rule whose address is another guest's
        reservation is that guest's, so it neither fails the teardown nor goes."""
        self._host(a_rules=False, a_proxy=True, a_reservation=False,
                   a_domain={"state": "shut off", "mac": A_MAC})

        result = self._run(self._script())

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("GUEST_PRESENT=true", result.stdout)
        self.a_removed()
        self.assert_others_untouched()

    def test_a_reservation_supplies_the_address_for_unmarked_rules(self) -> None:
        """No domain is left, but the guest's reservation names its address, so
        its rules written before markers are removed by that exact address."""
        self._host(a_rules=True, a_proxy=False, a_reservation=True, a_domain=None)

        result = self._run(self._script())

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"Guest address: {A_IP}", result.stdout)
        self.a_removed()
        self.assert_others_untouched()

    def test_an_unreadable_network_fails_before_anything_is_removed(self) -> None:
        self._host(a_rules=True, a_proxy=True, a_reservation=True,
                   a_domain={"state": "running", "address": A_IP, "mac": A_MAC})
        state = self.host.virsh()
        self.host.set_virsh(domains=state["domains"], hosts=state["hosts"],
                            network_unreadable=True)

        result = self._run(self._script())

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(A, self.host.virsh()["domains"])
        self.assertEqual([c for c in self.host.calls() if " -D " in c], [])


class AnUndefine(_Teardown):
    """vm_undefine's rule removal, with the address and port its earlier tasks read."""

    def test_it_removes_only_the_first_guests_rules(self) -> None:
        self._host(a_rules=True, a_proxy=False, a_reservation=True,
                   a_domain={"state": "shut off", "mac": A_MAC})
        earlier = {
            "{{ vm_ip_for_cleanup.stdout | default('') | trim }}": A_IP,
            "{{ vm_external_port_for_cleanup.stdout | default('') | trim }}": A_PORT,
        }

        def rendered(name: str) -> str:
            script = _task(VM_UNDEFINE, name)["shell"]
            for expression, value in earlier.items():
                script = script.replace(expression, value)
            return _render(script, A)

        port = self._run(rendered("Get external port before cleanup (for firewall rule removal)"))
        self.assertEqual(port.stdout.strip(), A_PORT)
        result = self._run(rendered("Clean up iptables port forwarding rules"))

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Removed 5 iptables rules", result.stdout)
        others = _others_rules()
        self.assertEqual(self.host.rules("nat"), others["nat"])
        self.assertEqual(self.host.rules("filter"), others["filter"])


class TheRulesACreateAdds(unittest.TestCase):
    def setUp(self) -> None:
        self.forwarding = _task(VM_CREATE, "Set up iptables port forwarding for SSH")["shell"]
        self.firewall = _task(VM_CREATE, "Configure firewall to allow external SSH port")["shell"]

    def _commands(self, text: str, command: str) -> list[str]:
        return [line.strip() for line in text.splitlines()
                if line.strip().startswith(command) and not line.strip().startswith("#")]

    def test_every_guest_rule_carries_the_guests_marker(self) -> None:
        self.assertIn('MARKER="{{ vm_guest_rule_marker }}"', self.forwarding)
        rules = self._commands(self.forwarding, "iptables ")
        guest_rules = [r for r in rules if "192.168.122.0/24" not in r]
        self.assertEqual(len(guest_rules), 4)
        for rule in guest_rules:
            self.assertIn('-m comment --comment "$MARKER"', rule)

    def test_the_subnet_masquerade_carries_no_guests_marker(self) -> None:
        (subnet,) = [r for r in self._commands(self.forwarding, "iptables ")
                     if "192.168.122.0/24" in r]
        self.assertNotIn("--comment", subnet)

    def test_the_firewall_openings_carry_the_marker(self) -> None:
        (ufw,) = self._commands(self.firewall, "ufw allow")
        self.assertIn("comment '{{ vm_guest_rule_marker }}'", ufw)
        (rule,) = self._commands(self.firewall, "iptables -A INPUT")
        self.assertIn("--comment '{{ vm_guest_rule_marker }}'", rule)

    def test_the_marker_names_the_guest_and_is_defined_once(self) -> None:
        self.assertEqual(
            yaml.safe_load(VARS.read_text(encoding="utf-8"))["vm_guest_rule_marker"],
            "arkhai-vm:{{ vm_name }}",
        )
        for path in (VM_CREATE, VM_REMOVE, VM_UNDEFINE):
            self.assertNotIn("arkhai-vm:", path.read_text(encoding="utf-8"), path.name)


class EveryTeardownPathSharesOneImplementation(unittest.TestCase):
    TEARDOWN_TASKS = (
        (VM_CREATE, "Create VM cleanup script on target host"),
        (VM_REMOVE, "Remove what the guest left without a cleanup script"),
        (VM_UNDEFINE, "Get external port before cleanup (for firewall rule removal)"),
        (VM_UNDEFINE, "Clean up iptables port forwarding rules"),
        (VM_UNDEFINE, "Clean up firewall rules for external ports"),
    )

    def _body(self, path: Path, name: str) -> str:
        task = _task(path, name)
        return task["copy"]["content"] if "copy" in task else task["shell"]

    def test_each_includes_the_shared_functions(self) -> None:
        for path, name in self.TEARDOWN_TASKS:
            self.assertIn(INCLUDE, self._body(path, name), name)

    def test_no_teardown_path_matches_by_a_prefix(self) -> None:
        """The matches the shared functions replace: a guest's address or port
        found anywhere in a listed line, and a proxy block found by a pattern
        a longer name also satisfies."""
        prefix_matches = re.compile(
            r'grep "to:\$VM_IP|grep "MASQUERADE\.\*|grep "ACCEPT\.\*|'
            r'grep "dpt:\$|grep "\$EXTERNAL_PORT/tcp"|/# BEGIN ANSIBLE MANAGED BLOCK FOR VM \$VM_NAME/'
        )
        for path in (VM_CREATE, VM_REMOVE, VM_UNDEFINE):
            text = path.read_text(encoding="utf-8")
            start = text.find("- name: Create VM cleanup script on target host")
            body = text[start:] if path == VM_CREATE else text
            for line in body.splitlines():
                if line.strip().startswith("#"):
                    continue
                self.assertIsNone(prefix_matches.search(line), f"{path.name}: {line.strip()}")

    def test_the_library_carries_no_template_delimiter(self) -> None:
        """It is included into templated text, so `{{`, `{%`, or `{#` in it would
        be read as Jinja rather than reach bash."""
        for delimiter in ("{{", "{%", "{#"):
            self.assertNotIn(delimiter, LIBRARY)


class ARemoveReportsWhatItFound(unittest.TestCase):
    def setUp(self) -> None:
        self.tasks = yaml.safe_load(VM_REMOVE.read_text(encoding="utf-8"))
        self.names = [t.get("name") for t in self.tasks]

    def test_a_missing_script_is_not_a_failure_by_itself(self) -> None:
        self.assertFalse(any("fail" in t for t in self.tasks))

    def test_each_path_runs_only_on_its_own_condition(self) -> None:
        def conditions(name: str) -> list[str]:
            when = _task(VM_REMOVE, name)["when"]
            return when if isinstance(when, list) else [when]

        self.assertIn("cleanup_script_stat.stat.exists", conditions("Run cleanup script"))
        self.assertIn("cleanup_script_stat.stat.exists",
                      conditions("Force-destroy VM (in case it is still running)"))
        self.assertIn("not cleanup_script_stat.stat.exists",
                      conditions("Remove what the guest left without a cleanup script"))

    def test_the_fact_reports_the_record_and_the_guests_presence(self) -> None:
        data = _task(VM_REMOVE, "Create JSON data structure for vm_remove action")["set_fact"]["vm_remove_data"]
        self.assertEqual(data["guest_present"], "{{ vm_guest_present | bool }}")
        self.assertEqual(data["cleanup_record"], "{{ cleanup_script_stat.stat.exists | bool }}")
        recorded = _task(VM_REMOVE, "Record the teardown that ran")["set_fact"]
        self.assertIn("GUEST_PRESENT=true", recorded["vm_guest_present"])


if __name__ == "__main__":
    unittest.main()
