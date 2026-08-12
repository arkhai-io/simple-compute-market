"""A paused storefront's loops run no cycle, and nothing is torn down to achieve it.

These are the properties an end-to-end scenario relies on when it pauses once and
advances deliberately: while paused, no loop does work; the loops are still alive,
so nothing was interrupted part-way and no loop-local position was lost; and
resuming needs no restart, so there is no window where two copies of a loop
overlap.

The pause gate is checked at the top of a cycle rather than delivered as a
cancellation. That is the difference between "every cycle either ran completely
or never began" and "some cycle was stopped at whatever await it happened to be
sitting on", and the tests below pin the first.
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
    server._set_loops_paused(False)
    lifecycle.reset_for_tests()
    yield
    lifecycle.reset_for_tests()
    server._set_loops_paused(False)
    await asyncio.sleep(0)


def _counting_loop(counter: list[int], *, interval: float = 0.001):
    """A loop shaped like the real ones: gate first, then work."""

    async def _loop() -> None:
        while True:
            await asyncio.sleep(interval)
            if lifecycle.is_paused():
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

        server._set_loops_paused(True)
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

        server._set_loops_paused(True)

        assert not lifecycle._HANDLES["alpha"].done()
        assert lifecycle.loop_states() == {"alpha": "paused"}

    async def test_resuming_returns_the_same_loop_to_work(self):
        counter: list[int] = []
        lifecycle.start_registered_loop(
            StorefrontBackgroundTask(name="alpha", task_factory=_counting_loop(counter))
        )
        before = lifecycle._HANDLES["alpha"]
        server._set_loops_paused(True)
        await _let_loops_run()

        server._set_loops_paused(False)
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

        server._set_loops_paused(True)
        states = server._set_loops_paused(True)

        assert states == {"alpha": "paused"}

    async def test_resuming_a_never_paused_storefront_changes_nothing(self):
        counter: list[int] = []
        lifecycle.start_registered_loop(
            StorefrontBackgroundTask(name="alpha", task_factory=_counting_loop(counter))
        )
        before = lifecycle._HANDLES["alpha"]

        states = server._set_loops_paused(False)

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
        server._set_loops_paused(True)

        assert lifecycle.loop_states()["alpha"] == "exited"
