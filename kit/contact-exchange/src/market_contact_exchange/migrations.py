"""Contact-exchange-owned SQLite persistence for revealed introductions.

Contact payloads are deliberate, bounded PII persistence: one row per
introduced deal, keyed by the neutral obligation ref, written exactly once at
introduction start and deleted as part of the deal lifecycle.
"""

from __future__ import annotations

import json
import sqlite3

from market_settlement_runtime import SettlementMigration

from .introduction_routes import IntroductionRecord

CONTACT_EXCHANGE_INTRODUCTIONS_MIGRATION_ID = "20260815_006_contact_introductions"


def _add_contact_introductions(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS contact_introductions (
            obligation_ref TEXT PRIMARY KEY,
            agreement_ref TEXT NOT NULL,
            buyer_contact TEXT NOT NULL,
            seller_contact TEXT NOT NULL,
            introduction_package TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
        )
        """
    )


CONTACT_EXCHANGE_MIGRATIONS = (
    SettlementMigration(
        CONTACT_EXCHANGE_INTRODUCTIONS_MIGRATION_ID,
        _add_contact_introductions,
    ),
)


def insert_introduction(
    conn: sqlite3.Connection,
    record: IntroductionRecord,
) -> IntroductionRecord:
    """Persist one introduction exactly once; identical re-inserts are idempotent."""

    existing = load_introduction(conn, record.obligation_ref)
    if existing is not None:
        if existing != record:
            raise ValueError(
                "introduction already revealed with different contact payloads"
            )
        return existing
    conn.execute(
        "INSERT INTO contact_introductions "
        "(obligation_ref, agreement_ref, buyer_contact, seller_contact, "
        "introduction_package) VALUES (?, ?, ?, ?, ?)",
        (
            record.obligation_ref,
            record.agreement_ref,
            json.dumps(record.buyer_contact, sort_keys=True),
            json.dumps(record.seller_contact, sort_keys=True),
            json.dumps(record.introduction_package, sort_keys=True),
        ),
    )
    return record


def load_introduction(
    conn: sqlite3.Connection,
    obligation_ref: str,
) -> IntroductionRecord | None:
    row = conn.execute(
        "SELECT obligation_ref, agreement_ref, buyer_contact, seller_contact, "
        "introduction_package FROM contact_introductions WHERE obligation_ref=?",
        (obligation_ref,),
    ).fetchone()
    if row is None:
        return None
    return IntroductionRecord(
        obligation_ref=row[0],
        agreement_ref=row[1],
        buyer_contact=json.loads(row[2]),
        seller_contact=json.loads(row[3]),
        introduction_package=json.loads(row[4]),
    )


def delete_introduction(conn: sqlite3.Connection, obligation_ref: str) -> bool:
    """Remove one introduction's contact payloads as part of deal teardown."""

    cursor = conn.execute(
        "DELETE FROM contact_introductions WHERE obligation_ref=?",
        (obligation_ref,),
    )
    return cursor.rowcount > 0


__all__ = [
    "CONTACT_EXCHANGE_INTRODUCTIONS_MIGRATION_ID",
    "CONTACT_EXCHANGE_MIGRATIONS",
    "delete_introduction",
    "insert_introduction",
    "load_introduction",
]
