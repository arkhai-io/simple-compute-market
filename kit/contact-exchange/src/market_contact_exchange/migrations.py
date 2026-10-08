"""Contact-exchange-owned SQLite persistence for revealed introductions.

Contact payloads are deliberate, bounded PII persistence: one row per
introduced deal, keyed by the neutral obligation ref, written exactly once at
introduction start. Deleting the payloads redacts that row in place rather
than removing it, because the row is also the only record that the
introduction was revealed: without it, a later start would reveal again. See
openspec/specs/contact-exchange-settlement/spec.md, "Deleting contact payloads
leaves a tombstone".
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from market_settlement_runtime import SettlementMigration

from .introduction_routes import IntroductionPayloadsDeletedError, IntroductionRecord

CONTACT_EXCHANGE_INTRODUCTIONS_MIGRATION_ID = "20260815_006_contact_introductions"
CONTACT_EXCHANGE_TOMBSTONES_MIGRATION_ID = (
    "20261001_007_contact_introduction_tombstones"
)

#: The text form of every timestamp in ``contact_introductions``: UTC, second
#: precision, as SQLite's ``strftime('%Y-%m-%dT%H:%M:%SZ','now')`` writes
#: ``created_at``. One fixed-width form is what lets eligibility compare
#: timestamps as strings, which an index serves.
_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

#: What a redacted row's contact columns hold. Not NULL: the columns are
#: ``NOT NULL`` and a redacted record still decodes as a mapping.
_REDACTED_CONTACT = "{}"


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


def _add_introduction_tombstones(conn: sqlite3.Connection) -> None:
    columns = {
        str(row[1]) for row in conn.execute("PRAGMA table_info(contact_introductions)")
    }
    if "payloads_deleted_at" not in columns:
        conn.execute(
            "ALTER TABLE contact_introductions ADD COLUMN payloads_deleted_at TEXT"
        )
    # A row is written once at reveal and changed at most once afterwards, by
    # the one-way redaction. Enforced here rather than by callers so that no
    # code path can restore a payload, rewrite the agreed context, or clear a
    # tombstone and let the introduction be revealed again.
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS contact_introductions_redaction_only
        BEFORE UPDATE ON contact_introductions
        WHEN NOT (
            OLD.payloads_deleted_at IS NULL
            AND NEW.payloads_deleted_at IS NOT NULL
            AND NEW.payloads_deleted_at <> ''
            AND NEW.buyer_contact = '{}'
            AND NEW.seller_contact = '{}'
            AND NEW.obligation_ref IS OLD.obligation_ref
            AND NEW.agreement_ref IS OLD.agreement_ref
            AND NEW.introduction_package IS OLD.introduction_package
            AND NEW.created_at IS OLD.created_at
        )
        BEGIN
            SELECT RAISE(
                ABORT,
                'a contact introduction changes only by one-way payload redaction'
            );
        END
        """
    )
    # Removing an unredacted row would erase both its payloads and the fact
    # that it was revealed. A tombstone may be removed: that is how its growth
    # is eventually bounded, once its deal can no longer be revealed again.
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS contact_introductions_keep_unredacted
        BEFORE DELETE ON contact_introductions
        WHEN OLD.payloads_deleted_at IS NULL
        BEGIN
            SELECT RAISE(
                ABORT,
                'an unredacted contact introduction cannot be removed'
            );
        END
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS contact_introductions_retention "
        "ON contact_introductions (created_at) WHERE payloads_deleted_at IS NULL"
    )


CONTACT_EXCHANGE_MIGRATIONS = (
    SettlementMigration(
        CONTACT_EXCHANGE_INTRODUCTIONS_MIGRATION_ID,
        _add_contact_introductions,
    ),
    SettlementMigration(
        CONTACT_EXCHANGE_TOMBSTONES_MIGRATION_ID,
        _add_introduction_tombstones,
    ),
)


def format_introduction_timestamp(value: datetime) -> str:
    """Render a timezone-aware instant in the table's own timestamp text form."""

    if value.tzinfo is None:
        raise ValueError("introduction timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).strftime(_TIMESTAMP_FORMAT)


def insert_introduction(
    conn: sqlite3.Connection,
    record: IntroductionRecord,
) -> IntroductionRecord:
    """Persist one introduction exactly once; identical re-inserts are idempotent.

    A redacted introduction is never persisted over: its payloads were deleted,
    and storing a fresh pair would reveal it again.
    """

    existing = load_introduction(conn, record.obligation_ref)
    if existing is not None:
        if existing.payloads_deleted_at is not None:
            raise IntroductionPayloadsDeletedError(existing.payloads_deleted_at)
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
    """Load one introduction; a redacted one carries empty contacts."""

    row = conn.execute(
        "SELECT obligation_ref, agreement_ref, buyer_contact, seller_contact, "
        "introduction_package, payloads_deleted_at "
        "FROM contact_introductions WHERE obligation_ref=?",
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
        payloads_deleted_at=row[5],
    )


def delete_introduction_payloads(
    conn: sqlite3.Connection,
    obligation_ref: str,
    *,
    deleted_at: datetime,
) -> bool:
    """Redact one introduction's contact payloads in place, once.

    Both payloads empty and the tombstone time set in one statement, so a
    concurrent reader sees the whole introduction or the tombstone and never a
    record with one payload gone. Returns ``True`` when this call redacted, and
    ``False`` for an already-redacted introduction or a deal that never started
    one, so a retried deletion converges rather than failing.
    """

    cursor = conn.execute(
        "UPDATE contact_introductions "
        "SET payloads_deleted_at=?, buyer_contact=?, seller_contact=? "
        "WHERE obligation_ref=? AND payloads_deleted_at IS NULL",
        (
            format_introduction_timestamp(deleted_at),
            _REDACTED_CONTACT,
            _REDACTED_CONTACT,
            obligation_ref,
        ),
    )
    return cursor.rowcount > 0


def select_expired_introductions(
    conn: sqlite3.Connection,
    *,
    cutoff: datetime,
    limit: int,
) -> list[str]:
    """Obligation refs of unredacted introductions revealed at or before ``cutoff``.

    ``created_at`` is set at first persist, which is the reveal, so an
    introduction revealed at ``cutoff`` or earlier has reached a window of
    ``now - cutoff``. Oldest first, so a bounded sweep drains the backlog in
    reveal order.
    """

    if limit <= 0:
        raise ValueError("an expired-introduction query requires a positive limit")
    rows = conn.execute(
        "SELECT obligation_ref FROM contact_introductions "
        "WHERE payloads_deleted_at IS NULL AND created_at <= ? "
        "ORDER BY created_at, obligation_ref LIMIT ?",
        (format_introduction_timestamp(cutoff), int(limit)),
    ).fetchall()
    return [str(row[0]) for row in rows]


__all__ = [
    "CONTACT_EXCHANGE_INTRODUCTIONS_MIGRATION_ID",
    "CONTACT_EXCHANGE_MIGRATIONS",
    "CONTACT_EXCHANGE_TOMBSTONES_MIGRATION_ID",
    "delete_introduction_payloads",
    "format_introduction_timestamp",
    "insert_introduction",
    "load_introduction",
    "select_expired_introductions",
]
