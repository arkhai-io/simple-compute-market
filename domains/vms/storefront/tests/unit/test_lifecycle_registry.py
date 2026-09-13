"""A paused storefront's loops run no cycle, and nothing is torn down to achieve it.

These are the properties an end-to-end scenario relies on when it pauses once and
advances deliberately: while paused, no loop does work; the loops are still alive,
so nothing was interrupted part-way and no loop-local position was lost; and
resuming needs no restart, so there is no window where two copies of a loop
overlap.

The pause gate is checked at the top of a cycle rather than delivered as a
cancellation, which is what makes "every cycle either ran completely or never
began" true rather than "some cycle was stopped at whatever await it happened to
be sitting on". The tests below pin that, and that a paused loop stays alive so
its loop-local position survives.

These tests drive a synthetic loop, so they prove the *mechanism* and say nothing
about which production loops use it. That distinction is not academic: four of
the five production loops once read the pause without acknowledging, and every
test in this file passed throughout. `test_loop_gate_wiring.py` is the file that
covers the wiring, and the two are only meaningful together.
"""

from __future__ import annotations

import asyncio

import pytest

from core_storefront.app_startup import StorefrontBackgroundTask
from market_storefront import lifecycle, server


@pytest.fixture(autouse=True)
async def _clean_registry():
    """Async so teardown runs inside the test's event loop.

    A sync fixture tears down after the loop has closed, and cancelling a task
    then raises `Event loop is closed` — reported against the registry rather
    than the fixture.
    """
    server._LOOPS_PAUSED = False
    lifecycle.reset_for_tests()
    yield
    lifecycle.reset_for_tests()
    server._LOOPS_PAUSED = False
    await asyncio.sleep(0)


def _counting_loop(counter: list[int], *, interval: float = 0.001):
    """A loop shaped like the real ones: gate first, then work.

    Gating through `lifecycle.gate` is what the production loops are required to
    do, not an observation that they do — see this module's docstring.
    """

    async def _loop() -> None:
        while True:
            await asyncio.sleep(interval)
            if lifecycle.gate("alpha"):
                continue
            counter.append(1)

    return _loop


async def _let_loops_run(cycles: int = 5, interval: float = 0.001) -> None:
    await asyncio.sleep(interval * cycles * 3)


class TestPauseHoldsEveryLoopIdle:
    async def test_a_running_loop_does_work(self):
        counter: list[int] = []
        lifecycle.start_registered_loop(
            StorefrontBackgroundTask(name="alpha", task_factory=_counting_loop(counter))
        )

        await _let_loops_run()

        assert counter, "the loop should be doing work before anything pauses it"

    async def test_a_paused_loop_does_no_work_at_all(self):
        counter: list[int] = []
        lifecycle.start_registered_loop(
            StorefrontBackgroundTask(name="alpha", task_factory=_counting_loop(counter))
        )
        await _let_loops_run()

        await server._set_loops_paused(True)
        counter.clear()
        await _let_loops_run(cycles=10)

        assert counter == [], (
            "a paused loop performed work — the whole contract is that a paused "
            "storefront changes no state on its own"
        )

    async def test_pausing_does_not_stop_the_task(self):
        """Idle, not torn down.

        The task staying alive is what preserves loop-local state across a pause
        — the capacity poller's feed position above all — and what removes any
        possibility of a half-finished cycle.
        """
        lifecycle.start_registered_loop(
            StorefrontBackgroundTask(name="alpha", task_factory=_counting_loop([]))
        )
        await _let_loops_run()

        await server._set_loops_paused(True)

        assert not lifecycle._HANDLES["alpha"].done()
        assert lifecycle.loop_states() == {"alpha": "paused"}

    async def test_resuming_returns_the_same_loop_to_work(self):
        counter: list[int] = []
        lifecycle.start_registered_loop(
            StorefrontBackgroundTask(name="alpha", task_factory=_counting_loop(counter))
        )
        before = lifecycle._HANDLES["alpha"]
        await server._set_loops_paused(True)
        await _let_loops_run()

        await server._set_loops_paused(False)
        counter.clear()
        await _let_loops_run()

        assert counter, "resuming did not return the loop to work"
        assert lifecycle._HANDLES["alpha"] is before, (
            "resume replaced the task — a restart would lose loop-local position "
            "and could overlap a predecessor"
        )


