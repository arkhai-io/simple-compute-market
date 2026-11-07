"""Fulfillment convergence's gate state: held only once no timer cycle runs.

The watchdog's timer loop runs with its production cycle replaced by one held
on an event, so the test decides when a cycle is in flight; nothing else of the
cycle is reached, so its collaborators are absent.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from compute_provisioning_service.services.fulfillment_convergence import (
    FulfillmentConvergenceWatchdog,
)

#: Far longer than any test waits, so the loop sleeps after its one cycle.
_LONG_INTERVAL = 3600


class _HeldCycles:
    """A convergence cycle that waits on ``release``; ``started`` is set as each
    begins and ``finished`` as it returns, in the same step as the loop's own
    bookkeeping after it."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.finished = asyncio.Event()
        self.runs = 0

    async def __call__(self) -> dict[str, object]:
        self.runs += 1
        self.started.set()
        await self.release.wait()
        self.finished.set()
        return {}


def _watchdog(cycles: _HeldCycles) -> FulfillmentConvergenceWatchdog:
    watchdog = FulfillmentConvergenceWatchdog(
        session_factory=None,
        repository=None,
        provider_registry=None,
        settings=SimpleNamespace(
            fulfillment_convergence_watchdog_poll_interval_seconds=_LONG_INTERVAL
        ),
    )
    watchdog.run_cycle = cycles
    return watchdog


@pytest.mark.asyncio
async def test_an_idle_watchdog_is_at_its_gate_once_paused():
    watchdog = _watchdog(_HeldCycles())

    assert (watchdog.is_paused, watchdog.is_at_gate) == (False, False)
    watchdog.pause()
    assert (watchdog.is_paused, watchdog.is_at_gate) == (True, True)
    watchdog.resume()
    assert (watchdog.is_paused, watchdog.is_at_gate) == (False, False)


@pytest.mark.asyncio
async def test_a_timer_cycle_in_flight_keeps_a_paused_watchdog_off_its_gate():
    """A pause stops the next timer cycle, not one already running; once that
    one ends the loop waits out its interval and can start no other while
    paused, so it is held. An explicit cycle is the caller's own and never
    counts."""
    cycles = _HeldCycles()
    watchdog = _watchdog(cycles)
    loop = asyncio.create_task(watchdog.run())
    try:
        await asyncio.wait_for(cycles.started.wait(), timeout=1)
        watchdog.pause()
        assert (watchdog.is_paused, watchdog.is_at_gate) == (True, False)
        cycles.release.set()
        await asyncio.wait_for(cycles.finished.wait(), timeout=1)
        assert watchdog.is_at_gate is True

        cycles.started.clear()
        cycles.release.clear()
        explicit = asyncio.create_task(watchdog.run_cycle())
        await asyncio.wait_for(cycles.started.wait(), timeout=1)
        assert watchdog.is_at_gate is True
        cycles.release.set()
        await asyncio.wait_for(explicit, timeout=1)
        assert cycles.runs == 2
    finally:
        loop.cancel()
        await asyncio.gather(loop, return_exceptions=True)


@pytest.mark.asyncio
async def test_a_pause_straight_after_a_resume_holds_the_cycle_the_resume_woke():
    """A resume wakes the timer loop waiting at the gate; a pause before that
    loop runs answers "at the gate", so the woken loop must wait again rather
    than run a cycle inside the hold."""
    cycles = _HeldCycles()
    watchdog = _watchdog(cycles)
    watchdog.pause()
    loop = asyncio.create_task(watchdog.run())
    try:
        await asyncio.sleep(0)
        watchdog.resume()
        watchdog.pause()
        assert watchdog.is_at_gate is True
        for _ in range(5):
            await asyncio.sleep(0)

        assert cycles.runs == 0
        assert watchdog.is_at_gate is True
        watchdog.resume()
        await asyncio.wait_for(cycles.started.wait(), timeout=1)
        cycles.release.set()
        await asyncio.wait_for(cycles.finished.wait(), timeout=1)
        assert cycles.runs == 1
    finally:
        loop.cancel()
        await asyncio.gather(loop, return_exceptions=True)
