"""A held storefront's loops run no cycle, and nothing is torn down to achieve it.

These are the properties an end-to-end scenario relies on when it pauses once and
advances deliberately: while paused, no loop does work; the loops are still alive,
so nothing was interrupted part-way and no loop-local position was lost; and
resuming needs no restart, so there is no window where two copies of a loop
overlap.

The pause gate is checked at the top of a cycle rather than delivered as a
cancellation, which is what makes "every cycle either ran completely or never
began" true rather than "some cycle was stopped at whatever await it happened to
be sitting on".

These tests drive synthetic loops, so they prove the mechanism and say nothing
about which production loops use it. Each storefront's own wiring tests cover
that, and the two are only meaningful together.

Every interleaving is coordinated with events. A synthetic loop cycles once,
then idles through the controller until the test ticks it; while held it waits
for the test to release it. Nothing here waits on time.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
from datetime import UTC, datetime

import pytest

from core_storefront.app_startup import StorefrontBackgroundTask
from market_storefront_kit import LoopNotFound, PreviewNotOffered, StorefrontLoopController

#: A wait no test should ever see expire; a loop parked in it is woken only by a
#: tick or a pause request.
_FOREVER = 3600.0


@pytest.fixture
async def controller():
    loops = StorefrontLoopController()
    yield loops
    handles = list(loops._handles.values())
    loops.clear_loops()
    await asyncio.gather(*handles, return_exceptions=True)


class _Loop:
    """A loop shaped like the production ones: gate, one cycle, then `idle`."""

    def __init__(self, controller: StorefrontLoopController, name: str = "alpha") -> None:
        self.controller = controller
        self.name = name
        self.cycles = 0
        self.gated = asyncio.Event()
        self.held = asyncio.Event()
        self.worked = asyncio.Event()
        self.tick = asyncio.Event()
        self.unhold = asyncio.Event()

    async def body(self) -> None:
        while True:
            if self.controller.gate(self.name):
                self.gated.set()
                self.held.set()
                await self.unhold.wait()
                self.unhold.clear()
                continue
            self.gated.set()
            self.cycles += 1
            self.worked.set()
            await self.controller.idle(_FOREVER, wake=self.tick)
            self.tick.clear()

    def start(self, **kwargs) -> "_Loop":
        self.controller.start_loop(
            StorefrontBackgroundTask(name=self.name, task_factory=self.body), **kwargs
        )
        return self

    async def first_cycle(self) -> None:
        await asyncio.wait_for(self.worked.wait(), timeout=1)

    async def next_cycle(self) -> None:
        self.worked.clear()
        self.tick.set()
        await asyncio.wait_for(self.worked.wait(), timeout=1)

    async def regate_while_held(self) -> None:
        """Release the held loop once and wait for it to gate again."""
        self.held.clear()
        self.unhold.set()
        await asyncio.wait_for(self.held.wait(), timeout=1)

    async def resume(self) -> None:
        self.worked.clear()
        await self.controller.resume()
        self.unhold.set()
        await asyncio.wait_for(self.worked.wait(), timeout=1)


class TestPauseHoldsEveryLoopIdle:
    async def test_a_running_loop_does_work(self, controller):
        loop = _Loop(controller).start()

        await loop.first_cycle()
        await loop.next_cycle()

        assert loop.cycles == 2

    async def test_a_paused_loop_does_no_work_at_all(self, controller):
        loop = _Loop(controller).start()
        await loop.first_cycle()

        assert await controller.pause() == {"alpha": "paused"}
        loop.tick.set()
        await loop.regate_while_held()
        await loop.regate_while_held()

        assert loop.cycles == 1, (
            "a paused loop performed work — the whole contract is that a paused "
            "storefront changes no state on its own"
        )

    async def test_a_pause_interrupts_the_wait_between_cycles(self, controller):
        """A loop idling between cycles reaches its gate as soon as a pause is
        requested, however long its interval, so the bounded pause sees it stop."""
        loop = _Loop(controller).start()
        await loop.first_cycle()

        states = await asyncio.wait_for(controller.pause(), timeout=1)

        assert states == {"alpha": "paused"}

    async def test_pausing_does_not_stop_the_task(self, controller):
        """Idle, not torn down.

        The task staying alive is what preserves loop-local state across a pause
        — the capacity poller's feed position above all — and what removes any
        possibility of a half-finished cycle.
        """
        loop = _Loop(controller).start()
        await loop.first_cycle()

        await controller.pause()

        assert not controller._handles["alpha"].done()
        assert controller.states() == {"alpha": "paused"}

    async def test_resuming_returns_the_same_loop_to_work(self, controller):
        loop = _Loop(controller).start()
        await loop.first_cycle()
        before = controller._handles["alpha"]
        await controller.pause()

        await loop.resume()

        assert loop.cycles == 2, "resuming did not return the loop to work"
        assert controller._handles["alpha"] is before, (
            "resume replaced the task — a restart would lose loop-local position "
            "and could overlap a predecessor"
        )


class TestIdempotence:
    async def test_pausing_twice_is_harmless(self, controller):
        loop = _Loop(controller).start()
        await loop.first_cycle()

        await controller.pause()
        states = await controller.pause()

        assert states == {"alpha": "paused"}

    async def test_resuming_a_never_paused_storefront_changes_nothing(self, controller):
        loop = _Loop(controller).start()
        await loop.first_cycle()
        before = controller._handles["alpha"]

        states = await controller.resume()

        assert states == {"alpha": "running"}
        assert controller._handles["alpha"] is before


class TestAScheduledLoopIsNotYetRunning:
    """`running` is earned by reaching a gate, not by having a task object.

    Registration is `create_task`, which schedules a coroutine without executing
    a step of it. A loop reported `running` at that moment cannot observe a
    pause, so a caller that pauses on the strength of it is told the loop stopped
    when it had not started.
    """

    async def test_a_registered_loop_reports_starting_before_its_first_gate(self, controller):
        _Loop(controller).start()

        assert controller.states() == {"alpha": "starting"}
        assert controller.starting_loop_names() == ["alpha"]

    async def test_it_reports_running_once_it_has_gated(self, controller):
        loop = _Loop(controller).start()

        await asyncio.wait_for(loop.gated.wait(), timeout=1)

        assert controller.states() == {"alpha": "running"}
        assert controller.starting_loop_names() == []

    async def test_a_loop_that_never_gates_is_not_reported_as_pausing(self, controller):
        """The two are told apart by whether a cycle is in flight.

        `pausing` promises a cycle that will finish and then stop; a loop that has
        never gated promises nothing. Reporting the second as the first would make
        a loop that reads the pause without acknowledging indistinguishable from
        one finishing a long reconcile.

        Requests the pause without waiting rather than through `pause`, which
        would spend the whole quiescence window waiting for an acknowledgement
        that never comes.
        """
        entered = asyncio.Event()

        async def _never_gates() -> None:
            entered.set()
            await asyncio.Event().wait()

        controller.start_loop(StorefrontBackgroundTask(name="alpha", task_factory=_never_gates))
        await asyncio.wait_for(entered.wait(), timeout=1)

        controller.request_pause(True)

        assert controller.states() == {"alpha": "starting"}

    async def test_loops_check_separates_starting_from_ended(self, controller):
        loop = _Loop(controller).start()
        assert controller.loops_check().startswith("starting:")

        await asyncio.wait_for(loop.gated.wait(), timeout=1)
        assert controller.loops_check() == "ok"

    async def test_loops_check_reports_no_registered_loops(self, controller):
        """Distinct from healthy. A storefront with no timer loops registered has
        not finished starting, and an empty registry must not read as ok."""
        assert controller.loops_check() != "ok"


async def _ended(controller: StorefrontLoopController, name: str) -> None:
    await asyncio.wait_for(
        asyncio.gather(controller._handles[name], return_exceptions=True), timeout=1
    )


class TestALoopThatEnds:
    async def test_an_ended_loop_is_named_as_failed(self, controller):
        async def _exits() -> None:
            return None

        controller.start_loop(StorefrontBackgroundTask(name="alpha", task_factory=_exits))
        await _ended(controller, "alpha")

        assert controller.failed_loop_names() == ["alpha"]
        assert controller.loops_check().startswith("error:")

    async def test_a_loop_that_raises_is_reported_as_ended(self, controller):
        """Not as cancelled, and not as merely absent.

        Nothing restarts a loop, so a loop that raised is stopped for the life of
        the process, and a health surface has to be able to tell it apart from a
        loop that has not started yet.
        """
        async def _raises() -> None:
            raise RuntimeError("loop failed")

        controller.start_loop(StorefrontBackgroundTask(name="alpha", task_factory=_raises))
        await _ended(controller, "alpha")

        assert controller.states() == {"alpha": "exited"}
        assert controller.failed_loop_names() == ["alpha"]


class TestGateNameDiscipline:
    async def test_gating_under_an_unregistered_name_is_reported(self, controller, caplog):
        """A misspelled name acknowledges something nobody waits on.

        The registered loop then stays unacknowledged forever, which presents
        exactly as a loop that never gates. The warning is the only thing that
        tells the two apart from outside the process.
        """
        _Loop(controller).start()

        with caplog.at_level("WARNING"):
            controller.gate("alpah")

        assert any("not registered" in r.getMessage() for r in caplog.records)


class TestLoopStateReporting:
    async def test_every_registered_loop_is_reported(self, controller):
        for name in ("alpha", "beta"):
            _Loop(controller, name).start()

        assert sorted(controller.states()) == ["alpha", "beta"]
        assert controller.registered_loop_names() == ["alpha", "beta"]

    async def test_a_loop_that_exits_on_its_own_is_not_reported_as_paused(self, controller):
        """A crashed loop is neither working nor deliberately idle.

        Reporting it as either would hide the crash behind an operator control's
        vocabulary, which is what the status surface exists to prevent.
        """
        async def _exits() -> None:
            return None

        controller.start_loop(StorefrontBackgroundTask(name="alpha", task_factory=_exits))
        await _ended(controller, "alpha")
        await controller.pause()

        assert controller.states()["alpha"] == "exited"


class TestPauseDoesNotClaimQuiescenceItCannotSee:
    """`paused` must mean the loop reached its gate, not that a flag was set.

    This is the guarantee the whole control exists to provide: a caller that reads
    `paused` uses it to decide nothing is still writing. A status derived from the
    flag alone reports `paused` for a loop halfway through a reconcile, and no
    assertion built on it can fail — which is worse than no assertion, because it
    looks like proof.
    """

    async def test_a_loop_mid_cycle_is_reported_pausing_not_paused(self, controller):
        entered = asyncio.Event()
        release = asyncio.Event()

        async def _slow_loop() -> None:
            while True:
                if controller.gate("alpha"):
                    await asyncio.Event().wait()
                entered.set()
                await release.wait()

        controller.start_loop(StorefrontBackgroundTask(name="alpha", task_factory=_slow_loop))
        await asyncio.wait_for(entered.wait(), timeout=1)

        # The cycle is in flight and cannot come back until released, so the
        # bounded wait expires and the report must say so rather than claiming a
        # stop it cannot see. The loop cannot arrive, so the expiry is certain;
        # a short bound keeps the test quick.
        controller.request_pause(True)
        await controller.await_quiescence(timeout=0.05)

        assert controller.states() == {"alpha": "pausing"}, (
            "a loop still inside a cycle was reported as paused; a caller would "
            "read that as 'nothing is in flight' on evidence that cannot show it"
        )

        # Let the cycle finish. The loop returns to its gate, finds the pause, and
        # acknowledges — only now is `paused` true.
        release.set()
        await asyncio.wait_for(controller.await_quiescence(), timeout=1)
        assert controller.states() == {"alpha": "paused"}

    async def test_quiescence_returns_once_every_loop_reaches_its_gate(self, controller):
        loop = _Loop(controller).start()
        await loop.first_cycle()

        states = await asyncio.wait_for(controller.pause(), timeout=1)

        assert loop.held.is_set()
        assert states == {"alpha": "paused"}, (
            "a loop sitting at its gate should be reported paused without the "
            f"bounded wait having to expire: {states}"
        )


class TestDeclaredGatesWithoutAHandle:
    """Gated names whose tasks are created elsewhere still hold a pause.

    Capacity polling fans out one poller per site inside
    `kit/capacity-publication`, which owns the gather, so the storefront never
    holds a task per site. Without declaring those names, quiescence would not
    wait on them, and a site poller could still be mid-cycle while the pause
    reported every loop idle -- optimistic in the one direction a pause exists to
    prevent.
    """

    async def test_a_declared_gate_is_waited_on_and_reports_paused(self, controller):
        name = "capacity_events_poller:default"
        site_gate = controller.declare(name)
        gated = asyncio.Event()
        held = asyncio.Event()

        async def _site_poller() -> None:
            while True:
                if site_gate():
                    held.set()
                    await asyncio.Event().wait()
                gated.set()
                await controller.idle(_FOREVER)

        task = asyncio.create_task(_site_poller())
        try:
            await asyncio.wait_for(gated.wait(), timeout=1)
            states = await asyncio.wait_for(controller.pause(), timeout=1)
            assert states.get(name) == "paused", (
                "a declared per-site gate was not waited on; the pause reported "
                f"{states}, which would let a site still writing look idle"
            )
            assert held.is_set()
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_declaring_does_not_warn_about_an_unregistered_name(self, controller, caplog):
        """A declared name is known, so gating it is not a wiring mistake."""
        name = "capacity_events_poller:somewhere"
        gate = controller.declare(name)
        with caplog.at_level("WARNING"):
            gate()
        assert not [r for r in caplog.records if "not registered" in r.message], (
            "declaring a name should suppress the unregistered-name warning, "
            "which exists for names nobody waits on"
        )


class TestIdleWakesOnPause:
    async def test_idle_returns_when_a_pause_is_requested(self, controller):
        waiting = asyncio.create_task(controller.idle(_FOREVER))
        controller.request_pause(True)
        await asyncio.wait_for(waiting, timeout=1)

    async def test_idle_returns_on_its_wake_event(self, controller):
        wake = asyncio.Event()
        waiting = asyncio.create_task(controller.idle(_FOREVER, wake=wake))
        wake.set()
        await asyncio.wait_for(waiting, timeout=1)


class TestSteps:
    async def test_a_held_loop_is_stepped_through_its_registered_operation(self, controller):
        calls: list[str] = []

        async def _step():
            calls.append("step")
            return {"loop": "alpha", "processed": 1}

        loop = _Loop(controller).start(route="alpha-route", step=_step)
        await loop.first_cycle()
        await controller.pause()

        result = await controller.run_cycle("alpha-route")

        assert result == {"loop": "alpha", "processed": 1}
        assert calls == ["step"]
        assert loop.cycles == 1, "a step runs its registered operation, not the loop body"
        assert controller.states() == {"alpha": "paused"}, "a step must not resume the loops"

    async def test_an_unknown_route_is_not_found(self, controller):
        with pytest.raises(LoopNotFound):
            await controller.run_cycle("missing")

    async def test_a_loop_without_a_preview_offers_none(self, controller):
        async def _step():
            return {}

        controller.register_step("publication", route="publication", step=_step)
        with pytest.raises(PreviewNotOffered):
            await controller.dry_run("publication")

    async def test_a_preview_runs_and_the_step_does_not(self, controller):
        calls: list[str] = []

        async def _step():
            calls.append("step")
            return {}

        async def _preview():
            calls.append("preview")
            return {"dry_run": True}

        controller.register_step("alpha", route="alpha", step=_step, preview=_preview)
        assert await controller.dry_run("alpha") == {"dry_run": True}
        assert calls == ["preview"]

    def test_a_route_cannot_name_two_loops(self, controller):
        async def _step():
            return {}

        controller.register_step("alpha", route="shared", step=_step)
        with pytest.raises(ValueError):
            controller.register_step("beta", route="shared", step=_step)

    def test_step_routes_name_their_loops(self, controller):
        async def _step():
            return {}

        controller.register_step("settlement_servicing", route="settlement-servicing", step=_step)
        assert controller.step_routes() == {"settlement-servicing": "settlement_servicing"}

    async def test_clearing_loops_keeps_registered_steps(self, controller):
        async def _step():
            return {"ok": True}

        _Loop(controller).start(step=_step)
        controller.clear_loops()

        assert controller.states() == {}
        assert await controller.run_cycle("alpha") == {"ok": True}


class _ParkedStep:
    """A step whose every invocation parks until the test releases it.

    Each invocation is numbered from zero; `entered(i)` is set when invocation
    `i` starts and `release(i)` lets it return. `in_flight` and
    `most_in_flight` show whether two invocations ever overlapped.
    """

    def __init__(self, *, fail: BaseException | None = None) -> None:
        self.calls = 0
        self.in_flight = 0
        self.most_in_flight = 0
        self._entered: dict[int, asyncio.Event] = {}
        self._release: dict[int, asyncio.Event] = {}
        self._fail = fail

    def entered(self, index: int) -> asyncio.Event:
        return self._entered.setdefault(index, asyncio.Event())

    def release(self, index: int) -> asyncio.Event:
        return self._release.setdefault(index, asyncio.Event())

    async def __call__(self):
        index = self.calls
        self.calls += 1
        self.in_flight += 1
        self.most_in_flight = max(self.most_in_flight, self.in_flight)
        self.entered(index).set()
        try:
            await self.release(index).wait()
        finally:
            self.in_flight -= 1
        if self._fail is not None:
            raise self._fail
        return {"invocation": index}


class _CountingStep:
    """A step that returns at once, signalling each invocation; it may name a stage and fail."""

    def __init__(self, *, fail: BaseException | None = None, stage: str | None = None):
        self.calls = 0
        self.done = asyncio.Event()
        self._fail = fail
        self._stage = stage
        self.controller: StorefrontLoopController | None = None

    async def __call__(self):
        self.calls += 1
        self.done.set()
        if self._stage is not None and self.controller is not None:
            self.controller.enter_stage(self._stage)
        if self._fail is not None:
            raise self._fail
        return {"calls": self.calls}

    async def next_call(self) -> None:
        self.done.clear()
        await asyncio.wait_for(self.done.wait(), timeout=1)


async def _cycle_recorded(lock: asyncio.Lock) -> None:
    """Wait until the cycle holding `lock` has recorded its outcome.

    The step's own signal fires before the cycle's outcome is recorded, so a
    test reading the snapshot after it waits for the controller to get there.
    The cycle holds the loop's lock until it has recorded, so acquiring that
    lock once is enough.
    """

    async with lock:
        pass


class _LogSignal(logging.Handler):
    """Signals when the controller logs a record whose message starts with `prefix`.

    The controller logs a loop's first gate read as it reaches its gate, and a
    timer then goes straight into its wait, so once that signal fires and the
    test resumes, the timer is waiting.
    """

    def __init__(self, prefix: str) -> None:
        super().__init__(level=logging.INFO)
        self._prefix = prefix
        self.seen = asyncio.Event()

    def emit(self, record: logging.LogRecord) -> None:
        if record.getMessage().startswith(self._prefix):
            self.seen.set()


class _ObservedLock(asyncio.Lock):
    """A loop's cycle lock, reporting each attempt to acquire it.

    Lets a test wait until a step is actually waiting on the lock, rather than
    yielding and hoping it got there.
    """

    def __init__(self) -> None:
        super().__init__()
        self.attempts = 0
        self._attempted = asyncio.Event()

    async def acquire(self) -> bool:
        self.attempts += 1
        self._attempted.set()
        return await super().acquire()

    async def attempts_reach(self, count: int) -> None:
        while self.attempts < count:
            self._attempted.clear()
            await asyncio.wait_for(self._attempted.wait(), timeout=1)


_WATCHED_LOGGERS = itertools.count()


def _watched_logger(handler: logging.Handler) -> logging.Logger:
    """A logger of the test's own, so the watcher sees only this controller.

    Each call names a new logger, so a handler never attaches to one another test used.
    """

    logger = logging.getLogger(f"{__name__}.watched{next(_WATCHED_LOGGERS)}")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    return logger


@pytest.fixture
async def observed():
    """A controller whose every loop's cycles hold one observed lock."""

    lock = _ObservedLock()
    loops = StorefrontLoopController(cycle_lock_factory=lambda _name: lock)
    yield loops, lock
    handles = list(loops._handles.values())
    loops.clear_loops()
    await asyncio.gather(*handles, return_exceptions=True)


