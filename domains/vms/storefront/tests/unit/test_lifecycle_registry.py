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
    """A loop shaped like the real ones: gate first, then work."""

    async def _loop() -> None:
        while True:
            await asyncio.sleep(interval)
            # Through `gate`, as every production loop does: reading the flag and
            # acknowledging must not be separately forgettable.
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

        states = await server._set_loops_paused(False)

        assert states == {"alpha": "running"}
        assert lifecycle._HANDLES["alpha"] is before


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
