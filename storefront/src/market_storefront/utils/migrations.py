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
    _add_column_if_missing(conn, "compute_allocations", "pool_id", "TEXT")
    _add_column_if_missing(conn, "compute_allocations", "member_id", "TEXT")
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


def _migrate_compute_inventory_pools(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS compute_inventory_pools (
          pool_id TEXT PRIMARY KEY,
          seller_id TEXT,
          resource_type TEXT NOT NULL DEFAULT 'compute.gpu',
          gpu_model TEXT,
          region TEXT,
          sla NUMERIC,
          total_gpu_count INTEGER NOT NULL DEFAULT 0,
          status TEXT NOT NULL DEFAULT 'active',
          pricing_policy_id TEXT,
          escrow_policy_id TEXT,
          allocation_policy TEXT NOT NULL DEFAULT 'first_fit',
          min_price TEXT,
          token TEXT,
          max_duration_seconds INTEGER,
          accepted_escrows TEXT,
          created_at TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')),
          updated_at TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS compute_pool_members (
          member_id TEXT PRIMARY KEY,
          pool_id TEXT NOT NULL,
          resource_id TEXT NOT NULL UNIQUE,
          provider_id TEXT,
          provider_resource_id TEXT,
          provider_host_id TEXT,
          gpu_count INTEGER NOT NULL,
          status TEXT NOT NULL DEFAULT 'active',
          attributes TEXT,
          created_at TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')),
          updated_at TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')),
          FOREIGN KEY(pool_id) REFERENCES compute_inventory_pools(pool_id)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_compute_pool_members_pool "
        "ON compute_pool_members(pool_id, status)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_compute_allocations_pool_state "
        "ON compute_allocations(pool_id, state)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_compute_allocations_member_state "
        "ON compute_allocations(member_id, state)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_derived_compute_listings_pool "
        "ON derived_compute_listings(pool_id, gpu_count)"
    )
    _backfill_compute_pools(conn)


def _migrate_derived_compute_listing_pool_ids(conn: sqlite3.Connection) -> None:
    _add_column_if_missing(conn, "derived_compute_listings", "pool_id", "TEXT")
    if _table_exists(conn, "derived_compute_listings"):
        conn.execute(
            """
            UPDATE derived_compute_listings
            SET pool_id = COALESCE(
              pool_id,
              (
                SELECT pool_id
                FROM compute_pool_members
                WHERE compute_pool_members.resource_id = derived_compute_listings.resource_id
              ),
              resource_id
            )
            WHERE pool_id IS NULL
            """
        )


def _resource_attrs(raw: object) -> dict[str, object]:
    if not isinstance(raw, str) or not raw.strip():
        return {}
    import json

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _backfill_compute_pools(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, "resources"):
        return
    cols = {row[1] for row in conn.execute("PRAGMA table_info(resources)").fetchall()}
    if not {"resource_id", "resource_type", "value", "attributes"} <= cols:
        return
    rows = conn.execute(
        """
        SELECT resource_id, resource_subtype, value, state, attributes,
               min_price, token, max_duration_seconds, accepted_escrows,
               created_at, updated_at
        FROM resources
        WHERE resource_type = 'compute.gpu'
          AND (state IS NULL OR state != 'deleted')
        """
    ).fetchall()
    grouped: dict[str, list[tuple[object, ...]]] = {}
    for row in rows:
        attrs = _resource_attrs(row[4])
        pool_id = str(attrs.get("pool_id") or row[0])
        grouped.setdefault(pool_id, []).append(row)

    for pool_id, pool_rows in grouped.items():
        first = pool_rows[0]
        attrs = _resource_attrs(first[4])
        total = 0
        for row in pool_rows:
            row_attrs = _resource_attrs(row[4])
            try:
                gpu_count = int(row[2] if row[2] is not None else row_attrs.get("gpu_count", 1))
            except (TypeError, ValueError):
                gpu_count = 0
            total += max(gpu_count, 0)
            conn.execute(
                """
                INSERT INTO compute_pool_members(
                  member_id, pool_id, resource_id, provider_id, provider_resource_id,
                  provider_host_id, gpu_count, status, attributes, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, COALESCE(?, STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')), COALESCE(?, STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')))
                ON CONFLICT(resource_id) DO UPDATE SET
                  pool_id=excluded.pool_id,
                  provider_id=excluded.provider_id,
                  provider_resource_id=excluded.provider_resource_id,
                  provider_host_id=excluded.provider_host_id,
                  gpu_count=excluded.gpu_count,
                  status=excluded.status,
                  attributes=excluded.attributes,
                  updated_at=excluded.updated_at
                """,
                (
                    f"resource:{row[0]}",
                    pool_id,
                    row[0],
                    row_attrs.get("provider_id"),
                    row_attrs.get("provider_resource_id") or row[0],
                    row_attrs.get("vm_host"),
                    max(gpu_count, 0),
                    row[4],
                    row[9],
                    row[10],
                ),
            )
        conn.execute(
            """
            INSERT INTO compute_inventory_pools(
              pool_id, resource_type, gpu_model, region, sla, total_gpu_count,
              status, allocation_policy, min_price, token, max_duration_seconds,
              accepted_escrows, created_at, updated_at
            )
            VALUES (?, 'compute.gpu', ?, ?, ?, ?, 'active', 'first_fit', ?, ?, ?, ?,
                    COALESCE(?, STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')),
                    COALESCE(?, STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')))
            ON CONFLICT(pool_id) DO UPDATE SET
              gpu_model=excluded.gpu_model,
              region=excluded.region,
              sla=excluded.sla,
              total_gpu_count=excluded.total_gpu_count,
              status=excluded.status,
              min_price=excluded.min_price,
              token=excluded.token,
              max_duration_seconds=excluded.max_duration_seconds,
              accepted_escrows=excluded.accepted_escrows,
              updated_at=excluded.updated_at
            """,
            (
                pool_id,
                attrs.get("gpu_model") or first[1],
                attrs.get("region"),
                attrs.get("sla"),
                total,
                first[5],
                first[6],
                first[7],
                first[8],
                first[9],
                first[10],
            ),
        )
    if _table_exists(conn, "compute_allocations"):
        conn.execute(
            """
            UPDATE compute_allocations
            SET pool_id = COALESCE(
                  pool_id,
                  (
                    SELECT pool_id
                    FROM compute_pool_members
                    WHERE compute_pool_members.resource_id = compute_allocations.resource_id
                  )
                ),
                member_id = COALESCE(
                  member_id,
                  (
                    SELECT member_id
                    FROM compute_pool_members
                    WHERE compute_pool_members.resource_id = compute_allocations.resource_id
                  )
                )
            WHERE pool_id IS NULL OR member_id IS NULL
            """
        )


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
    Migration(
        "20260604_002_compute_inventory_pools",
        _migrate_compute_inventory_pools,
    ),
    Migration(
        "20260604_003_derived_compute_listing_pool_ids",
        _migrate_derived_compute_listing_pool_ids,
    ),
)
