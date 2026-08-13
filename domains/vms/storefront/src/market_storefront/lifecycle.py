"""The storefront's timer loops, and the flag that holds them idle.

A paused storefront makes no state change on its own. That is what an operator
reading `POST /api/v1/admin/lifecycle/pause` should expect, and it is what lets
an end-to-end scenario observe every side effect in the order the system
produces it: pause, assert, advance one step, assert again.

Loops are held idle by a flag each one consults once per cycle, not by
cancelling their tasks. The distinction is the whole safety property. Cancelling
delivers `CancelledError` at whatever await the coroutine happens to be sitting
on, which may be in the middle of a reconcile that has written some of its rows;
a flag checked before a cycle begins means every cycle either ran completely or
never started. It also means loop-local state survives a pause -- the capacity
poller keeps its feed position, so resuming continues from where it stopped
rather than re-converging from the feed head.

Every loop reads the flag through `gate`, which acknowledges in the same call.
Two of the five loop bodies live in `core_storefront` and cannot import a flag
owned here, so both accept an optional `paused` predicate and are given a
name-bound `gate`. The other three call it directly. Same gate, same
cycle-boundary semantics, five loops.

A loop's reported state is derived from what the loop has done, never from the
existence of the task running it. A scheduled task whose coroutine has not yet
reached its gate cannot observe a pause, so it reports `starting` rather than
`running`: a caller that pauses on the strength of `running` would otherwise be
told a loop had stopped when it had not yet begun. See
`openspec/specs/storefront-publication/spec.md`'s requirement that a loop's
reported state is established by the loop.

Advancing a paused loop is a separate concern: each loop's work is reachable as
an ordinary operation, and the admin lifecycle routes call that operation
directly rather than driving an iteration of the loop. See
`market_storefront.controllers.admin_controller`.
"""

from __future__ import annotations

import asyncio
import logging
import os
from functools import partial
from typing import Any, Callable

