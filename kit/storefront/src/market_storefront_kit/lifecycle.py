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
operation its timer runs. A loop registered with its interval is run by the
controller's own timer, which calls that step through `run_cycle`, the one
operation a cycle runs through: it holds the loop's lock, so a timer cycle and
an operator's step never run concurrently, and it records each cycle's outcome
for status. These contracts are the storefront loop requirements in
openspec/specs/market-composition/spec.md.

One controller belongs to one storefront process. The pause is process-local:
a restarted storefront resumes its loops, because one that came back silently
idle would stop servicing work with nothing to say so.
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
import os
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
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

#: What a timer cycle returns when the gate, re-read under the cycle's lock,
#: held it: no step ran and no outcome was recorded.
_NOT_RUN = object()

#: What a timer cycle returns when its step failed: the failure is recorded and
#: logged, and the timer carries on to its next interval.
_FAILED = object()


#: The stages a cycle reports, in the order a publication cycle passes them:
#: composing what the cycle reads, running it, and converging registries. A
#: cycle starts in `run`, so a loop with no stages of its own reports a failure
#: in the one stage it has.
CYCLE_STAGES = ("compose", "run", "converge")
DEFAULT_CYCLE_STAGE = "run"

#: How a cycle was started: by the controller's timer, or by an operator's step.
TIMER_TRIGGER = "timer"
STEP_TRIGGER = "step"


class LoopNotFound(LookupError):
    """No loop step is registered under the requested route name."""


class PreviewNotOffered(LookupError):
    """The loop is registered but offers no read-only preview of its cycle."""


@dataclass(frozen=True, slots=True)
class CycleError:
    """The error that ended a cycle, as status may show it.

    `message` is present only for an exception type the storefront declared
    disclosable -- its own configuration and publication errors, whose text
    names keys and reasons. Any other exception's text may carry a URL, a
    credential, or a provider's response, so it is recorded by type alone and
    its detail stays in the log.
    """

    type: str
    message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "message": self.message}


@dataclass(frozen=True, slots=True)
class CycleOutcome:
    """The terminal outcome of one cycle, whichever of timer or step ran it.

    `stage` names the stage a failed cycle was in; a completed cycle has none.
    A cycle cancelled part-way did not complete, and its error is the
    cancellation; a step cancelled while it waited for the running cycle
    reached no stage, so it names none.
    """

    finished_at: datetime
    trigger: str
    completed: bool
    stage: str | None = None
    error: CycleError | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "finished_at": self.finished_at.isoformat(),
            "trigger": self.trigger,
            "completed": self.completed,
            "stage": self.stage,
            "error": self.error.to_dict() if self.error is not None else None,
        }


@dataclass(frozen=True, slots=True)
class LoopSnapshot:
    """One loop's reported state beside the last outcome it recorded.

    `state` is the vocabulary of `states`; it is `None` for a loop with no
    running timer, such as one registered as a step alone. The two fields are
    independent: a `running` loop whose last cycle failed is still running,
    while an `exited` or `cancelled` loop runs no further cycles whatever its
    last outcome was.
    """

    name: str
    state: str | None
    last_outcome: CycleOutcome | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "state": self.state,
            "last_outcome": (
                self.last_outcome.to_dict() if self.last_outcome is not None else None
            ),
        }


@dataclass(frozen=True, slots=True)
class _RegisteredStep:
    name: str
    step: LoopStep
    preview: LoopStep | None


@dataclass(frozen=True, slots=True)
class _RegisteredLoop:
    name: str
    route: str
    interval_seconds: float
    initial_delay_seconds: float
    wake: asyncio.Event | None


class _CycleInProgress:
    """The stage of one running cycle, set by its step through `enter_stage`."""

    __slots__ = ("controller", "stage")

    def __init__(self, controller: StorefrontLoopController) -> None:
        self.controller = controller
        self.stage = DEFAULT_CYCLE_STAGE


#: The cycle the current task is running, if any. A step's stage marks reach its
#: own cycle through this, without a parameter every step would have to accept,
#: and a step running outside a cycle -- a preview, or a direct call -- marks
#: nothing.
_CURRENT_CYCLE: contextvars.ContextVar[_CycleInProgress | None] = contextvars.ContextVar(
    "storefront_loop_cycle", default=None
)


