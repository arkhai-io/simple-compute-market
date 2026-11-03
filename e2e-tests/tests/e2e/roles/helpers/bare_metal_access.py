"""What the real-host bare-metal deal asks of installed buyer commands.

The scenario recovers a purchase through ``market bare-metal result``, ``access``,
and ``teardown``, each bound to the run ``buy`` recorded by ``--run-id``, and each
printing its JSON view with no flag. Teardown is one idempotent command: its first
call asks the site to end the lease, and each later call answers the lifecycle's
``state`` as provisioning reports it, until the storefront records ``released`` on
the site's capacity-released callback.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

#: The commands that recover a recorded bare-metal purchase by its run.
RECOVERY_COMMANDS = ("result", "access", "teardown")

#: The lifecycle state the storefront records once the site has released the lease.
RELEASED = "released"
#: The lifecycle state of a teardown that failed; its capacity stays held.
TEARDOWN_FAILED = "teardown_failed"

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


def forbidden_flags(arguments: Sequence[str], flags: Sequence[str]) -> list[str]:
    """Which of ``flags`` the arguments name, alone or as ``flag=value``."""
    lowered = tuple(argument.lower() for argument in arguments)
    return [
        flag
        for flag in flags
        if any(argument == flag or argument.startswith(flag + "=") for argument in lowered)
    ]


__all__ = [
    "BUY_AGREED",
    "BUY_EVENTS",
    "RECOVERY_COMMANDS",
    "RELEASED",
    "TEARDOWN_FAILED",
    "assert_purchase_recorded",
    "forbidden_flags",
    "recovery_command",
    "wait_for_release",
]
