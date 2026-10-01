"""The aggregate capacity-event loop holds while gated and surfaces a failed fan-out."""

from __future__ import annotations

import asyncio

import pytest

from market_capacity_publication import run_capacity_event_pollers


async def test_the_fan_out_receives_the_site_gate_factory_and_is_cancelled_on_exit():
    received = {}
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def _poll_events(*, paused):
        received["paused"] = paused
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    def site_gate(site_id):
        return lambda: False

    task = asyncio.create_task(
        run_capacity_event_pollers(_poll_events, gate=lambda: False, site_gate=site_gate, gate_seconds=0.001)
    )
    await asyncio.wait_for(started.wait(), timeout=1)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert received["paused"] is site_gate
    await asyncio.wait_for(cancelled.wait(), timeout=1)


async def test_a_failed_fan_out_ends_the_aggregate_loop():
    async def _poll_events(*, paused):
        raise RuntimeError("authority unreachable")

    with pytest.raises(RuntimeError, match="authority unreachable"):
        await asyncio.wait_for(
            run_capacity_event_pollers(
                _poll_events, gate=lambda: False, site_gate=lambda site: (lambda: False), gate_seconds=0.001
            ),
            timeout=1,
        )


async def test_a_gated_aggregate_does_not_surface_the_fan_out_until_released():
    held = {"value": True}
    gate_reads = []

    def _gate():
        gate_reads.append(held["value"])
        return held["value"]

    async def _poll_events(*, paused):
        raise RuntimeError("authority unreachable")

    task = asyncio.create_task(
        run_capacity_event_pollers(_poll_events, gate=_gate, site_gate=lambda site: (lambda: True), gate_seconds=0.001)
    )
    await asyncio.sleep(0.05)
    assert not task.done(), "a held aggregate loop acted on its fan-out"
    assert gate_reads and all(gate_reads)

    held["value"] = False
    with pytest.raises(RuntimeError):
        await asyncio.wait_for(task, timeout=1)


async def test_a_storefront_with_no_site_keeps_its_aggregate_loop_alive():
    async def _poll_events(*, paused):
        return None

    task = asyncio.create_task(
        run_capacity_event_pollers(_poll_events, gate=lambda: False, site_gate=lambda site: (lambda: False), gate_seconds=0.001)
    )
    await asyncio.sleep(0.02)
    assert not task.done()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
