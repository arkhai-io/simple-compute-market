"""Abandoned claims end leases: settlement's "deal is over" → capacity.

The single coupling joint between the design doc's two parts: the
settlement lifecycle decides the deal is over, the capacity layer must
learn it to release the allocation.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from market_storefront.services import claims_runtime
from market_storefront.services.claims_runtime import (
    submit_claim,
    truncate_lease_for_abandoned_claim,
)
from market_storefront.utils.sqlite_client import SQLiteClient


@pytest.fixture
def db(tmp_path):
    return SQLiteClient(db_path=str(tmp_path / "abandon-test.db"))


def _embedded_settings():
    return SimpleNamespace(
        capacity=SimpleNamespace(mode="", sites=None),
        admin_api_key="",
    )


async def _leased_allocation(db: SQLiteClient, escrow_uid: str) -> dict:
    await db.upsert_resource(
        resource_id="res-trunc",
        resource_type="compute.gpu",
        resource_subtype="h200",
        unit="count",
        value=2,
        state="available",
        attributes={"gpu_model": "H200", "vm_host": "kvm1"},
    )
    reserved = await db.reserve_available_compute_vm(escrow_uid=escrow_uid)
    await db.update_compute_allocation_state(
        allocation_id=reserved["allocation_id"],
        state="leased",
        lease_end_utc="2099-01-01 00:00",
    )
    return reserved


@pytest.mark.asyncio
async def test_truncates_the_embedded_lease_to_now(db):
    reserved = await _leased_allocation(db, "0xabandoned")

    with patch(
        "market_storefront.utils.config.settings", _embedded_settings(),
    ):
        truncated = await truncate_lease_for_abandoned_claim(
            db, escrow_uid="0xabandoned", reason="expiration window passed",
        )

    assert truncated is not None
    row = await db.find_held_compute_allocation(escrow_uid="0xabandoned")
    assert row["allocation_id"] == reserved["allocation_id"]
    assert row["state"] == "leased"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert str(row["lease_end_utc"]).startswith(today)


@pytest.mark.asyncio
async def test_no_live_allocation_is_a_quiet_noop(db):
    with patch(
        "market_storefront.utils.config.settings", _embedded_settings(),
    ):
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
