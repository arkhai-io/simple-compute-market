"""Host diagnostics read a host's boot, guests and unit generations.

Behaviour first, through `shell_harness`: the role's `files/host_diagnostics.sh`
runs as its real shell against fake `systemctl`, `virsh` and `uname`, and a
temporary tree standing in for `/proc`, and its output is read as the task reads
it, as JSON. The fakes log each call, so the order of the reads is checked too.
Where ansible-core 2.17 to 2.19 is installed, as in the native Ansible gate, the
shipped task file also runs through ansible-playbook against localhost with the
same fakes, so its templating and the fact it sets are exercised.

Then the role's structure: the action's include, the task passing the management
unit quoted, the fact printed for the codec, and the prerequisites leaving
libvirtd as the job finds it.

The boot and invocation IDs here are synthetic. None of this runs against a real
host's systemd or libvirt.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

from shell_harness import assert_bash_syntax_valid, fake_binaries, run_bash


ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "ansible/roles/vm-management"
SCRIPT = ROLE / "files/host_diagnostics.sh"
TASKS = ROLE / "tasks/host-diagnostics.yml"
MAIN = ROLE / "tasks/main.yml"
OUTPUT = ROLE / "tasks/json-output.yml"
PREREQUISITES = ROLE / "tasks/prerequisites.yml"

BOOT_ID = "0f6c1d2e-3a4b-4c5d-8e9f-a0b1c2d3e4f5"

# Each unit's `systemctl show` answer, as key=value lines.
UNITS = {
    "libvirtd.service": {
        "ActiveState": "active",
        "InvocationID": "11111111111111111111111111111111",
        "MainPID": "812",
        "NRestarts": "0",
        "ActiveEnterTimestamp": "Thu 2026-11-05 09:00:00 UTC",
        "Result": "success",
    },
    "frpc-buyers.service": {
        "ActiveState": "active",
        "InvocationID": "22222222222222222222222222222222",
        "MainPID": "913",
        "NRestarts": "2",
        "ActiveEnterTimestamp": "Thu 2026-11-05 09:00:05 UTC",
        "Result": "success",
    },
    "operator-agent.service": {
        "ActiveState": "inactive",
        "InvocationID": "",
        "MainPID": "0",
        "NRestarts": "0",
        "ActiveEnterTimestamp": "",
        "Result": "exit-code",
    },
}


def _systemctl(units: dict[str, dict[str, str]], log: Path, *, fails: bool = False) -> str:
    """A `systemctl show` answering for ``units``, logging each unit it is asked
    for; a unit it does not know answers as systemd does for one not loaded."""
    cases = "\n".join(
        f"    {shlex.quote(name)}) printf '%s\\n' "
        f"{' '.join(shlex.quote(f'{key}={value}') for key, value in fields.items())} ;;"
        for name, fields in units.items()
    )
    failure = "echo 'Failed to connect to bus' >&2; exit 1" if fails else ""
    return f"""#!/bin/bash
[ "$1" = show ] || exit 2
unit="${{@: -1}}"
[ "${{@: -2:1}}" = "--" ] || exit 3
echo "systemctl $unit" >> {shlex.quote(str(log))}
{failure}
case "$unit" in
{cases}
    *) printf '%s\\n' ActiveState=inactive InvocationID= MainPID=0 NRestarts=0 ActiveEnterTimestamp= Result=success ;;
esac
"""


def _virsh(guests: list[str], log: Path, *, fails: bool = False) -> str:
    names = "".join(f"{guest}\\n" for guest in guests)
    failure = "echo 'error: failed to connect to the hypervisor' >&2; exit 1" if fails else ""
    return f"""#!/bin/bash
