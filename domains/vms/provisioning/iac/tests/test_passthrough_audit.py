"""Behavioral coverage for the passthrough audit's classifier.

The audit decides whether a GPU can be handed to a guest without taking a
device the host needs with it. Getting that wrong in the permissive direction
strands a rented machine: the binding is applied to a network controller and
the host loses its only route, with no in-band path back.

Substring assertions over the task YAML cannot prove a classifier classifies,
so these tests run the audit's real embedded script against fixture sysfs
trees, with ``lspci``, ``ip``, ``findmnt``, and ``lsblk`` faked through PATH by
`shell_harness` — the same technique `test_gpu_attachment_discovery.py` uses.

The fixtures describe IOMMU topologies rather than machines: a card alone in
its group, a card with its own audio function, a card behind a bridge, and a
card grouped with the onboard NICs.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from shell_harness import (
    assert_bash_syntax_valid,
    extract_between,
    fake_binaries,
    run_bash,
)


def _unit_directives(text: str) -> str:
    """Directive lines only.

    The unit explains in comments which dependency types it deliberately does
    not declare, so a literal search over the whole file matches the prose that
    says a directive is absent. Assertions here are about what systemd reads.
    """
    return "\n".join(
        line for line in text.splitlines() if not line.strip().startswith("#")
    )

ROOT = Path(__file__).resolve().parents[1]
AUDIT_TASK = ROOT / "ansible/roles/vm-setup/tasks/passthrough-audit.yml"

_SCRIPT_START = "      python3 - <<'PY'\n"
_SCRIPT_END = "\n      PY\n"


def _audit_script() -> str:
    """Return the audit's embedded script, de-indented, as bash would see it."""
    text = AUDIT_TASK.read_text(encoding="utf-8")
    body = extract_between(text, _SCRIPT_START, _SCRIPT_END)
    lines = [line[6:] if line.startswith(" " * 6) else line for line in body.splitlines()]
    return "python3 - <<'PY'\n" + "\n".join(lines) + "\nPY\n"


# Class codes as sysfs reports them, in the `0x` form the audit parses.
VGA = "0x030000"
AUDIO = "0x040300"
USB = "0x0c0300"
UCSI = "0x0c8000"
BRIDGE = "0x060400"
ETHERNET = "0x020000"
NVME = "0x010802"


class Fixture:
    """A fake sysfs tree describing PCI devices and their IOMMU groups."""

    def __init__(self, tmp: str) -> None:
        self.root = Path(tmp) / "sys"
        (self.root / "class/iommu").mkdir(parents=True)
        (self.root / "bus/pci/devices").mkdir(parents=True)
        (self.root / "kernel/iommu_groups").mkdir(parents=True)
        (self.root / "class/net").mkdir(parents=True)
        (self.root / "block").mkdir(parents=True)
        self._devices_dir = self.root / "devices"
        self._devices_dir.mkdir()

    def enable_iommu(self) -> "Fixture":
        (self.root / "class/iommu/dmar0").mkdir()
        return self

    def device(self, addr: str, cls: str, vendor: str, device: str,
               driver: str | None = None) -> "Fixture":
        path = self.root / "bus/pci/devices" / addr
        path.mkdir(parents=True)
        (path / "class").write_text(cls)
        (path / "vendor").write_text(vendor)
        (path / "device").write_text(device)
        if driver is not None:
            driver_dir = self.root / "bus/pci/drivers" / driver
            driver_dir.mkdir(parents=True, exist_ok=True)
            (path / "driver").symlink_to(driver_dir)
        # A real device also lives under /sys/devices; the audit walks a
        # resolved path back to a PCI address for the route and root lookups.
        (self._devices_dir / addr).mkdir(exist_ok=True)
        return self

    def group(self, number: str, addrs: list[str]) -> "Fixture":
        devices = self.root / "kernel/iommu_groups" / number / "devices"
        devices.mkdir(parents=True)
        for addr in addrs:
            (devices / addr).symlink_to(self.root / "bus/pci/devices" / addr)
        return self

    def interface(self, name: str, addr: str) -> "Fixture":
        iface = self.root / "class/net" / name
        iface.mkdir(parents=True)
        (iface / "device").symlink_to(self._devices_dir / addr)
        return self

    def block_device(self, name: str, addr: str) -> "Fixture":
        (self.root / "block" / name).symlink_to(self._devices_dir / addr)
        return self


