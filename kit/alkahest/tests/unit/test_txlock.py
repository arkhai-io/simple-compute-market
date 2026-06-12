
"""Per-chain transaction serialization."""

import asyncio

import pytest

from market_alkahest.txlock import chain_tx_lock


@pytest.mark.asyncio
async def test_same_chain_same_loop_is_one_lock():
    assert chain_tx_lock("anvil") is chain_tx_lock("anvil")
    assert chain_tx_lock("anvil") is not chain_tx_lock("base")
    assert chain_tx_lock(None) is chain_tx_lock(None)


@pytest.mark.asyncio
async def test_submissions_serialize():
    order: list[str] = []
    lock = chain_tx_lock("anvil")

    async def submit(tag: str):
        async with lock:
            order.append(f"{tag}:in")
            await asyncio.sleep(0.01)
            order.append(f"{tag}:out")

    await asyncio.gather(submit("a"), submit("b"))
    assert order in (
        ["a:in", "a:out", "b:in", "b:out"],
        ["b:in", "b:out", "a:in", "a:out"],
    )


def test_fresh_loop_gets_a_fresh_lock():
    first = asyncio.new_event_loop()
    try:
        l1 = first.run_until_complete(_grab())
    finally:
        first.close()
    second = asyncio.new_event_loop()
    try:
        l2 = second.run_until_complete(_grab())
    finally:
        second.close()
    assert l1 is not l2


async def _grab():
    return chain_tx_lock("anvil")