from core_storefront.app_startup import (
    StorefrontBackgroundTask,
    start_storefront_background_task,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Loop names.
#
# One definition per loop, used both by the registration in `startup.py` and by
# the loop body's own gate call. A name spelled independently in those two places
# can drift, and a loop acknowledging a name nobody waits on is indistinguishable
# from a loop that never gates at all -- the registered name stays unacknowledged
# either way. `gate` reports an unregistered name for the same reason.
# ---------------------------------------------------------------------------

NEGOTIATION_WATCHDOG = "negotiation_watchdog"
CLAIMS_ENGINE = "claims_engine"
FULFILLMENT_RESUME = "fulfillment_resume"
CAPACITY_EVENTS_POLLER = "capacity_events_poller"
SITE_PROJECTION_POLLER = "site_projection_poller"


def capacity_site_loop_name(site: str) -> str:
    """The registered name of one site's capacity-event poller.

    Capacity polling fans out one poller per configured site, and each is
    registered under its own name rather than sharing the aggregate's. A shared
    acknowledgement would let whichever site reached its gate first answer for
    the others, so a pause could report `paused` while another site's cycle was
    still writing — optimistic in the one direction the pause exists to prevent.
    Per-site names also make the status surface say which site is still
    stopping, rather than only that something is.
    """
    return f"{CAPACITY_EVENTS_POLLER}:{site}"

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

#: How many times each loop has consulted its gate. Load-bearing, not merely
#: diagnostic: a zero count is what distinguishes a loop that has not started
#: cycling from one that is running, and `_ACKED` cannot carry that distinction
#: because an unpaused gate call clears the event it would have to set.
_GATE_CALLS: dict[str, int] = {}

#: Names `gate` has already reported as unregistered. Bounded so a loop calling a
#: misspelled name once per second does not fill the log with one fact.
_UNREGISTERED_REPORTED: set[str] = set()

#: How long `await_quiescence` waits for loops to reach their gates. Bounded on
#: purpose: a loop's gate is at the end of its interval, and the shipped intervals
#: run to 30s, so an unbounded wait would let an operator endpoint hang for half a
#: minute. A loop that has not acknowledged inside the window is reported
#: `pausing`, which is true, rather than `paused`, which would not be.
QUIESCENCE_TIMEOUT_SECONDS = 5.0


def _log_loop_completion(name: str, handle: asyncio.Task[Any]) -> None:
    """Report a loop that ended, at the moment it ends.

    Nothing restarts a loop, so a loop that ends stops doing its work for the
    lifetime of the process. Without this the only evidence is a status read
    somebody happens to make later; `loop_states` reports it as `exited` and the
    health surface fails liveness on it, but neither says when or why.
    """
    if handle.cancelled():
        logger.info("[LIFECYCLE] %s was cancelled", name)
        return
    exc = handle.exception()
    if exc is not None:
        logger.error("[LIFECYCLE] %s ended on an exception", name, exc_info=exc)
    else:
        logger.error("[LIFECYCLE] %s returned; it will not run again", name)


def start_registered_loop(
    task: StorefrontBackgroundTask, *, task_logger: Any = None
) -> asyncio.Task[Any]:
    """Start one background loop and keep its handle for status reporting."""
    handle = start_storefront_background_task(task, logger=task_logger or logger)
    _HANDLES[task.name] = handle
    _ACKED.setdefault(task.name, asyncio.Event())
    handle.add_done_callback(partial(_log_loop_completion, task.name))
    logger.info("[LIFECYCLE] registered %s (pid=%s)", task.name, os.getpid())
    return handle


def acknowledge_gate(name: str, *, paused: bool) -> None:
    """A loop reports whether it is sitting at its gate.

    Called by each loop once per cycle, immediately after reading the pause flag
    and before doing any work: `paused=True` when it is about to skip the cycle,
    `paused=False` when it is about to run one. A loop that never calls this is
    reported as never having reached its gate, which is the safe direction to be
    wrong in.
    """
    seen = _GATE_CALLS[name] = _GATE_CALLS.get(name, 0) + 1
    if seen == 1:
        # The transition from `starting` to a state a caller may act on. Logged
        # once, unconditionally, because it is the moment a loop becomes able to
        # observe a pause at all.
        logger.info("[LIFECYCLE] %s reached its gate for the first time", name)

    event = _ACKED.setdefault(name, asyncio.Event())
    if paused:
        if not event.is_set():
            # Logged on the transition only, not every cycle.
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
        # Name the loops and separate the two reasons a loop can be missing from
        # the acknowledged set. A loop with gate calls behind it is mid-cycle and
        # will arrive; a loop with none has not started cycling, and no length of
        # wait fixes that. They have opposite causes and the counts tell them
        # apart.
        unacked = sorted(
            n for n, h in _HANDLES.items()
            if not h.done() and not _ACKED[n].is_set()
        )
        never_gated = sorted(n for n in unacked if not _GATE_CALLS.get(n))
        logger.info(
            "[LIFECYCLE] %d loop(s) had not reached a gate within %ss: %s "
            "(never gated: %s) (gate calls: %s)",
            len(unacked), deadline, unacked,
            never_gated or "none",
            dict(sorted(_GATE_CALLS.items())),
        )


def registered_loop_names() -> list[str]:
    return sorted(_HANDLES)


def gate(name: str) -> bool:
    """The pause gate a named loop consults once per cycle, before any work.

    Returns True when the loop should skip this cycle. Acknowledging is folded
    into the read rather than left to each caller: a loop that checked the flag
    but forgot to acknowledge would be reported as still working forever, and the
    two must not be separately forgettable. `_pause_requested` is private for the
    same reason — there is no supported way to read the flag without saying so.
    """
    if name not in _HANDLES and name not in _UNREGISTERED_REPORTED:
        _UNREGISTERED_REPORTED.add(name)
        logger.warning(
            "[LIFECYCLE] %s gated under a name that is not registered; "
            "registered names are %s. The registered loop will never be "
            "reported as paused.",
            name, registered_loop_names() or "none",
        )
    paused = _pause_requested()
    acknowledge_gate(name, paused=paused)
    return paused


def loop_gate(name: str) -> Callable[[], bool]:
    """A no-argument gate bound to one loop's name.

    For the two loop bodies that live in `core_storefront` and take a `paused`
    predicate: they cannot name a loop they do not know about, so composition
    supplies the binding.
    """
    return partial(gate, name)


def _pause_requested() -> bool:
    """Whether the operator has asked the timer loops to hold.

    Reads the *loop* pause flag, not the trading one. A storefront closed for new
    negotiations is still expected to finish the work it already accepted, and a
    storefront whose loops are idle is still expected to trade; conflating the two
    made the second impossible to ask for.

    Private: every production read goes through `gate`, which acknowledges. An
    importable unacknowledged read is how four of five loops came to consult the
    pause without ever reporting that they had.

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
    actually doing.

    `starting` is checked before the pause states and is deliberately distinct
    from `pausing`. A loop that has never reached its gate has not started
    cycling; a loop reported `pausing` has a cycle in flight that will finish.
    Collapsing them reports a loop that cannot observe the pause as one that is
    about to obey it.

    `exited` is likewise distinct from `paused`: a loop that ended on its own is
    neither idle nor healthy, and reporting it as either would hide a crash behind
    an operator control's vocabulary.
    """
    paused = _pause_requested()
    states: dict[str, str] = {}
    for name, handle in _HANDLES.items():
        if handle.done():
            states[name] = "cancelled" if handle.cancelled() else "exited"
        elif not _GATE_CALLS.get(name):
            states[name] = "starting"
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


def loops_check() -> str:
    """One-line loop health for the `checks` map on the health surfaces.

    `"ok"` only when every registered loop is cycling or deliberately idle. The
    two not-ok values are separated because they mean opposite things to a
    caller: `starting` resolves on its own and gates readiness, `exited` does not
    resolve at all and gates liveness while nothing restarts a loop.
    """
    states = loop_states()
    if not states:
        return "error: no timer loops registered"
    failed = sorted(n for n, s in states.items() if s in ("exited", "cancelled"))
    if failed:
        return f"error: ended - {', '.join(failed)}"
    starting = sorted(n for n, s in states.items() if s == "starting")
    if starting:
        return f"starting: {', '.join(starting)}"
    return "ok"


def failed_loop_names() -> list[str]:
    """Loops that ended on their own. Liveness fails on a non-empty result.

    Nothing in this process restarts a loop, so replacing the process is the only
    recovery available and liveness is how it is requested. If loop supervision is
    ever added, this stops being a liveness condition and becomes a readiness one.
    """
    return sorted(
        n for n, s in loop_states().items() if s in ("exited", "cancelled")
    )


def starting_loop_names() -> list[str]:
    """Loops registered but not yet cycling. Readiness fails on a non-empty
    result: a storefront whose loops have not begun will not do the background
    work a caller relies on, and cannot observe a pause either."""
    return sorted(n for n, s in loop_states().items() if s == "starting")


def reset_for_tests() -> None:
    """Drop all registrations. Test-only; production never unregisters a loop."""
    for handle in _HANDLES.values():
        if not handle.done():
            handle.cancel()
    _HANDLES.clear()
    _ACKED.clear()
    _GATE_CALLS.clear()
    _UNREGISTERED_REPORTED.clear()
