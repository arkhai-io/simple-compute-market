from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

import pytest
from market_identity import Identity, IdentityScheme

from market_settlement_runtime import (
    SETTLEMENT_MIGRATION_ID,
    SETTLEMENT_MECHANISM_PARAMS_MIGRATION_ID,
    SETTLEMENT_PRINCIPAL_MIGRATION_ID,
    SettlementObligationRecord,
    SettlementOperationRecord,
    SettlementSQLiteRepository,
    derive_obligation_ref,
    obligation_payload_hash,
    settlement_migrations,
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
        "payer_principal": (
            BUYER if payer == "buyer" else SELLER
        ).model_dump(mode="json"),
        "claimant_principal": (
            SELLER if payer == "buyer" else BUYER
        ).model_dump(mode="json"),
        "mechanism": "test.v1",
        "expiration_unix": 100,
    }


def hosted_obligation(
    *,
    payment_method_types: list[str] | None = None,
    funding_profile: str | None = None,
) -> dict:
    params: dict = {
        "account_ref": "account-1",
        "payer_principal": BUYER.model_dump(mode="json"),
        "claimant_principal": SELLER.model_dump(mode="json"),
        "funds_flow": "separate_charges_transfers",
        "condition": {"kind": "accepted"},
    }
    if payment_method_types is not None:
        params["payment_method_types"] = payment_method_types
    if funding_profile is not None:
        params["funding_profile"] = funding_profile
    return {
        **obligation(),
        "amount": "100",
        "asset": "usd",
        "mechanism": "fiat.stripe.v1",
        "params": params,
    }


