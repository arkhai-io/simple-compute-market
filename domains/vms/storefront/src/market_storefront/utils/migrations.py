"""VM-domain schema migrations and legacy demand synthesis.

The migration engine plus the domain-neutral market-state migrations
live in ``core_storefront.sqlite_migrations``; this module keeps the
compute-flavored ones (pools, allocations, derived listings) and the
config-coupled ``accepted_escrows`` synthesizer, which it registers
with core so the shared escrows/listings migration can backfill
legacy ``demand_resource`` rows.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any

from core_storefront.sqlite_migrations import (  # noqa: F401 — re-exported
    Migration,
    _add_column_if_missing,
    _column_exists,
    _table_exists,
    apply_schema_migrations,
    set_accepted_escrows_synthesizer,
)

logger = logging.getLogger(__name__)


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

    from market_alkahest.alkahest import get_erc20_escrow_obligation_nontierable

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


# The shared escrows/listings migration backfills legacy rows through
# this hook; registration happens at import (the SQLite client module
# imports this one before any client is constructed).
set_accepted_escrows_synthesizer(synthesize_accepted_escrows_from_demand)


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


def _migrate_pool_member_sites(conn: sqlite3.Connection) -> None:
    """Pool members reference ``(site, resource_id)`` — the aggregator key.

    NULL means "the storefront's home site", so embedded deployments and
    pre-aggregation databases need no config-coupled backfill; only
    members of resources hosted at *other* sites carry a name.
    """
    _add_column_if_missing(conn, "compute_pool_members", "site", "TEXT")


def _migrate_allocation_hold_expiry(conn: sqlite3.Connection) -> None:
    """Two-phase reserve: TTL soft holds on the embedded ledger.

    A reserved allocation with ``hold_expires_at`` in the past lapses
    back to available (swept lazily ahead of reads and reserves) —
    mirroring the site ledger's semantics.
    """
    _add_column_if_missing(conn, "compute_allocations", "hold_expires_at", "TEXT")


VM_MIGRATIONS: tuple[Migration, ...] = (
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
        "20260611_006_pool_member_sites",
        _migrate_pool_member_sites,
    ),
    Migration(
        "20260611_007_allocation_hold_expiry",
        _migrate_allocation_hold_expiry,
    ),
)
