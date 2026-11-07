"""Bare-metal cycles and terminal ends do not hold the asyncio executor."""

import asyncio
import threading

import pytest
from market_deal_servicing.evidence import transaction

from integration.test_payment_settlement_client import enabled, harness


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["cycle", "local_end"])
async def test_busy_writer_does_not_block_lifecycle_operations(harness, operation):
    h = harness
    h.serve()
    await h.settle()
    lifecycle = h.runtime.lifecycle
    locked = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    progressed = []

    def hold():
        with transaction(lifecycle.path):
            loop.call_soon_threadsafe(locked.set)
            progressed.append(release.wait(timeout=2))

    holder = asyncio.create_task(asyncio.to_thread(hold))
    await asyncio.wait_for(locked.wait(), 5)
    action = lifecycle.cycle() if operation == "cycle" else lifecycle.local_end(
        h.negotiation_id, cause="fixture-terminal",
    )
    task = asyncio.create_task(action)
    try:
        await asyncio.sleep(0)  # One explicit scheduling turn, not elapsed-time ordering.
    finally:
        release.set()
        await holder
    await task
    assert progressed == [True], "SQLite blocked the event loop from releasing an independent writer"
