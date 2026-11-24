from __future__ import annotations

import sqlite3

import pytest
from market_identity import Identity, IdentityScheme
from settlement_tables import settlement_database

from market_settlement_runtime import (
    SettlementObligationRecord,
    SettlementOperationRecord,
    SettlementSQLiteRepository,
    derive_obligation_ref,
    obligation_payload_hash,
)

BUYER = Identity(
    scheme=IdentityScheme.ED25519,
    identifier="ERERERERERERERERERERERERERERERERERERERERERE",
)
SELLER = Identity(
    scheme=IdentityScheme.ED25519,
    identifier="IiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiI",
)


def obligation(*, payer: str = "buyer") -> dict:
    return {
        "payer": payer,
        "claimant": "seller" if payer == "buyer" else "buyer",
        "payer_principal": (BUYER if payer == "buyer" else SELLER).model_dump(
            mode="json"
        ),
        "claimant_principal": (SELLER if payer == "buyer" else BUYER).model_dump(
            mode="json"
        ),
        "mechanism": "test.v1",
        "expiration_unix": 100,
    }


async def test_repository_identity_cas_and_immutable_fulfillment(tmp_path) -> None:
    repository = SettlementSQLiteRepository(settlement_database(tmp_path / "state.db"))
    record = SettlementObligationRecord.from_obligation(
        agreement_ref="agreement",
        obligation_index=0,
        obligation=obligation(),
    )
    stored = await repository.upsert_settlement_obligation(record.model_dump())
    assert await repository.upsert_settlement_obligation(record.model_dump()) == stored
    changed = SettlementObligationRecord.from_obligation(
        agreement_ref="agreement",
        obligation_index=0,
        obligation=obligation(payer="seller"),
    )
    with pytest.raises(ValueError, match="different terms"):
        await repository.upsert_settlement_obligation(changed.model_dump())
    assert stored["payer_principal"] == BUYER.model_dump(mode="json")
    assert stored["claimant_principal"] == SELLER.model_dump(mode="json")
    conn = sqlite3.connect(repository.db_path)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE settlement_obligations SET payer_principal=NULL "
                "WHERE obligation_ref=?",
                (record.obligation_ref,),
            )
        conn.rollback()
    finally:
        conn.close()
    bound = await repository.bind_settlement_fulfillment(
        obligation_ref=record.obligation_ref,
        fulfillment_ref="fulfillment-1",
    )
    assert bound["fulfillment_ref"] == "fulfillment-1"
    assert (
        await repository.bind_settlement_fulfillment(
            obligation_ref=record.obligation_ref,
            fulfillment_ref="fulfillment-1",
        )
    )["fulfillment_ref"] == "fulfillment-1"
    with pytest.raises(ValueError, match="immutable"):
        await repository.bind_settlement_fulfillment(
            obligation_ref=record.obligation_ref,
            fulfillment_ref="fulfillment-2",
        )


async def test_principal_columns_preserve_a_legacy_obligation_identity(
    tmp_path,
) -> None:
    repository = SettlementSQLiteRepository(
        settlement_database(tmp_path / "legacy-principal.db")
    )
    legacy_obligation = obligation()
    del legacy_obligation["payer_principal"]
    del legacy_obligation["claimant_principal"]
    legacy_ref = derive_obligation_ref("agreement", 0, legacy_obligation)
    legacy_hash = obligation_payload_hash(legacy_obligation)
    record = SettlementObligationRecord(
        obligation_ref=legacy_ref,
        agreement_ref="agreement",
        obligation_index=0,
        obligation_hash=legacy_hash,
        obligation=legacy_obligation,
        payer_principal=BUYER,
        claimant_principal=SELLER,
    )

    await repository.upsert_settlement_obligation(record.model_dump())

    stored = await repository.load_settlement_obligation(legacy_ref)
    assert stored is not None
    migrated = SettlementObligationRecord.model_validate(stored)
    assert migrated.obligation_ref == legacy_ref
    assert migrated.obligation_hash == legacy_hash
    assert migrated.obligation == legacy_obligation
    assert migrated.payer_principal == BUYER
    assert migrated.claimant_principal == SELLER


async def test_operation_journal_rejects_changed_request(tmp_path) -> None:
    repository = SettlementSQLiteRepository(settlement_database(tmp_path / "journal.db"))
    record = SettlementObligationRecord.from_obligation(
        agreement_ref="agreement",
        obligation_index=0,
        obligation=obligation(),
    )
    await repository.upsert_settlement_obligation(record.model_dump())
    operation = SettlementOperationRecord(
        obligation_ref=record.obligation_ref,
        operation="materialize",
        request_hash="request-a",
    )
    await repository.upsert_settlement_operation(operation.model_dump())
    with pytest.raises(ValueError, match="different request"):
        await repository.upsert_settlement_operation(
            operation.model_copy(update={"request_hash": "request-b"}).model_dump()
        )


def test_the_repository_issues_no_ddl(tmp_path) -> None:
    """Opening a repository leaves an empty database empty: its tables are a
    storefront chain's."""
    path = tmp_path / "empty.db"
    SettlementSQLiteRepository(str(path))
    conn = sqlite3.connect(path)
    try:
        assert conn.execute("SELECT name FROM sqlite_master").fetchall() == []
    finally:
        conn.close()


async def test_materialization_params_are_immutable_and_identity_preserving(
    tmp_path,
) -> None:
    repository = SettlementSQLiteRepository(
        settlement_database(tmp_path / "mechanism-params.db")
    )
    record = SettlementObligationRecord.from_obligation(
        agreement_ref="agreement",
        obligation_index=0,
        obligation=obligation(),
    )
    stored = await repository.upsert_settlement_obligation(record.model_dump())
    params = {"authorization_ref": "accepted-authorization-1"}

    bound = await repository.bind_settlement_mechanism_params(
        obligation_ref=record.obligation_ref,
        mechanism_params=params,
    )
    retried = await repository.bind_settlement_mechanism_params(
        obligation_ref=record.obligation_ref,
        mechanism_params=params,
    )
    with pytest.raises(ValueError, match="immutable"):
        await repository.bind_settlement_mechanism_params(
            obligation_ref=record.obligation_ref,
            mechanism_params={"authorization_ref": "changed"},
        )

    assert (
        bound["obligation_ref"] == retried["obligation_ref"] == stored["obligation_ref"]
    )
    assert (
        bound["obligation_hash"]
        == retried["obligation_hash"]
        == stored["obligation_hash"]
    )
    assert bound["obligation"] == retried["obligation"] == stored["obligation"]
    assert bound["mechanism_params"] == retried["mechanism_params"] == params
