"""Claims engine over the real SQLite store: submit → sweep → collect."""

from __future__ import annotations

import pytest

from core_storefront.settlement_lifecycle import ClaimsEngine
from market_storefront.services.claims_runtime import submit_claim
from market_storefront.utils.sqlite_client import SQLiteClient


@pytest.fixture
def db(tmp_path):
    client = SQLiteClient(db_path=str(tmp_path / "claims-test.db"))
    return client


class CollectEverything:
    async def check_conditions(self, claim) -> str:
        claim.mechanism_state["checked"] = True
        return "ready"

    async def collect(self, claim):
        return {"receipt": "0xfeed"}


@pytest.mark.asyncio
async def test_submit_persists_and_engine_collects(db):
    await submit_claim(
        sqlite_client=db,
        escrow_uid="esc-int-1",
        fulfillment_uid="ful-int-1",
        negotiation_id="neg-1",
        listing_id="lst-1",
        obligation={
            "mechanism": "alkahest.v1",
            "expiration_unix": 4_102_444_800,
            "params": {"chain_name": "anvil", "escrow_contract": "0x" + "11" * 20},
        },
    )

    row = await db.load_claim("esc-int-1")
    assert row is not None
    assert row["state"] == "awaiting_conditions"
    assert row["deal_ref"] == {"negotiation_id": "neg-1", "listing_id": "lst-1"}
    assert row["fulfillment_ref"] == "ful-int-1"

    engine = ClaimsEngine(db, {"alkahest.v1": CollectEverything()})
    assert await engine.tick() == 1

    row = await db.load_claim("esc-int-1")
    assert row["state"] == "collected"
    assert row["result"] == {"receipt": "0xfeed"}
    assert row["mechanism_state"] == {"checked": True}

    # Terminal claims drop out of subsequent sweeps.
    assert await engine.tick() == 0


@pytest.mark.asyncio
async def test_submit_without_obligation_builds_minimal_envelope(db):
    await submit_claim(
        sqlite_client=db,
        escrow_uid="esc-int-2",
        fulfillment_uid=None,
        chain_name="anvil",
        escrow_address="0x" + "22" * 20,
    )
    row = await db.load_claim("esc-int-2")
    assert row["obligation"]["mechanism"] == "alkahest.v1"
    assert row["obligation"]["params"]["chain_name"] == "anvil"
    assert row["obligation"]["params"]["escrow_contract"] == "0x" + "22" * 20


@pytest.mark.asyncio
async def test_submit_is_idempotent_by_escrow_uid(db):
    for _ in range(2):
        await submit_claim(
            sqlite_client=db,
            escrow_uid="esc-int-3",
            fulfillment_uid="ful-a",
        )
    row = await db.load_claim("esc-int-3")
    assert row["fulfillment_ref"] == "ful-a"


@pytest.mark.asyncio
async def test_backoff_round_trips_through_sqlite(db):
    class AlwaysPending:
        async def check_conditions(self, claim) -> str:
            return "pending"

        async def collect(self, claim):  # pragma: no cover
            raise AssertionError("must not collect")

    await submit_claim(sqlite_client=db, escrow_uid="esc-int-4", fulfillment_uid="f")
    engine = ClaimsEngine(
        db, {"alkahest.v1": AlwaysPending()},
        base_backoff_seconds=60, clock=lambda: 1_000.0,
    )
    await engine.tick()
    row = await db.load_claim("esc-int-4")
    assert row["attempts"] == 1
    assert row["next_attempt_unix"] == 1_060.0
    # Not due → not swept.
    assert await engine.tick() == 0
