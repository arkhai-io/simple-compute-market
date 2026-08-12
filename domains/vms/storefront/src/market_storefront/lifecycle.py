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
import os
from typing import Any

from core_storefront.app_startup import (
    StorefrontBackgroundTask,
    start_storefront_background_task,
)

logger = logging.getLogger(__name__)

#: Handles are kept for status reporting only. Nothing cancels them: a paused
#: loop is a live task doing nothing, which is what makes the pause safe.
_HANDLES: dict[str, asyncio.Task[Any]] = {}

#: Set by a loop when it reaches its gate and finds the pause requested; cleared
#: when it passes the gate and starts a cycle. This is the difference between
#: "pause was requested" and "this loop has stopped", and only the loop itself can
#: report the second. Without it, a status derived from the flag says `paused` for
#: a loop that is part-way through a reconcile, which is precisely the claim a
#: caller uses the status to check.
_ACKED: dict[str, asyncio.Event] = {}

#: Diagnostic only: how many times each loop has consulted its gate.
_GATE_CALLS: dict[str, int] = {}

#: How long `await_quiescence` waits for loops to reach their gates. Bounded on
#: purpose: a loop's gate is at the end of its interval, and the shipped intervals
#: run to 30s, so an unbounded wait would let an operator endpoint hang for half a
#: minute. A loop that has not acknowledged inside the window is reported
#: `pausing`, which is true, rather than `paused`, which would not be.
QUIESCENCE_TIMEOUT_SECONDS = 5.0


def start_registered_loop(
    task: StorefrontBackgroundTask, *, task_logger: Any = None
) -> asyncio.Task[Any]:
    """Start one background loop and keep its handle for status reporting."""
    handle = start_storefront_background_task(task, logger=task_logger or logger)
    _HANDLES[task.name] = handle
    _ACKED.setdefault(task.name, asyncio.Event())
    # pid and registry identity, because a loop that never observes a pause set in
    # the request handler is either not calling the gate or not sharing state with
    # it, and those are told apart by whether these match.
    logger.info(
        "[LIFECYCLE] registered %s (pid=%s registry=%s)",
        task.name, os.getpid(), hex(id(_ACKED)),
    )
    return handle


def acknowledge_gate(name: str, *, paused: bool) -> None:
    """A loop reports whether it is sitting at its gate.

    Called by each loop once per cycle, immediately after reading the pause flag
    and before doing any work: `paused=True` when it is about to skip the cycle,
    `paused=False` when it is about to run one. A loop that never calls this is
    reported as never having reached its gate, which is the safe direction to be
    wrong in.
    """
    # First few calls per loop are logged unconditionally. Transition-only logging
    # cannot distinguish "this loop reached its gate and saw no pause" from "this
    # loop never reached its gate at all", and that is exactly the open question:
    # four loops share a registry and a process with the request handler, the flag
    # reads True there, and they log no transition. Bounded so it does not flood.
    seen = _GATE_CALLS[name] = _GATE_CALLS.get(name, 0) + 1
    if seen <= 3:
        logger.info(
            "[LIFECYCLE] %s gate call #%d (paused=%s)", name, seen, paused,
        )

    event = _ACKED.setdefault(name, asyncio.Event())
    if paused:
        if not event.is_set():
            # Logged on the transition only, not every cycle. A pause that reports
            # `pausing` for a loop that has clearly stopped working is unresolvable
            # from the outside: it cannot be told apart from a loop that never
            # reached its gate. This line is the difference.
            logger.info("[LIFECYCLE] %s reached its gate and is idle", name)
        event.set()
    else:
        if event.is_set():
            logger.info("[LIFECYCLE] %s left its gate and is working", name)
        event.clear()


async def await_quiescence(timeout: float | None = None) -> None:
    """Wait, bounded, for every live loop to reach its gate.

    Returns when all have acknowledged or the window elapses — the caller reads
    `loop_states()` afterwards to see which. Not an error on timeout: a loop still
    finishing a cycle is a normal state to report, and raising would turn an
    honest answer into a failed request.
    """
    deadline = timeout if timeout is not None else QUIESCENCE_TIMEOUT_SECONDS
    pending = [
        _ACKED[name].wait()
        for name, handle in _HANDLES.items()
        if not handle.done() and name in _ACKED
    ]
    if not pending:
        return
    try:
        await asyncio.wait_for(asyncio.gather(*pending), timeout=deadline)
    except (asyncio.TimeoutError, TimeoutError):
        # Name the loops and both key sets. A count alone cannot distinguish "the
        # loop never acknowledged" from "the waiter watched a different object
        # than the loop set", and those have opposite fixes.
        unacked = sorted(
            n for n, h in _HANDLES.items()
            if not h.done() and not _ACKED[n].is_set()
        )
        logger.info(
            "[LIFECYCLE] %d loop(s) had not reached a gate within %ss: %s "
            "(handles=%s acked=%s set=%s pid=%s registry=%s paused=%s)",
            len(unacked), deadline, unacked,
            sorted(_HANDLES), sorted(_ACKED),
            sorted(n for n, e in _ACKED.items() if e.is_set()),
            os.getpid(), hex(id(_ACKED)), is_paused(),
        )
        logger.info(
            "[LIFECYCLE] gate calls so far: %s", dict(sorted(_GATE_CALLS.items())),
        )


def registered_loop_names() -> list[str]:
    return sorted(_HANDLES)


def gate(name: str) -> bool:
    """The pause gate a named loop consults once per cycle, before any work.

    Returns True when the loop should skip this cycle. Acknowledging is folded
    into the read rather than left to each caller: a loop that checked the flag
    but forgot to acknowledge would be reported as still working forever, and the
    two must not be separately forgettable.
    """
    paused = is_paused()
    acknowledge_gate(name, paused=paused)
    return paused


def is_paused() -> bool:
    """The pause gate every timer loop consults once per cycle.

    Reads the *loop* pause flag, not the trading one. A storefront closed for new
    negotiations is still expected to finish the work it already accepted, and a
    storefront whose loops are idle is still expected to trade; conflating the two
    made the second impossible to ask for.

    Imported inside the function because the loop modules import this one at
    module scope and `server` imports them; hoisting it produces
    `ImportError: cannot import name 'is_paused' from partially initialized
    module`, verified by attempting the move rather than assumed.
    """
    from market_storefront.server import are_loops_paused

    return are_loops_paused()


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
        elif not paused:
            states[name] = "running"
        elif _ACKED.get(name) is not None and _ACKED[name].is_set():
            states[name] = "paused"
        else:
            # The flag is set and this loop has not yet reached its gate, so a
            # cycle that began before the request may still be writing. Reporting
            # `paused` here is the failure this state exists to prevent: a caller
            # would read it as "nothing is in flight" on exactly the evidence that
            # cannot establish that.
            states[name] = "pausing"
    return states


def reset_for_tests() -> None:
    """Drop all registrations. Test-only; production never unregisters a loop."""
    for handle in _HANDLES.values():
        if not handle.done():
            handle.cancel()
    _HANDLES.clear()
    _ACKED.clear()
    _GATE_CALLS.clear()
