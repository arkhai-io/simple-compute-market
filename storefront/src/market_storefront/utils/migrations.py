"""Versioned schema migrations for the storefront SQLite database.

``SQLiteClient`` creates missing tables during startup, but SQLite does not
alter existing tables to match new model columns. Keep additive compatibility
changes here so persisted storefront DBs can upgrade across image versions.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any
from collections.abc import Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)


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


def _normalize_to_dict(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None
    return None


def synthesize_accepted_escrows_from_demand(
    demand_resource: Any,
) -> list[dict[str, Any]] | None:
    """Build ``accepted_escrows`` from a legacy ERC20 ``demand_resource``."""
    from market_storefront.utils.config import CHAINS

    normalized = _normalize_to_dict(demand_resource)
    if not normalized:
        return None
    token = normalized.get("token")
    if not isinstance(token, dict):
        return None
    contract_address = token.get("contract_address")
    if not isinstance(contract_address, str) or not contract_address:
        return None

    amount = normalized.get("amount")
    if isinstance(amount, bool):
        rate_value: str | None = None
    elif isinstance(amount, int):
        rate_value = str(amount)
    elif isinstance(amount, str):
        stripped = amount.strip()
        rate_value = stripped if stripped.isdigit() else None
    else:
        rate_value = None

    from service.clients.alkahest import get_erc20_escrow_obligation_nontierable

    entries: list[dict[str, Any]] = []
    for name, chain in CHAINS.items():
        try:
            escrow_address = get_erc20_escrow_obligation_nontierable(
                name,
                config_path=chain.alkahest_address_config_path,
            )
        except Exception as exc:
            logger.debug(
                "Skipping accepted_escrows synthesis for chain %r: %s", name, exc
            )
            continue
        entries.append(
            {
                "chain_name": name,
                "escrow_address": escrow_address.lower(),
                "literal_fields": {"token": contract_address},
                "rates": [
                    {
                        "field": "amount",
                        "per": "hour",
                        "value": rate_value,
                    }
                ]
                if rate_value is not None
                else [],
            }
        )
    return entries or None


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


def _backfill_accepted_escrows(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT listing_id, demand_resource FROM listings "
        "WHERE accepted_escrows IS NULL AND demand_resource IS NOT NULL"
    ).fetchall()
    for listing_id, demand_resource in rows:
        synthesized = synthesize_accepted_escrows_from_demand(demand_resource)
        if not synthesized:
            continue
        conn.execute(
            "UPDATE listings SET accepted_escrows=? WHERE listing_id=?",
            (json.dumps(synthesized), listing_id),
        )


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
    Migration(
        "20260604_004_negotiation_amount_text_columns",
        _migrate_negotiation_amount_columns,
    ),
    Migration(
        "20260604_005_escrows_and_listings",
        _migrate_escrows_and_listings,
    ),
)
