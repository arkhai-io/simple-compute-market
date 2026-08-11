"""Registry of this storefront's timer-driven loops, so pause can halt them.

A paused storefront makes no state change on its own. That is what an operator
reading `POST /api/v1/admin/pause` should expect, and it is what lets an
end-to-end scenario observe every side effect in the order the system produces
it: pause, assert, advance one step, assert again.

Loops are stopped by cancelling their tasks rather than by each loop consulting
a flag. Two of the five loop bodies live in `core_storefront` — the claims
engine's `run()` and the capacity poller's `site_events_poller` — and cannot see
a flag owned here, so a flag would cover three loops and cancellation the other
two. One concept implemented two ways is worse than one blunt mechanism: a
reader would have to know which loop is which to predict what pause does.

Cancellation loses loop-local state, and for one loop that matters. The capacity
events poller holds its feed position in a local variable, so a resumed poller
re-positions at the feed head and re-runs its full reconcile. That is the same
path it takes after a process restart or a ledger reset, so it is self-healing
rather than lossy — but it means resuming performs a reconciliation, which is
why a scenario resumes at teardown and not between assertions.

Advancing a halted loop is a separate concern: each loop's work is reachable as
an ordinary operation, and the admin surface calls that operation directly
rather than driving one iteration of the loop. See the lifecycle routes in
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

# Name -> specification, so a cancelled loop can be restarted from the same
# factory it was started from. Handles are separate because a paused storefront
# has specifications and no handles.
_SPECS: dict[str, StorefrontBackgroundTask] = {}
_HANDLES: dict[str, asyncio.Task[Any]] = {}


def start_registered_loop(
    task: StorefrontBackgroundTask, *, task_logger: Any = None
) -> asyncio.Task[Any]:
    """Start one background loop and keep its handle so pause can cancel it.

    Replaces a bare `start_storefront_background_task` call at every startup
    site. The helper already returns the handle; nothing kept it, which is why
    the loops could not be stopped.
    """
    handle = start_storefront_background_task(task, logger=task_logger or logger)
    _SPECS[task.name] = task
    _HANDLES[task.name] = handle
    return handle


def registered_loop_names() -> list[str]:
    return sorted(_SPECS)


def loop_states() -> dict[str, str]:
    """Per-loop state for the operator status surface.

    A bare `paused` boolean cannot distinguish "the flag is set" from "the loops
    actually stopped", and after this becomes the substantive half of what pause
    means, that distinction is the thing worth reporting.
    """
    states: dict[str, str] = {}
    for name in _SPECS:
        handle = _HANDLES.get(name)
        if handle is None:
            states[name] = "stopped"
        elif handle.done():
            # A loop that exited on its own is neither running nor deliberately
            # stopped, and reporting it as either would hide a crash.
            states[name] = "cancelled" if handle.cancelled() else "exited"
        else:
            states[name] = "running"
    return states


def pause_loops() -> dict[str, str]:
    """Cancel every registered loop. Idempotent.

    Cancelling an already-cancelled loop is a no-op rather than an error: pause
    is an operator control and a second call should not fail because the first
    succeeded.
    """
    for name, handle in list(_HANDLES.items()):
        if not handle.done():
            handle.cancel()
        _HANDLES.pop(name, None)
    logger.info("[LIFECYCLE] Paused %d timer loop(s)", len(_SPECS))
    return loop_states()


def resume_loops() -> dict[str, str]:
    """Restart every registered loop that is not running. Idempotent.

    Restarting only what is absent matters: starting a second copy of a poller
    would be invisible until two reconciliations raced each other, which is the
    class of defect this whole control exists to make observable.
    """
    for name, spec in _SPECS.items():
        handle = _HANDLES.get(name)
        if handle is not None and not handle.done():
            continue
        _HANDLES[name] = start_storefront_background_task(spec, logger=logger)
    logger.info("[LIFECYCLE] Resumed %d timer loop(s)", len(_SPECS))
    return loop_states()


def reset_for_tests() -> None:
    """Drop all registrations. Test-only; production never unregisters a loop."""
    for handle in _HANDLES.values():
        if not handle.done():
            handle.cancel()
    _HANDLES.clear()
    _SPECS.clear()
