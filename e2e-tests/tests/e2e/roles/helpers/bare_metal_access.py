"""What the real-host bare-metal deal asks of the installed buyer commands and SSH.

The scenario recovers a purchase through ``market bare-metal result``, ``access``,
and ``teardown``, each bound to the run ``buy`` recorded by ``--run-id``, and each
printing its JSON view with no flag. Teardown is one idempotent command: its first
call asks the site to end the lease, and each later call answers the lifecycle's
``state`` as provisioning reports it, until the storefront records ``released`` on
the site's capacity-released callback.

Access is judged by fresh SSH processes against a host key the operator pinned, so
an attempt cannot ride a shared connection or a host it does not know, and only an
authentication refusal from that host proves access was revoked.
"""

from __future__ import annotations

import enum
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

#: The commands that recover a recorded bare-metal purchase by its run.
RECOVERY_COMMANDS = ("result", "access", "teardown")

#: The lifecycle state the storefront records once the site has released the lease.
RELEASED = "released"
#: The lifecycle state of a teardown that failed; its capacity stays held.
TEARDOWN_FAILED = "teardown_failed"

#: What the access probe prints on the delivered host.
ACCESS_PROBE_OUTPUT = "arkhai-bare-metal-access-ok"

#: The events a completed ``buy`` records in its run log, in order. ``buy`` settles
#: through Arkhai payments alone, so its one settlement event is the approval; the
#: bare-metal buyer's run-log test pins the same sequence on the producer's side.
BUY_EVENTS = ("run_started", "agreement_accepted", "payment_approved", "run_ended")
#: The status a completed purchase's ``run_ended`` records.
BUY_AGREED = "agreed"


def assert_purchase_recorded(events: Sequence[Mapping[str, Any]]) -> None:
    """``events`` are a completed purchase's: its events in order, ending agreed."""
    names = [event.get("event") for event in events]
    remaining = iter(names)
    if not all(expected in remaining for expected in BUY_EVENTS):
        raise AssertionError(f"buy recorded {names!r}, not {list(BUY_EVENTS)!r} in order")
    ended = [event for event in events if event.get("event") == "run_ended"]
    if ended[-1].get("status") != BUY_AGREED:
        raise AssertionError(
            f"buy's run ended {ended[-1].get('status')!r}, not {BUY_AGREED!r}"
        )


def recovery_command(command: str, run_id: str) -> tuple[str, ...]:
    """The ``market`` arguments recovering ``run_id`` through ``command``."""
    if command not in RECOVERY_COMMANDS:
        raise ValueError(f"{command!r} is not a bare-metal recovery command")
    if not run_id:
        raise ValueError("a recovery command needs the run id buy recorded")
    return ("bare-metal", command, "--run-id", run_id)


def wait_for_release(
    teardown: Callable[[], Mapping[str, Any]],
    *,
    timeout_seconds: float,
    poll_interval_seconds: float,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> Mapping[str, Any]:
    """Run ``teardown`` until its lifecycle is ``released``, and return that view.

    Each call is the same idempotent command, so the first requests the teardown
    and the rest observe it. A failed teardown stops the wait at once rather than
    waiting out the bound, since nothing will release its capacity.
    """
    deadline = clock() + timeout_seconds
    while True:
        view = teardown()
        state = view.get("state")
        if state == RELEASED:
            return view
        if state == TEARDOWN_FAILED:
            raise AssertionError(
                "bare-metal teardown failed: state "
                f"{state!r}, failure_reason {view.get('failure_reason')!r}"
            )
        if clock() >= deadline:
            raise AssertionError(
                f"bare-metal teardown did not reach {RELEASED!r} within "
                f"{timeout_seconds}s; last state {state!r}"
            )
        sleep(poll_interval_seconds)


def ssh_command(
    access: Mapping[str, Any],
    *,
    private_key_file: Path,
    known_hosts_file: Path,
) -> list[str]:
    """One fresh, non-interactive SSH attempt with only the role's key.

    It reads no configuration file and shares no connection, so a master socket
    left by an earlier attempt cannot answer for it, and it trusts only the host
    key the operator pinned.
    """
    host = str(access.get("host") or "")
    username = str(access.get("username") or "")
    if not host or not username:
        raise AssertionError("authenticated access view omitted host or username")
    port = int(access.get("port") or 22)
    options = (
        "BatchMode=yes",
        "ConnectTimeout=10",
        "ControlMaster=no",
        "ControlPath=none",
        "IdentitiesOnly=yes",
        "IdentityAgent=none",
        "PreferredAuthentications=publickey",
        "PasswordAuthentication=no",
        "KbdInteractiveAuthentication=no",
        "StrictHostKeyChecking=yes",
        f"UserKnownHostsFile={known_hosts_file}",
        "GlobalKnownHostsFile=/dev/null",
        "UpdateHostKeys=no",
    )
    command = ["ssh", "-F", "none", "-i", str(private_key_file), "-p", str(port)]
    for option in options:
        command += ["-o", option]
    return [*command, f"{username}@{host}", f"printf {ACCESS_PROBE_OUTPUT}"]


class SshOutcome(enum.Enum):
    """What one SSH attempt proved about the tenant's access."""

    ACCEPTED = "accepted"
    REFUSED = "refused"


def classify_ssh(returncode: int, stdout: str, stderr: str) -> SshOutcome:
    """Read one attempt as access accepted or refused by authentication.

    SSH exits 255 for its own failures, a refused connection, a timeout, and a
    host-key mismatch among them, so the exit status alone cannot tell a revoked
    key from a host that could not be reached. Only the server's refusal of the
    public key proves revocation; every other failure is raised, never counted
    as revoked.
    """
    if returncode == 0 and stdout == ACCESS_PROBE_OUTPUT:
        return SshOutcome.ACCEPTED
    if returncode == 255 and "Permission denied" in stderr and "publickey" in stderr:
        return SshOutcome.REFUSED
    raise AssertionError(
        f"SSH attempt proved neither access nor revocation: exit {returncode}, "
        f"stderr {stderr.strip()[-300:]!r}"
    )


def forbidden_flags(arguments: Sequence[str], flags: Sequence[str]) -> list[str]:
    """Which of ``flags`` the arguments name, alone or as ``flag=value``."""
    lowered = tuple(argument.lower() for argument in arguments)
    return [
        flag
        for flag in flags
        if any(argument == flag or argument.startswith(flag + "=") for argument in lowered)
    ]


__all__ = [
    "ACCESS_PROBE_OUTPUT",
    "BUY_AGREED",
    "BUY_EVENTS",
    "RECOVERY_COMMANDS",
    "RELEASED",
    "TEARDOWN_FAILED",
    "SshOutcome",
    "assert_purchase_recorded",
    "classify_ssh",
    "forbidden_flags",
    "recovery_command",
    "ssh_command",
    "wait_for_release",
]
