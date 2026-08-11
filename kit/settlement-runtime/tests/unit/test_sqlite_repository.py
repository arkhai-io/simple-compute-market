from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

import pytest

from market_settlement_runtime import (
    SETTLEMENT_MIGRATION_ID,
    SettlementObligationRecord,
    SettlementOperationRecord,
    SettlementSQLiteRepository,
    settlement_migrations,
)


def obligation(*, payer: str = "buyer") -> dict:
    return {
        "payer": payer,
        "claimant": "seller" if payer == "buyer" else "buyer",
        "mechanism": "test.v1",
        "expiration_unix": 100,
    }


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
    assert settlement_migrations()[0].id == SETTLEMENT_MIGRATION_ID


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
