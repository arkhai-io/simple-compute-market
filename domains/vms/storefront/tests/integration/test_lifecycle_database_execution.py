"""Lifecycle recovery and operator work leave the asyncio executor available."""

import asyncio
import threading

import pytest
from market_deal_servicing.evidence import transaction

from tests.integration.test_payment_settlement import NEGOTIATION, SELLER, make


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["cycle", "interrupt"])
async def test_busy_writer_does_not_block_lifecycle_operations(make, operation):
    h = await make()
    h.serve()
    await h.settle()
    await h.delivered()
    locked = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    progressed = []

    def hold():
        with transaction(h.lifecycle.path):
            loop.call_soon_threadsafe(locked.set)
            progressed.append(release.wait(timeout=2))

    holder = asyncio.create_task(asyncio.to_thread(hold))
    await asyncio.wait_for(locked.wait(), 5)
    action = h.lifecycle.cycle() if operation == "cycle" else h.lifecycle.interrupt(
        NEGOTIATION, actor=SELLER.identity, operation_key="operator-end", reason="fixture maintenance",
    )
    task = asyncio.create_task(action)
    try:
        await asyncio.sleep(0)  # One explicit scheduling turn, not elapsed-time ordering.
    finally:
        release.set()
        await holder
    await task
    assert progressed == [True], "SQLite blocked the event loop from releasing an independent writer"
