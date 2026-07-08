"""Bare-metal publication planning for storefront capacity snapshots."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from arkhai_bare_metal import (
    BareMetalListing,
    available_bare_metal_listings,
    bare_metal_listing_key,
)


def ensure_derived_bare_metal_listings_table(conn: sqlite3.Connection) -> None:
    """Create the storefront-local table tracking derived bare-metal listings."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS derived_bare_metal_listings (
          listing_id TEXT PRIMARY KEY,
          machine_id TEXT NOT NULL,
          physical_host_id TEXT NOT NULL,
          status TEXT NOT NULL,
          derivation_key TEXT NOT NULL UNIQUE,
          last_reconciled_at TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_derived_bare_metal_listings_machine "
        "ON derived_bare_metal_listings(machine_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_derived_bare_metal_listings_status "
        "ON derived_bare_metal_listings(status)"
    )


def bare_metal_listing_candidates(
    resources: list[dict[str, Any]],
    *,
    min_duration_seconds: int | None = None,
    max_duration_seconds: int | None = None,
    site: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Return publishable bare-metal listing candidates from snapshot rows."""
    return [
        {
            "derivation_key": bare_metal_listing_key(listing.machine_id),
            "machine_id": listing.machine_id,
            "physical_host_id": listing.physical_host_id,
            "offer_resource": listing.model_dump(exclude_none=True),
            "listing": listing,
        }
        for listing in available_bare_metal_listings(
            resources,
            min_duration_seconds=min_duration_seconds,
            max_duration_seconds=max_duration_seconds,
            site=site,
        )
    ]


def open_bare_metal_listing_keys(db_path: str) -> set[str]:
    """Return derivation keys already covered by open bare-metal listings."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro&nolock=1", uri=True, timeout=5)
    try:
        rows = conn.execute(
            "SELECT offer_resource FROM listings WHERE status = 'open'",
        ).fetchall()
    finally:
        conn.close()
    keys: set[str] = set()
    for (raw,) in rows:
        listing = _parse_bare_metal_offer(raw)
        if listing is not None:
            keys.add(bare_metal_listing_key(listing.machine_id))
    return keys


def stale_open_bare_metal_listing_ids(
    db_path: str,
    resources: list[dict[str, Any]],
) -> list[str]:
    """Open bare-metal listing IDs whose machine is no longer available."""
    available_keys = {
        candidate["derivation_key"]
        for candidate in bare_metal_listing_candidates(resources)
    }
    conn = sqlite3.connect(f"file:{db_path}?mode=ro&nolock=1", uri=True, timeout=5)
    try:
        rows = conn.execute(
            "SELECT listing_id, offer_resource FROM listings WHERE status = 'open'",
        ).fetchall()
    finally:
        conn.close()
    stale: list[str] = []
    for listing_id, raw in rows:
        listing = _parse_bare_metal_offer(raw)
        if listing is None:
            continue
        if bare_metal_listing_key(listing.machine_id) not in available_keys:
            stale.append(str(listing_id))
    return stale


def closed_available_bare_metal_listing_ids(
    db_path: str,
    resources: list[dict[str, Any]],
) -> list[str]:
    """Closed derived bare-metal listings whose machine is available again."""
    available_keys = {
        candidate["derivation_key"]
        for candidate in bare_metal_listing_candidates(resources)
    }
    if not available_keys:
        return []
    conn = sqlite3.connect(f"file:{db_path}?mode=ro&nolock=1", uri=True, timeout=5)
    try:
        if not _table_exists(conn, "derived_bare_metal_listings"):
            return []
        placeholders = ", ".join("?" for _ in available_keys)
        rows = conn.execute(
            f"""
            SELECT d.listing_id
            FROM derived_bare_metal_listings d
            LEFT JOIN listings l ON l.listing_id = d.listing_id
            WHERE d.derivation_key IN ({placeholders})
              AND (d.status != 'open' OR l.status != 'open')
            ORDER BY d.machine_id
            """,
            tuple(sorted(available_keys)),
        ).fetchall()
    finally:
        conn.close()
    return [str(row[0]) for row in rows]


def load_derived_bare_metal_listing(
    db_path: str,
    *,
    machine_id: str,
) -> dict[str, Any] | None:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro&nolock=1", uri=True, timeout=5)
    try:
        if not _table_exists(conn, "derived_bare_metal_listings"):
            return None
        row = conn.execute(
            """
            SELECT d.listing_id, d.machine_id, d.physical_host_id, d.status,
                   d.derivation_key, l.status AS listing_status
            FROM derived_bare_metal_listings d
            LEFT JOIN listings l ON l.listing_id = d.listing_id
            WHERE d.derivation_key = ?
            LIMIT 1
            """,
            (bare_metal_listing_key(machine_id),),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    keys = [
        "listing_id",
        "machine_id",
        "physical_host_id",
        "status",
        "derivation_key",
        "listing_status",
    ]
    return dict(zip(keys, row))


def record_derived_bare_metal_listing(
    db_path: str,
    *,
    listing_id: str,
    listing: BareMetalListing,
    status: str = "open",
) -> None:
    conn = sqlite3.connect(db_path)
    try:
        ensure_derived_bare_metal_listings_table(conn)
        conn.execute(
            """
            INSERT INTO derived_bare_metal_listings(
              listing_id, machine_id, physical_host_id, status, derivation_key,
              last_reconciled_at
            )
            VALUES (?, ?, ?, ?, ?, STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now'))
            ON CONFLICT(derivation_key) DO UPDATE SET
              listing_id=excluded.listing_id,
              machine_id=excluded.machine_id,
              physical_host_id=excluded.physical_host_id,
              status=excluded.status,
              last_reconciled_at=excluded.last_reconciled_at
            """,
            (
                listing_id,
                listing.machine_id,
                listing.physical_host_id,
                status,
                bare_metal_listing_key(listing.machine_id),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def mark_derived_bare_metal_listings_closed(
    db_path: str,
    listing_ids: list[str],
) -> None:
    if not listing_ids:
        return
    conn = sqlite3.connect(db_path)
    try:
        ensure_derived_bare_metal_listings_table(conn)
        placeholders = ", ".join("?" for _ in listing_ids)
        conn.execute(
            f"""
            UPDATE derived_bare_metal_listings
            SET status = 'closed',
                last_reconciled_at = STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE listing_id IN ({placeholders})
            """,
            tuple(listing_ids),
        )
        conn.commit()
    finally:
        conn.close()


def _parse_bare_metal_offer(raw: str | bytes | None) -> BareMetalListing | None:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, dict):
        return None
    if parsed.get("kind") != "bare_metal.v1":
        return None
    try:
        return BareMetalListing.model_validate(parsed)
    except Exception:
        return None


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None
