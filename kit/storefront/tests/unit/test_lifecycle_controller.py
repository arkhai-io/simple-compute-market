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
