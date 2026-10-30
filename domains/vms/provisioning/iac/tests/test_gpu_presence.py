"""Behavioral coverage for host preparation's GPU-presence probe.

Presence decides whether a host's boot configuration is changed for
passthrough, so a false positive changes the boot of a machine reachable only
over its network for nothing, and a false negative leaves a GPU host
unprepared. These tests run the probe's real embedded script against fixture
sysfs trees through `shell_harness`, as `test_passthrough_audit.py` does for
the audit.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

import yaml

from shell_harness import assert_bash_syntax_valid, run_bash

ROOT = Path(__file__).resolve().parents[1]
PRESENCE_TASK = ROOT / "ansible/roles/vm-setup/tasks/gpu-presence.yml"

# Class codes and vendors as sysfs reports them.
VGA = "0x030000"
DISPLAY_3D = "0x030200"
AUDIO = "0x040300"
ETHERNET = "0x020000"
NVIDIA = "0x10de"
AMD = "0x1002"
ASPEED = "0x1a03"
QEMU_VGA = "0x1234"
INTEL_NIC = "0x8086"


def _probe_script() -> str:
    tasks = yaml.safe_load(PRESENCE_TASK.read_text(encoding="utf-8"))
    (probe,) = [task for task in tasks if "shell" in task]
    return probe["shell"]["cmd"]


class Sysfs:
    """A fake sysfs tree of PCI devices, each with a class and a vendor."""

    def __init__(self, tmp: str) -> None:
        self.root = Path(tmp) / "sys"
        (self.root / "bus/pci/devices").mkdir(parents=True)

    def device(self, addr: str, cls: str, vendor: str) -> "Sysfs":
        path = self.root / "bus/pci/devices" / addr
        path.mkdir()
        (path / "class").write_text(cls + "\n")
        (path / "vendor").write_text(vendor + "\n")
        return self


class TestGpuPresence(unittest.TestCase):
    def _present(self, build) -> bool:
        with tempfile.TemporaryDirectory() as tmp:
            sysfs = build(Sysfs(tmp))
            env = dict(os.environ)
            env["SYSFS_ROOT"] = str(sysfs.root)
            result = run_bash(_probe_script(), env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(result.stdout.strip(), {"true", "false"}, result.stdout)
        return result.stdout.strip() == "true"

    def test_the_script_parses(self) -> None:
        assert_bash_syntax_valid(_probe_script())

    def test_an_nvidia_display_controller_is_a_gpu(self) -> None:
        self.assertTrue(self._present(lambda s: s.device("0000:01:00.0", VGA, NVIDIA)))

    def test_an_amd_3d_controller_is_a_gpu(self) -> None:
        self.assertTrue(
            self._present(lambda s: s.device("0000:41:00.0", DISPLAY_3D, AMD))
        )

    def test_a_management_controllers_display_is_no_gpu(self) -> None:
        self.assertFalse(self._present(lambda s: s.device("0000:03:00.0", VGA, ASPEED)))

    def test_an_emulated_display_is_no_gpu(self) -> None:
        self.assertFalse(
            self._present(lambda s: s.device("0000:00:02.0", VGA, QEMU_VGA))
        )

    def test_a_host_with_no_display_device_has_no_gpu(self) -> None:
        self.assertFalse(
            self._present(lambda s: s.device("0000:00:03.0", ETHERNET, INTEL_NIC))
        )

    def test_a_host_with_no_pci_devices_has_no_gpu(self) -> None:
        self.assertFalse(self._present(lambda s: s))

    def test_a_gpus_audio_function_alone_is_no_gpu(self) -> None:
        self.assertFalse(self._present(lambda s: s.device("0000:01:00.1", AUDIO, NVIDIA)))

    def test_a_gpu_beside_a_management_controller_is_found(self) -> None:
        self.assertTrue(
            self._present(
                lambda s: s.device("0000:03:00.0", VGA, ASPEED)
                .device("0000:41:00.0", DISPLAY_3D, NVIDIA)
            )
        )


if __name__ == "__main__":
    unittest.main()
