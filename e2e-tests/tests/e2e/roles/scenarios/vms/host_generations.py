"""Whether a VM host's services kept their process generation across reads.

The VM qualification reads the host's diagnostics before, during and after a
second guest is created and removed beside a first one
(``vm_provisioning_operator.HostDiagnostics``). Its pass criterion:

- the operator's management unit keeps one invocation ID, stays active and adds
  no restarts across every read;
- libvirtd adds no restarts and has no failed result across every read, and
  keeps one invocation ID across the reads taken while the first guest runs.
  It is socket-activated and may exit when idle, and a read can itself start
  it, so a new generation between reads with no guest running is not a
  restart.

Each check returns its faults, each naming the read and the unit, so a stage
fails naming every change at once.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

#: The result systemd records for a unit whose last run ended cleanly.
CLEAN_RESULT = "success"


@dataclass(frozen=True)
class DiagnosticsRead:
    """One read of the host's diagnostics, and when it was taken."""

    #: Where in the scenario it was taken, as a failure names it.
    label: str
    #: The typed diagnostics (``HostDiagnostics``).
    diagnostics: Any
    #: Whether the first guest was running when it was taken.
    first_guest_running: bool


def management_unit_faults(reads: Sequence[DiagnosticsRead], unit: str) -> list[str]:
    """How the management unit failed to keep one active generation."""
    faults = []
    first = None
    for read in reads:
        state = read.diagnostics.management
        if state is None:
            faults.append(f"{read.label}: {unit} was not reported")
            continue
        if state.active_state != "active":
            faults.append(
                f"{read.label}: {unit} is {state.active_state!r}, not active (a unit "
                "systemd has not loaded, such as a misspelt name, also reads inactive)"
            )
        if first is None:
            first = state
            continue
        if state.invocation_id != first.invocation_id:
            faults.append(
                f"{read.label}: {unit}'s invocation changed from {first.invocation_id!r} "
                f"to {state.invocation_id!r}"
            )
        if state.restart_count > first.restart_count:
            faults.append(
                f"{read.label}: {unit} restarted {state.restart_count - first.restart_count} "
                "time(s) since the first read"
            )
    return faults


def libvirtd_faults(reads: Sequence[DiagnosticsRead], unit: str = "libvirtd.service") -> list[str]:
    """How libvirtd failed to keep its generation where the criterion asks it to."""
    faults = []
    first = reads[0].diagnostics.libvirtd if reads else None
    running_invocation = None
    for read in reads:
        state = read.diagnostics.libvirtd
        if state.restart_count > first.restart_count:
            faults.append(
                f"{read.label}: {unit} restarted {state.restart_count - first.restart_count} "
                "time(s) since the first read"
            )
        if state.result != CLEAN_RESULT:
            faults.append(f"{read.label}: {unit}'s result is {state.result!r}, not {CLEAN_RESULT!r}")
        if not read.first_guest_running:
            continue
        if running_invocation is None:
            running_invocation = state.invocation_id
        elif state.invocation_id != running_invocation:
            faults.append(
                f"{read.label}: {unit}'s invocation changed from {running_invocation!r} to "
                f"{state.invocation_id!r} while the first guest ran"
            )
    return faults
