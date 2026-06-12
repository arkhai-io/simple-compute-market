"""Versioned schema migrations for the storefront market-state database.

``SQLiteClient`` creates missing tables during startup, but SQLite does not
alter existing tables to match new model columns. Keep additive compatibility
changes here so persisted storefront DBs can upgrade across image versions.

This module owns the migration engine plus the domain-neutral migrations
(negotiation/escrow/listing tables). Domain composition roots keep their
own inventory migrations and pass them through
``SQLiteClient._domain_migrations``.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any
from collections.abc import Callable, Sequence
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Migration:
    id: str
    apply: Callable[[sqlite3.Connection], None]


def apply_schema_migrations(
    conn: sqlite3.Connection,
    extra_migrations: Sequence[Migration] = (),
) -> None:
    """Apply all known migrations once, tracking completion in the database.

    ``extra_migrations`` carries the domain composition root's own
    migrations; they run after the core set, keyed by the same
    once-per-id tracking table.
    """
    _ensure_schema_migrations_table(conn)
    applied = _applied_migration_ids(conn)

    for migration in (*_MIGRATIONS, *extra_migrations):
        if migration.id in applied:
            continue
        migration.apply(conn)
        _record_migration(conn, migration.id)


def _ensure_schema_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
          id TEXT PRIMARY KEY,
          applied_at TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )
        """
    )


