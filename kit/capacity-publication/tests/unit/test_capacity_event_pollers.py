"""The aggregate capacity-event loop holds while gated and surfaces a failed fan-out.

The aggregate's cadence is the injected wait, which the test drives: each wait
parks until the test ticks it or a pause is requested. Nothing here waits on time.
"""

from __future__ import annotations

import asyncio

import pytest

from market_capacity_publication import run_capacity_event_pollers


class _Control:
    """A gate and an interruptible wait standing in for a loop controller."""

    def __init__(self) -> None:
        self.paused = False
        self.signal = asyncio.Event()
        self.tick = asyncio.Event()
        self.waiting = asyncio.Event()
        self.acknowledged = asyncio.Event()
        self.waits = 0

    def gate(self) -> bool:
        if self.paused:
            self.acknowledged.set()
        return self.paused

    async def wait(self, seconds: float) -> None:
        self.waits += 1
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
        """Release the aggregate from its wait and let it return to the next one."""
        self.waiting.clear()
        self.tick.set()
        await asyncio.wait_for(self.waiting.wait(), timeout=1)

    def pause(self) -> None:
        self.paused = True
        self.signal.set()


def _site_gate(site_id):
    return lambda: False


async def _stop(task: asyncio.Task) -> None:
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def test_the_fan_out_receives_the_site_gates_and_wait_and_is_cancelled_on_exit():
    received = {}
    started = asyncio.Event()
    cancelled = asyncio.Event()
    control = _Control()

    async def _poll_events(*, paused, wait):
        received.update(paused=paused, wait=wait)
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    task = asyncio.create_task(
        run_capacity_event_pollers(
            _poll_events, gate=control.gate, site_gate=_site_gate, wait=control.wait
        )
    )
    await asyncio.wait_for(started.wait(), timeout=1)
    await _stop(task)

    assert received == {"paused": _site_gate, "wait": control.wait}
    await asyncio.wait_for(cancelled.wait(), timeout=1)


async def test_a_failed_fan_out_ends_the_aggregate_loop():
    control = _Control()
    failed = asyncio.Event()

    async def _poll_events(*, paused, wait):
        failed.set()
        raise RuntimeError("authority unreachable")

    task = asyncio.create_task(
        run_capacity_event_pollers(
            _poll_events, gate=control.gate, site_gate=_site_gate, wait=control.wait
        )
    )
    await asyncio.wait_for(failed.wait(), timeout=1)
    await asyncio.wait_for(control.waiting.wait(), timeout=1)
    control.tick.set()

    with pytest.raises(RuntimeError, match="authority unreachable"):
        await asyncio.wait_for(task, timeout=1)


async def test_a_gated_aggregate_does_not_surface_the_fan_out_until_released():
    gate_reads: list[bool] = []
    held = {"value": True}
    read_twice = asyncio.Event()
    control = _Control()

    def _gate() -> bool:
        gate_reads.append(held["value"])
        if len(gate_reads) >= 2:
            read_twice.set()
        return held["value"]

    async def _poll_events(*, paused, wait):
        raise RuntimeError("authority unreachable")

    task = asyncio.create_task(
        run_capacity_event_pollers(
            _poll_events, gate=_gate, site_gate=_site_gate, wait=control.wait
        )
    )
    try:
        await asyncio.wait_for(read_twice.wait(), timeout=1)
        assert not task.done(), "a held aggregate loop acted on its fan-out"
        assert all(gate_reads)
    finally:
        held["value"] = False

    with pytest.raises(RuntimeError):
        await asyncio.wait_for(task, timeout=1)


async def test_a_storefront_with_no_site_keeps_its_aggregate_loop_alive():
    control = _Control()

    async def _poll_events(*, paused, wait):
        return None

    task = asyncio.create_task(
        run_capacity_event_pollers(
            _poll_events, gate=control.gate, site_gate=_site_gate, wait=control.wait
        )
    )
    try:
        await asyncio.wait_for(control.waiting.wait(), timeout=1)
        await control.next_wait()
        await control.next_wait()
        assert not task.done()
    finally:
        await _stop(task)


async def test_a_pause_reaches_the_aggregate_through_its_wait():
    """However long the aggregate's cadence, a pause requested while it waits
    reaches its gate at once."""
    control = _Control()

    async def _poll_events(*, paused, wait):
        await asyncio.Event().wait()

    task = asyncio.create_task(
        run_capacity_event_pollers(
            _poll_events,
            gate=control.gate,
            site_gate=_site_gate,
            wait=control.wait,
            gate_seconds=3600,
        )
    )
    try:
        await asyncio.wait_for(control.waiting.wait(), timeout=1)
        control.pause()
        await asyncio.wait_for(control.acknowledged.wait(), timeout=1)
    finally:
        await _stop(task)
