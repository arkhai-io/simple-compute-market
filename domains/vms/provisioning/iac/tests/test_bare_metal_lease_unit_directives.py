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
    })
    return templar.template(trust_as_template((TEMPLATES / name).read_text(encoding="utf-8")))


def _rendered_units(tmp_path: Path) -> list[Path]:
    written = []
    for template, unit_name in UNIT_TEMPLATES.items():
        path = tmp_path / unit_name
        path.write_text(_render(template), encoding="utf-8")
        written.append(path)
    return written


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
