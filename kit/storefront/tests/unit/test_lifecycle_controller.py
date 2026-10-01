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
"""

from __future__ import annotations

import asyncio

import pytest

from core_storefront.app_startup import StorefrontBackgroundTask
from market_storefront_kit import StorefrontLoopController


@pytest.fixture
async def controller():
    """Async so teardown runs inside the test's event loop.

    Cancelling a task after the loop has closed raises `Event loop is closed`,
    reported against the controller rather than the fixture.
    """
    loops = StorefrontLoopController()
    yield loops
    loops.clear_loops()
    await asyncio.sleep(0)


def _counting_loop(controller: StorefrontLoopController, counter: list[int], *, interval: float = 0.001):
    """A loop shaped like the real ones: gate, then work."""

    async def _loop() -> None:
        while True:
            await asyncio.sleep(interval)
            if controller.gate("alpha"):
                continue
            counter.append(1)

    return _loop


async def _let_loops_run(cycles: int = 5, interval: float = 0.001) -> None:
    await asyncio.sleep(interval * cycles * 3)


class TestPauseHoldsEveryLoopIdle:
    async def test_a_running_loop_does_work(self, controller):
        counter: list[int] = []
        controller.start_loop(
            StorefrontBackgroundTask(name="alpha", task_factory=_counting_loop(controller, counter))
        )

        await _let_loops_run()

        assert counter, "the loop should be doing work before anything pauses it"

    async def test_a_paused_loop_does_no_work_at_all(self, controller):
        counter: list[int] = []
        controller.start_loop(
            StorefrontBackgroundTask(name="alpha", task_factory=_counting_loop(controller, counter))
        )
        await _let_loops_run()

        await controller.pause()
        counter.clear()
        await _let_loops_run(cycles=10)

        assert counter == [], (
            "a paused loop performed work — the whole contract is that a paused "
            "storefront changes no state on its own"
        )

    async def test_pausing_does_not_stop_the_task(self, controller):
        """Idle, not torn down.

        The task staying alive is what preserves loop-local state across a pause
        — the capacity poller's feed position above all — and what removes any
        possibility of a half-finished cycle.
        """
        controller.start_loop(
            StorefrontBackgroundTask(name="alpha", task_factory=_counting_loop(controller, []))
        )
        await _let_loops_run()

        await controller.pause()

        assert not controller._handles["alpha"].done()
        assert controller.states() == {"alpha": "paused"}

    async def test_resuming_returns_the_same_loop_to_work(self, controller):
        counter: list[int] = []
        controller.start_loop(
            StorefrontBackgroundTask(name="alpha", task_factory=_counting_loop(controller, counter))
        )
        before = controller._handles["alpha"]
        await controller.pause()
        await _let_loops_run()

        await controller.resume()
        counter.clear()
        await _let_loops_run()

        assert counter, "resuming did not return the loop to work"
        assert controller._handles["alpha"] is before, (
            "resume replaced the task — a restart would lose loop-local position "
            "and could overlap a predecessor"
        )


class TestIdempotence:
    async def test_pausing_twice_is_harmless(self, controller):
        controller.start_loop(
            StorefrontBackgroundTask(name="alpha", task_factory=_counting_loop(controller, []))
        )

        await controller.pause()
        states = await controller.pause()

        assert states == {"alpha": "paused"}

    async def test_resuming_a_never_paused_storefront_changes_nothing(self, controller):
        counter: list[int] = []
        controller.start_loop(
            StorefrontBackgroundTask(name="alpha", task_factory=_counting_loop(controller, counter))
        )
        before = controller._handles["alpha"]
        await _let_loops_run()

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
        controller.start_loop(
            StorefrontBackgroundTask(name="alpha", task_factory=_counting_loop(controller, []))
        )

        assert controller.states() == {"alpha": "starting"}
        assert controller.starting_loop_names() == ["alpha"]

    async def test_it_reports_running_once_it_has_gated(self, controller):
        controller.start_loop(
            StorefrontBackgroundTask(name="alpha", task_factory=_counting_loop(controller, []))
        )

        await _let_loops_run()

        assert controller.states() == {"alpha": "running"}
        assert controller.starting_loop_names() == []

    async def test_a_loop_that_never_gates_is_not_reported_as_pausing(self, controller):
        """The two are told apart by whether a cycle is in flight.

        `pausing` promises a cycle that will finish and then stop; a loop that has
        never gated promises nothing. Reporting the second as the first is the
        defect this state was added for: four production loops read the pause
        without acknowledging, and every pause reported them as `pausing`
        indefinitely, indistinguishable from four long reconciles.

        Requests the pause without waiting rather than through `pause`,
        which would spend the whole quiescence window waiting for an
        acknowledgement that never comes.
        """
        async def _never_gates() -> None:
            while True:
                await asyncio.sleep(0.001)

        controller.start_loop(
            StorefrontBackgroundTask(name="alpha", task_factory=_never_gates)
        )
        await _let_loops_run()

        controller.request_pause(True)

        assert controller.states() == {"alpha": "starting"}

    async def test_loops_check_separates_starting_from_ended(self, controller):
        controller.start_loop(
            StorefrontBackgroundTask(name="alpha", task_factory=_counting_loop(controller, []))
        )
        assert controller.loops_check().startswith("starting:")

        await _let_loops_run()
        assert controller.loops_check() == "ok"

    async def test_loops_check_reports_no_registered_loops(self, controller):
        """Distinct from healthy. A storefront with no timer loops registered has
        not finished starting, and an empty registry must not read as ok."""
        assert controller.loops_check() != "ok"


class TestALoopThatEnds:
    async def test_an_ended_loop_is_named_as_failed(self, controller):
        async def _exits() -> None:
            return None

        controller.start_loop(
            StorefrontBackgroundTask(name="alpha", task_factory=_exits)
        )
        await asyncio.sleep(0)
        await asyncio.sleep(0)

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

        controller.start_loop(
            StorefrontBackgroundTask(name="alpha", task_factory=_raises)
        )
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        assert controller.states() == {"alpha": "exited"}
        assert controller.failed_loop_names() == ["alpha"]


class TestGateNameDiscipline:
    async def test_gating_under_an_unregistered_name_is_reported(self, controller, caplog):
        """A misspelled name acknowledges something nobody waits on.

        The registered loop then stays unacknowledged forever, which presents
        exactly as a loop that never gates. The warning is the only thing that
        tells the two apart from outside the process.
        """
        controller.start_loop(
            StorefrontBackgroundTask(name="alpha", task_factory=_counting_loop(controller, []))
        )

        with caplog.at_level("WARNING"):
            controller.gate("alpah")

        assert any("not registered" in r.getMessage() for r in caplog.records)


class TestLoopStateReporting:
    async def test_every_registered_loop_is_reported(self, controller):
        for name in ("alpha", "beta"):
            controller.start_loop(
                StorefrontBackgroundTask(name=name, task_factory=_counting_loop(controller, []))
            )
        await asyncio.sleep(0)

        assert sorted(controller.states()) == ["alpha", "beta"]
        assert controller.registered_loop_names() == ["alpha", "beta"]

    async def test_a_loop_that_exits_on_its_own_is_not_reported_as_paused(self, controller):
        """A crashed loop is neither working nor deliberately idle.

        Reporting it as either would hide the crash behind an operator control's
        vocabulary, which is what the status surface exists to prevent.
        """
        async def _exits() -> None:
            return None

        controller.start_loop(
            StorefrontBackgroundTask(name="alpha", task_factory=_exits)
        )
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        await controller.pause()

        assert controller.states()["alpha"] == "exited"


class TestPauseDoesNotClaimQuiescenceItCannotSee:
    """`paused` must mean the loop reached its gate, not that a flag was set.

    This is the guarantee the whole control exists to provide: a caller that reads
    `paused` uses it to decide nothing is still writing. A status derived from the
    flag alone reports `paused` for a loop halfway through a reconcile, and no
    assertion built on it can fail — which is worse than no assertion, because it
    looks like proof.

    Coordinated with events rather than sleeps, so the interleaving is exact.
    """

    async def test_a_loop_mid_cycle_is_reported_pausing_not_paused(self, controller):
        entered = asyncio.Event()
        release = asyncio.Event()

        async def _slow_loop() -> None:
            while True:
                if controller.gate("alpha"):
                    await asyncio.sleep(0.001)
                    continue
                entered.set()
                await release.wait()

        controller.start_loop(
            StorefrontBackgroundTask(name="alpha", task_factory=_slow_loop)
        )
        await asyncio.wait_for(entered.wait(), timeout=1)

        # The cycle is in flight and cannot come back until released, so the
        # bounded wait expires and the report must say so rather than claiming a
        # stop it cannot see. A short timeout keeps the test quick; the property
        # is the reported state, not the duration.
        controller.request_pause(True)
        await controller.await_quiescence(timeout=0.05)

        assert controller.states() == {"alpha": "pausing"}, (
            "a loop still inside a cycle was reported as paused; a caller would "
            "read that as 'nothing is in flight' on evidence that cannot show it"
        )

        # Let the cycle finish. The loop returns to its gate, finds the pause, and
        # acknowledges — only now is `paused` true.
        release.set()
        await asyncio.wait_for(
            _until(lambda: controller.states() == {"alpha": "paused"}), timeout=1,
        )

    async def test_quiescence_returns_once_every_loop_reaches_its_gate(self, controller):
        at_gate = asyncio.Event()

        async def _quick_loop() -> None:
            while True:
                if controller.gate("alpha"):
                    at_gate.set()
                    await asyncio.sleep(0.001)
                    continue
                await asyncio.sleep(0.001)

        controller.start_loop(
            StorefrontBackgroundTask(name="alpha", task_factory=_quick_loop)
        )

        states = await controller.pause()

        assert at_gate.is_set()
        assert states == {"alpha": "paused"}, (
            "a loop sitting at its gate should be reported paused without the "
            f"bounded wait having to expire: {states}"
        )


class TestDeclaredGatesWithoutAHandle:
    """Gated names whose tasks are created elsewhere still hold a pause.

    Capacity polling fans out one poller per site inside
    `kit/capacity-publication`, which owns the gather, so the storefront never
    holds a task per site. Quiescence waits on handles, so without
    declaring those names a site poller could still be mid-cycle while the
    pause reported every loop idle -- optimistic in the one direction a pause
    exists to prevent.
    """

    async def test_a_declared_gate_is_waited_on_and_reports_paused(self, controller):
        name = "capacity_events_poller:default"
        site_gate = controller.declare(name)
        at_gate = asyncio.Event()
        stop = asyncio.Event()

        async def _site_poller():
            while not stop.is_set():
                if site_gate():
                    at_gate.set()
                    await asyncio.sleep(0.001)
                    continue
                await asyncio.sleep(0.001)

        task = asyncio.create_task(_site_poller())
        try:
            await asyncio.wait_for(_until(lambda: name in controller.states()), 1.0)
            states = await controller.pause()
            assert states.get(name) == "paused", (
                "a declared per-site gate was not waited on; the pause reported "
                f"{states}, which would let a site still writing look idle"
            )
            assert at_gate.is_set()
        finally:
            stop.set()
            await controller.resume()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

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

async def _until(predicate, interval: float = 0.001) -> None:
    """Yield until a predicate holds. Bounded by the caller's `wait_for`."""
    while not predicate():
        await asyncio.sleep(interval)


