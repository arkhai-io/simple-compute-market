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


def _add_contact_delivery(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS contact_finalizations (
        obligation_ref TEXT NOT NULL, finalization_id TEXT NOT NULL,
        agreement_ref TEXT NOT NULL, status TEXT NOT NULL, code TEXT,
        expires_at INTEGER, salt BLOB, buyer_fingerprint TEXT,
        seller_fingerprint TEXT, token_digest TEXT, committed_fingerprint TEXT,
        PRIMARY KEY (obligation_ref,finalization_id))""")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS contact_one_finalization ON contact_finalizations(obligation_ref) WHERE status='committed'")
    conn.execute("""CREATE TABLE IF NOT EXISTS contact_delivery_intents (
        intent_id TEXT PRIMARY KEY, obligation_ref TEXT NOT NULL,
        recipient_role TEXT NOT NULL, policy_kind TEXT NOT NULL,
        status TEXT NOT NULL, route TEXT, attempts INTEGER NOT NULL,
        attempt_id TEXT, claim_expires_at INTEGER, next_attempt_at INTEGER,
        failure_code TEXT,
        UNIQUE(obligation_ref,recipient_role,policy_kind))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS contact_delivery_attempts (
        attempt_id TEXT PRIMARY KEY, intent_id TEXT NOT NULL,
        started_at INTEGER NOT NULL, finished_at INTEGER,
        status TEXT NOT NULL, failure_code TEXT)""")


CONTACT_EXCHANGE_MIGRATIONS = (
    SettlementMigration(
        CONTACT_EXCHANGE_INTRODUCTIONS_MIGRATION_ID,
        _add_contact_introductions,
    ),
    SettlementMigration("20260909_007_contact_delivery", _add_contact_delivery),
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
