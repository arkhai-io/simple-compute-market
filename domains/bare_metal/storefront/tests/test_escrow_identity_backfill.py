"""Legacy Alkahest escrows gain their mechanism-neutral obligation identity."""

from __future__ import annotations

from typing import Any

from core_storefront.escrow_identity import backfill_escrow_obligation_records
from market_identity import Eip191Signer
from market_settlement_runtime import (
    SettlementRuntime,
    SettlementSQLiteRepository,
)

from arkhai_bare_metal_storefront.domain_runtime import get_market_domain_contract
from arkhai_bare_metal_storefront.sqlite_client import SQLiteClient

_BUYER = Eip191Signer(bytes.fromhex("22" * 32)).identity
_SELLER = Eip191Signer(bytes.fromhex("11" * 32)).identity
_ESCROW_UID = "0x" + "ab" * 32


def _plan() -> dict[str, Any]:
    buyer = _BUYER.model_dump(mode="json")
    seller = _SELLER.model_dump(mode="json")
    return {
        "buyer_principal": buyer,
        "seller_principal": seller,
        "service_terms": {},
        "obligations": [
            {
                "payer": "buyer",
                "claimant": "seller",
                "payer_principal": buyer,
                "claimant_principal": seller,
                "amount": 250,
                "asset": "0x" + "01" * 20,
                "expiration_unix": 1_900_000_000,
                "conditions": [],
                "mechanism": "alkahest.v1",
                "params": {"chain_name": "base-sepolia"},
            }
        ],
    }


async def _legacy_deal(db: SQLiteClient, *, negotiation_id: str, with_plan: bool):
    await db.create_negotiation_thread(
        negotiation_id=negotiation_id,
        our_listing_id="L-1",
        their_listing_id="",
        our_agent_id="seller",
        their_agent_id="buyer",
        buyer_principal=_BUYER,
        seller_principal=_SELLER,
        owner_id="seller",
    )
    if with_plan:
        await db.commit_settlement_plan(
            negotiation_id=negotiation_id,
            settlement_plan=_plan(),
            buyer_principal=_BUYER,
            seller_principal=_SELLER,
        )


async def test_backfill_records_legacy_escrows_idempotently(tmp_path) -> None:
    db = SQLiteClient(
        str(tmp_path / "storefront.db"), domain=get_market_domain_contract()
    )
    await _legacy_deal(db, negotiation_id="neg-legacy", with_plan=True)
    await db.insert_escrow(
        escrow_uid=_ESCROW_UID,
        negotiation_id="neg-legacy",
        chain_name="base-sepolia",
        escrow_address="0x" + "ee" * 20,
    )
    repository = SettlementSQLiteRepository(db.db_path, apply_migrations=False)
    runtime = SettlementRuntime(repository, {})

    backfilled = await backfill_escrow_obligation_records(
        sqlite_client=db,
        settlement_runtime=runtime,
        local_principal=_SELLER,
    )
    assert backfilled == 1
    record = await repository.load_settlement_obligation_by_mechanism_ref(_ESCROW_UID)
    assert record is not None
    assert record["agreement_ref"] == "neg-legacy"
    assert record["obligation"]["mechanism"] == "alkahest.v1"
    assert record["mechanism_status"] == "ready"

    again = await backfill_escrow_obligation_records(
        sqlite_client=db,
        settlement_runtime=runtime,
        local_principal=_SELLER,
    )
    assert again == 0


async def test_backfill_skips_planless_rows_without_inventing_identity(
    tmp_path,
) -> None:
    db = SQLiteClient(
        str(tmp_path / "storefront.db"), domain=get_market_domain_contract()
    )
    await _legacy_deal(db, negotiation_id="neg-preplan", with_plan=False)
    escrow_uid = "0x" + "cd" * 32
    await db.insert_escrow(
        escrow_uid=escrow_uid,
        negotiation_id="neg-preplan",
        chain_name="base-sepolia",
        escrow_address="0x" + "ee" * 20,
    )
    repository = SettlementSQLiteRepository(db.db_path, apply_migrations=False)
    runtime = SettlementRuntime(repository, {})

    backfilled = await backfill_escrow_obligation_records(
        sqlite_client=db,
        settlement_runtime=runtime,
        local_principal=_SELLER,
    )
    assert backfilled == 0
    assert (
        await repository.load_settlement_obligation_by_mechanism_ref(escrow_uid)
    ) is None