def _applied_migration_ids(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT id FROM schema_migrations").fetchall()
    return {str(row[0]) for row in rows}


def _record_migration(conn: sqlite3.Connection, migration_id: str) -> None:
    conn.execute(
        "INSERT INTO schema_migrations (id) VALUES (?)",
        (migration_id,),
    )


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def _column_exists(conn: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    if not _table_exists(conn, table_name):
        return False
    return column_name in {
        str(row[1]) for row in conn.execute(f"PRAGMA table_info({table_name})")
    }


def _add_column_if_missing(
    conn: sqlite3.Connection,
    table_name: str,
    column_name: str,
    column_sql: str,
) -> None:
    if not _table_exists(conn, table_name) or _column_exists(
        conn, table_name, column_name
    ):
        return
    conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}")



# ---------------------------------------------------------------------------
# Legacy accepted_escrows backfill — synthesis is domain vocabulary.
# ---------------------------------------------------------------------------

_accepted_escrows_synthesizer: Callable[[Any], list[dict[str, Any]] | None] | None = None


def set_accepted_escrows_synthesizer(
    fn: Callable[[Any], list[dict[str, Any]] | None],
) -> None:
    """Install the domain's legacy ``demand_resource`` → ``accepted_escrows``
    converter.

    The escrows/listings migration backfills pre-cutover listing rows
    through this hook; with none installed (a composition root that never
    had legacy rows) the backfill is skipped.
    """
    global _accepted_escrows_synthesizer
    _accepted_escrows_synthesizer = fn


def _backfill_accepted_escrows(conn: sqlite3.Connection) -> None:
    if _accepted_escrows_synthesizer is None:
        return
    rows = conn.execute(
        "SELECT listing_id, demand_resource FROM listings "
        "WHERE accepted_escrows IS NULL AND demand_resource IS NOT NULL"
    ).fetchall()
    for listing_id, demand_resource in rows:
        synthesized = _accepted_escrows_synthesizer(demand_resource)
        if not synthesized:
            continue
        conn.execute(
            "UPDATE listings SET accepted_escrows=? WHERE listing_id=?",
            (json.dumps(synthesized), listing_id),
        )


def _column_types(conn: sqlite3.Connection, table_name: str) -> dict[str, str]:
    return {
        str(row[1]): str(row[2] or "").upper()
        for row in conn.execute(f"PRAGMA table_info({table_name})")
    }


def _needs_rebuild(
    conn: sqlite3.Connection,
    table_name: str,
    columns: tuple[str, ...],
) -> bool:
    if not _table_exists(conn, table_name):
        return False
    types = _column_types(conn, table_name)
    return any(types.get(column) != "TEXT" for column in columns)


def _migrate_negotiation_amount_columns(conn: sqlite3.Connection) -> None:
    """Move EVM amount columns off SQLite INTEGER affinity."""
    if _table_exists(conn, "negotiation_threads"):
        for column_name, column_sql in (
            ("buyer", "TEXT"),
            ("matched_offer_id", "TEXT"),
        ):
            _add_column_if_missing(
                conn, "negotiation_threads", column_name, column_sql
            )

    if _needs_rebuild(conn, "negotiation_threads", ("agreed_price",)):
        conn.execute("DROP TABLE IF EXISTS negotiation_threads__amount_migration")
        conn.execute(
            "ALTER TABLE negotiation_threads RENAME TO negotiation_threads__amount_migration"
        )
        conn.execute(
            """
            CREATE TABLE negotiation_threads (
              negotiation_id TEXT PRIMARY KEY,
              our_listing_id TEXT,
              their_listing_id TEXT,
              our_agent_id TEXT,
              their_agent_id TEXT,
              status TEXT DEFAULT 'active',
              created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
              updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
              terminal_state TEXT,
              requested_duration_seconds INTEGER,
              buyer_escrow_proposal TEXT,
              agreed_price TEXT,
              agreed_duration_seconds INTEGER,
              agreed_at TEXT,
              buyer TEXT,
              matched_offer_id TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO negotiation_threads (
                negotiation_id, our_listing_id, their_listing_id,
                our_agent_id, their_agent_id, status, created_at,
                updated_at, terminal_state, requested_duration_seconds,
                buyer_escrow_proposal, agreed_price,
                agreed_duration_seconds, agreed_at, buyer, matched_offer_id
            )
            SELECT negotiation_id, our_listing_id, their_listing_id,
                   our_agent_id, their_agent_id, status, created_at,
                   updated_at, terminal_state, requested_duration_seconds,
                   buyer_escrow_proposal,
                   CASE WHEN agreed_price IS NULL THEN NULL ELSE CAST(agreed_price AS TEXT) END,
                   agreed_duration_seconds, agreed_at, buyer, matched_offer_id
            FROM negotiation_threads__amount_migration
            """
        )
        conn.execute("DROP TABLE negotiation_threads__amount_migration")

    if _needs_rebuild(conn, "negotiation_local_state", ("our_initial_price",)):
        conn.execute("DROP TABLE IF EXISTS negotiation_local_state__amount_migration")
        conn.execute(
            "ALTER TABLE negotiation_local_state RENAME TO negotiation_local_state__amount_migration"
        )
        conn.execute(
            """
            CREATE TABLE negotiation_local_state (
              negotiation_id TEXT NOT NULL,
              owner_id TEXT NOT NULL,
              our_initial_price TEXT,
              our_strategy TEXT,
              PRIMARY KEY(negotiation_id, owner_id),
              FOREIGN KEY(negotiation_id) REFERENCES negotiation_threads(negotiation_id)
            )
            """
        )
        conn.execute(
            """
            INSERT INTO negotiation_local_state (
                negotiation_id, owner_id, our_initial_price, our_strategy
            )
            SELECT negotiation_id, owner_id,
                   CASE WHEN our_initial_price IS NULL THEN NULL ELSE CAST(our_initial_price AS TEXT) END,
                   our_strategy
            FROM negotiation_local_state__amount_migration
            """
        )
        conn.execute("DROP TABLE negotiation_local_state__amount_migration")

    if _needs_rebuild(
        conn,
        "negotiation_messages",
        ("our_price", "their_price", "proposed_price"),
    ):
        conn.execute("DROP TABLE IF EXISTS negotiation_messages__amount_migration")
        conn.execute(
            "ALTER TABLE negotiation_messages RENAME TO negotiation_messages__amount_migration"
        )
        conn.execute(
            """
            CREATE TABLE negotiation_messages (
              message_id INTEGER PRIMARY KEY AUTOINCREMENT,
              negotiation_id TEXT NOT NULL,
              round INTEGER NOT NULL,
              sender TEXT NOT NULL,
              our_price TEXT,
              their_price TEXT,
              proposed_price TEXT,
              action_taken TEXT NOT NULL,
              message_type TEXT NOT NULL,
              timestamp TEXT NOT NULL,
              FOREIGN KEY(negotiation_id) REFERENCES negotiation_threads(negotiation_id),
              UNIQUE(negotiation_id, round)
            )
            """
        )
        conn.execute(
            """
            INSERT INTO negotiation_messages (
                message_id, negotiation_id, round, sender,
                our_price, their_price, proposed_price,
                action_taken, message_type, timestamp
            )
            SELECT message_id, negotiation_id, round, sender,
                   CASE WHEN our_price IS NULL THEN NULL ELSE CAST(our_price AS TEXT) END,
                   CASE WHEN their_price IS NULL THEN NULL ELSE CAST(their_price AS TEXT) END,
                   CASE WHEN proposed_price IS NULL THEN NULL ELSE CAST(proposed_price AS TEXT) END,
                   action_taken, message_type, timestamp
            FROM negotiation_messages__amount_migration
            """
        )
        conn.execute("DROP TABLE negotiation_messages__amount_migration")


def _cols(conn: sqlite3.Connection, table_name: str) -> set[str]:
    if not _table_exists(conn, table_name):
        return set()
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table_name})")}


def _drop_column_if_exists(
    conn: sqlite3.Connection,
    table_name: str,
    column_name: str,
) -> None:
    if not _column_exists(conn, table_name, column_name):
        return
    try:
        conn.execute(f"ALTER TABLE {table_name} DROP COLUMN {column_name}")
    except sqlite3.OperationalError:
        pass