class TestTheControllerRunsRegisteredLoops:
    """A loop registered with its interval is timed by the controller itself.

    The timer is a gate, `run_cycle`'s own operation, and an `idle` wait, so
    the timer and an operator's step run exactly one operation, under one lock.
    """

    async def test_the_timer_runs_the_registered_step_through_the_controller(self, observed):
        controller, lock = observed
        step = _CountingStep()
        controller.register_loop("alpha", step=step, interval_seconds=_FOREVER)

        controller.start_loops()
        await asyncio.wait_for(step.done.wait(), timeout=1)
        await _cycle_recorded(lock)

        outcome = controller.last_outcome("alpha")
        assert step.calls == 1
        assert outcome is not None and outcome.completed and outcome.trigger == "timer"

    async def test_a_step_requested_during_a_timer_cycle_runs_after_it(self, observed):
        controller, lock = observed
        step = _ParkedStep()
        controller.register_loop("alpha", route="alpha-route", step=step, interval_seconds=_FOREVER)
        controller.start_loops()
        await asyncio.wait_for(step.entered(0).wait(), timeout=1)

        stepped = asyncio.create_task(controller.run_cycle("alpha-route"))
        await lock.attempts_reach(2)
        assert step.calls == 1, "the step started while the timer's cycle was running"

        step.release(0).set()
        await asyncio.wait_for(step.entered(1).wait(), timeout=1)
        timer_outcome = controller.last_outcome("alpha")
        assert timer_outcome is not None and timer_outcome.trigger == "timer"
        assert timer_outcome.completed

        step.release(1).set()
        assert await asyncio.wait_for(stepped, timeout=1) == {"invocation": 1}
        step_outcome = controller.last_outcome("alpha")
        assert step_outcome is not None and step_outcome.trigger == "step"
        assert step_outcome.completed
        assert step.most_in_flight == 1

    async def test_two_steps_of_one_loop_run_one_after_the_other(self, observed):
        controller, lock = observed
        step = _ParkedStep()
        controller.register_step("alpha", route="alpha", step=step)

        first = asyncio.create_task(controller.run_cycle("alpha"))
        await asyncio.wait_for(step.entered(0).wait(), timeout=1)
        second = asyncio.create_task(controller.run_cycle("alpha"))
        await lock.attempts_reach(2)
        assert step.calls == 1

        step.release(0).set()
        step.release(1).set()
        await asyncio.wait_for(asyncio.gather(first, second), timeout=1)
        assert step.calls == 2 and step.most_in_flight == 1

    async def test_a_held_loop_runs_no_timer_cycle_and_its_step_does_not_wait(self, observed):
        controller, lock = observed
        step = _CountingStep()
        controller.register_loop("alpha", step=step, interval_seconds=_FOREVER)
        controller.request_pause(True)

        controller.start_loops()
        await asyncio.wait_for(controller.await_quiescence(), timeout=1)
        assert controller.states() == {"alpha": "paused"}
        assert not lock.locked() and lock.attempts == 0, "the held timer took the cycle lock"

        result = await asyncio.wait_for(controller.run_cycle("alpha"), timeout=1)

        assert result == {"calls": 1}
        assert lock.attempts == 1, "the step waited on, or contended for, the cycle lock"
        assert step.calls == 1, "the held timer ran a cycle of its own"
        assert controller.last_outcome("alpha").trigger == "step"
        assert controller.states() == {"alpha": "paused"}, "a step must not resume the loops"

    async def test_a_pause_lands_within_the_bound_with_a_long_interval(self, observed):
        """The controller's own timer waits through `idle`, so a pause requested
        while it waits out an interval far longer than the test reaches its gate
        at once."""
        controller, lock = observed
        step = _CountingStep()
        controller.register_loop("alpha", step=step, interval_seconds=_FOREVER)
        controller.start_loops()
        await asyncio.wait_for(step.done.wait(), timeout=1)
        await _cycle_recorded(lock)

        states = await asyncio.wait_for(controller.pause(), timeout=1)

        assert states == {"alpha": "paused"}
        assert step.calls == 1

    async def test_a_wake_while_held_runs_the_cycle_once_resumed(self, controller):
        step = _CountingStep()
        wake = asyncio.Event()
        controller.register_loop("alpha", step=step, interval_seconds=_FOREVER, wake=wake)
        controller.start_loops()
        await asyncio.wait_for(step.done.wait(), timeout=1)
        await controller.pause()

        wake.set()
        await controller.resume()
        await step.next_call()

        assert step.calls == 2

    async def test_a_wake_ends_the_wait_between_cycles(self, controller):
        step = _CountingStep()
        wake = asyncio.Event()
        controller.register_loop("alpha", step=step, interval_seconds=_FOREVER, wake=wake)
        controller.start_loops()
        await asyncio.wait_for(step.done.wait(), timeout=1)

        wake.set()
        await step.next_call()

        assert step.calls == 2

    async def test_the_first_cycle_waits_out_its_initial_delay_through_the_controller(self):
        """A delayed first cycle still reads its gate, so a pause during the delay
        lands at once, and a wake brings the cycle forward."""
        watcher = _LogSignal("[LIFECYCLE] alpha reached its gate for the first time")
        controller = StorefrontLoopController(logger=_watched_logger(watcher))
        step = _CountingStep()
        wake = asyncio.Event()
        controller.register_loop(
            "alpha",
            step=step,
            interval_seconds=_FOREVER,
            initial_delay_seconds=_FOREVER,
            wake=wake,
        )
        handle = controller.start_loops()["alpha"]
        await asyncio.wait_for(watcher.seen.wait(), timeout=1)
        assert controller.states() == {"alpha": "running"}

        assert await asyncio.wait_for(controller.pause(), timeout=1) == {"alpha": "paused"}
        assert step.calls == 0

        await controller.resume()
        wake.set()
        await step.next_call()
        assert step.calls == 1
        controller.clear_loops()
        await asyncio.gather(handle, return_exceptions=True)

    async def _timer_queued_behind_a_step(self, controller, lock, wake):
        """Park a step, wake the timer, and wait until it queues on the cycle lock."""
        step = _ParkedStep()
        controller.register_loop(
            "alpha",
            step=step,
            interval_seconds=_FOREVER,
            initial_delay_seconds=_FOREVER,
            wake=wake,
        )
        stepped = asyncio.create_task(controller.run_cycle("alpha"))
        await asyncio.wait_for(step.entered(0).wait(), timeout=1)
        controller.start_loops()
        wake.set()
        await lock.attempts_reach(2)
        return step, stepped

    async def test_a_timer_held_while_it_waited_on_a_step_runs_no_cycle(self, observed):
        """The timer reads its gate again under the lock, immediately before the
        step, so a pause requested while it queued behind a step holds it."""
        controller, lock = observed
        step, stepped = await self._timer_queued_behind_a_step(
            controller, lock, asyncio.Event()
        )

        controller.request_pause(True)
        step.release(0).set()
        await asyncio.wait_for(stepped, timeout=1)
        await asyncio.wait_for(controller.await_quiescence(timeout=1), timeout=2)

        assert controller.states() == {"alpha": "paused"}
        assert step.calls == 1, "the held timer ran a cycle after the step"
        assert controller.last_outcome("alpha").trigger == "step"

    async def test_a_wake_the_held_timer_did_not_act_on_runs_once_resumed(self, observed):
        """A wake survives a pause that held the timer before its cycle began, so
        the loop runs promptly once resumed rather than waiting out its interval."""
        controller, lock = observed
        wake = asyncio.Event()
        step, stepped = await self._timer_queued_behind_a_step(controller, lock, wake)

        controller.request_pause(True)
        step.release(0).set()
        await asyncio.wait_for(stepped, timeout=1)
        await asyncio.wait_for(controller.await_quiescence(timeout=1), timeout=2)
        assert wake.is_set(), "the held timer consumed a wake it did not act on"

        await controller.resume()
        step.release(1).set()
        await asyncio.wait_for(step.entered(1).wait(), timeout=1)
        await _cycle_recorded(lock)
        assert controller.last_outcome("alpha").trigger == "timer"
        assert not wake.is_set()

    async def test_a_timer_that_cannot_start_a_cycle_logs_it_and_carries_on(self, caplog):
        def _no_lock(name: str) -> asyncio.Lock:
            raise RuntimeError("no lock for you")

        watcher = _LogSignal("[LIFECYCLE] alpha timer could not start a cycle")
        controller = StorefrontLoopController(
            cycle_lock_factory=_no_lock, logger=_watched_logger(watcher)
        )
        controller.register_loop("alpha", step=_CountingStep(), interval_seconds=_FOREVER)
        with caplog.at_level("ERROR"):
            handle = controller.start_loops()["alpha"]
            await asyncio.wait_for(watcher.seen.wait(), timeout=1)

        assert any(
            "could not start a cycle" in r.getMessage() and r.exc_info for r in caplog.records
        )
        # It carries on: waiting out its interval, so a pause reaches it at once.
        assert await asyncio.wait_for(controller.pause(), timeout=1) == {"alpha": "paused"}
        assert controller.last_outcome("alpha") is None
        controller.clear_loops()
        await asyncio.gather(handle, return_exceptions=True)

    async def test_a_failing_cycle_does_not_end_the_timer(self, controller):
        step = _CountingStep(fail=RuntimeError("boom"))
        wake = asyncio.Event()
        controller.register_loop("alpha", step=step, interval_seconds=_FOREVER, wake=wake)
        controller.start_loops()
        await asyncio.wait_for(step.done.wait(), timeout=1)

        wake.set()
        await step.next_call()

        assert step.calls == 2
        assert controller.states() == {"alpha": "running"}

    def test_a_registered_loop_needs_a_positive_interval(self, controller):
        with pytest.raises(ValueError):
            controller.register_loop("alpha", step=_CountingStep(), interval_seconds=0)

    async def test_a_running_loop_cannot_be_registered_again(self, controller):
        controller.register_loop("alpha", step=_CountingStep(), interval_seconds=_FOREVER)
        controller.start_loops()

        with pytest.raises(ValueError):
            controller.register_loop("alpha", step=_CountingStep(), interval_seconds=_FOREVER)

    async def test_starting_again_starts_no_second_timer(self, controller):
        controller.register_loop("alpha", step=_CountingStep(), interval_seconds=_FOREVER)

        first = controller.start_loops()
        second = controller.start_loops()

        assert list(first) == ["alpha"]
        assert second == {}


