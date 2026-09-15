"""Every directive the lease units use exists in the target systemd.

The managed profile targets systemd 249 on Ubuntu 22.04. A directive systemd
does not know is not an error: it is logged as an unknown key and ignored, so a
unit that silently drops ``NoNewPrivileges`` still starts and still looks fine.
``systemd-analyze verify`` exits zero in that case too, which is why this test
reads its output rather than its exit status.

This check needs the target toolchain, so it runs in its own lane rather than
on whatever runner the ordinary suite happens to get. The lane sets
``ARKHAI_SYSTEMD_COMPAT_LANE=1`` and provides systemd 249; inside it, a missing
tool or a different version is a failure, never a skip. Outside it the check is
skipped explicitly, because a newer systemd parsing these units would not be
evidence about 249.

The portable assertions about what the units contain live in
``test_bare_metal_lease_runtime_render.py`` and run everywhere.

Nothing here activates a unit.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

try:
    from ansible.template import trust_as_template
except ImportError:  # ansible-core < 2.19 has no trust model
    def trust_as_template(value):
        return value

TEMPLATES = (
    Path(__file__).resolve().parents[1]
    / "ansible" / "roles" / "bare-metal-access" / "templates"
)
GENERATION = "g-7f3a9c21"
TARGET_SYSTEMD = 249
LANE = "ARKHAI_SYSTEMD_COMPAT_LANE"

UNIT_TEMPLATES = {
    "lease.socket.j2": f"arkhai-lease-{GENERATION}.socket",
    "lease-sshd@.service.j2": f"arkhai-lease-{GENERATION}@.service",
    "lease.slice.j2": f"arkhai-lease-{GENERATION}.slice",
    "lease-storage-prepare@.service.j2": (
        "arkhai-lease-storage-prepare@"
        "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef.service"
    ),
}

in_compatibility_lane = pytest.mark.skipif(
    os.environ.get(LANE) != "1",
    reason=(
        f"needs the pinned systemd {TARGET_SYSTEMD} toolchain; set {LANE}=1 in a "
        "runner that provides it. Parsing these units on another version would "
        "not be evidence about the target."
    ),
)


def _render(name: str) -> str:
    templar = Templar(loader=DataLoader(), variables={
        "bare_metal_lease_generation": GENERATION,
        "bare_metal_ssh_user": "arkhai-70f5f19cca87f7e6",
        "bare_metal_lease_buyer_port": 2222,
        "bare_metal_lease_volume_path": f"/var/lib/arkhai/lease-{GENERATION}/volume",
        "bare_metal_lease_view_path": f"/run/arkhai/lease-{GENERATION}/view",
        "bare_metal_lease_netns": f"arkhai-lease-{GENERATION}",
        "bare_metal_lease_gpu_nodes": ["/dev/nvidia0", "/dev/nvidiactl"],
        "bare_metal_lease_sshd_binary": "/usr/sbin/sshd",
        "bare_metal_lease_privsep_user": "sshd",
        "bare_metal_lease_tenant_uid": 61001,
        "bare_metal_lease_tenant_gid": 61001,
        "bare_metal_lease_storage_supervisor_path": (
            "/usr/lib/arkhai/arkhai-supervise-lease-storage"
        ),
        "bare_metal_lease_storage_supervision_profile_path": (
            "/etc/arkhai/lease-storage-supervision.json"
        ),
        "bare_metal_lease_storage_request_root": (
            "/var/lib/arkhai/lease-storage-requests"
        ),
        "bare_metal_lease_storage_state_root": "/var/lib/arkhai/lease-storage",
        "bare_metal_lease_tpm_device": "/dev/tpm0",
        "bare_metal_lease_cryptsetup_path": "/usr/sbin/cryptsetup",
        "bare_metal_lease_cryptsetup_version": "2.4.3",
    })
    return templar.template(trust_as_template((TEMPLATES / name).read_text(encoding="utf-8")))


def _rendered_units(tmp_path: Path) -> list[Path]:
    written = []
    for template, unit_name in UNIT_TEMPLATES.items():
        path = tmp_path / unit_name
        path.write_text(_render(template), encoding="utf-8")
        written.append(path)
    return written


def test_storage_supervision_profile_renders_only_public_fixed_configuration():
    profile = json.loads(_render("lease-storage-supervision.json.j2"))

    assert profile == {
        "schema": "arkhai.lease-storage-supervision.v1",
        "request_root": "/var/lib/arkhai/lease-storage-requests",
        "state_root": "/var/lib/arkhai/lease-storage",
        "tpm_device": "/dev/tpm0",
        "cryptsetup_path": "/usr/sbin/cryptsetup",
        "cryptsetup_version": "2.4.3",
    }
    assert not {"secret", "key", "password", "auth"} & set(profile)


def test_rendered_storage_unit_and_runtime_admission_compose(tmp_path):
    rendered = _render("lease-storage-prepare@.service.j2")
    request_id = "a" * 64
    unit_name = f"arkhai-lease-storage-prepare@{request_id}.service"
    slice_lines = [line for line in rendered.splitlines() if line.startswith("Slice=")]
    assert slice_lines == ["Slice=system.slice"]
    slice_name = slice_lines[0].partition("=")[2]

    supervisor_path = (
        TEMPLATES.parent / "files" / "arkhai-supervise-lease-storage.py"
    )
    spec = importlib.util.spec_from_file_location(
        "composed_storage_supervisor", supervisor_path
    )
    assert spec and spec.loader
    supervisor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(supervisor)

    proc = tmp_path / "proc"
    cgroups = tmp_path / "cgroup"
    (proc / "self").mkdir(parents=True)
    (proc / "sys" / "kernel").mkdir(parents=True)
    relative = Path(slice_name) / unit_name
    (cgroups / relative).mkdir(parents=True)
    (proc / "self" / "status").write_text("NoNewPrivs:\t1\n")
    (proc / "self" / "cgroup").write_text(f"0::/{relative}\n")
    (proc / "sys" / "kernel" / "core_pattern").write_text("core\n")
    (cgroups / relative / "memory.swap.max").write_text("0\n")

    supervisor.assert_runtime_controls(
        request_id,
        proc_root=proc,
        cgroup_root=cgroups,
        effective_uid=0,
        core_limit=(0, 0),
    )


def _local_systemd_version() -> int:
    output = subprocess.run(
        ["systemd-analyze", "--version"], capture_output=True, text=True, timeout=30
    ).stdout
    match = re.search(r"systemd (\d+)", output)
    assert match, f"cannot read the systemd version from {output!r}"
    return int(match.group(1))


@in_compatibility_lane
def test_the_lane_provides_the_target_systemd():
    """In the lane the toolchain is a requirement, so its absence fails."""
    assert shutil.which("systemd-analyze"), (
        "the compatibility lane must provide systemd-analyze; a missing tool is "
        "a lane defect, not a reason to pass"
    )
    assert _local_systemd_version() == TARGET_SYSTEMD, (
        f"the lane provided systemd {_local_systemd_version()}, not "
        f"{TARGET_SYSTEMD}; parsing on another version is not evidence about "
        "the target profile"
    )


@in_compatibility_lane
def test_systemd_reports_no_unknown_key_in_the_rendered_units(tmp_path):
    units = _rendered_units(tmp_path)

    completed = subprocess.run(
        ["systemd-analyze", "verify", *[str(unit) for unit in units]],
        capture_output=True,
        text=True,
        timeout=120,
    )

    # verify exits zero even when it ignores a key, so the output is the check.
    # It also reports on system units it loads, which are not ours.
    ours = [
        line
        for line in (completed.stdout + completed.stderr).splitlines()
        if str(tmp_path) in line
    ]
    unknown = [line for line in ours if "Unknown key name" in line]
    assert not unknown, "systemd does not know these directives:\n" + "\n".join(unknown)
