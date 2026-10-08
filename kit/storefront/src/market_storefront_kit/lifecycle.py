"""One storefront's timer loops, the pause that holds them, and their steps.

A paused storefront makes no state change on its own. That is what an operator
pausing the lifecycle loops should expect, and it is what lets an end-to-end
scenario observe every side effect in the order the system produces it: pause,
assert, advance one step, assert again.

Loops are held idle by a flag each one consults once per cycle, not by
cancelling their tasks. The distinction is the whole safety property.
Cancelling delivers `CancelledError` at whatever await the coroutine happens to
be sitting on, which may be in the middle of a reconcile that has written some
of its rows; a flag checked before a cycle begins means every cycle either ran
completely or never started. It also means loop-local state survives a pause --
a feed poller keeps its position, so resuming continues from where it stopped.

Every loop reads the flag through `gate`, which acknowledges in the same call,
so a loop cannot read the flag without reporting that it has. A loop's reported
state is derived from what the loop has done, never from the existence of the
task running it.

Each loop's work is also reachable as one step, registered beside the loop
under a route name, so an operator advances a held loop by running exactly the
operation its timer runs. Both contracts are the storefront loop requirements in
openspec/specs/market-composition/spec.md.

One controller belongs to one storefront process. The pause is process-local:
a restarted storefront resumes its loops, because one that came back silently
idle would stop servicing work with nothing to say so.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from functools import partial
from typing import Any

from core_storefront.app_startup import (
    StorefrontBackgroundTask,
    start_storefront_background_task,
)

#: How long `pause` waits for loops to reach their gates. A loop waiting between
#: cycles reaches its gate at once, because its wait returns on a pause request;
#: the bound covers a loop still finishing a cycle, so an operator request cannot
#: hang for as long as the slowest cycle. A loop that has not acknowledged inside
#: the window is reported `pausing`, which is true, rather than `paused`, which
#: would not be.
QUIESCENCE_TIMEOUT_SECONDS = 5.0

#: How often a held loop re-reads its gate. A held loop cannot wait on the pause
#: signal, which stays set for as long as it is held, so it polls instead.
HELD_POLL_SECONDS = 0.05

# A loop body runs: gate (polling while held), then its work if due, then
# `idle` until the next cycle. The gate is read on entry, so a loop is
# observable from the moment it starts rather than after its first interval,
# and it is the last thing read before work, so a pause requested during the
# wait is observed before the next cycle's work.

LoopStep = Callable[[], Awaitable[Mapping[str, Any]]]


class LoopNotFound(LookupError):
    """No loop step is registered under the requested route name."""


class PreviewNotOffered(LookupError):
    """The loop is registered but offers no read-only preview of its cycle."""


@dataclass(frozen=True, slots=True)
class _RegisteredStep:
    name: str
    step: LoopStep
    preview: LoopStep | None


class StorefrontLoopController:
    """Registration, gating, pausing, and stepping for one storefront's loops."""

    def __init__(
        self,
        *,
        quiescence_timeout: float = QUIESCENCE_TIMEOUT_SECONDS,
        logger: logging.Logger | None = None,
    ) -> None:
        self._quiescence_timeout = quiescence_timeout
        self._logger = logger or logging.getLogger(__name__)
        #: Handles are kept for status reporting only. Nothing cancels them: a
        #: paused loop is a live task doing nothing, which is what makes the
        #: pause safe.
        self._handles: dict[str, asyncio.Task[Any]] = {}
        #: Set by a loop when it reaches its gate and finds the pause
        #: requested; cleared when it passes the gate and starts a cycle. This
        #: is the difference between "pause was requested" and "this loop has
        #: stopped", and only the loop itself can report the second.
        self._acked: dict[str, asyncio.Event] = {}
        #: How many times each loop has consulted its gate. A zero count is what
        #: distinguishes a loop that has not started cycling from one that is
        #: running; `_acked` cannot, because an unpaused gate call clears it.
        self._gate_calls: dict[str, int] = {}
        #: Names already reported as gating unregistered, so a misspelled name
        #: read once per cycle is logged once.
        self._unregistered_reported: set[str] = set()
        #: Gated names with no task handle of their own, such as per-site
        #: pollers whose fan-out a kit runtime owns. Declaring one is what makes
        #: a pause wait for it.
        self._declared: set[str] = set()
        self._steps: dict[str, _RegisteredStep] = {}
        self._pause_requested = False
        # Set while a pause is requested. A loop idling between cycles waits on
        # it as well as its interval, so a pause reaches every idle loop's gate
        # at once rather than at the end of whatever interval it is waiting out.
        self._pause_signal = asyncio.Event()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def start_loop(
        self,
        task: StorefrontBackgroundTask,
        *,
        route: str | None = None,
        step: LoopStep | None = None,
        preview: LoopStep | None = None,
        task_logger: Any = None,
    ) -> asyncio.Task[Any]:
        """Start one timer loop, keep its handle, and register its step."""

        if step is not None:
            self.register_step(task.name, route=route or task.name, step=step, preview=preview)
        handle = start_storefront_background_task(task, logger=task_logger or self._logger)
        self._handles[task.name] = handle
        self._acked.setdefault(task.name, asyncio.Event())
        handle.add_done_callback(partial(self._log_loop_completion, task.name))
        self._logger.info("[LIFECYCLE] registered %s (pid=%s)", task.name, os.getpid())
        return handle

    def register_step(
        self,
        name: str,
        *,
        route: str,
        step: LoopStep,
        preview: LoopStep | None = None,
    ) -> None:
        """Bind the operation one cycle of loop `name` runs to a route name.

        A loop with no timer registers a step alone. Registering the step with
        the loop, rather than in a route table, is what keeps the step and the
        timer calling the same operation.
        """

        existing = self._steps.get(route)
        if existing is not None and existing.name != name:
            raise ValueError(
                f"lifecycle route {route!r} is already registered for loop {existing.name!r}"
            )
        self._steps[route] = _RegisteredStep(name=name, step=step, preview=preview)

    def declare(self, name: str) -> Callable[[], bool]:
        """Declare a gated name this controller holds no handle for, and bind its gate."""

        self._declared.add(name)
        self._acked.setdefault(name, asyncio.Event())
        self._logger.info("[LIFECYCLE] declared gated name %s (no handle)", name)
        return partial(self.gate, name)

    def _log_loop_completion(self, name: str, handle: asyncio.Task[Any]) -> None:
        """Report a loop that ended, at the moment it ends.

        Nothing restarts a loop, so a loop that ends stops doing its work for
        the lifetime of the process. `states` reports it as `exited` from then
        on; this records when and why.
        """

        if handle.cancelled():
            self._logger.info("[LIFECYCLE] %s was cancelled", name)
            return
        exc = handle.exception()
        if exc is not None:
            self._logger.error("[LIFECYCLE] %s ended on an exception", name, exc_info=exc)
        else:
            self._logger.error("[LIFECYCLE] %s returned; it will not run again", name)

    # ------------------------------------------------------------------
    # Gating
    # ------------------------------------------------------------------

    def gate(self, name: str) -> bool:
        """The gate a named loop consults once per cycle, before any work.

        Returns True when the loop should skip this cycle. Acknowledging is
        folded into the read, so a loop cannot check the flag and forget to say
        so -- a loop that did would be reported as working forever.
        """

        if (
            name not in self._handles
            and name not in self._declared
            and name not in self._unregistered_reported
        ):
            self._unregistered_reported.add(name)
            self._logger.warning(
                "[LIFECYCLE] %s gated under a name that is not registered; "
                "registered names are %s. The registered loop will never be "
                "reported as paused.",
                name,
                self.registered_loop_names() or "none",
            )
        paused = self._pause_requested
        self._acknowledge(name, paused=paused)
        return paused

    def loop_gate(self, name: str) -> Callable[[], bool]:
        """A no-argument gate bound to one loop's name, for kit loop runners."""

        return partial(self.gate, name)

    def _acknowledge(self, name: str, *, paused: bool) -> None:
        seen = self._gate_calls[name] = self._gate_calls.get(name, 0) + 1
        if seen == 1:
            # The transition from `starting` to a state a caller may act on:
            # the moment a loop becomes able to observe a pause at all.
            self._logger.info("[LIFECYCLE] %s reached its gate for the first time", name)
        event = self._acked.setdefault(name, asyncio.Event())
        if paused:
            if not event.is_set():
                self._logger.info("[LIFECYCLE] %s reached its gate and is idle", name)
            event.set()
        else:
            if event.is_set():
                self._logger.info("[LIFECYCLE] %s left its gate and is working", name)
            event.clear()

    async def idle(self, seconds: float, *, wake: asyncio.Event | None = None) -> None:
        """Wait between cycles: until the interval ends, `wake` is set, or a pause.

        A loop calls this instead of sleeping, so a pause never waits on a
        loop's interval, however long it is configured.
        """

        waiters = [asyncio.ensure_future(self._pause_signal.wait())]
        if wake is not None:
            waiters.append(asyncio.ensure_future(wake.wait()))
        try:
            await asyncio.wait(waiters, timeout=seconds, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for waiter in waiters:
                waiter.cancel()

    # ------------------------------------------------------------------
    # Pausing
    # ------------------------------------------------------------------

    def request_pause(self, paused: bool) -> None:
        """Set or clear the pause request without waiting for any loop.

        Separate from the trading pause: a storefront closed for new
        negotiations still finishes accepted work, and a storefront whose loops
        are idle still trades.
        """

        self._pause_requested = bool(paused)
        if self._pause_requested:
            self._pause_signal.set()
        else:
            self._pause_signal.clear()

    def is_pause_requested(self) -> bool:
        return self._pause_requested

    async def pause(self) -> dict[str, str]:
        """Hold every loop, wait bounded for each to reach its gate, report each."""

        self.request_pause(True)
        await self.await_quiescence()
        return self.states()

    async def resume(self) -> dict[str, str]:
        """Return every loop to work. Nothing to wait for."""

        self.request_pause(False)
        return self.states()

    async def await_quiescence(self, timeout: float | None = None) -> None:
        """Wait, bounded, for every live loop to reach its gate.

        Returns when all have acknowledged or the window elapses; the caller
        reads `states` afterwards to see which. Not an error on timeout: a loop
        still finishing a cycle is a normal state to report.
        """

        deadline = self._quiescence_timeout if timeout is None else timeout
        pending = [
            self._acked[name].wait()
            for name, handle in self._handles.items()
            if not handle.done() and name in self._acked
        ] + [self._acked[name].wait() for name in sorted(self._declared) if name in self._acked]
        if not pending:
            return
        try:
            await asyncio.wait_for(asyncio.gather(*pending), timeout=deadline)
        except (asyncio.TimeoutError, TimeoutError):
            # A loop with gate calls behind it is mid-cycle and will arrive; a
            # loop with none has not started cycling, and no wait fixes that.
            # The counts tell the two apart.
            unacked = sorted(
                n
                for n in [*self._handles, *self._declared]
                if (n not in self._handles or not self._handles[n].done())
                and not self._acked[n].is_set()
            )
            never_gated = sorted(n for n in unacked if not self._gate_calls.get(n))
            self._logger.info(
                "[LIFECYCLE] %d loop(s) had not reached a gate within %ss: %s "
                "(never gated: %s) (gate calls: %s)",
                len(unacked),
                deadline,
                unacked,
                never_gated or "none",
                dict(sorted(self._gate_calls.items())),
            )

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def registered_loop_names(self) -> list[str]:
        return sorted(self._handles)

    def states(self) -> dict[str, str]:
        """Per-loop state, established by what each loop has acknowledged.

        `starting` is checked before the pause states and is distinct from
        `pausing`: a loop that has never reached its gate cannot observe a
        pause, while a `pausing` loop has a cycle in flight that will finish.
        `exited` is distinct from `paused`: a loop that ended on its own is
        neither idle nor healthy.
        """

        paused = self._pause_requested
        states: dict[str, str] = {}
        entries: list[tuple[str, asyncio.Task[Any] | None]] = [
            (n, None) for n in sorted(self._declared)
        ] + list(self._handles.items())
        for name, handle in entries:
            if handle is not None and handle.done():
                states[name] = "cancelled" if handle.cancelled() else "exited"
            elif not self._gate_calls.get(name):
                states[name] = "starting"
            elif not paused:
                states[name] = "running"
            elif name in self._acked and self._acked[name].is_set():
                states[name] = "paused"
            else:
                states[name] = "pausing"
        return states

    def starting_loop_names(self) -> list[str]:
        """Loops registered but not yet cycling, which cannot yet observe a pause."""

        return sorted(n for n, s in self.states().items() if s == "starting")

    def failed_loop_names(self) -> list[str]:
        """Loops that ended on their own; nothing in the process restarts them."""

        return sorted(n for n, s in self.states().items() if s in ("exited", "cancelled"))

    def loops_check(self) -> str:
        """One-line loop summary: `ok`, `starting: ...`, or `error: ended - ...`."""

        states = self.states()
        if not states:
            return "error: no timer loops registered"
        failed = self.failed_loop_names()
        if failed:
            return f"error: ended - {', '.join(failed)}"
        starting = self.starting_loop_names()
        if starting:
            return f"starting: {', '.join(starting)}"
        return "ok"

    def step_routes(self) -> dict[str, str]:
        """Each registered route name and the loop name its step reports."""

        return {route: registered.name for route, registered in sorted(self._steps.items())}

    # ------------------------------------------------------------------
    # Stepping
    # ------------------------------------------------------------------

    async def run_cycle(self, route: str) -> Mapping[str, Any]:
        """Run exactly the operation one cycle of the loop runs, held or not."""

        registered = self._steps.get(route)
        if registered is None:
            raise LoopNotFound(route)
        return await registered.step()

    async def dry_run(self, route: str) -> Mapping[str, Any]:
        """Report what one cycle of the loop would do, applying nothing."""

        registered = self._steps.get(route)
        if registered is None:
            raise LoopNotFound(route)
        if registered.preview is None:
            raise PreviewNotOffered(route)
        return await registered.preview()

    # ------------------------------------------------------------------
    # Process teardown
    # ------------------------------------------------------------------

    def clear_loops(self) -> None:
        """Cancel every loop and drop its state, keeping registered steps.

        Production never unregisters a loop while serving. A process that tears
        its loops down and starts them again within one interpreter -- an
        application rebuilt in place -- uses this so stale handles do not report
        for loops that no longer exist.
        """

        for handle in self._handles.values():
            if not handle.done():
                handle.cancel()
        self._handles.clear()
        self._acked.clear()
        self._gate_calls.clear()
        self._unregistered_reported.clear()
        self._declared.clear()
        self._pause_requested = False
        # A fresh signal: an event is bound to the event loop that first waited
        # on it, and loops started again may run on a different event loop.
        self._pause_signal = asyncio.Event()


__all__ = [
    "HELD_POLL_SECONDS",
    "LoopNotFound",
    "LoopStep",
    "PreviewNotOffered",
    "QUIESCENCE_TIMEOUT_SECONDS",
    "StorefrontLoopController",
]