class StorefrontLoopController:
    """Registration, gating, pausing, and stepping for one storefront's loops."""

    def __init__(
        self,
        *,
        quiescence_timeout: float = QUIESCENCE_TIMEOUT_SECONDS,
        logger: logging.Logger | None = None,
        disclosed_errors: tuple[type[BaseException], ...] = (),
        clock: Callable[[], datetime] | None = None,
        cycle_lock_factory: Callable[[str], asyncio.Lock] | None = None,
    ) -> None:
        """`disclosed_errors` are the exception types whose messages a recorded
        outcome may carry: the storefront's own configuration and publication
        errors. `clock` stamps each outcome, in UTC by default.
        `cycle_lock_factory` makes the lock a loop's cycles hold, given the
        loop's name; a plain `asyncio.Lock` unless a caller needs to observe
        who waits on it."""

        self._quiescence_timeout = quiescence_timeout
        self._logger = logger or logging.getLogger(__name__)
        self._disclosed_errors = tuple(disclosed_errors)
        self._clock = clock or (lambda: datetime.now(UTC))
        self._cycle_lock_factory = cycle_lock_factory or (lambda _name: asyncio.Lock())
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
        #: Loops whose timer this controller runs, by loop name.
        self._loops: dict[str, _RegisteredLoop] = {}
        #: One lock per loop name, held for the whole of every cycle that loop
        #: runs, whether its timer or a step started it.
        self._cycle_locks: dict[str, asyncio.Lock] = {}
        #: The last outcome each loop recorded, by loop name.
        self._outcomes: dict[str, CycleOutcome] = {}
        #: Advanced by `clear_loops`, so a cycle of a torn-down loop that
        #: finishes afterwards records nothing over the fresh state.
        self._generation = 0
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
        """Start one self-gating timer loop, keep its handle, and register its step.

        The loop body gates and waits for itself, so its timer cycles do not run
        through `run_cycle`; a loop registered with `register_loop` does.
        """

        if step is not None:
            self.register_step(task.name, route=route or task.name, step=step, preview=preview)
        return self._start_task(task, task_logger=task_logger)

    def _start_task(
        self, task: StorefrontBackgroundTask, *, task_logger: Any = None
    ) -> asyncio.Task[Any]:
        handle = start_storefront_background_task(task, logger=task_logger or self._logger)
        self._handles[task.name] = handle
        self._acked.setdefault(task.name, asyncio.Event())
        handle.add_done_callback(partial(self._log_loop_completion, task.name))
        self._logger.info("[LIFECYCLE] registered %s (pid=%s)", task.name, os.getpid())
        return handle

    def register_loop(
        self,
        name: str,
        *,
        step: LoopStep,
        interval_seconds: float,
        route: str | None = None,
        preview: LoopStep | None = None,
        wake: asyncio.Event | None = None,
        initial_delay_seconds: float = 0.0,
    ) -> None:
        """Register a loop whose timer this controller runs over its step.

        The timer, started by `start_loops`, gates, runs one cycle through
        `run_cycle`'s own operation, and waits `interval_seconds` through
        `idle`, so the timer and an operator's step run exactly one operation
        and never concurrently. `wake`, when set, ends the wait early so a
        change reaches the loop without waiting out its interval; it never
        advances a held loop. The first cycle is due `initial_delay_seconds`
        after the timer starts, with the gate read throughout the delay.
        """

        if interval_seconds <= 0:
            raise ValueError(f"loop {name!r} needs a positive interval")
        if initial_delay_seconds < 0:
            raise ValueError(f"loop {name!r} cannot have a negative initial delay")
        handle = self._handles.get(name)
        if handle is not None and not handle.done():
            raise ValueError(f"loop {name!r} is already running")
        route = route or name
        self.register_step(name, route=route, step=step, preview=preview)
        self._loops[name] = _RegisteredLoop(
            name=name,
            route=route,
            interval_seconds=float(interval_seconds),
            initial_delay_seconds=float(initial_delay_seconds),
            wake=wake,
        )

    def start_loops(self, *, task_logger: Any = None) -> dict[str, asyncio.Task[Any]]:
        """Start the timer of every registered loop that has none, by loop name.

        A loop whose timer ended keeps its handle, and so stays ended: nothing
        restarts a loop, so a status surface sees it `exited` rather than
        running again with no record of why it stopped. `clear_loops` drops
        every handle, after which this starts every registered loop afresh.
        """

        started: dict[str, asyncio.Task[Any]] = {}
        for name, loop in self._loops.items():
            if name in self._handles:
                continue
            started[name] = self._start_task(
                StorefrontBackgroundTask(name=name, task_factory=partial(self._timer, loop)),
                task_logger=task_logger,
            )
        return started

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

    async def _timer(self, loop: _RegisteredLoop) -> None:
        """A registered loop's timer: gate, a cycle when due, then `idle`.

        The gate is read again inside the cycle's lock, immediately before the
        step: a timer that passed its gate and then waited for an operator's
        step to finish must not start work a pause requested meanwhile holds,
        and a wake it has not acted on stays set for when the loop resumes. A
        failed cycle is recorded and logged by the cycle itself, and the timer
        carries on to its next interval.
        """

        clock = asyncio.get_running_loop().time
        due_at = clock() + loop.initial_delay_seconds
        while True:
            if self.gate(loop.name):
                await asyncio.sleep(HELD_POLL_SECONDS)
                continue
            woken = loop.wake is not None and loop.wake.is_set()
            remaining = due_at - clock()
            if remaining > 0 and not woken:
                await self.idle(remaining, wake=loop.wake)
                continue
            registered = self._steps[loop.route]
            try:
                result = await self._run_cycle(
                    loop.name, registered.step, trigger=TIMER_TRIGGER, wake=loop.wake
                )
            except Exception:
                # A failing step is recorded and logged by its cycle and never
                # reaches here; this is a failure before the step could start.
                self._logger.exception(
                    "[LIFECYCLE] %s timer could not start a cycle", loop.name
                )
                result = None
            if result is not _NOT_RUN:
                due_at = clock() + loop.interval_seconds

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

    def last_outcome(self, name: str) -> CycleOutcome | None:
        """The last outcome loop `name` recorded, or `None` before its first cycle."""

        return self._outcomes.get(name)

    def snapshot(self) -> dict[str, LoopSnapshot]:
        """Every loop's state and last recorded outcome, by loop name.

        Covers every loop with a state, every loop with a registered step, and
        every loop that has recorded an outcome, so a loop stepped but not
        timed is reported too, with no state.
        """

        states = self.states()
        names = (
            set(states)
            | {registered.name for registered in self._steps.values()}
            | set(self._outcomes)
        )
        return {
            name: LoopSnapshot(
                name=name,
                state=states.get(name),
                last_outcome=self._outcomes.get(name),
            )
            for name in sorted(names)
        }

    # ------------------------------------------------------------------
    # Stepping
    # ------------------------------------------------------------------

    async def run_cycle(self, route: str) -> Mapping[str, Any]:
        """Run exactly the operation one cycle of the loop runs, held or not.

        The cycle holds the loop's lock, so a step requested while the loop's
        timer is mid-cycle runs after that cycle, never alongside it. A held
        loop's timer runs no cycle, so a step while held never waits. Every
        step records exactly one outcome -- including one cancelled while it
        waited for the running cycle, which records a cancelled outcome naming
        no stage -- and a failure is raised to the caller.
        """

        registered = self._steps.get(route)
        if registered is None:
            raise LoopNotFound(route)
        return await self._run_cycle(registered.name, registered.step, trigger=STEP_TRIGGER)

    async def _run_cycle(
        self,
        name: str,
        step: LoopStep,
        *,
        trigger: str,
        wake: asyncio.Event | None = None,
    ) -> Any:
        """Run one cycle of loop `name` under its lock and record its outcome.

        A timer cycle re-reads the gate once it holds the lock and returns
        `_NOT_RUN`, recording nothing and leaving `wake` as it found it, when a
        pause has been requested; otherwise it clears `wake`, since the cycle
        about to run is the one the wake asked for. A timer cycle's failure is
        recorded and returned as `_FAILED`, not raised, so the timer carries on.
        """

        lock = self._cycle_locks.get(name)
        if lock is None:
            lock = self._cycle_locks[name] = self._cycle_lock_factory(name)
        generation = self._generation
        try:
            await lock.acquire()
        except asyncio.CancelledError as cancelled:
            if trigger == STEP_TRIGGER:
                self._record(name, trigger, None, cancelled, generation)
            raise
        try:
            if trigger == TIMER_TRIGGER and self.gate(name):
                return _NOT_RUN
            if wake is not None:
                wake.clear()
            generation = self._generation
            cycle = _CycleInProgress(self)
            token = _CURRENT_CYCLE.set(cycle)
            error: BaseException | None = None
            try:
                return await step()
            except BaseException as exc:
                error = exc
                if trigger == TIMER_TRIGGER and isinstance(exc, Exception):
                    return _FAILED
                raise
            finally:
                _CURRENT_CYCLE.reset(token)
                self._record(name, trigger, cycle.stage, error, generation)
        finally:
            lock.release()

    def enter_stage(self, stage: str) -> None:
        """Name the stage the cycle running in this task has reached.

        A failure is reported in the stage last entered. Outside a cycle of
        this controller -- a preview, or a step called directly -- it records
        nothing.
        """

        if stage not in CYCLE_STAGES:
            raise ValueError(f"unknown cycle stage {stage!r}; stages are {CYCLE_STAGES}")
        cycle = _CURRENT_CYCLE.get()
        if cycle is not None and cycle.controller is self:
            cycle.stage = stage

    def _record(
        self,
        name: str,
        trigger: str,
        stage: str | None,
        error: BaseException | None,
        generation: int,
    ) -> None:
        """Record one outcome; `stage` is `None` for a cycle that never started."""

        if error is None:
            outcome = CycleOutcome(
                finished_at=self._clock(), trigger=trigger, completed=True
            )
        else:
            if isinstance(error, asyncio.CancelledError):
                self._logger.info(
                    "[LIFECYCLE] %s %s cycle was cancelled %s",
                    name,
                    trigger,
                    f"in {stage}" if stage is not None else "before it started",
                )
            else:
                self._logger.error(
                    "[LIFECYCLE] %s %s cycle failed in %s",
                    name,
                    trigger,
                    stage,
                    exc_info=error,
                )
            disclosed = isinstance(error, self._disclosed_errors)
            outcome = CycleOutcome(
                finished_at=self._clock(),
                trigger=trigger,
                completed=False,
                stage=stage,
                error=CycleError(
                    type=type(error).__name__,
                    message=str(error) if disclosed else None,
                ),
            )
        if generation == self._generation:
            self._outcomes[name] = outcome

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

    def clear_loops(self, *, keep_registrations: bool = True) -> None:
        """Cancel every loop and drop its state, keeping registered steps.

        Production never unregisters a loop while serving. A process that tears
        its loops down and starts them again within one interpreter -- an
        application rebuilt in place -- uses this so stale handles and outcomes
        do not report for loops that no longer exist; `start_loops` starts the
        registered loops' timers again. With `keep_registrations=False` the
        loops registered with `register_loop` are forgotten too, their steps
        staying registered, so a later `start_loops` starts only what is
        registered again: a test's reset, which must not leave one test's loops
        for the next to start.
        """

        for handle in self._handles.values():
            if not handle.done():
                handle.cancel()
        if not keep_registrations:
            self._loops.clear()
        self._generation += 1
        self._handles.clear()
        self._outcomes.clear()
        # Fresh locks for the same reason as the fresh pause signal below: a
        # lock a cancelled cycle still holds belongs to the torn-down loop.
        self._cycle_locks.clear()
        self._acked.clear()
        self._gate_calls.clear()
        self._unregistered_reported.clear()
        self._declared.clear()
        self._pause_requested = False
        # A fresh signal: an event is bound to the event loop that first waited
        # on it, and loops started again may run on a different event loop.
        self._pause_signal = asyncio.Event()

    async def stop_loops(self, *, keep_registrations: bool = True) -> None:
        """`clear_loops`, then wait for every cancelled loop to end.

        A loop is cancelled at whatever await it is on; waiting here means none
        is still unwinding when the caller goes on, for instance to close the
        event loop the loops ran on.
        """

        handles = list(self._handles.values())
        self.clear_loops(keep_registrations=keep_registrations)
        await asyncio.gather(*handles, return_exceptions=True)


__all__ = [
    "CYCLE_STAGES",
    "CycleError",
    "CycleOutcome",
    "DEFAULT_CYCLE_STAGE",
    "HELD_POLL_SECONDS",
    "LoopNotFound",
    "LoopSnapshot",
    "LoopStep",
    "PreviewNotOffered",
    "QUIESCENCE_TIMEOUT_SECONDS",
    "STEP_TRIGGER",
    "StorefrontLoopController",
    "TIMER_TRIGGER",
]