def _migrate_escrows_and_listings(conn: sqlite3.Connection) -> None:
    """Migrate legacy settlement/listing columns to escrows/thread tables."""
    if _table_exists(conn, "settlement_jobs") and not _table_exists(conn, "escrows"):
        conn.execute("ALTER TABLE settlement_jobs RENAME TO escrows")
        for old_idx in ("idx_settlement_jobs_status", "idx_settlement_jobs_negotiation"):
            conn.execute(f"DROP INDEX IF EXISTS {old_idx}")

    if _table_exists(conn, "escrows"):
        for column_name, column_sql in (
            ("chain_name", "TEXT"),
            ("escrow_address", "TEXT"),
            ("is_primary", "INTEGER NOT NULL DEFAULT 1"),
            ("fulfillment_uid", "TEXT"),
        ):
            _add_column_if_missing(conn, "escrows", column_name, column_sql)

    if _table_exists(conn, "negotiation_threads"):
        for column_name, column_sql in (
            ("buyer", "TEXT"),
            ("matched_offer_id", "TEXT"),
        ):
            _add_column_if_missing(
                conn, "negotiation_threads", column_name, column_sql
            )

    if _table_exists(conn, "listings"):
        for column_name, column_sql in (
            ("accepted_escrows", "TEXT"),
            ("demands", "TEXT"),
        ):
            _add_column_if_missing(conn, "listings", column_name, column_sql)
        if _column_exists(conn, "listings", "demand_resource"):
            _backfill_accepted_escrows(conn)

    listing_cols = _cols(conn, "listings")
    escrow_cols = _cols(conn, "escrows")

    if "attestation_uid" in escrow_cols:
        conn.execute(
            "UPDATE escrows SET fulfillment_uid = attestation_uid "
            "WHERE fulfillment_uid IS NULL AND attestation_uid IS NOT NULL"
        )

    if (
        "accepted_escrows" in listing_cols
        and _table_exists(conn, "escrows")
        and _table_exists(conn, "negotiation_threads")
    ):
        rows = conn.execute(
            """
            SELECT escrows.escrow_uid, l.accepted_escrows
            FROM escrows
            JOIN negotiation_threads nt
              ON nt.negotiation_id = escrows.negotiation_id
            JOIN listings l
              ON l.listing_id = nt.our_listing_id
            WHERE escrows.chain_name IS NULL OR escrows.escrow_address IS NULL
            """
        ).fetchall()
        for escrow_uid, ae_blob in rows:
            if not ae_blob:
                continue
            try:
                ae_list = json.loads(ae_blob) if isinstance(ae_blob, str) else ae_blob
            except (ValueError, TypeError):
                continue
            if not isinstance(ae_list, list) or not ae_list:
                continue
            first = ae_list[0]
            if not isinstance(first, dict):
                continue
            conn.execute(
                "UPDATE escrows SET chain_name = ?, escrow_address = ? "
                "WHERE escrow_uid = ?",
                (first.get("chain_name"), first.get("escrow_address"), escrow_uid),
            )

    if "buyer" in listing_cols and _table_exists(conn, "negotiation_threads"):
        conn.execute(
            """
            UPDATE negotiation_threads
            SET buyer = (
                SELECT l.buyer FROM listings l
                WHERE l.listing_id = negotiation_threads.our_listing_id
                LIMIT 1
            )
            WHERE buyer IS NULL
            """
        )
    if "matched_offer_id" in listing_cols and _table_exists(
        conn, "negotiation_threads"
    ):
        conn.execute(
            """
            UPDATE negotiation_threads
            SET matched_offer_id = (
                SELECT l.matched_offer_id FROM listings l
                WHERE l.listing_id = negotiation_threads.our_listing_id
                LIMIT 1
            )
            WHERE matched_offer_id IS NULL
            """
        )

    for table_name, column_name in (
        ("escrows", "attestation_uid"),
        ("listings", "demand_resource"),
        ("listings", "escrow_uid"),
        ("listings", "buyer_attestation"),
        ("listings", "seller_attestation"),
        ("listings", "buyer"),
        ("listings", "matched_offer_id"),
    ):
        _drop_column_if_exists(conn, table_name, column_name)


def _migrate_listing_resource_timestamps(conn: sqlite3.Connection) -> None:
    for table_name in ("listings", "resources"):
        _add_column_if_missing(conn, table_name, "created_at", "TEXT")
        _add_column_if_missing(conn, table_name, "updated_at", "TEXT")
        if _table_exists(conn, table_name):
            conn.execute(
                f"""
                UPDATE {table_name}
                SET created_at = COALESCE(
                      created_at,
                      STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')
                    ),
                    updated_at = COALESCE(
                      updated_at,
                      STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')
                    )
                """
            )


_MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        "20260604_000_listing_resource_timestamps",
        _migrate_listing_resource_timestamps,
    ),
    Migration(
        "20260604_004_negotiation_amount_text_columns",
        _migrate_negotiation_amount_columns,
    ),
    Migration(
        "20260604_005_escrows_and_listings",
        _migrate_escrows_and_listings,
    ),
)