def create_preprincipal_obligation_database(
    path,
    obligations: list[tuple[str, int, dict]],
) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE schema_migrations (
              id TEXT PRIMARY KEY,
              applied_at TEXT NOT NULL DEFAULT 'test'
            )
            """
        )
        conn.executemany(
            "INSERT INTO schema_migrations VALUES (?, 'legacy')",
            [
                (SETTLEMENT_MIGRATION_ID,),
                ("20260810_002_settlement_servicing_runtime",),
            ],
        )
        conn.execute(
            """
            CREATE TABLE settlement_obligations (
              obligation_ref TEXT PRIMARY KEY,
              agreement_ref TEXT NOT NULL,
              obligation_index INTEGER NOT NULL,
              obligation_hash TEXT NOT NULL,
              obligation TEXT NOT NULL,
              mechanism_ref TEXT,
              mechanism_status TEXT,
              mechanism_state TEXT NOT NULL DEFAULT '{}',
              buyer_action TEXT,
              condition_anchor TEXT,
              fulfillment_ref TEXT,
              materialization_state TEXT NOT NULL DEFAULT 'pending',
              condition_state TEXT NOT NULL DEFAULT 'pending',
              collection_state TEXT NOT NULL DEFAULT 'pending',
              reclaim_state TEXT NOT NULL DEFAULT 'pending',
              materialization_receipt TEXT,
              status_receipt TEXT,
              collection_receipt TEXT,
              reclaim_receipt TEXT,
              last_error TEXT,
              version INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              UNIQUE (agreement_ref, obligation_index)
            )
            """
        )
        for agreement_ref, index, value in obligations:
            conn.execute(
                """
                INSERT INTO settlement_obligations (
                  obligation_ref, agreement_ref, obligation_index,
                  obligation_hash, obligation, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'legacy', 'legacy')
                """,
                (
                    derive_obligation_ref(agreement_ref, index, value),
                    agreement_ref,
                    index,
                    obligation_payload_hash(value),
                    json.dumps(value, separators=(",", ":"), sort_keys=True),
                ),
            )
        conn.commit()
    finally:
        conn.close()


async def test_repository_identity_cas_and_immutable_fulfillment(tmp_path) -> None:
    repository = SettlementSQLiteRepository(str(tmp_path / "state.db"))
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
    repository = SettlementSQLiteRepository(str(tmp_path / "legacy-principal.db"))
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


async def test_legacy_evm_principals_migrate_atomically_and_recover(
    tmp_path,
) -> None:
    path = tmp_path / "legacy-evm.db"
    payer = "0x" + "AB" * 20
    claimant = "0x" + "cd" * 20
    legacy = {
        "payer": payer,
        "claimant": claimant,
        "mechanism": "test.v1",
        "expiration_unix": 100,
    }
    create_preprincipal_obligation_database(
        path,
        [("agreement", 0, legacy)],
    )
    legacy_ref = derive_obligation_ref("agreement", 0, legacy)
    legacy_hash = obligation_payload_hash(legacy)

    repository = SettlementSQLiteRepository(str(path))
    stored = await repository.load_settlement_obligation(legacy_ref)
    assert stored is not None
    migrated = SettlementObligationRecord.model_validate(stored)
    assert migrated.payer_principal == Identity(
        scheme=IdentityScheme.EIP191,
        identifier=payer.lower(),
    )
    assert migrated.claimant_principal == Identity(
        scheme=IdentityScheme.EIP191,
        identifier=claimant,
    )
    assert migrated.obligation_ref == legacy_ref
    assert migrated.obligation_hash == legacy_hash
    assert migrated.obligation == legacy

    reopened = SettlementSQLiteRepository(str(path))
    assert await reopened.load_settlement_obligation(legacy_ref) == stored


@pytest.mark.parametrize(
    ("payer_value", "payer_principal", "message"),
    [
        ("not-an-address", None, "malformed legacy payer"),
        (
            "0x" + "11" * 20,
            {
                "scheme": "eip191",
                "identifier": "0x" + "22" * 20,
            },
            "ambiguous payer identities",
        ),
    ],
)
def test_legacy_principal_migration_rolls_back_invalid_population(
    tmp_path,
    payer_value,
    payer_principal,
    message,
) -> None:
    path = tmp_path / "invalid-legacy.db"
    valid = {
        "payer": "0x" + "33" * 20,
        "claimant": "0x" + "44" * 20,
        "mechanism": "test.v1",
        "expiration_unix": 100,
    }
    invalid = {
        "payer": payer_value,
        "claimant": "0x" + "55" * 20,
        "mechanism": "test.v1",
        "expiration_unix": 100,
    }
    if payer_principal is not None:
        invalid["payer_principal"] = payer_principal
    create_preprincipal_obligation_database(
        path,
        [
            ("valid", 0, valid),
            ("invalid", 0, invalid),
        ],
    )

    with pytest.raises(ValueError, match=message):
        SettlementSQLiteRepository(str(path))

    conn = sqlite3.connect(path)
    try:
        columns = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(settlement_obligations)"
            )
        }
        applied = conn.execute(
            "SELECT 1 FROM schema_migrations WHERE id=?",
            (SETTLEMENT_PRINCIPAL_MIGRATION_ID,),
        ).fetchone()
        rows = conn.execute(
            "SELECT agreement_ref, obligation FROM settlement_obligations "
            "ORDER BY agreement_ref"
        ).fetchall()
    finally:
        conn.close()
    assert "payer_principal" not in columns
    assert "claimant_principal" not in columns
    assert applied is None
    assert [row[0] for row in rows] == ["invalid", "valid"]


async def test_operation_journal_rejects_changed_request(tmp_path) -> None:
    repository = SettlementSQLiteRepository(str(tmp_path / "journal.db"))
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


def create_legacy_claim_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE settlement_claims (
          claim_ref TEXT PRIMARY KEY, state TEXT NOT NULL, deal_ref TEXT,
          obligation TEXT, fulfillment_ref TEXT, attempts INTEGER NOT NULL,
          next_attempt_unix REAL, mechanism_state TEXT, last_error TEXT,
          result TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )
        """
    )


