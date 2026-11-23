"""The convergence of running VM guests host preparation runs.

The command, `files/guest_converge.sh`, runs as its real shell against the
stateful fake `virsh` and `bridge` of `host_fakes`, on a `PATH` holding only
those fakes and the ordinary tools the command uses, so no real `virsh` or
`bridge` on the machine running the tests is reached; what it leaves is read
back from the fakes' state. Host preparation's tasks are read for what they
install, where, and in what order; where ansible-core 2.17 to 2.19 is
installed, as in the native Ansible gate, the tasks that run the command and
report on it run through ansible-playbook against a fake command, so Ansible's
own templating decides what the play names.

None of this runs against a real libvirt or kernel bridge: whether libvirt
binds a running guest's filter live, and whether isolating a port keeps the
guest's sessions, shows only on a real host.
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

import yaml

from host_fakes import FakeHost
from shell_harness import fake_binaries


ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "ansible/roles/vm-setup"
GUEST_POLICY = SETUP / "tasks/guest-policy.yml"
COMMAND = SETUP / "files/guest_converge.sh"
INSTALLED = "/usr/local/sbin/arkhai-guest-converge"

INSTALL = "Install the command that converges running guests"
RUN = "Converge every running guest to an isolated, filtered port"
UNCONVERGED = "Name each running guest left unconverged"
WAITING = "Name each running guest whose filter waits for its next start"

CLEAN_TRAFFIC = {
    "filter": "clean-traffic",
    "parameters": {"CTRL_IP_LEARNING": "dhcp", "DHCPSERVER": "192.168.122.1"},
}

# The ordinary tools the command runs beside virsh and bridge.
TOOLS = ("sh", "mktemp", "rm", "tr", "sed", "grep", "awk", "cut", "cat")


def _interface(tap: str, mac: str, *, converged: bool) -> dict:
    """A guest interface on the default network, as a guest created with the
    isolated, filtered interface holds it (converged), or as one created
    without either holds it."""
    held = {"port": converged, "filterref": CLEAN_TRAFFIC if converged else None}
    return {
        "tap": tap, "mac": mac, "source": "default", "bridge_isolated": converged,
        "live": dict(held), "saved": dict(held),
    }


def _guest(*interfaces: dict, state: str = "running", **flags) -> dict:
    return {"state": state, "mac": interfaces[0]["mac"] if interfaces else "",
            "interfaces": list(interfaces), **flags}


def _tasks() -> list[dict]:
    return yaml.safe_load(GUEST_POLICY.read_text(encoding="utf-8"))


def _named(name: str) -> dict:
    (task,) = [t for t in _tasks() if t.get("name") == name]
    return task


class TestTheCommand(unittest.TestCase):
    """The command converges each running guest and reports it in one line."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="guest-convergence-")
        self.root = Path(self._tmp.name)
        self.host = FakeHost(self.root / "host")
        self.tools = self.root / "tools"
        self.tools.mkdir()
        for tool in TOOLS:
            (self.tools / tool).symlink_to(shutil.which(tool))
        (self.tools / "python3").symlink_to(sys.executable)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _converge(self, binaries: dict[str, str] | None = None) -> subprocess.CompletedProcess:
        with fake_binaries(binaries or self.host.binaries()) as bin_dir:
            env = self.host.environment({"PATH": f"{bin_dir}:{self.tools}"})
            return subprocess.run(
                ["sh", str(COMMAND)], capture_output=True, text=True, env=env, timeout=60,
            )

    def _reports(self, result: subprocess.CompletedProcess) -> dict[str, dict]:
        self.assertEqual(result.returncode, 0, result.stderr)
        reports = [json.loads(line) for line in result.stdout.splitlines()]
        return {report.pop("name"): report for report in reports}

    def _interface(self, guest: str, index: int = 0) -> dict:
        return self.host.virsh()["domains"][guest]["interfaces"][index]

    def _mutations(self) -> list[str]:
        return [c for c in self.host.calls()
                if c.startswith("bridge link set") or c.startswith("virsh update-device")]

    def test_the_script_parses(self) -> None:
        result = subprocess.run(["sh", "-n", str(COMMAND)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_an_unconverged_guest_is_converged_live_and_its_saved_definition_carries_both(self) -> None:
        self.host.set_virsh(
            domains={"vm-old": _guest(_interface("vnet3", "52:54:00:00:00:31", converged=False))},
            hosts=[],
        )

        reports = self._reports(self._converge())

        self.assertEqual(reports, {"vm-old": {
            "port_isolated": True, "filter": "live", "saved_definition": True,
            "changed": True, "error": None,
        }})
        interface = self._interface("vm-old")
        self.assertTrue(interface["bridge_isolated"])
        self.assertEqual(interface["live"]["filterref"], CLEAN_TRAFFIC)
        self.assertEqual(interface["saved"], {"port": True, "filterref": CLEAN_TRAFFIC})
        # The port is isolated through the bridge; the live update leaves the
        # running definition's <port> as libvirt holds it, which the fake
        # would have refused to change.
        self.assertFalse(interface["live"]["port"])

    def test_a_guest_whose_live_filter_libvirt_refuses_waits_for_its_next_start(self) -> None:
        self.host.set_virsh(
            domains={"vm-old": _guest(_interface("vnet3", "52:54:00:00:00:31", converged=False),
                                      live_filter_refused=True)},
            hosts=[],
        )

        report = self._reports(self._converge())["vm-old"]

        self.assertEqual(
            {k: report[k] for k in ("port_isolated", "filter", "saved_definition", "changed")},
            {"port_isolated": True, "filter": "next_start", "saved_definition": True,
             "changed": True},
        )
        self.assertIn("libvirt did not bind the filter live", report["error"])
        self.assertIn("cannot modify network device filter", report["error"])
        interface = self._interface("vm-old")
        self.assertTrue(interface["bridge_isolated"])
        self.assertIsNone(interface["live"]["filterref"])
        self.assertEqual(interface["saved"], {"port": True, "filterref": CLEAN_TRAFFIC})

    def test_a_guest_whose_port_cannot_be_isolated_is_reported_while_the_others_converge(self) -> None:
        self.host.set_virsh(
            domains={
                "vm-a": _guest(_interface("vnet1", "52:54:00:00:00:11", converged=False)),
                "vm-b": _guest(_interface("vnet2", "52:54:00:00:00:21", converged=False)),
            },
            hosts=[],
            isolation_refused=("vnet1",),
        )

        reports = self._reports(self._converge())

        self.assertFalse(reports["vm-a"]["port_isolated"])
        self.assertIn("cannot isolate the bridge port of vnet1", reports["vm-a"]["error"])
        self.assertIn("Operation not supported", reports["vm-a"]["error"])
        self.assertEqual(reports["vm-b"], {
            "port_isolated": True, "filter": "live", "saved_definition": True,
            "changed": True, "error": None,
        })
        self.assertFalse(self._interface("vm-a")["bridge_isolated"])
        self.assertTrue(self._interface("vm-b")["bridge_isolated"])

    def test_a_converged_guest_is_reported_converged_and_left_unchanged(self) -> None:
        guest = _guest(_interface("vnet4", "52:54:00:00:00:41", converged=True))
        self.host.set_virsh(domains={"vm-new": guest}, hosts=[])

        reports = self._reports(self._converge())

        self.assertEqual(reports, {"vm-new": {
            "port_isolated": True, "filter": "live", "saved_definition": True,
            "changed": False, "error": None,
        }})
        self.assertEqual(self._mutations(), [])
        self.assertEqual(self.host.virsh()["domains"]["vm-new"], guest)

    def test_a_saved_definition_that_cannot_be_written_is_reported(self) -> None:
        """A transient guest has no saved definition to carry either."""
        self.host.set_virsh(
            domains={"vm-transient": _guest(
                _interface("vnet5", "52:54:00:00:00:51", converged=False), transient=True)},
            hosts=[],
        )

        report = self._reports(self._converge())["vm-transient"]

        self.assertTrue(report["port_isolated"])
        self.assertEqual(report["filter"], "live")
        self.assertFalse(report["saved_definition"])
        self.assertIn("cannot write the saved definition of 52:54:00:00:00:51", report["error"])

    def test_a_live_filter_refused_without_a_saved_definition_waits_for_nothing(self) -> None:
        """Neither definition holds the filter, so none is reported rather than
        a next start that would not bind it."""
        self.host.set_virsh(
            domains={"vm-transient": _guest(
                _interface("vnet5", "52:54:00:00:00:51", converged=False),
                transient=True, live_filter_refused=True)},
            hosts=[],
        )

        report = self._reports(self._converge())["vm-transient"]

        self.assertEqual((report["port_isolated"], report["filter"], report["saved_definition"]),
                         (True, "none", False))

    def test_a_guest_with_no_interface_on_the_default_network_is_reported_unconverged(self) -> None:
        interface = dict(_interface("vnet7", "52:54:00:00:00:71", converged=False),
                         source="other")
        self.host.set_virsh(domains={"vm-elsewhere": _guest(interface)}, hosts=[])

        report = self._reports(self._converge())["vm-elsewhere"]

        self.assertEqual(report, {
            "port_isolated": False, "filter": "none", "saved_definition": False,
            "changed": False, "error": "it has no interface on the default network",
        })
        self.assertEqual(self._mutations(), [])

    def test_a_guest_whose_interfaces_cannot_be_read_is_reported_while_the_others_converge(self) -> None:
        self.host.set_virsh(
            domains={
                "vm-a": _guest(_interface("vnet1", "52:54:00:00:00:11", converged=False)),
                "vm-b": _guest(_interface("vnet2", "52:54:00:00:00:21", converged=False)),
            },
            hosts=[],
        )
        self.host.refuse("virsh domiflist")

        reports = self._reports(self._converge())

        self.assertEqual(
            {k: reports["vm-a"][k] for k in ("port_isolated", "filter", "saved_definition")},
            {"port_isolated": False, "filter": "none", "saved_definition": False},
        )
        self.assertIn("cannot read its interfaces", reports["vm-a"]["error"])
        self.assertEqual(reports["vm-b"]["error"], None)
        self.assertTrue(self._interface("vm-b")["bridge_isolated"])

    def test_an_unreadable_running_definition_leaves_the_filter_to_the_saved_one(self) -> None:
        self.host.set_virsh(
            domains={"vm-old": _guest(_interface("vnet3", "52:54:00:00:00:31", converged=False))},
            hosts=[],
        )
        # The command reads the running definition before the saved one.
        self.host.refuse("virsh dumpxml")

        report = self._reports(self._converge())["vm-old"]

        self.assertEqual(
            {k: report[k] for k in ("port_isolated", "filter", "saved_definition")},
            {"port_isolated": True, "filter": "next_start", "saved_definition": True},
        )
        self.assertIn("cannot read its running definition", report["error"])
        self.assertIsNone(self._interface("vm-old")["live"]["filterref"])

    def test_a_host_with_no_running_guest_reports_nothing(self) -> None:
        self.host.set_virsh(
            domains={"vm-off": _guest(_interface("vnet6", "52:54:00:00:00:61", converged=False),
                                      state="shut off")},
            hosts=[],
        )

        result = self._converge()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual([c for c in self.host.calls() if c.startswith("virsh")],
                         ["virsh list --state-running --name"])

    def test_without_bridge_it_fails_naming_it_and_converges_nothing(self) -> None:
        binaries = {k: v for k, v in self.host.binaries().items() if k != "bridge"}
        self.host.set_virsh(
            domains={"vm-old": _guest(_interface("vnet3", "52:54:00:00:00:31", converged=False))},
            hosts=[],
        )

        result = self._converge(binaries)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("bridge is not installed", result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(self.host.calls(), [])

    def test_unreadable_running_guests_fail_it(self) -> None:
        self.host.set_virsh(domains={}, hosts=[])
        self.host.refuse("virsh list")

        result = self._converge()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cannot list the running guests", result.stderr)
        self.assertEqual(result.stdout, "")


class TestHostPreparationConvergesRunningGuests(unittest.TestCase):
    """What host preparation installs, when it runs it, and what it names."""

    def test_the_command_is_installed_where_it_is_run(self) -> None:
        installed = _named(INSTALL)["copy"]
        self.assertEqual(
            (installed["src"], installed["dest"], installed["owner"], installed["mode"]),
            (COMMAND.name, INSTALLED, "root", "0755"),
        )
        run = _named(RUN)
        self.assertEqual(run["command"], INSTALLED)
        self.assertEqual(run["register"], "guest_convergence")
        # Its exit status alone fails host preparation: it is non-zero only when
        # the command cannot run.
        self.assertNotIn("failed_when", run)
        self.assertNotIn("ignore_errors", run)

    def test_it_runs_after_the_guest_policy_is_installed(self) -> None:
        names = [t.get("name") for t in _tasks()]
        policy = names.index("Install the guest policy now and at every boot and libvirt start")
        self.assertLess(policy, names.index(INSTALL))
        self.assertLess(names.index(INSTALL), names.index(RUN))
        self.assertLess(names.index(RUN), names.index(UNCONVERGED))
        self.assertLess(names.index(RUN), names.index(WAITING))

    def test_the_report_reads_the_lines_the_run_registered(self) -> None:
        """What the report names is the native tests'; here, only that it reads
        the run's own output."""
        for name in (UNCONVERGED, WAITING):
            with self.subTest(task=name):
                self.assertIn("guest_convergence.stdout_lines", _named(name)["loop"])


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
class TestTheReportNatively(unittest.TestCase):
    """The shipped tasks that run the command and report on it, run by
    ansible-playbook against localhost with a fake command at a path of the
    test's own in place of the installed one."""

    def _play(self, lines: list[dict], *, exit_status: int = 0) -> subprocess.CompletedProcess:
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            command = work / "arkhai-guest-converge"
            printed = "".join(f"echo {shlex.quote(json.dumps(line))}\n" for line in lines)
            command.write_text(f"#!/bin/sh\n{printed}exit {exit_status}\n", encoding="utf-8")
            command.chmod(0o755)
            run = dict(_named(RUN), command=str(command))
            play = [{
                "hosts": "localhost", "connection": "local", "gather_facts": False,
                "tasks": [run, _named(UNCONVERGED), _named(WAITING)],
            }]
            path = work / "play.yml"
            path.write_text(yaml.safe_dump(play, sort_keys=False), encoding="utf-8")
            environment = {k: v for k, v in os.environ.items() if not k.startswith("ANSIBLE_")}
            environment.update(ANSIBLE_NOCOLOR="true", ANSIBLE_LOG_PATH="/dev/null")
            return subprocess.run(
                [ANSIBLE_PLAYBOOK, "-i", "localhost,", str(path)], cwd=work,
                env=environment, capture_output=True, text=True, timeout=90, check=False,
            )

    def test_the_play_names_an_unconverged_guest_and_one_whose_filter_waits(self) -> None:
        run = self._play([
            {"name": "vm-stuck", "port_isolated": False, "filter": "live",
             "saved_definition": True, "changed": False,
             "error": "cannot isolate the bridge port of vnet1: Operation not supported"},
            {"name": "vm-later", "port_isolated": True, "filter": "next_start",
             "saved_definition": True, "changed": True,
             "error": "libvirt did not bind the filter live"},
            {"name": "vm-gone", "port_isolated": False, "filter": "none",
             "saved_definition": False, "changed": False,
             "error": "it has no interface on the default network"},
            {"name": "vm-fine", "port_isolated": True, "filter": "live",
             "saved_definition": True, "changed": False, "error": None},
        ])

        output = run.stdout + run.stderr
        self.assertEqual(run.returncode, 0, output)
        self.assertIn(
            "Guest vm-stuck is NOT converged: its bridge port is not isolated, its saved "
            "definition carries the isolation and the filter, and its filter is bound live. "
            "Reason: cannot isolate the bridge port of vnet1: Operation not supported.",
            output,
        )
        self.assertIn(
            "Guest vm-later's clean-traffic filter waits for its next start: it is not bound "
            "live, and its saved definition carries it. Reason: libvirt did not bind the "
            "filter live.",
            output,
        )
        self.assertIn(
            "Guest vm-gone is NOT converged: its bridge port is not isolated, its saved "
            "definition does not carry the isolation and the filter, and its filter is not "
            "bound. Reason: it has no interface on the default network.",
            output,
        )
        self.assertNotIn("Guest vm-fine", output)
        self.assertNotIn("Guest vm-later is NOT converged", output)
        self.assertNotIn("Guest vm-gone's clean-traffic filter", output)
        self.assertRegex(output, r"changed: \[localhost\]")

    def test_a_command_that_cannot_run_fails_host_preparation(self) -> None:
        run = self._play([], exit_status=1)

        self.assertNotEqual(run.returncode, 0)
        self.assertIn(RUN, run.stdout)
        self.assertRegex(run.stdout, r"fatal: \[localhost\]")


if __name__ == "__main__":
    unittest.main()
