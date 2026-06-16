"""Abandoned claims end leases: settlement's "deal is over" → capacity.

The single coupling joint between the design doc's two parts: the
settlement lifecycle decides the deal is over, the capacity layer must
learn it to release the allocation.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from market_storefront.services import claims_runtime
from market_storefront.services.claims_runtime import (
    submit_claim,
    truncate_lease_for_abandoned_claim,
)
from market_storefront.utils.sqlite_client import SQLiteClient
from tests.fake_site import FakeSite, site_capacity


@pytest.fixture
def db(tmp_path):
    return SQLiteClient(db_path=str(tmp_path / "abandon-test.db"))


@pytest.mark.asyncio
async def test_truncates_the_ledger_lease_to_now(db):
    fake = FakeSite()
    fake.add_resource("res-trunc", 2, attributes={"vm_host": "kvm1"})

    with site_capacity(fake) as capacity:
        reserved = await capacity.reserve(
            claim={}, deal_ref={"escrow_uid": "0xabandoned"},
        )
        await capacity.commit(
            resource_id=reserved["resource_id"],
            allocation_id=reserved["allocation_id"],
            lease_end_utc="2099-01-01 00:00",
        )
        truncated = await truncate_lease_for_abandoned_claim(
            db, escrow_uid="0xabandoned", reason="expiration window passed",
        )

    assert truncated is not None
    row = fake.allocations[reserved["allocation_id"]]
    assert row["state"] == "leased"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert str(row["lease_end_utc"]).startswith(today)


@pytest.mark.asyncio
async def test_no_live_allocation_is_a_quiet_noop(db):
    with site_capacity(FakeSite()):
        assert await truncate_lease_for_abandoned_claim(
            db, escrow_uid="0xunknown",
        ) is None


@pytest.mark.asyncio
async def test_engine_abandonment_fires_the_truncation(db):
    """End to end through the engine: a claim whose expiration window
    (plus grace) has passed abandons on the sweep and schedules the
    lease truncation for its escrow."""
    await submit_claim(
        sqlite_client=db,
        escrow_uid="0xexpired",
        fulfillment_uid="ful-1",
        negotiation_id="neg-1",
        obligation={
            "mechanism": "alkahest.v1",
            # Expired far beyond the engine's abandonment grace.
            "expiration_unix": 1_000_000,
            "params": {"chain_name": "anvil"},
        },
    )

    fired = AsyncMock(return_value=None)
    with patch.object(
        claims_runtime, "truncate_lease_for_abandoned_claim", fired,
    ):
        engine = claims_runtime.build_claims_engine(db)
        assert await engine.tick() == 1
        await asyncio.sleep(0)  # let the fire-and-forget task run

    fired.assert_awaited_once()
    assert fired.await_args.kwargs["escrow_uid"] == "0xexpired"
    assert fired.await_args.kwargs["reason"] == "expiration window passed"
    row = await db.load_claim("0xexpired")
    assert row["state"] == "abandoned"