class TestIdempotence:
    async def test_pausing_twice_is_harmless(self):
        lifecycle.start_registered_loop(
            StorefrontBackgroundTask(name="alpha", task_factory=_counting_loop([]))
        )

        await server._set_loops_paused(True)
        states = await server._set_loops_paused(True)

        assert states == {"alpha": "paused"}

    async def test_resuming_a_never_paused_storefront_changes_nothing(self):
        counter: list[int] = []
        lifecycle.start_registered_loop(
            StorefrontBackgroundTask(name="alpha", task_factory=_counting_loop(counter))
        )
        before = lifecycle._HANDLES["alpha"]
        await _let_loops_run()

        states = await server._set_loops_paused(False)

        assert states == {"alpha": "running"}
        assert lifecycle._HANDLES["alpha"] is before


class TestAScheduledLoopIsNotYetRunning:
    """`running` is earned by reaching a gate, not by having a task object.

    Registration is `create_task`, which schedules a coroutine without executing
    a step of it. A loop reported `running` at that moment cannot observe a
    pause, so a caller that pauses on the strength of it is told the loop stopped
    when it had not started.
    """

    async def test_a_registered_loop_reports_starting_before_its_first_gate(self):
        lifecycle.start_registered_loop(
            StorefrontBackgroundTask(name="alpha", task_factory=_counting_loop([]))
        )

        assert lifecycle.loop_states() == {"alpha": "starting"}
        assert lifecycle.starting_loop_names() == ["alpha"]

    async def test_it_reports_running_once_it_has_gated(self):
        lifecycle.start_registered_loop(
            StorefrontBackgroundTask(name="alpha", task_factory=_counting_loop([]))
        )

        await _let_loops_run()

        assert lifecycle.loop_states() == {"alpha": "running"}
        assert lifecycle.starting_loop_names() == []

    async def test_a_loop_that_never_gates_is_not_reported_as_pausing(self):
        """The two are told apart by whether a cycle is in flight.

        `pausing` promises a cycle that will finish and then stop; a loop that has
        never gated promises nothing. Reporting the second as the first is the
        defect this state was added for: four production loops read the pause
        without acknowledging, and every pause reported them as `pausing`
        indefinitely, indistinguishable from four long reconciles.

        Sets the flag directly rather than going through `_set_loops_paused`,
        which would spend the whole quiescence window waiting for an
        acknowledgement that never comes.
        """
        async def _never_gates() -> None:
            while True:
                await asyncio.sleep(0.001)

        lifecycle.start_registered_loop(
            StorefrontBackgroundTask(name="alpha", task_factory=_never_gates)
        )
        await _let_loops_run()

        server._LOOPS_PAUSED = True

        assert lifecycle.loop_states() == {"alpha": "starting"}

    async def test_loops_check_separates_starting_from_ended(self):
        lifecycle.start_registered_loop(
            StorefrontBackgroundTask(name="alpha", task_factory=_counting_loop([]))
        )
        assert lifecycle.loops_check().startswith("starting:")

        await _let_loops_run()
        assert lifecycle.loops_check() == "ok"

    async def test_loops_check_reports_no_registered_loops(self):
        """Distinct from healthy. A storefront with no timer loops registered has
        not finished starting, and an empty registry must not read as ok."""
        assert lifecycle.loops_check() != "ok"


class TestALoopThatEnds:
    async def test_an_ended_loop_is_named_for_liveness(self):
        async def _exits() -> None:
            return None

        lifecycle.start_registered_loop(
            StorefrontBackgroundTask(name="alpha", task_factory=_exits)
        )
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        assert lifecycle.failed_loop_names() == ["alpha"]
        assert lifecycle.loops_check().startswith("error:")

    async def test_a_loop_that_raises_is_reported_as_ended(self):
        """Not as cancelled, and not as merely absent.

        Nothing restarts a loop, so a loop that raised is stopped for the life of
        the process — which is why liveness keys off this and readiness alone
        would leave a storefront serving with its background work dead.
        """
        async def _raises() -> None:
            raise RuntimeError("loop failed")

        lifecycle.start_registered_loop(
            StorefrontBackgroundTask(name="alpha", task_factory=_raises)
        )
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        assert lifecycle.loop_states() == {"alpha": "exited"}
        assert lifecycle.failed_loop_names() == ["alpha"]


