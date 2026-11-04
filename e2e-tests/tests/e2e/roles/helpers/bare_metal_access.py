"""What the real-host bare-metal deal asks of installed buyer commands.

The scenario recovers a purchase through ``market bare-metal result``, ``access``,
``teardown`` and ``delivery``, each bound to the run ``buy`` recorded by ``--run-id``,
and each printing its JSON view with no flag. Teardown is the buyer's end of
delivery through the lifecycle client: one idempotent surrender the storefront
acknowledges with a signed receipt. Delivery is the buyer's read of the deal: its
``delivery.progress`` is what the storefront records, ``tearing_down`` from the
acknowledged end until the site's capacity-released callback records ``released``,
and its ``site_reports`` are the site-signed intended-end reports the storefront
retained, which a proven release must carry.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

#: The commands that recover a recorded bare-metal purchase by its run.
RECOVERY_COMMANDS = ("result", "access", "teardown", "delivery")

#: The delivery progress the storefront records once the site has released the lease.
RELEASED = "released"
#: The delivery progress of an end the storefront cannot converge; its capacity stays
#: held until an operator repairs it.
REPAIR_REQUIRED = "repair_required"

#: The events a completed ``buy`` records in its run log, in order. ``buy`` settles
#: through Arkhai payments alone, so its one settlement event is the approval; the
#: bare-metal buyer's run-log test pins the same sequence on the producer's side.
BUY_EVENTS = ("run_started", "negotiation_completed", "payment_approved", "run_ended")
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
    delivery: Callable[[], Mapping[str, Any]],
    *,
    timeout_seconds: float,
    poll_interval_seconds: float,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> Mapping[str, Any]:
    """Read ``delivery`` until its progress is ``released``, and return that view.

    The end was already surrendered; each call is the same read. A released
    delivery must carry the site's retained end report, since the storefront
    proves the release by the site's callback and keeps the site's signed intended
    end beside it. An end that needs repair stops the wait at once rather than
    waiting out the bound, since nothing will release its capacity.
    """
    deadline = clock() + timeout_seconds
    while True:
        view = delivery()
        record = view.get("delivery") or {}
        progress = record.get("progress")
        if progress == RELEASED:
            if not record.get("site_reports"):
                raise AssertionError("proven release has no retained site end report")
            return view
        if progress == REPAIR_REQUIRED:
            raise AssertionError(
                f"bare-metal teardown needs repair: progress {progress!r}, view {view!r}"
            )
        if clock() >= deadline:
            raise AssertionError(
                f"bare-metal teardown did not reach {RELEASED!r} within "
                f"{timeout_seconds}s; last progress {progress!r}"
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
    "REPAIR_REQUIRED",
    "assert_purchase_recorded",
    "forbidden_flags",
    "recovery_command",
    "wait_for_release",
]