echo "virsh $*" >> {shlex.quote(str(log))}
[ "$*" = "list --state-running --name" ] || exit 2
{failure}
printf '{names}\\n'
"""


class _Host:
    """A temporary `/proc` and log, and the fakes over them."""

    def __init__(self, tmp: str) -> None:
        self.root = Path(tmp)
        self.log = self.root / "calls.log"
        self.log.touch()
        proc = self.root / "proc"
        (proc / "sys/kernel/random").mkdir(parents=True)
        (proc / "sys/kernel/random/boot_id").write_text(BOOT_ID + "\n")
        (proc / "uptime").write_text("86400.25 170000.10\n")

    def run(self, *arguments: str, units=UNITS, guests=("tenant-a", "tenant-b"),
            virsh_fails=False, systemctl_fails=False):
        fakes = {
            "systemctl": _systemctl(units, self.log, fails=systemctl_fails),
            "virsh": _virsh(list(guests), self.log, fails=virsh_fails),
            "uname": "#!/bin/sh\n[ \"$1\" = -r ] && echo 6.8.0-49-generic\n",
        }
        command = shlex.join(["bash", str(SCRIPT), *arguments])
        env = {"PATH": os.environ["PATH"], "PROC_ROOT": str(self.root / "proc")}
        with fake_binaries(fakes) as bin_dir:
            return run_bash(command, fake_bin_dir=bin_dir, env=env)

    def calls(self) -> list[str]:
        return self.log.read_text().splitlines()


class TestHostDiagnosticsScript(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="host-diagnostics-")
        self.host = _Host(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _fact(self, *arguments: str, **options) -> dict:
        result = self.host.run(*arguments, **options)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_the_script_parses(self) -> None:
        assert_bash_syntax_valid(SCRIPT.read_text(encoding="utf-8"))

    def test_a_named_management_unit_is_reported_beside_the_two_host_units(self) -> None:
        fact = self._fact("operator-agent.service")

        self.assertEqual(fact["boot_id"], BOOT_ID)
        self.assertEqual(fact["uptime_seconds"], 86400.25)
        self.assertEqual(fact["kernel"], "6.8.0-49-generic")
        self.assertEqual(fact["running_guests"], 2)
        self.assertEqual(fact["management_unit"], "operator-agent.service")
        self.assertEqual(
            list(fact["units"]),
            ["libvirtd.service", "frpc-buyers.service", "operator-agent.service"],
        )
        self.assertEqual(fact["units"]["frpc-buyers.service"], {
            "active_state": "active",
            "invocation_id": "22222222222222222222222222222222",
            "main_pid": 913,
            "restart_count": 2,
            "active_enter_timestamp": "Thu 2026-11-05 09:00:05 UTC",
            "result": "success",
        })
        self.assertEqual(fact["units"]["operator-agent.service"]["invocation_id"], "")
        self.assertRegex(fact["timestamp"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")

    def test_without_a_management_unit_only_the_host_units_are_reported(self) -> None:
        fact = self._fact()

        self.assertIsNone(fact["management_unit"])
        self.assertEqual(list(fact["units"]), ["libvirtd.service", "frpc-buyers.service"])

    def test_no_running_guest_is_counted_as_zero(self) -> None:
        self.assertEqual(self._fact(guests=())["running_guests"], 0)

    def test_the_units_are_read_before_virsh_can_start_libvirtd(self) -> None:
        self._fact("operator-agent.service")

        calls = self.host.calls()
        self.assertEqual(calls[-1], "virsh list --state-running --name")
        self.assertEqual(calls[:-1], [
            "systemctl libvirtd.service",
            "systemctl frpc-buyers.service",
            "systemctl operator-agent.service",
        ])

    def test_a_number_systemd_does_not_report_is_printed_as_text(self) -> None:
        """An older systemd reports no NRestarts; the fact carries the empty
        text, which the typed reader refuses by name, rather than a zero."""
        units = {**UNITS, "libvirtd.service": {**UNITS["libvirtd.service"], "NRestarts": ""}}

        fact = self._fact(units=units)

        self.assertEqual(fact["units"]["libvirtd.service"]["restart_count"], "")

    def test_a_value_with_quotes_backslashes_and_a_tab_stays_valid_json(self) -> None:
        odd = 'say "hi" \\ there\tnow'
        units = {**UNITS, "libvirtd.service": {**UNITS["libvirtd.service"], "Result": odd}}

        self.assertEqual(self._fact(units=units)["units"]["libvirtd.service"]["result"], odd)

    def test_a_management_unit_that_is_a_host_unit_is_read_once(self) -> None:
        fact = self._fact("libvirtd.service")

        self.assertEqual(fact["management_unit"], "libvirtd.service")
        self.assertEqual(list(fact["units"]), ["libvirtd.service", "frpc-buyers.service"])
        self.assertEqual(self.host.calls().count("systemctl libvirtd.service"), 1)

    def test_a_failed_guest_count_fails_the_script(self) -> None:
        result = self.host.run(virsh_fails=True)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("failed to connect to the hypervisor", result.stderr)

    def test_a_failed_unit_read_fails_the_script_naming_the_unit(self) -> None:
        result = self.host.run(systemctl_fails=True)

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("systemctl show failed for libvirtd.service", result.stderr)


def _tasks(path: Path) -> list[dict]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


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
class TestHostDiagnosticsTaskNatively(unittest.TestCase):
    """The shipped task file, run by ansible-playbook against localhost with the
    real script and the same fakes, passes the unit through and sets the fact
    `json-output.yml` prints. Printing it is the structure case's."""

    def _fact(self, variables: dict) -> dict:
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            host = _Host(directory)
            (work / "files").mkdir()
            shutil.copy(SCRIPT, work / "files" / SCRIPT.name)
            bin_dir = work / "bin"
            bin_dir.mkdir()
            for name, content in {
                "systemctl": _systemctl(UNITS, host.log),
                "virsh": _virsh(["tenant-a"], host.log),
                "uname": "#!/bin/sh\n[ \"$1\" = -r ] && echo 6.8.0-49-generic\n",
            }.items():
                (bin_dir / name).write_text(content, encoding="utf-8")
                (bin_dir / name).chmod(0o755)
            output = work / "fact.json"
            play = [{
                "hosts": "localhost", "connection": "local", "gather_facts": False,
                "environment": {
                    "PATH": f"{bin_dir}:{os.environ['PATH']}",
                    "PROC_ROOT": str(host.root / "proc"),
                },
                "vars": {"target_host": "localhost", **variables},
                "tasks": _tasks(TASKS) + [{"name": "Export the rendered fact", "copy": {
                    "content": "{{ host_diagnostics_data | to_json }}", "dest": str(output),
                    "mode": "0600"}}],
            }]
            path = work / "play.yml"
            path.write_text(yaml.safe_dump(play, sort_keys=False), encoding="utf-8")
            environment = {k: v for k, v in os.environ.items() if not k.startswith("ANSIBLE_")}
            environment.update(ANSIBLE_NOCOLOR="true", ANSIBLE_LOG_PATH="/dev/null")
            run = subprocess.run([ANSIBLE_PLAYBOOK, "-i", "localhost,", str(path)], cwd=work,
                                 env=environment, capture_output=True, text=True, timeout=90,
                                 check=False)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            return json.loads(output.read_text(encoding="utf-8"))

    def test_a_named_unit_reaches_the_script_and_the_fact_names_the_action(self) -> None:
        fact = self._fact({"management_unit": "operator-agent.service"})

        self.assertEqual(
            (fact["action"], fact["host"], fact["status"]), ("diagnose", "localhost", "success"),
        )
        self.assertEqual(fact["management_unit"], "operator-agent.service")
        self.assertIn("operator-agent.service", fact["units"])
        self.assertEqual(fact["units"]["frpc-buyers.service"]["restart_count"], 2)
        self.assertEqual(fact["running_guests"], 1)

    def test_a_unit_name_with_a_shell_metacharacter_reaches_the_script_whole(self) -> None:
        """systemd escapes a unit name's dashes as `\\x2d`; unquoted, the shell
        would drop the backslash."""
        unit = "operator-agent@by\\x2dlabel.service"

        fact = self._fact({"management_unit": unit})

        self.assertEqual(fact["management_unit"], unit)
        self.assertIn(unit, fact["units"])

    def test_no_unit_named_reports_the_host_units_alone(self) -> None:
        for variables in ({}, {"management_unit": None}):
            with self.subTest(variables=variables):
                fact = self._fact(variables)

                self.assertIsNone(fact["management_unit"])
                self.assertEqual(
                    sorted(fact["units"]), ["frpc-buyers.service", "libvirtd.service"],
                )


