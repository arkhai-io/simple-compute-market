"""Lifecycle recovery, operator and negotiation work leave the event loop available."""

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from market_deal_servicing.evidence import transaction
from market_identity import canonical_json

from tests.integration.test_payment_settlement import BUYER, NEGOTIATION, SELLER, make


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["cycle", "interrupt", "capture_negotiation"])
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
    if operation == "cycle":
        action = h.lifecycle.cycle()
    elif operation == "interrupt":
        action = h.lifecycle.interrupt(
            NEGOTIATION, actor=SELLER.identity, operation_key="operator-end", reason="fixture maintenance",
        )
    else:
        request = SimpleNamespace(
            state=SimpleNamespace(marketplace_authenticated=SimpleNamespace(
                principal=BUYER.identity, timestamp=h.lifecycle.clock(),
            )),
            body=AsyncMock(return_value=b"fixture buyer message"),
            headers={"x-fixture-envelope": "buyer"}, method="POST",
        )
        action = h.lifecycle.capture_negotiation(
            request, canonical_json({"negotiation_id": NEGOTIATION, "action": "accept",
                                     "agreement_bytes": "fixture accepted agreement"}),
            {"x-fixture-envelope": "seller"}, operation="negotiate_continue", resource=NEGOTIATION, status=200,
        )
    task = asyncio.create_task(action)
    try:
        await asyncio.sleep(0)  # One explicit scheduling turn, not elapsed-time ordering.
    finally:
        release.set()
        await holder
    await task
    assert progressed == [True], "SQLite blocked the event loop from releasing an independent writer"
    if operation == "capture_negotiation":
        record = await h.lifecycle.evidence.read(NEGOTIATION)
        captured = [item for item in record.items if "x-fixture-envelope" in item.headers]
        assert {item.context["role"] for item in captured} == {"buyer", "seller"}
        assert record.acceptance_expires_at == h.data.mandate.expires