def fakes(route_iface: str = "eno1", root_source: str = "/dev/nvme0n1p2",
          root_parent: str = "nvme0n1", lspci: str = "") -> dict[str, str]:
    return {
        "ip": f"#!/bin/sh\necho '1.1.1.1 via 10.0.0.1 dev {route_iface} src 10.0.0.5'\n",
        "findmnt": (
            "#!/bin/sh\n"
            f"case \"$*\" in *UUID*) echo 'abcd-1234' ;; *) echo '{root_source}' ;; esac\n"
        ),
        "lsblk": f"#!/bin/sh\necho '{root_parent}'\n",
        "lspci": f"#!/bin/sh\ncat <<'EOF'\n{lspci}EOF\n",
    }


def audit(fixture: Fixture, binaries: dict[str, str]) -> dict:
    with fake_binaries(binaries) as bin_dir:
        env = dict(os.environ)
        env["SYSFS_ROOT"] = str(fixture.root)
        result = run_bash(_audit_script(), fake_bin_dir=bin_dir, env=env)
    if result.returncode != 0:
        raise AssertionError(f"audit failed:\n{result.stderr}")
    return json.loads(result.stdout)


def gpu(report: dict, addr: str) -> dict:
    for entry in report["gpus"]:
        if entry["address"] == addr:
            return entry
    raise AssertionError(f"{addr} not reported as a GPU: {report['gpus']}")


class TestAuditSyntax(unittest.TestCase):
    def test_embedded_script_parses(self) -> None:
        assert_bash_syntax_valid(_audit_script())


