"""A GPU create passes the host's boot GPU through only by its pool's opt-in,
waits for its guest within its pool's bound, and autostarts it as the pool says.

Behaviour first, through `shell_harness`: each task that selects or counts GPUs
runs as its real shell, with the shared `files/gpu_eligibility.sh` included as
the role includes it, against `host_fakes.FakeGpuHost`: a sysfs PCI tree under a
temporary directory (the library's `/sys/bus/pci/devices` is rewritten to it,
the way the teardown tests rewrite `/etc/frp`), `lspci` printing `-vmm` records
Slot-first as a real host does, and the host devices each defined guest has
attached. The GPUs are synthetic devices at arbitrary addresses.

The readiness wait runs with `ssh` and `sleep` faked, so a wait of many
attempts takes no time.

Then the role's structure: the settings' defaults and the type check that
precedes every host effect, the autostart condition, every selector reading
the one test and the one setting, and no task binding or unbinding a device.

None of this passes a real GPU through; that, the guest's readiness on the
lane's host, and the GPU's return to its host driver are the live VM lane's
evidence.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import unittest
from pathlib import Path

import yaml

from host_fakes import FakeGpuHost
from shell_harness import assert_bash_syntax_valid, fake_binaries, run_bash


ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "ansible/roles/vm-management"
LIBRARY = (ROLE / "files/gpu_eligibility.sh").read_text(encoding="utf-8")
VM_CREATE = ROLE / "tasks/vm-create.yml"
RETRY = ROLE / "tasks/gpu-virt-install-retry.yml"
PREREQUISITES = ROLE / "tasks/prerequisites.yml"
DEFAULTS = ROLE / "defaults/main.yml"

INCLUDE = "{{ lookup('file', 'gpu_eligibility.sh') }}"
OPT_IN = "{{ vm_passthrough_boot_gpu | bool | lower }}"
LOCKFILE = "/etc/libvirt/gpu-capabilities/gpu-lockfile.json"

BOOT, SECOND, THIRD, FOURTH = "0000:0a:00.0", "0000:0b:00.0", "0000:0c:00.0", "0000:0d:00.0"

SELECTOR = "Find least-used available GPU (avoid exhausting first GPU)"
RETRY_COUNT = "Get total available GPUs for retry calculation (not attached to VMs)"
MULTI = "Auto-select available GPUs by count"
ALTERNATIVES = (
    (VM_CREATE, "Get alternative GPU (excluding attempted ones)"),
    (RETRY, "Get next alternative GPU (excluding attempted ones)"),
)
WAIT = "Wait for VM setup completion by checking for setup log"
AUTOSTART = "Set VM to autostart on host boot"


def _all_tasks(tasks: list) -> list[dict]:
    """Every task, those inside blocks and their rescues included."""
    found = []
    for task in tasks or []:
        found.append(task)
        for section in ("block", "rescue", "always"):
            found.extend(_all_tasks(task.get(section)))
    return found


def _tasks_named(path: Path, name: str) -> list[dict]:
    tasks = [t for t in _all_tasks(yaml.safe_load(path.read_text(encoding="utf-8")))
             if t.get("name") == name]
    if not tasks:
        raise AssertionError(f"no task named {name!r} in {path.name}")
    return tasks


def _shell(task: dict) -> str:
    body = task["shell"]
    return body if isinstance(body, str) else body["cmd"]


class _Gpus(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="gpu-eligibility-"))
        self.host = FakeGpuHost(self.root)
        self.lockfile = self.root / LOCKFILE.lstrip("/")
        self.lockfile.parent.mkdir(parents=True)

    def inventory(self, *addresses: str) -> str:
        self.lockfile.write_text(json.dumps(
            {"gpu_modes": {"passthrough": {"supported": True, "available_devices": list(addresses)}}}
        ), encoding="utf-8")
        return " ".join(addresses)

    def render(self, script: str, *, opt_in: bool, candidates: str = "",
               attempted: tuple[str, ...] = (), requested: int = 0) -> str:
        """Render the Jinja a selector carries, as Ansible would for a pool
        with this opt-in and a host with this inventory."""
        script = re.sub(r"^\s*\{% if gpu_lockfile is not defined.*?\{% endif %\}\n", "",
                        script, flags=re.S | re.M)
        script = re.sub(r"^\s*\{% (if attempted_gpus.*|endif) %\}\n", "", script, flags=re.M)
        script = script.replace(
            '({% for gpu in attempted_gpus %}"{{ gpu }}" {% endfor %})',
            "(" + " ".join(f'"{a}"' for a in attempted) + ")",
        )
        script = script.replace(INCLUDE, LIBRARY)
        script = script.replace(OPT_IN, "true" if opt_in else "false")
        script = script.replace(
            '{{ gpu_lockfile.gpu_modes.passthrough.available_devices | join(" ") }}', candidates
        )
        script = script.replace("{{ vm_gpu_count | default(0) }}", str(requested))
        script = script.replace("/sys/bus/pci/devices", str(self.host.devices))
        script = script.replace(LOCKFILE, str(self.lockfile))
        leftover = re.findall(r"\{\{.*?\}\}|\{%.*?%\}", script)
        self.assertEqual(leftover, [], "a template expression was left unrendered")
        return script

    def run_script(self, script: str):
        assert_bash_syntax_valid(script)
        with fake_binaries(self.host.binaries()) as fake_bin:
            return run_bash(script, fake_bin_dir=fake_bin,
                            env=self.host.environment(dict(os.environ)), timeout=30)


class TheSelector(_Gpus):
    """The single-GPU selector, the create's first choice."""

    def select(self, *candidates: str, opt_in: bool):
        (task,) = _tasks_named(VM_CREATE, SELECTOR)
        return self.run_script(self.render(
            _shell(task), opt_in=opt_in, candidates=self.inventory(*candidates)))

    def test_a_hosts_only_gpu_is_its_boot_gpu_and_the_pool_does_not_opt_in(self) -> None:
        """The regression: lspci prints Slot: before Class:, and the boot GPU is
        still recognized, by its own flag, and never selected."""
        self.host.add_gpu(BOOT, boot=True, driver="vfio-pci")

        result = self.select(BOOT, opt_in=False)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "NO_AVAILABLE_GPU")
        self.assertIn(f"{BOOT}, the boot GPU, and the pool does not opt in", result.stderr)

    def test_the_pool_opts_in_and_the_boot_gpu_is_bound_for_passthrough(self) -> None:
        self.host.add_gpu(BOOT, boot=True, driver="vfio-pci")

        result = self.select(BOOT, opt_in=True)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), BOOT)

    def test_a_stale_inventory_never_takes_the_boot_gpu_from_its_host_driver(self) -> None:
        for driver, named in (("nvidia", "nvidia"), (None, "no driver")):
            with self.subTest(driver=named):
                self.setUp()
                self.host.add_gpu(BOOT, boot=True, driver=driver)

                result = self.select(BOOT, opt_in=True)

                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), "NO_AVAILABLE_GPU")
                self.assertIn(f"bound to {named} rather than vfio-pci", result.stderr)

    def test_the_pool_opts_in_but_a_defined_guest_holds_the_boot_gpu(self) -> None:
        self.host.add_gpu(BOOT, boot=True, driver="vfio-pci")
        self.host.set_guests({"tenant-other": [{"source": BOOT}]})

        result = self.select(BOOT, opt_in=True)

        self.assertEqual(result.stdout.strip(), "NO_AVAILABLE_GPU")
        self.assertIn(f"{BOOT}, attached to a defined guest", result.stderr)

    def test_a_second_gpu_is_selected_while_the_boot_gpu_stays_the_hosts(self) -> None:
        self.host.add_gpu(BOOT, boot=True, driver="vfio-pci")
        self.host.add_gpu(SECOND, boot=False, driver="vfio-pci")

        result = self.select(BOOT, SECOND, opt_in=False)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), SECOND)

    def test_only_a_hostdevs_source_address_is_an_attachment(self) -> None:
        """A device's address inside its guest is not a host device: a guest
        whose passed-through GPU sits at bus 0x0b inside it holds THIRD, not
        SECOND."""
        self.host.add_gpu(SECOND, boot=False, driver="vfio-pci")
        self.host.set_guests({"tenant-other": [{"source": THIRD, "guest_bus": "0x0b"}]})

        result = self.select(SECOND, opt_in=False)

        self.assertEqual(result.stdout.strip(), SECOND)

    def test_attachment_that_cannot_be_read_fails_the_selection(self) -> None:
        self.host.add_gpu(SECOND, boot=False, driver="vfio-pci")
        self.host.set_guests({}, list_fails=True)

        result = self.select(SECOND, opt_in=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(SECOND, result.stdout)


class TheAlternativesAfterAFailedAttempt(_Gpus):
    """Each selector a create retries with applies the same test."""

    def alternative(self, path: Path, name: str, *, opt_in: bool) -> list:
        results = []
        for task in _tasks_named(path, name):
            results.append(self.run_script(self.render(
                _shell(task), opt_in=opt_in, attempted=(SECOND,))))
        return results

    def test_a_retry_never_falls_back_to_the_boot_gpu_without_the_opt_in(self) -> None:
        self.host.add_gpu(BOOT, boot=True, driver="vfio-pci")
        self.host.add_gpu(SECOND, boot=False, driver="vfio-pci")
        self.inventory(BOOT, SECOND)
        counted = 0
        for path, name in ALTERNATIVES:
            for result in self.alternative(path, name, opt_in=False):
                counted += 1
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), "NO_AVAILABLE_GPU", (path.name, name))
        # Two in vm-create.yml (scratch and golden) and the recursive retry's.
        self.assertEqual(counted, 3)

    def test_a_retry_takes_the_prepared_boot_gpu_with_the_opt_in(self) -> None:
        self.host.add_gpu(BOOT, boot=True, driver="vfio-pci")
        self.host.add_gpu(SECOND, boot=False, driver="vfio-pci")
        self.inventory(BOOT, SECOND)
        for path, name in ALTERNATIVES:
            for result in self.alternative(path, name, opt_in=True):
                self.assertEqual(result.stdout.strip(), BOOT, (path.name, name))

    def test_the_retry_count_counts_only_eligible_gpus(self) -> None:
        self.host.add_gpu(BOOT, boot=True, driver="vfio-pci")
        self.host.add_gpu(SECOND, boot=False, driver="vfio-pci")
        self.host.add_gpu(THIRD, boot=False, driver="vfio-pci")
        self.host.set_guests({"tenant-other": [{"source": THIRD}]})
        self.inventory(BOOT, SECOND, THIRD)
        (task,) = _tasks_named(VM_CREATE, RETRY_COUNT)
        for opt_in, expected in ((False, "1"), (True, "2")):
            result = self.run_script(self.render(_shell(task), opt_in=opt_in))
            self.assertEqual(result.stdout.strip(), expected, opt_in)


