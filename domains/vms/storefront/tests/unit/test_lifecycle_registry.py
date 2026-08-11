"""Pause halts every registered timer loop; resume restarts exactly what stopped.

These are the properties an end-to-end scenario relies on when it pauses once at
setup and advances deliberately: nothing runs on its own while paused, and
resuming does not leave two copies of a loop racing each other.
"""

from __future__ import annotations

import asyncio

import pytest

from core_storefront.app_startup import StorefrontBackgroundTask
from market_storefront import lifecycle


@pytest.fixture(autouse=True)
async def _clean_registry():
    """Async so teardown runs inside the test's event loop.

    A sync fixture tears down after the loop has closed, and cancelling a task
    then raises `Event loop is closed` — which would report as an error in the
    registry rather than in the fixture.
    """
    lifecycle.reset_for_tests()
    yield
    lifecycle.reset_for_tests()
    # Let the cancellations the reset requested actually be delivered, so a
    # pending task does not outlive the loop and print a destroyed-task warning.
    await asyncio.sleep(0)


def _forever(started: asyncio.Event | None = None):
    async def _loop() -> None:
        if started is not None:
            started.set()
        while True:
            await asyncio.sleep(3600)

    return _loop


class TestPauseHaltsEveryLoop:
    async def test_registered_loops_report_running_before_a_pause(self):
        lifecycle.start_registered_loop(
            StorefrontBackgroundTask(name="alpha", task_factory=_forever())
        )
        lifecycle.start_registered_loop(
            StorefrontBackgroundTask(name="beta", task_factory=_forever())
        )
        await asyncio.sleep(0)

        assert lifecycle.loop_states() == {"alpha": "running", "beta": "running"}

    async def test_pause_stops_all_of_them(self):
        started = asyncio.Event()
        lifecycle.start_registered_loop(
            StorefrontBackgroundTask(name="alpha", task_factory=_forever(started))
        )
        lifecycle.start_registered_loop(
            StorefrontBackgroundTask(name="beta", task_factory=_forever())
        )
        await asyncio.wait_for(started.wait(), timeout=1)

        states = lifecycle.pause_loops()

        assert states == {"alpha": "stopped", "beta": "stopped"}
        assert lifecycle.registered_loop_names() == ["alpha", "beta"], (
            "a paused loop keeps its registration — resume restarts it from the "
            "same factory it was started from"
        )

    async def test_resume_restarts_everything_pause_stopped(self):
        lifecycle.start_registered_loop(
            StorefrontBackgroundTask(name="alpha", task_factory=_forever())
        )
        lifecycle.pause_loops()

        states = lifecycle.resume_loops()
        await asyncio.sleep(0)

        assert states["alpha"] == "running"


class TestIdempotence:
    """Pause and resume are operator controls; a second call must not fail or
    duplicate. A duplicated poller would be invisible until two reconciliations
    raced, which is the defect class this control exists to make observable."""

    async def test_pausing_twice_is_harmless(self):
        lifecycle.start_registered_loop(
            StorefrontBackgroundTask(name="alpha", task_factory=_forever())
        )
        lifecycle.pause_loops()

        assert lifecycle.pause_loops() == {"alpha": "stopped"}

    async def test_resuming_twice_starts_one_loop_not_two(self):
        lifecycle.start_registered_loop(
            StorefrontBackgroundTask(name="alpha", task_factory=_forever())
        )
        lifecycle.pause_loops()

        lifecycle.resume_loops()
        await asyncio.sleep(0)
        first = lifecycle._HANDLES["alpha"]
        lifecycle.resume_loops()
        await asyncio.sleep(0)

        assert lifecycle._HANDLES["alpha"] is first, (
            "resume must not replace a running loop — the old task would keep "
            "running unreferenced alongside the new one"
        )

    async def test_resuming_a_never_paused_storefront_changes_nothing(self):
        lifecycle.start_registered_loop(
            StorefrontBackgroundTask(name="alpha", task_factory=_forever())
        )
        await asyncio.sleep(0)
        before = lifecycle._HANDLES["alpha"]

        lifecycle.resume_loops()

        assert lifecycle._HANDLES["alpha"] is before


class TestLoopStateReporting:
    async def test_a_loop_that_exits_on_its_own_is_not_reported_as_stopped(self):
        """A crashed loop is neither running nor deliberately halted.

        Reporting it as either would hide the crash behind an operator control's
        vocabulary, which is exactly the kind of quiet failure the status
        surface exists to prevent.
        """
        async def _exits() -> None:
            return None

        lifecycle.start_registered_loop(
            StorefrontBackgroundTask(name="alpha", task_factory=_exits)
        )
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        assert lifecycle.loop_states()["alpha"] == "exited"
