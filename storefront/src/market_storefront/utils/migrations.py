"""Versioned schema migrations for the storefront SQLite database.

``SQLiteClient`` creates missing tables during startup, but SQLite does not
alter existing tables to match new model columns. Keep additive compatibility
changes here so persisted storefront DBs can upgrade across image versions.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Migration:
    id: str
    apply: Callable[[sqlite3.Connection], None]


def apply_schema_migrations(conn: sqlite3.Connection) -> None:
    """Apply all known migrations once, tracking completion in the database."""
    _ensure_schema_migrations_table(conn)
    applied = _applied_migration_ids(conn)

    for migration in _MIGRATIONS:
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


def _migrate_compute_allocation_callback_metadata(conn: sqlite3.Connection) -> None:
    for column in (
        "provider_id",
        "provider_job_id",
        "provider_lease_id",
        "provider_resource_id",
        "vm_host",
        "vm_target",
        "lease_end_utc",
        "failure_reason",
        "failure_message",
        "logs_ref",
        "check_job_id",
    ):
        _add_column_if_missing(conn, "compute_allocations", column, "TEXT")


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
        "20260604_001_compute_allocation_callback_metadata",
        _migrate_compute_allocation_callback_metadata,
    ),
)