class TestBindableTopologies(unittest.TestCase):
    def test_gpu_alone_in_its_group_is_bindable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = (Fixture(tmp).enable_iommu()
                  .device("0000:01:00.0", VGA, "0x10de", "0x2204", driver="nouveau")
                  .device("0000:02:00.0", ETHERNET, "0x14e4", "0x165f", driver="tg3")
                  .device("0000:00:17.0", NVME, "0x8086", "0xa282", driver="nvme")
                  .group("14", ["0000:01:00.0"])
                  .group("2", ["0000:02:00.0"])
                  .group("3", ["0000:00:17.0"])
                  .interface("eno1", "0000:02:00.0")
                  .block_device("nvme0n1", "0000:00:17.0"))
            report = audit(fx, fakes())

        self.assertTrue(report["assessable"])
        self.assertTrue(gpu(report, "0000:01:00.0")["bindable"])
        self.assertEqual(report["bind_addresses"], ["0000:01:00.0"])

    def test_gpu_with_audio_function_binds_both(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = (Fixture(tmp).enable_iommu()
                  .device("0000:01:00.0", VGA, "0x10de", "0x2204")
                  .device("0000:01:00.1", AUDIO, "0x10de", "0x1aef")
                  .device("0000:02:00.0", ETHERNET, "0x14e4", "0x165f", driver="tg3")
                  .group("14", ["0000:01:00.0", "0000:01:00.1"])
                  .group("2", ["0000:02:00.0"])
                  .interface("eno1", "0000:02:00.0"))
            report = audit(fx, fakes())

        entry = gpu(report, "0000:01:00.0")
        self.assertTrue(entry["bindable"])
        self.assertEqual(
            report["bind_addresses"], ["0000:01:00.0", "0000:01:00.1"]
        )

    def test_turing_usb_and_ucsi_functions_are_companions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = (Fixture(tmp).enable_iommu()
                  .device("0000:01:00.0", VGA, "0x10de", "0x1e04")
                  .device("0000:01:00.1", AUDIO, "0x10de", "0x10f7")
                  .device("0000:01:00.2", USB, "0x10de", "0x1ad6")
                  .device("0000:01:00.3", UCSI, "0x10de", "0x1ad7")
                  .device("0000:02:00.0", ETHERNET, "0x14e4", "0x165f")
                  .group("14", ["0000:01:00.0", "0000:01:00.1",
                                "0000:01:00.2", "0000:01:00.3"])
                  .group("2", ["0000:02:00.0"])
                  .interface("eno1", "0000:02:00.0"))
            report = audit(fx, fakes())

        self.assertTrue(gpu(report, "0000:01:00.0")["bindable"])
        self.assertEqual(len(report["bind_addresses"]), 4)

    def test_bridge_in_group_is_not_a_blocker_and_is_not_bound(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = (Fixture(tmp).enable_iommu()
                  .device("0000:00:01.0", BRIDGE, "0x8086", "0x1901")
                  .device("0000:01:00.0", VGA, "0x10de", "0x2204")
                  .device("0000:02:00.0", ETHERNET, "0x14e4", "0x165f")
                  .group("14", ["0000:00:01.0", "0000:01:00.0"])
                  .group("2", ["0000:02:00.0"])
                  .interface("eno1", "0000:02:00.0"))
            report = audit(fx, fakes())

        entry = gpu(report, "0000:01:00.0")
        self.assertTrue(entry["bindable"])
        self.assertEqual(report["bind_addresses"], ["0000:01:00.0"])
        roles = {m["address"]: m["role"] for m in entry["members"]}
        self.assertEqual(roles["0000:00:01.0"], "bridge")


class TestBlockedTopologies(unittest.TestCase):
    def test_gpu_grouped_with_a_network_controller_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = (Fixture(tmp).enable_iommu()
                  .device("0000:01:00.0", VGA, "0x10de", "0x2204")
                  .device("0000:02:00.0", ETHERNET, "0x14e4", "0x165f", driver="tg3")
                  .group("14", ["0000:01:00.0", "0000:02:00.0"])
                  .interface("eno1", "0000:02:00.0"))
            report = audit(fx, fakes())

        entry = gpu(report, "0000:01:00.0")
        self.assertFalse(entry["bindable"])
        self.assertEqual(entry["bind_addresses"], [])
        self.assertEqual(report["bind_addresses"], [])
        self.assertTrue(
            any("0000:02:00.0" in b for b in entry["blockers"]),
            entry["blockers"],
        )

    def test_incident_topology_is_refused_and_leaks_no_nic_id(self) -> None:
        """The exact grouping that stranded a rented host.

        GPU 01:00.0 grouped with two Broadcom NICs and the ASPEED bridge and
        VGA, one NIC carrying the default route. The regression that matters is
        not only the verdict but that no NIC vendor:device reaches the bind
        list: a vendor-scoped bind claims every device with that ID in the
        machine, which is how one group's contents cost a host all networking.
        """
        with tempfile.TemporaryDirectory() as tmp:
            fx = (Fixture(tmp).enable_iommu()
                  .device("0000:01:00.0", VGA, "0x10de", "0x2204")
                  .device("0000:02:00.0", ETHERNET, "0x14e4", "0x165f", driver="tg3")
                  .device("0000:02:00.1", ETHERNET, "0x14e4", "0x165f", driver="tg3")
                  .device("0000:03:00.0", BRIDGE, "0x1a03", "0x1150")
                  .device("0000:04:00.0", VGA, "0x1a03", "0x2000", driver="ast")
                  .group("14", ["0000:01:00.0", "0000:02:00.0", "0000:02:00.1",
                                "0000:03:00.0", "0000:04:00.0"])
                  .interface("eno1", "0000:02:00.0"))
            report = audit(fx, fakes())

        entry = gpu(report, "0000:01:00.0")
        self.assertFalse(entry["bindable"])
        self.assertEqual(report["bind_addresses"], [])
        self.assertEqual(report["route_device"], "0000:02:00.0")
        serialized = json.dumps(report["bind_addresses"])
        self.assertNotIn("14e4:165f", serialized)
        self.assertNotIn("0000:02:00.0", serialized)

    def test_route_holding_device_is_named_as_the_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = (Fixture(tmp).enable_iommu()
                  .device("0000:01:00.0", VGA, "0x10de", "0x2204")
                  .device("0000:02:00.0", ETHERNET, "0x14e4", "0x165f")
                  .group("14", ["0000:01:00.0", "0000:02:00.0"])
                  .interface("eno1", "0000:02:00.0"))
            report = audit(fx, fakes())

        members = {m["address"]: m for m in gpu(report, "0000:01:00.0")["members"]}
        self.assertEqual(members["0000:02:00.0"]["role"], "blocker")
        self.assertIn("default route", members["0000:02:00.0"]["reason"])

    def test_root_filesystem_controller_blocks_its_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = (Fixture(tmp).enable_iommu()
                  .device("0000:01:00.0", VGA, "0x10de", "0x2204")
                  .device("0000:00:17.0", NVME, "0x8086", "0xa282", driver="nvme")
                  .device("0000:02:00.0", ETHERNET, "0x14e4", "0x165f")
                  .group("14", ["0000:01:00.0", "0000:00:17.0"])
                  .group("2", ["0000:02:00.0"])
                  .interface("eno1", "0000:02:00.0")
                  .block_device("nvme0n1", "0000:00:17.0"))
            report = audit(fx, fakes())

        entry = gpu(report, "0000:01:00.0")
        self.assertFalse(entry["bindable"])
        self.assertEqual(report["root_device"], "0000:00:17.0")

    def test_unknown_device_class_blocks_rather_than_binds(self) -> None:
        """Fail closed: a class the classifier does not recognise is a blocker."""
        with tempfile.TemporaryDirectory() as tmp:
            fx = (Fixture(tmp).enable_iommu()
                  .device("0000:01:00.0", VGA, "0x10de", "0x2204")
                  .device("0000:01:00.4", "0x0d2000", "0x8086", "0x2723")
                  .device("0000:02:00.0", ETHERNET, "0x14e4", "0x165f")
                  .group("14", ["0000:01:00.0", "0000:01:00.4"])
                  .group("2", ["0000:02:00.0"])
                  .interface("eno1", "0000:02:00.0"))
            report = audit(fx, fakes())

        self.assertFalse(gpu(report, "0000:01:00.0")["bindable"])


class TestMixedAndDegradedMachines(unittest.TestCase):
    def test_clean_and_dirty_groups_are_judged_independently(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = (Fixture(tmp).enable_iommu()
                  .device("0000:01:00.0", VGA, "0x10de", "0x2204")
                  .device("0000:05:00.0", VGA, "0x10de", "0x2204")
                  .device("0000:02:00.0", ETHERNET, "0x14e4", "0x165f")
                  .group("14", ["0000:01:00.0"])
                  .group("15", ["0000:05:00.0", "0000:02:00.0"])
                  .interface("eno1", "0000:02:00.0"))
            report = audit(fx, fakes())

        self.assertTrue(gpu(report, "0000:01:00.0")["bindable"])
        self.assertFalse(gpu(report, "0000:05:00.0")["bindable"])
        self.assertEqual(report["bind_addresses"], ["0000:01:00.0"])

    def test_disabled_iommu_cannot_assess_rather_than_reporting_clean(self) -> None:
        """The two states the previous guards conflated.

        No groups because the IOMMU is off looks identical to no conflicts
        found. They mean opposite things, and only one of them may result in a
        device being bound.
        """
        with tempfile.TemporaryDirectory() as tmp:
            fx = (Fixture(tmp)
                  .device("0000:01:00.0", VGA, "0x10de", "0x2204")
                  .device("0000:02:00.0", ETHERNET, "0x14e4", "0x165f")
                  .interface("eno1", "0000:02:00.0"))
            report = audit(fx, fakes())

        self.assertFalse(report["iommu_enabled"])
        self.assertFalse(report["assessable"])
        self.assertEqual(report["bind_addresses"], [])
        self.assertEqual(report["gpus"], [])
        self.assertIn("reason", report)

    def test_iommu_present_but_no_groups_cannot_assess(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = (Fixture(tmp).enable_iommu()
                  .device("0000:01:00.0", VGA, "0x10de", "0x2204")
                  .interface("eno1", "0000:01:00.0"))
            report = audit(fx, fakes())

        self.assertTrue(report["iommu_enabled"])
        self.assertFalse(report["assessable"])
        self.assertEqual(report["bind_addresses"], [])

    def test_route_device_chosen_among_several_interfaces(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = (Fixture(tmp).enable_iommu()
                  .device("0000:01:00.0", VGA, "0x10de", "0x2204")
                  .device("0000:02:00.0", ETHERNET, "0x14e4", "0x165f")
                  .device("0000:02:00.1", ETHERNET, "0x14e4", "0x165f")
                  .device("0000:06:00.0", ETHERNET, "0x8086", "0x1572")
                  .group("14", ["0000:01:00.0", "0000:02:00.1"])
                  .group("2", ["0000:02:00.0"])
                  .group("6", ["0000:06:00.0"])
                  .interface("eno1", "0000:02:00.0")
                  .interface("eno2", "0000:02:00.1")
                  .interface("ens5", "0000:06:00.0"))
            # The route runs over eno2, whose controller shares the GPU's group.
            report = audit(fx, fakes(route_iface="eno2"))

        self.assertEqual(report["route_device"], "0000:02:00.1")
        self.assertFalse(gpu(report, "0000:01:00.0")["bindable"])

    def test_absent_lspci_degrades_the_report_not_the_verdict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = (Fixture(tmp).enable_iommu()
                  .device("0000:01:00.0", VGA, "0x10de", "0x2204")
                  .device("0000:02:00.0", ETHERNET, "0x14e4", "0x165f")
                  .group("14", ["0000:01:00.0"])
                  .group("2", ["0000:02:00.0"])
                  .interface("eno1", "0000:02:00.0"))
            binaries = fakes()
            binaries["lspci"] = "#!/bin/sh\nexit 127\n"
            report = audit(fx, binaries)

        entry = gpu(report, "0000:01:00.0")
        self.assertTrue(entry["bindable"])
        self.assertEqual(entry["model"], "")
        self.assertEqual(entry["ids"], "10de:2204")


class TestRenderedArtifacts(unittest.TestCase):
    """The unsafe mechanism must be gone from the task files, not just unused."""

    def test_no_vendor_id_binding_remains_in_the_role(self) -> None:
        """No artifact *binds* by vendor ID.

        Checked against non-comment lines only. Several files name the
        mechanism in prose in order to say why it is not used, and a test that
        could be satisfied by rewording a comment would be measuring the wrong
        thing. What must not exist is a directive: a kernel command line
        carrying ``vfio-pci.ids=`` or a modprobe option setting ``ids=``.
        """
        role = ROOT / "ansible/roles/vm-setup"
        offenders = []
        for path in sorted(role.rglob("*")):
            if not path.is_file() or "backup" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for number, line in enumerate(text.splitlines(), start=1):
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if "vfio-pci.ids=" in stripped or "options vfio-pci ids=" in stripped:
                    offenders.append(f"{path.relative_to(ROOT)}:{number}: {stripped}")
        self.assertEqual(offenders, [])

    def test_the_removal_of_stale_command_line_binding_is_present(self) -> None:
        """A host prepared before this mechanism carries a stale ids= list.

        Removing the tasks that wrote it does not remove it from a machine that
        already has it, so the role must actively strip it.
        """
        text = (ROOT / "ansible/roles/vm-setup/tasks/gpu-passthrough.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("vfio-pci\\.(ids|disable_vga)=", text)
        self.assertIn("/etc/modprobe.d/vfio.conf", text)
        self.assertIn("state: absent", text)

    def test_rescue_entry_does_not_inherit_the_current_command_line(self) -> None:
        """The rollback target must not carry whatever the host already had.

        Inheriting ``GRUB_CMDLINE_LINUX_DEFAULT`` would reproduce a stale
        ``vfio-pci.ids`` inside the entry that exists to escape it.
        """
        text = (ROOT / "ansible/roles/vm-setup/templates/09_rescue_novfio.j2").read_text(
            encoding="utf-8"
        )
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            self.assertNotIn("GRUB_CMDLINE_LINUX_DEFAULT", stripped)
            self.assertNotIn("GRUB_CMDLINE_LINUX", stripped)

    def test_bind_script_honours_the_rescue_token(self) -> None:
        text = (ROOT / "ansible/roles/vm-setup/templates/vfio-bind.sh.j2").read_text(
            encoding="utf-8"
        )
        self.assertIn("/proc/cmdline", text)
        self.assertIn("rescue_cmdline_token", text)

    def test_bind_service_does_not_take_libvirtd_down_with_it(self) -> None:
        """A failed bind degrades capacity; it must not disable virtualization."""
        directives = _unit_directives(
            (ROOT / "ansible/roles/vm-setup/templates/vfio-bind.service.j2")
            .read_text(encoding="utf-8")
        )
        self.assertIn("Before=libvirtd.service", directives)
        self.assertNotIn("Requires=", directives)
        self.assertNotIn("BindsTo=", directives)


class TestCapacityReflectsPassthrough(unittest.TestCase):
    """A host publishes the GPUs it can actually hand to a guest.

    Counting every card present over-reports capacity on a machine where some
    cards share an IOMMU group with a device the host needs: those cards stay
    on their normal driver, and a create job asking for one cannot succeed.
    """

    _COUNT_START = "- name: Get total GPU count\n  shell: |\n"
    _COUNT_END = "\n  register: host_total_gpus\n"

    def _count_script(self) -> str:
        text = (ROOT / "ansible/roles/vm-management/tasks/vm-check.yml").read_text(
            encoding="utf-8"
        )
        body = extract_between(text, self._COUNT_START, self._COUNT_END)
        return "\n".join(
            line[4:] if line.startswith(" " * 4) else line
            for line in body.splitlines()
        )

    def _count(self, fixture: Fixture) -> int:
        with fake_binaries(fakes()) as bin_dir:
            env = dict(os.environ)
            env["SYSFS_ROOT"] = str(fixture.root)
            result = run_bash(self._count_script(), fake_bin_dir=bin_dir, env=env)
        if result.returncode != 0:
            raise AssertionError(f"count failed:\n{result.stderr}")
        return int(result.stdout.strip().splitlines()[-1])

    def test_count_script_parses(self) -> None:
        assert_bash_syntax_valid(self._count_script())

    def test_bound_gpu_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = (Fixture(tmp)
                  .device("0000:01:00.0", VGA, "0x10de", "0x2204", driver="vfio-pci"))
            self.assertEqual(self._count(fx), 1)

    def test_unbound_gpu_does_not_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = (Fixture(tmp)
                  .device("0000:01:00.0", VGA, "0x10de", "0x2204", driver="nouveau"))
            self.assertEqual(self._count(fx), 0)

    def test_only_bound_cards_of_a_mixed_host_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = (Fixture(tmp)
                  .device("0000:01:00.0", VGA, "0x10de", "0x2204", driver="vfio-pci")
                  .device("0000:05:00.0", VGA, "0x10de", "0x2204", driver="nouveau"))
            self.assertEqual(self._count(fx), 1)

    def test_companion_functions_are_not_counted_separately(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = (Fixture(tmp)
                  .device("0000:01:00.0", VGA, "0x10de", "0x2204", driver="vfio-pci")
                  .device("0000:01:00.1", AUDIO, "0x10de", "0x1aef", driver="vfio-pci"))
            self.assertEqual(self._count(fx), 1)

    def test_non_gpu_vfio_device_is_not_counted_as_a_gpu(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = (Fixture(tmp)
                  .device("0000:02:00.0", ETHERNET, "0x14e4", "0x165f", driver="vfio-pci"))
            self.assertEqual(self._count(fx), 0)

    def test_host_with_no_passthrough_capable_card_reports_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = (Fixture(tmp)
                  .device("0000:01:00.0", VGA, "0x10de", "0x2204", driver="nouveau")
                  .device("0000:04:00.0", VGA, "0x1a03", "0x2000", driver="ast"))
            self.assertEqual(self._count(fx), 0)


if __name__ == "__main__":
    unittest.main()
