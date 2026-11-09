"""The storefront's read of the listings it holds open, over a real SQLite file."""

from __future__ import annotations

import sqlite3

import pytest

from core_database import core_database
from core_storefront.sqlite_client import SQLiteClient


def _insert(db_path: str, listing_id: str, *, status: str, paused: int = 0) -> None:
    closed_by = "reconciliation" if status == "closed" else None
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO listings (listing_id, status, created_at, updated_at, "
            "listing_resource, storefront_url, seller_scheme, seller_identifier, "
            "paused, closed_by) VALUES (?, ?, '2026-11-09T00:00:00Z', "
            "'2026-11-09T00:00:00Z', '{}', 'https://seller.example', 'ed25519', "
            "?, ?, ?)",
            (listing_id, status, "11" * 32, paused, closed_by),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_every_open_listing_is_held_paused_or_not_and_no_closed_one(tmp_path):
    db_path = core_database(tmp_path / "storefront.db")
    client = SQLiteClient(db_path)
    _insert(db_path, "open-1", status="open")
    _insert(db_path, "open-paused", status="open", paused=1)
    _insert(db_path, "closed-1", status="closed")

    assert await client.open_listing_ids() == frozenset({"open-1", "open-paused"})


@pytest.mark.asyncio
async def test_a_storefront_with_no_listing_holds_none(tmp_path):
    client = SQLiteClient(core_database(tmp_path / "storefront.db"))

    assert await client.open_listing_ids() == frozenset()