class TestIdleWakesOnPause:
    async def test_idle_returns_when_a_pause_is_requested(self, controller):
        waiting = asyncio.create_task(controller.idle(60))
        await asyncio.sleep(0)
        controller.request_pause(True)
        await asyncio.wait_for(waiting, timeout=1)

    async def test_idle_returns_on_its_wake_event(self, controller):
        wake = asyncio.Event()
        waiting = asyncio.create_task(controller.idle(60, wake=wake))
        await asyncio.sleep(0)
        wake.set()
        await asyncio.wait_for(waiting, timeout=1)


class TestSteps:
    async def test_a_held_loop_is_stepped_through_its_registered_operation(self, controller):
        calls: list[str] = []

        async def _step():
            calls.append("step")
            return {"loop": "alpha", "processed": 1}

        controller.start_loop(
            StorefrontBackgroundTask(name="alpha", task_factory=_counting_loop(controller, [])),
            route="alpha-route",
            step=_step,
        )
        await controller.pause()

        result = await controller.run_cycle("alpha-route")

        assert result == {"loop": "alpha", "processed": 1}
        assert calls == ["step"]
        assert controller.states() == {"alpha": "paused"}, "a step must not resume the loops"

    async def test_an_unknown_route_is_not_found(self, controller):
        from market_storefront_kit import LoopNotFound

        with pytest.raises(LoopNotFound):
            await controller.run_cycle("missing")

    async def test_a_loop_without_a_preview_offers_none(self, controller):
        from market_storefront_kit import PreviewNotOffered

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

        controller.start_loop(
            StorefrontBackgroundTask(name="alpha", task_factory=_counting_loop(controller, [])),
            step=_step,
        )
        controller.clear_loops()

        assert controller.states() == {}
        assert await controller.run_cycle("alpha") == {"ok": True}

