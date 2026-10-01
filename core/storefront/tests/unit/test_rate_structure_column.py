"""The generic listing table's rate-structure column."""

from __future__ import annotations

import json
import sqlite3

from core_storefront.sqlite_client import write_listing_update
from core_storefront.sqlite_migrations import migrate_listing_rate_structure

_STRUCTURE = {"gpu": [{"asset": "usd", "rate": "2", "per": "hour"}]}


def _listings(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE listings (listing_id TEXT PRIMARY KEY, updated_at TEXT, "
        "closed_by TEXT, max_duration_seconds INTEGER)"
    )
    conn.execute("INSERT INTO listings(listing_id, updated_at) VALUES ('l1', 'then')")


def _column(conn: sqlite3.Connection) -> object:
    return conn.execute(
        "SELECT rate_structure FROM listings WHERE listing_id = 'l1'"
    ).fetchone()[0]


def test_the_migration_adds_a_null_column_to_an_existing_table() -> None:
    conn = sqlite3.connect(":memory:")
    _listings(conn)

    migrate_listing_rate_structure(conn)
    migrate_listing_rate_structure(conn)  # repeatable

    assert _column(conn) is None


def test_an_update_writes_clears_and_otherwise_keeps_the_structure() -> None:
    conn = sqlite3.connect(":memory:")
    _listings(conn)
    migrate_listing_rate_structure(conn)

    write_listing_update(conn, listing_id="l1", rate_structure=_STRUCTURE)
    assert json.loads(_column(conn)) == _STRUCTURE

    write_listing_update(conn, listing_id="l1", max_duration_seconds=60)
    assert json.loads(_column(conn)) == _STRUCTURE

    write_listing_update(conn, listing_id="l1", rate_structure=None)
    assert _column(conn) is None
