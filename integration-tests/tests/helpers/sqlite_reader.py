"""Read-only SQLite queries for e2e verification."""

from __future__ import annotations

import sqlite3
from typing import Any


_LISTING_COLUMNS = [
    "listing_id", "status", "created_at", "updated_at",
    "offer_resource", "demand_resource", "fulfillment_resource",
    "duration_hours", "seller", "buyer", "matched_offer_id",
    "seller_attestation", "buyer_attestation", "escrow_uid", "oracle_address",
]


def get_all_orders(db_path: str) -> list[dict[str, Any]]:
    """Return all listings with full column set."""
    conn = sqlite3.connect(db_path, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute(
            f"SELECT {', '.join(_LISTING_COLUMNS)} FROM listings ORDER BY updated_at DESC"
        )
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def get_latest_order(db_path: str) -> dict[str, Any] | None:
    """Return the most recently updated listing, or None."""
    orders = get_all_orders(db_path)
    return orders[0] if orders else None