class TestHostDiagnosticsStructure(unittest.TestCase):
    def test_the_action_includes_the_task_file(self) -> None:
        (include,) = [t for t in _tasks(MAIN) if t.get("when") == 'vm_action == "diagnose"']
        self.assertEqual(include["include_tasks"]["file"], "host-diagnostics.yml")

    def test_the_task_runs_the_script_with_the_unit_quoted(self) -> None:
        read, fact = _tasks(TASKS)
        self.assertTrue(read["script"].startswith("host_diagnostics.sh"))
        self.assertIn("management_unit | quote", read["script"])
        self.assertIs(read["changed_when"], False)
        self.assertEqual(read["delegate_to"], "{{ target_host }}")
        self.assertIn("host_diagnostics_read.stdout | from_json", fact["set_fact"]["host_diagnostics_data"])
        self.assertIn("'action': 'diagnose'", fact["set_fact"]["host_diagnostics_data"])

    def test_the_fact_is_printed_as_the_codec_reads_it(self) -> None:
        printed = [
            t for t in _tasks(OUTPUT)
            if "debug" in t and 'vm_action == "diagnose"' in t.get("when", "")
        ]
        self.assertEqual(
            [t["debug"] for t in printed],
            [{"var": "host_diagnostics_data"}, {"msg": "{{ host_diagnostics_json }}"}],
        )

    def test_the_prerequisites_leave_libvirtd_as_the_diagnostics_find_it(self) -> None:
        (start,) = [t for t in _tasks(PREREQUISITES) if t.get("name") == "Ensure libvirtd is running"]
        self.assertEqual(start["when"], 'vm_action != "diagnose"')


if __name__ == "__main__":
    unittest.main()