class _ConfigurationProblem(ValueError):
    """Stands in for a storefront's own configuration error, which it discloses."""


class TestCycleOutcomes:
    async def test_a_raising_step_records_one_failed_outcome_naming_its_stage(self, controller):
        step = _CountingStep(fail=RuntimeError("boom"), stage="compose")
        step.controller = controller
        controller.register_step("publication", route="publication", step=step)

        with pytest.raises(RuntimeError):
            await controller.run_cycle("publication")

        outcome = controller.last_outcome("publication")
        assert outcome is not None
        assert outcome.completed is False
        assert outcome.stage == "compose"
        assert outcome.trigger == "step"
        assert outcome.error.type == "RuntimeError"

    async def test_a_failure_with_no_stage_named_is_in_the_run_stage(self, controller):
        step = _CountingStep(fail=RuntimeError("boom"))
        controller.register_step("alpha", route="alpha", step=step)

        with pytest.raises(RuntimeError):
            await controller.run_cycle("alpha")

        assert controller.last_outcome("alpha").stage == "run"

    async def test_a_completed_cycle_names_no_stage_or_error(self, controller):
        step = _CountingStep(stage="converge")
        step.controller = controller
        controller.register_step("alpha", route="alpha", step=step)

        await controller.run_cycle("alpha")

        outcome = controller.last_outcome("alpha")
        assert outcome.completed is True
        assert outcome.stage is None and outcome.error is None

    async def test_an_undisclosed_exception_is_recorded_by_type_only(self, caplog):
        controller = StorefrontLoopController(disclosed_errors=(_ConfigurationProblem,))
        secret_url = "https://site-authority.invalid/private?token=canary-7f3a"

        async def _step():
            raise ConnectionError(f"could not reach {secret_url}")

        controller.register_step("publication", route="publication", step=_step)
        with caplog.at_level("ERROR"), pytest.raises(ConnectionError):
            await controller.run_cycle("publication")

        outcome = controller.last_outcome("publication")
        assert outcome.error.type == "ConnectionError"
        assert outcome.error.message is None
        assert secret_url not in repr(outcome.to_dict())
        assert any(
            r.exc_info and secret_url in str(r.exc_info[1]) for r in caplog.records
        ), "the full exception belongs in the log"

    async def test_a_disclosed_exception_keeps_its_message(self):
        controller = StorefrontLoopController(disclosed_errors=(_ConfigurationProblem,))

        async def _step():
            raise _ConfigurationProblem("no registry is configured: [registry].urls is empty")

        controller.register_step("publication", route="publication", step=_step)
        with pytest.raises(_ConfigurationProblem):
            await controller.run_cycle("publication")

        error = controller.last_outcome("publication").error
        assert error.type == "_ConfigurationProblem"
        assert error.message == "no registry is configured: [registry].urls is empty"

    async def test_a_timer_cycle_that_fails_is_recorded_as_a_step_would_be(self, observed):
        controller, lock = observed
        step = _CountingStep(fail=RuntimeError("boom"), stage="run")
        step.controller = controller
        controller.register_loop("alpha", step=step, interval_seconds=_FOREVER)
        controller.start_loops()
        await asyncio.wait_for(step.done.wait(), timeout=1)
        await _cycle_recorded(lock)

        outcome = controller.last_outcome("alpha")
        assert outcome.trigger == "timer"
        assert outcome.completed is False
        assert outcome.stage == "run" and outcome.error.type == "RuntimeError"

    async def test_a_cancelled_cycle_records_that_it_did_not_complete(self, controller):
        step = _ParkedStep()
        controller.register_step("alpha", route="alpha", step=step)
        stepped = asyncio.create_task(controller.run_cycle("alpha"))
        await asyncio.wait_for(step.entered(0).wait(), timeout=1)

        stepped.cancel()
        await asyncio.gather(stepped, return_exceptions=True)

        outcome = controller.last_outcome("alpha")
        assert outcome.completed is False
        assert outcome.error.type == "CancelledError"

    async def test_a_step_cancelled_while_it_waits_records_a_cancelled_outcome(self, observed):
        """Each step records exactly one outcome, even one that never got to run;
        it reached no stage, so it names none."""
        controller, lock = observed
        step = _ParkedStep()
        controller.register_step("alpha", route="alpha", step=step)
        first = asyncio.create_task(controller.run_cycle("alpha"))
        await asyncio.wait_for(step.entered(0).wait(), timeout=1)
        queued = asyncio.create_task(controller.run_cycle("alpha"))
        await lock.attempts_reach(2)

        queued.cancel()
        await asyncio.gather(queued, return_exceptions=True)

        outcome = controller.last_outcome("alpha")
        assert outcome.trigger == "step" and outcome.completed is False
        assert outcome.stage is None and outcome.error.type == "CancelledError"
        assert step.calls == 1

        step.release(0).set()
        await asyncio.wait_for(first, timeout=1)
        assert controller.last_outcome("alpha").completed is True

    async def test_a_preview_records_nothing(self, controller):
        async def _step():
            return {}

        async def _preview():
            return {"dry_run": True}

        controller.register_step("alpha", route="alpha", step=_step, preview=_preview)
        await controller.dry_run("alpha")

        assert controller.last_outcome("alpha") is None
        assert controller.snapshot()["alpha"].last_outcome is None

    async def test_a_stage_marked_outside_a_cycle_records_nothing(self, controller):
        controller.enter_stage("compose")

        assert controller.snapshot() == {}

    def test_an_unknown_stage_is_refused(self, controller):
        with pytest.raises(ValueError):
            controller.enter_stage("publish")

    async def test_each_outcome_is_stamped_by_the_clock(self):
        stamp = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
        controller = StorefrontLoopController(clock=lambda: stamp)
        controller.register_step("alpha", route="alpha", step=_CountingStep())

        await controller.run_cycle("alpha")

        assert controller.last_outcome("alpha").finished_at == stamp
        assert controller.last_outcome("alpha").to_dict()["finished_at"] == stamp.isoformat()