async def test_legacy_migration_preserves_id_and_exact_state(tmp_path) -> None:
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    now = datetime.now(timezone.utc).isoformat()
    try:
        create_legacy_claim_table(conn)
        conn.execute(
            "INSERT INTO settlement_claims VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "escrow-1",
                "collected",
                json.dumps({"agreement_ref": "agreement", "obligation_index": 1}),
                json.dumps(obligation(payer="seller")),
                "fulfillment",
                2,
                None,
                json.dumps({"requested": True}),
                None,
                json.dumps({"transaction": "receipt"}),
                now,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    repository = SettlementSQLiteRepository(str(path))
    rows = await repository.list_settlement_obligations("agreement")
    assert len(rows) == 1
    assert rows[0]["obligation_index"] == 1
    assert rows[0]["mechanism_ref"] == "escrow-1"
    assert rows[0]["mechanism_state"] == {"requested": True}
    assert rows[0]["collection_state"] == "succeeded"
    conn = sqlite3.connect(path)
    try:
        ids = {row[0] for row in conn.execute("SELECT id FROM schema_migrations")}
    finally:
        conn.close()
    assert SETTLEMENT_MIGRATION_ID in ids
    assert SETTLEMENT_PRINCIPAL_MIGRATION_ID in ids
    assert settlement_migrations()[0].id == SETTLEMENT_MIGRATION_ID
    assert settlement_migrations()[-1].id == SETTLEMENT_MECHANISM_PARAMS_MIGRATION_ID


def test_legacy_conflict_rolls_back_whole_migration(tmp_path) -> None:
    path = tmp_path / "conflict.db"
    conn = sqlite3.connect(path)
    now = datetime.now(timezone.utc).isoformat()
    try:
        create_legacy_claim_table(conn)
        for ref, value in (("one", obligation()), ("two", obligation(payer="seller"))):
            conn.execute(
                "INSERT INTO settlement_claims VALUES (?, 'awaiting_conditions', ?, ?, NULL, 0, NULL, '{}', NULL, NULL, ?, ?)",
                (
                    ref,
                    json.dumps({"agreement_ref": "agreement", "obligation_index": 0}),
                    json.dumps(value),
                    now,
                    now,
                ),
            )
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(ValueError, match="conflict"):
        SettlementSQLiteRepository(str(path))
    conn = sqlite3.connect(path)
    try:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if "schema_migrations" in tables:
            assert (
                conn.execute(
                    "SELECT 1 FROM schema_migrations WHERE id=?",
                    (SETTLEMENT_MIGRATION_ID,),
                ).fetchone()
                is None
            )
    finally:
        conn.close()


async def test_hosted_materialization_params_are_immutable_and_identity_preserving(
    tmp_path,
) -> None:
    repository = SettlementSQLiteRepository(str(tmp_path / "mechanism-params.db"))
    record = SettlementObligationRecord.from_obligation(
        agreement_ref="agreement",
        obligation_index=0,
        obligation=hosted_obligation(funding_profile="card.v1"),
    )
    stored = await repository.upsert_settlement_obligation(record.model_dump())
    params = {
        "funding_profile": "card.v1",
        "funding_authorization_ref": "funding-authorization-1",
    }

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
            mechanism_params={**params, "funding_authorization_ref": "changed"},
        )

    assert bound["obligation_ref"] == retried["obligation_ref"] == stored["obligation_ref"]
    assert bound["obligation_hash"] == retried["obligation_hash"] == stored["obligation_hash"]
    assert bound["obligation"] == retried["obligation"] == stored["obligation"]
    assert bound["mechanism_params"] == retried["mechanism_params"] == params


async def test_legacy_hosted_card_migration_classifies_without_rewriting_identity(
    tmp_path,
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
            "mechanism_status": "ready",
            "materialization_state": "materialized",
            "materialization_receipt": {"historical": True},
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
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "DELETE FROM schema_migrations WHERE id=?",
            (SETTLEMENT_MECHANISM_PARAMS_MIGRATION_ID,),
        )
        conn.commit()
    finally:
        conn.close()

    migrated_repository = SettlementSQLiteRepository(str(path))
    migrated = await migrated_repository.load_settlement_obligation(
        record.obligation_ref
    )
    migrated_operation = await migrated_repository.load_settlement_operation(
        record.obligation_ref,
        "status",
    )

    assert migrated is not None
    assert migrated["mechanism_params"] == {
        "legacy_recovery": "hosted-card.v1"
    }
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
    assert settlement_migrations()[-1].id == SETTLEMENT_MECHANISM_PARAMS_MIGRATION_ID


async def test_legacy_hosted_card_migration_rolls_back_ambiguous_rows(
    tmp_path,
) -> None:
    path = tmp_path / "ambiguous-hosted-card.db"
    repository = SettlementSQLiteRepository(str(path))
    for index, value in enumerate(
        (
            hosted_obligation(payment_method_types=["card"]),
            hosted_obligation(payment_method_types=["card", "us_bank_account"]),
        )
    ):
        record = SettlementObligationRecord.from_obligation(
            agreement_ref=f"negotiation-{index}",
            obligation_index=0,
            obligation=value,
        )
        await repository.upsert_settlement_obligation(record.model_dump())
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "DELETE FROM schema_migrations WHERE id=?",
            (SETTLEMENT_MECHANISM_PARAMS_MIGRATION_ID,),
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(ValueError, match="ambiguous legacy funding"):
        SettlementSQLiteRepository(str(path))

    conn = sqlite3.connect(path)
    try:
        rows = conn.execute(
            "SELECT mechanism_params FROM settlement_obligations "
            "ORDER BY obligation_ref"
        ).fetchall()
        migration = conn.execute(
            "SELECT 1 FROM schema_migrations WHERE id=?",
            (SETTLEMENT_MECHANISM_PARAMS_MIGRATION_ID,),
        ).fetchone()
    finally:
        conn.close()
    assert rows == [("{}",), ("{}",)]
    assert migration is None
