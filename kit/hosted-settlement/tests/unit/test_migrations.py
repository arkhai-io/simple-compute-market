from __future__ import annotations

import sqlite3

import pytest
from market_identity import Identity, IdentityScheme
from market_settlement_runtime import (
    SettlementObligationRecord,
    SettlementOperationRecord,
    SettlementSQLiteRepository,
)

from market_hosted_settlement import (
    HOSTED_SETTLEMENT_FUNDING_MIGRATION_ID,
    HOSTED_SETTLEMENT_MIGRATIONS,
)

BUYER = Identity(
    scheme=IdentityScheme.ED25519,
    identifier="ERERERERERERERERERERERERERERERERERERERERERE",
)
SELLER = Identity(
    scheme=IdentityScheme.ED25519,
    identifier="IiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiI",
)


def hosted_obligation(*, payment_method_types: list[str]) -> dict:
    return {
        "payer": "buyer",
        "claimant": "seller",
        "payer_principal": BUYER.model_dump(mode="json"),
        "claimant_principal": SELLER.model_dump(mode="json"),
        "amount": "100",
        "asset": "usd",
        "expiration_unix": 100,
        "mechanism": "fiat.stripe.v1",
        "params": {
            "account_ref": "account-1",
            "payer_principal": BUYER.model_dump(mode="json"),
            "claimant_principal": SELLER.model_dump(mode="json"),
            "funds_flow": "separate_charges_transfers",
            "condition": {"kind": "accepted"},
            "payment_method_types": payment_method_types,
        },
    }


@pytest.mark.parametrize(
    "lifecycle",
    [
        {"mechanism_status": "creating"},
        {"mechanism_status": "awaiting_payment"},
        {"mechanism_status": "pending"},
        {"mechanism_status": "requires_action"},
        {"mechanism_status": "ready", "materialization_state": "materialized"},
        {
            "mechanism_status": "collected",
            "materialization_state": "materialized",
            "collection_state": "succeeded",
        },
        {
            "mechanism_status": "reclaimed",
            "materialization_state": "materialized",
            "reclaim_state": "succeeded",
        },
        {"mechanism_status": "expired", "materialization_state": "materialized"},
        {"mechanism_status": "failed", "materialization_state": "materialized"},
        {
            "mechanism_status": "manual_required",
            "materialization_state": "manual_required",
        },
    ],
)
async def test_legacy_hosted_card_migration_preserves_identity_and_lifecycle(
    tmp_path,
    lifecycle,
) -> None:
    path = tmp_path / "legacy-hosted-card.db"
    repository = SettlementSQLiteRepository(str(path))
    record = SettlementObligationRecord.from_obligation(
        agreement_ref="accepted-negotiation",
        obligation_index=0,
        obligation=hosted_obligation(payment_method_types=["card"]),
    ).model_copy(
        update={
            "mechanism_ref": "hosted-settlement-1",
            "materialization_receipt": {"historical": True},
            **lifecycle,
        }
    )
    before = await repository.upsert_settlement_obligation(record.model_dump())
    operation = SettlementOperationRecord(
        obligation_ref=record.obligation_ref,
        operation="status",
        request_hash="a" * 64,
    )
    before_operation = await repository.upsert_settlement_operation(
        operation.model_dump()
    )

    migrated_repository = SettlementSQLiteRepository(
        str(path),
        extra_migrations=HOSTED_SETTLEMENT_MIGRATIONS,
    )
    migrated = await migrated_repository.load_settlement_obligation(
        record.obligation_ref
    )
    migrated_operation = await migrated_repository.load_settlement_operation(
        record.obligation_ref,
        "status",
    )

    assert migrated is not None
    assert migrated["mechanism_params"] == {"legacy_recovery": "hosted-card.v1"}
    for field in (
        "obligation_ref",
        "agreement_ref",
        "obligation_hash",
        "obligation",
        "mechanism_ref",
        "mechanism_status",
        "materialization_receipt",
    ):
        assert migrated[field] == before[field]
    assert migrated_operation == before_operation
    assert HOSTED_SETTLEMENT_MIGRATIONS[-1].id == (
        HOSTED_SETTLEMENT_FUNDING_MIGRATION_ID
    )


async def test_legacy_hosted_card_migration_rolls_back_ambiguous_rows(
    tmp_path,
) -> None:
    path = tmp_path / "ambiguous-hosted-card.db"
    repository = SettlementSQLiteRepository(str(path))
    for index, methods in enumerate((["card"], ["card", "us_bank_account"])):
        record = SettlementObligationRecord.from_obligation(
            agreement_ref=f"negotiation-{index}",
            obligation_index=0,
            obligation=hosted_obligation(payment_method_types=methods),
        ).model_copy(update={"mechanism_ref": f"hosted-settlement-{index}"})
        await repository.upsert_settlement_obligation(record.model_dump())

    with pytest.raises(ValueError, match="ambiguous legacy funding"):
        SettlementSQLiteRepository(
            str(path),
            extra_migrations=HOSTED_SETTLEMENT_MIGRATIONS,
        )

    conn = sqlite3.connect(path)
    try:
        rows = conn.execute(
            "SELECT mechanism_params FROM settlement_obligations "
            "ORDER BY obligation_ref"
        ).fetchall()
        migration = conn.execute(
            "SELECT 1 FROM schema_migrations WHERE id=?",
            (HOSTED_SETTLEMENT_FUNDING_MIGRATION_ID,),
        ).fetchone()
    finally:
        conn.close()
    assert rows == [("{}",), ("{}",)]
    assert migration is None