class TestSnapshot:
    async def test_an_exited_loop_is_distinct_from_a_running_loop_whose_cycle_failed(
        self, observed
    ):
        controller, lock = observed
        failing = _CountingStep(fail=RuntimeError("boom"))
        controller.register_loop("failing", step=failing, interval_seconds=_FOREVER)
        controller.start_loops()
        await asyncio.wait_for(failing.done.wait(), timeout=1)
        await _cycle_recorded(lock)

        async def _exits() -> None:
            return None

        controller.start_loop(StorefrontBackgroundTask(name="ended", task_factory=_exits))
        await _ended(controller, "ended")

        snapshot = controller.snapshot()
        assert snapshot["failing"].state == "running"
        assert snapshot["failing"].last_outcome.completed is False
        assert snapshot["ended"].state == "exited"
        assert snapshot["ended"].last_outcome is None

    async def test_a_cancelled_timer_is_reported_cancelled_with_its_last_outcome(
        self, observed
    ):
        controller, lock = observed
        step = _CountingStep()
        controller.register_loop("alpha", step=step, interval_seconds=_FOREVER)
        handles = controller.start_loops()
        await asyncio.wait_for(step.done.wait(), timeout=1)
        await _cycle_recorded(lock)

        handles["alpha"].cancel()
        await asyncio.gather(handles["alpha"], return_exceptions=True)

        snapshot = controller.snapshot()["alpha"]
        assert snapshot.state == "cancelled"
        assert snapshot.last_outcome.completed is True

    async def test_a_step_only_loop_is_reported_without_a_state(self, controller):
        controller.register_step("publication", route="publication", step=_CountingStep())

        await controller.run_cycle("publication")

        snapshot = controller.snapshot()["publication"]
        assert snapshot.state is None
        assert snapshot.last_outcome.completed is True
        assert snapshot.to_dict()["last_outcome"]["trigger"] == "step"

    async def test_clearing_loops_drops_outcomes_and_starting_again_restarts_timers(
        self, observed
    ):
        controller, lock = observed
        step = _CountingStep()
        controller.register_loop("alpha", step=step, interval_seconds=_FOREVER)
        before = controller.start_loops()["alpha"]
        await asyncio.wait_for(step.done.wait(), timeout=1)
        await _cycle_recorded(lock)

        controller.clear_loops()
        await asyncio.gather(before, return_exceptions=True)
        assert controller.last_outcome("alpha") is None

        controller.start_loops()
        await step.next_call()
        assert step.calls == 2
