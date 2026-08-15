"""Heartbeat mechanics: skew window, monotonic replay protection."""

from __future__ import annotations

import pytest
from market_identity import Identity


from core_storefront.heartbeats import (
    HeartbeatError,
    heartbeat_gap_seconds,
    record_heartbeat,
)

BUYER = Identity(scheme="eip191", identifier="0x" + "11" * 20)
SELLER = Identity(scheme="eip191", identifier="0x" + "22" * 20)


async def _record(store, *, deal_ref, sent_at_unix, now, max_skew_seconds=300):
    return await record_heartbeat(
        store,
        deal_ref=deal_ref,
        buyer_principal=BUYER,
        seller_principal=SELLER,
        sent_at_unix=sent_at_unix,
        now=now,
        max_skew_seconds=max_skew_seconds,
    )


class FakeStore:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    async def latest_heartbeat(self, deal_ref):
        mine = [r for r in self.rows if r["deal_ref"] == deal_ref]
        return max(mine, key=lambda r: r["sent_at_unix"]) if mine else None

    async def insert_heartbeat(self, record):
        self.rows.append(dict(record))


async def test_first_heartbeat_records():
    store = FakeStore()
    rec = await _record(
        store, deal_ref="d1", sent_at_unix=1_000.0, now=1_001.0
    )
    assert rec["payload"] == {}
    assert store.rows[0]["sent_at_unix"] == 1_000.0
    assert store.rows[0]["received_at_unix"] == 1_001.0


async def test_monotonicity_rejects_replay_and_out_of_order():
    store = FakeStore()
    await _record(store, deal_ref="d1", sent_at_unix=1_000.0, now=1_000.0)
    with pytest.raises(HeartbeatError) as exc:
        await _record(store, deal_ref="d1", sent_at_unix=1_000.0, now=1_001.0)
    assert exc.value.status_code == 409
    with pytest.raises(HeartbeatError):
        await _record(store, deal_ref="d1", sent_at_unix=999.0, now=1_001.0)
    # A different deal is unaffected.
    await _record(store, deal_ref="d2", sent_at_unix=999.0, now=1_001.0)


async def test_skew_window_bounds_both_directions():
    store = FakeStore()
    with pytest.raises(HeartbeatError) as exc:
        await _record(
            store,
            deal_ref="d1",
            sent_at_unix=400.0,
            now=1_000.0,
            max_skew_seconds=300,
        )
    assert exc.value.status_code == 400
    with pytest.raises(HeartbeatError):
        await _record(
            store,
            deal_ref="d1",
            sent_at_unix=1_400.0,
            now=1_000.0,
            max_skew_seconds=300,
        )


async def test_gap_seconds():
    assert heartbeat_gap_seconds(None) is None
    assert heartbeat_gap_seconds({"sent_at_unix": 900.0}, now=1_000.0) == 100.0