class TheMultiGpuSelection(_Gpus):
    def test_a_multi_gpu_create_never_takes_the_boot_gpu_without_the_opt_in(self) -> None:
        """The selection keeps the first eligible GPU back and takes the rest.
        Three are asked of four listed, the boot GPU second: it may take only
        the two eligible ones it does not keep back, and the create's own count
        check then refuses the shortfall."""
        for address in (SECOND, BOOT, THIRD, FOURTH):
            self.host.add_gpu(address, boot=address == BOOT, driver="vfio-pci")
        self.inventory(SECOND, BOOT, THIRD, FOURTH)
        (task,) = _tasks_named(VM_CREATE, MULTI)

        result = self.run_script(self.render(_shell(task), opt_in=False, requested=3))

        self.assertEqual(result.returncode, 0, result.stderr)
        selected = [gpu["pci"] for gpu in json.loads(result.stdout)]
        self.assertEqual(sorted(selected), [THIRD, FOURTH])


class TheReadinessWait(unittest.TestCase):
    def _run(self, *, attempts: int, interval: int, ready_on: int | None):
        (task,) = _tasks_named(VM_CREATE, WAIT)
        script = _shell(task)
        for template, value in (
            ("{{ vm_setup_wait_attempts }}", str(attempts)),
            ("{{ vm_setup_wait_interval_seconds }}", str(interval)),
            ("{{ vm_name }}", "tenant-guest"),
            ("{{ vm_root_ssh_filename }}", "tenant-guest_root_ed25519"),
            ("{{ vm_ip }}", "192.0.2.7"),
        ):
            script = script.replace(template, value)
        self.assertNotIn("{{", script)
        work = Path(tempfile.mkdtemp(prefix="readiness-wait-"))
        ready = "exit 1" if ready_on is None else (
            f'[ "$(wc -l < "$WORK/ssh")" -ge {ready_on} ] && exit 0; exit 1'
        )
        fakes = {
            "ssh": f'#!/bin/bash\necho "$@" >> "$WORK/ssh"\n{ready}\n',
            "sleep": '#!/bin/bash\necho "$1" >> "$WORK/sleep"\n',
        }
        with fake_binaries(fakes) as fake_bin:
            result = run_bash(script, fake_bin_dir=fake_bin, env=dict(os.environ, WORK=str(work)))
        def lines(name: str) -> list[str]:
            path = work / name
            return path.read_text().splitlines() if path.exists() else []

        return result, len(lines("ssh")), lines("sleep")

    def test_the_defaults_wait_ten_attempts_thirty_seconds_apart(self) -> None:
        defaults = yaml.safe_load(DEFAULTS.read_text(encoding="utf-8"))
        result, attempts, sleeps = self._run(
            attempts=defaults["vm_setup_wait_attempts"],
            interval=defaults["vm_setup_wait_interval_seconds"],
            ready_on=None,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(attempts, 10)
        self.assertEqual(sleeps, ["30"] * 9)
        self.assertIn("within 10 attempts, 30 seconds apart", result.stderr)

    def test_a_pools_longer_wait_is_used_and_names_its_bound_when_it_runs_out(self) -> None:
        result, attempts, sleeps = self._run(attempts=40, interval=15, ready_on=None)

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(attempts, 40)
        self.assertEqual(sleeps, ["15"] * 39)
        self.assertIn("within 40 attempts, 15 seconds apart", result.stderr)
        self.assertIn("vm_setup_wait_attempts, vm_setup_wait_interval_seconds", result.stderr)

    def test_a_guest_confirming_setup_ends_the_wait(self) -> None:
        result, attempts, sleeps = self._run(attempts=40, interval=15, ready_on=3)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((attempts, sleeps), (3, ["15", "15"]))


class TheSettings(unittest.TestCase):
    NAMES = ("vm_passthrough_boot_gpu", "vm_setup_wait_attempts",
             "vm_setup_wait_interval_seconds", "vm_autostart")

    def test_the_defaults_protect_the_boot_gpu_wait_ten_by_thirty_and_autostart(self) -> None:
        self.assertEqual(
            yaml.safe_load(DEFAULTS.read_text(encoding="utf-8")),
            {"vm_passthrough_boot_gpu": False, "vm_setup_wait_attempts": 10,
             "vm_setup_wait_interval_seconds": 30, "vm_autostart": True},
        )

    def test_each_is_type_checked_before_the_creates_first_host_effect(self) -> None:
        tasks = yaml.safe_load(PREREQUISITES.read_text(encoding="utf-8"))
        names = [t.get("name") for t in tasks]
        integers = tasks[names.index("Refuse a pool's readiness wait that is not a positive integer")]
        switches = tasks[names.index("Refuse a pool's GPU guest switch that is not a boolean")]
        self.assertEqual(integers["loop"], ["vm_setup_wait_attempts", "vm_setup_wait_interval_seconds"])
        self.assertEqual(integers["assert"]["that"],
                         ["lookup('vars', item) is integer", "lookup('vars', item) > 0"])
        self.assertEqual(switches["loop"], ["vm_passthrough_boot_gpu", "vm_autostart"])
        self.assertEqual(switches["assert"]["that"], ["lookup('vars', item) is boolean"])
        for check in (integers, switches):
            self.assertEqual(check["when"], 'vm_action == "create"')
            self.assertIn("{{ item }}", check["assert"]["fail_msg"])
            self.assertNotIn("delegate_to", check)
        first_on_the_host = next(i for i, t in enumerate(tasks) if "delegate_to" in t)
        self.assertLess(names.index(switches["name"]), first_on_the_host)
        self.assertLess(names.index(integers["name"]), first_on_the_host)

    def test_the_wait_reads_its_two_settings(self) -> None:
        (task,) = _tasks_named(VM_CREATE, WAIT)
        self.assertIn("MAX_RETRIES={{ vm_setup_wait_attempts }}", task["shell"])
        self.assertIn("INTERVAL={{ vm_setup_wait_interval_seconds }}", task["shell"])
        self.assertNotIn("sleep 30", task["shell"])

    def test_autostart_follows_the_pools_setting(self) -> None:
        (task,) = _tasks_named(VM_CREATE, AUTOSTART)
        self.assertIn("vm_autostart | bool", task["when"])


class OneTestForTheBootGpu(unittest.TestCase):
    SELECTING = (
        (VM_CREATE, "Get all GPUs currently attached to VMs"),
        (VM_CREATE, SELECTOR),
        (VM_CREATE, RETRY_COUNT),
        (VM_CREATE, MULTI),
        *ALTERNATIVES,
    )

    def test_every_task_choosing_a_gpu_includes_the_test_and_reads_the_opt_in(self) -> None:
        for path, name in self.SELECTING:
            for task in _tasks_named(path, name):
                self.assertIn(INCLUDE, _shell(task), name)
                self.assertIn(OPT_IN, _shell(task), name)

    def test_the_boot_gpu_is_read_from_its_own_flag_alone(self) -> None:
        self.assertIn('cat "$PCI_DEVICES/$1/boot_vga"', LIBRARY)
        self.assertIn("PCI_DEVICES=/sys/bus/pci/devices\n", LIBRARY)
        for path in (VM_CREATE, RETRY):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("boot_vga", text, path.name)
            self.assertNotIn("lspci -D -vmm", text, path.name)
            self.assertNotIn("HOST_GPU", text, path.name)

    def test_nothing_in_the_role_binds_or_unbinds_a_device(self) -> None:
        sources = [p for p in ROLE.rglob("*") if p.is_file()]
        for path in sources:
            text = path.read_text(encoding="utf-8")
            for binding in ("/unbind", "/bind", "driver_override", "new_id",
                            "nodedev-detach", "nodedev-reattach", "modprobe"):
                self.assertNotIn(binding, text, f"{path.name}: {binding}")

    def test_the_library_carries_no_template_delimiter(self) -> None:
        for delimiter in ("{{", "{%", "{#"):
            self.assertNotIn(delimiter, LIBRARY)


if __name__ == "__main__":
    unittest.main()