class TestGateNameDiscipline:
    async def test_gating_under_an_unregistered_name_is_reported(self, caplog):
        """A misspelled name acknowledges something nobody waits on.

        The registered loop then stays unacknowledged forever, which presents
        exactly as a loop that never gates. The warning is the only thing that
        tells the two apart from outside the process.
        """
        lifecycle.start_registered_loop(
            StorefrontBackgroundTask(name="alpha", task_factory=_counting_loop([]))
        )

        with caplog.at_level("WARNING"):
            lifecycle.gate("alpah")

        assert any("not registered" in r.getMessage() for r in caplog.records)


class TestLoopStateReporting:
    async def test_every_registered_loop_is_reported(self):
        for name in ("alpha", "beta"):
            lifecycle.start_registered_loop(
                StorefrontBackgroundTask(name=name, task_factory=_counting_loop([]))
            )
        await asyncio.sleep(0)

        assert sorted(lifecycle.loop_states()) == ["alpha", "beta"]
        assert lifecycle.registered_loop_names() == ["alpha", "beta"]

    async def test_a_loop_that_exits_on_its_own_is_not_reported_as_paused(self):
        """A crashed loop is neither working nor deliberately idle.

        Reporting it as either would hide the crash behind an operator control's
        vocabulary, which is what the status surface exists to prevent.
        """
        async def _exits() -> None:
            return None

        lifecycle.start_registered_loop(
            StorefrontBackgroundTask(name="alpha", task_factory=_exits)
        )
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        await server._set_loops_paused(True)

        assert lifecycle.loop_states()["alpha"] == "exited"


class TestPauseDoesNotClaimQuiescenceItCannotSee:
    """`paused` must mean the loop reached its gate, not that a flag was set.

    This is the guarantee the whole control exists to provide: a caller that reads
    `paused` uses it to decide nothing is still writing. A status derived from the
    flag alone reports `paused` for a loop halfway through a reconcile, and no
    assertion built on it can fail — which is worse than no assertion, because it
    looks like proof.

    Coordinated with events rather than sleeps, so the interleaving is exact.
    """

    async def test_a_loop_mid_cycle_is_reported_pausing_not_paused(self):
        entered = asyncio.Event()
        release = asyncio.Event()

        async def _slow_loop() -> None:
            while True:
                if lifecycle.gate("alpha"):
                    await asyncio.sleep(0.001)
                    continue
                entered.set()
                await release.wait()

        lifecycle.start_registered_loop(
            StorefrontBackgroundTask(name="alpha", task_factory=_slow_loop)
        )
        await asyncio.wait_for(entered.wait(), timeout=1)

        # The cycle is in flight and cannot come back until released, so the
        # bounded wait expires and the report must say so rather than claiming a
        # stop it cannot see. A short timeout keeps the test quick; the property
        # is the reported state, not the duration.
        server._LOOPS_PAUSED = True
        await lifecycle.await_quiescence(timeout=0.05)

        assert lifecycle.loop_states() == {"alpha": "pausing"}, (
            "a loop still inside a cycle was reported as paused; a caller would "
            "read that as 'nothing is in flight' on evidence that cannot show it"
        )

        # Let the cycle finish. The loop returns to its gate, finds the pause, and
        # acknowledges — only now is `paused` true.
        release.set()
        await asyncio.wait_for(
            _until(lambda: lifecycle.loop_states() == {"alpha": "paused"}), timeout=1,
        )

    async def test_quiescence_returns_once_every_loop_reaches_its_gate(self):
        at_gate = asyncio.Event()

        async def _quick_loop() -> None:
            while True:
                if lifecycle.gate("alpha"):
                    at_gate.set()
                    await asyncio.sleep(0.001)
                    continue
                await asyncio.sleep(0.001)

        lifecycle.start_registered_loop(
            StorefrontBackgroundTask(name="alpha", task_factory=_quick_loop)
        )

        states = await server._set_loops_paused(True)

        assert at_gate.is_set()
        assert states == {"alpha": "paused"}, (
            "a loop sitting at its gate should be reported paused without the "
            f"bounded wait having to expire: {states}"
        )


async def _until(predicate, interval: float = 0.001) -> None:
    """Yield until a predicate holds. Bounded by the caller's `wait_for`."""
    while not predicate():
        await asyncio.sleep(interval)
