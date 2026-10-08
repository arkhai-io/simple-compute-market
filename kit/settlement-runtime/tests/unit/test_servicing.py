"""The servicing loop's cycle ordering, against a worker that sweeps nothing.

Durable servicing against a real database is in
``tests/integration/test_servicing.py``.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from market_settlement_runtime import SettlementServicingWorker


class _CountingWorker(SettlementServicingWorker):
    """Counts sweeps; the loop's ordering is what these tests examine."""

    def __init__(self, *, interval_seconds: float) -> None:
        super().__init__(
            MagicMock(), MagicMock(), worker_id="counting", interval_seconds=interval_seconds
        )
        self.sweeps = 0

    async def run_once(self, limit: int = 50) -> int:
        self.sweeps += 1
        return 0


class _Control:
    """A gate and an interruptible wait, driven by the test.

    The wait returns only when the test ticks it or a pause is requested, so each
    tick lets the loop through one more cycle and nothing here waits on time.
    """

    def __init__(self) -> None:
        self.paused = False
        self.signal = asyncio.Event()
        self.tick = asyncio.Event()
        self.waiting = asyncio.Event()
        self.held_reads = 0
        self._held_read = asyncio.Event()

    def gate(self) -> bool:
        if self.paused:
            self.held_reads += 1
            self._held_read.set()
        return self.paused

    async def wait(self, seconds: float) -> None:
        self.waiting.set()
        tick = asyncio.ensure_future(self.tick.wait())
        pause = asyncio.ensure_future(self.signal.wait())
        try:
            await asyncio.wait({tick, pause}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            tick.cancel()
            pause.cancel()
        self.tick.clear()

    async def next_wait(self) -> None:
        self.waiting.clear()
        self.tick.set()
        await asyncio.wait_for(self.waiting.wait(), timeout=1)

    async def held_reads_reach(self, count: int) -> None:
        while self.held_reads < count:
            self._held_read.clear()
            await asyncio.wait_for(self._held_read.wait(), timeout=1)

    def pause(self) -> None:
        self.paused = True
        self.signal.set()

    def resume(self) -> None:
        self.paused = False
        self.signal.clear()


async def _stop(task: asyncio.Task) -> None:
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def test_the_first_sweep_waits_one_interval():
    worker = _CountingWorker(interval_seconds=3600)
    control = _Control()
    task = asyncio.create_task(worker.run(paused=control.gate, wait=control.wait))
    try:
        await asyncio.wait_for(control.waiting.wait(), timeout=1)
        assert worker.sweeps == 0
    finally:
        await _stop(task)


async def test_a_pause_requested_during_the_wait_holds_the_next_sweep():
    # Due by the next cycle; the test, not the clock, decides when that is.
    worker = _CountingWorker(interval_seconds=1e-6)
    control = _Control()
    task = asyncio.create_task(worker.run(paused=control.gate, wait=control.wait))
    try:
        await asyncio.wait_for(control.waiting.wait(), timeout=1)
        await control.next_wait()
        swept = worker.sweeps
        assert swept >= 1

        control.pause()
        await control.held_reads_reach(3)
        assert worker.sweeps == swept, "a held servicing loop swept"

        control.resume()
        await control.next_wait()
        assert worker.sweeps > swept
    finally:
        await _stop(task)


async def test_a_gated_loop_without_an_interruptible_wait_is_refused():
    worker = _CountingWorker(interval_seconds=3600)
    with pytest.raises(TypeError):
        await worker.run(paused=lambda: False)
