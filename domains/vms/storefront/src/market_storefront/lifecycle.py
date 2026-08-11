"""The storefront's timer loops, and the flag that holds them idle.

A paused storefront makes no state change on its own. That is what an operator
reading `POST /api/v1/admin/pause` should expect, and it is what lets an
end-to-end scenario observe every side effect in the order the system produces
it: pause, assert, advance one step, assert again.

Loops are held idle by a flag each one consults once per cycle, not by
cancelling their tasks. The distinction is the whole safety property. Cancelling
delivers `CancelledError` at whatever await the coroutine happens to be sitting
on, which may be in the middle of a reconcile that has written some of its rows;
a flag checked before a cycle begins means every cycle either ran completely or
never started. It also means loop-local state survives a pause -- the capacity
poller keeps its feed position, so resuming continues from where it stopped
rather than re-converging from the feed head.

Two of the five loop bodies live in `core_storefront` and cannot see a flag
owned here, so both accept an optional `paused` predicate and are given this
module's. The other three consult it directly. Same flag, same cycle-boundary
semantics, five loops.

Advancing a paused loop is a separate concern: each loop's work is reachable as
an ordinary operation, and the admin lifecycle routes call that operation
directly rather than driving an iteration of the loop. See
`market_storefront.controllers.admin_controller`.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from core_storefront.app_startup import (
    StorefrontBackgroundTask,
    start_storefront_background_task,
)

logger = logging.getLogger(__name__)

#: Handles are kept for status reporting only. Nothing cancels them: a paused
#: loop is a live task doing nothing, which is what makes the pause safe.
_HANDLES: dict[str, asyncio.Task[Any]] = {}


def start_registered_loop(
    task: StorefrontBackgroundTask, *, task_logger: Any = None
) -> asyncio.Task[Any]:
    """Start one background loop and keep its handle for status reporting."""
    handle = start_storefront_background_task(task, logger=task_logger or logger)
    _HANDLES[task.name] = handle
    return handle


def registered_loop_names() -> list[str]:
    return sorted(_HANDLES)


def is_paused() -> bool:
    """The pause gate every timer loop consults once per cycle.

    Reads the storefront's single pause flag rather than keeping a second one:
    "paused" must mean one thing to the negotiation path and to the loops, or an
    operator could pause and get half of it. Imported inside the function
    because `server` imports this module during startup.
    """
    from market_storefront.server import is_globally_paused

    return is_globally_paused()


def loop_states() -> dict[str, str]:
    """Per-loop state for the operator status surface.

    A bare `paused` boolean says the flag is set; this says what the loops are
    actually doing. `exited` is deliberately distinct from `paused`: a loop that
    ended on its own is neither idle nor healthy, and reporting it as either
    would hide a crash behind an operator control's vocabulary.
    """
    paused = is_paused()
    states: dict[str, str] = {}
    for name, handle in _HANDLES.items():
        if handle.done():
            states[name] = "cancelled" if handle.cancelled() else "exited"
        else:
            states[name] = "paused" if paused else "running"
    return states


def reset_for_tests() -> None:
    """Drop all registrations. Test-only; production never unregisters a loop."""
    for handle in _HANDLES.values():
        if not handle.done():
            handle.cancel()
    _HANDLES.clear()
