from __future__ import annotations

import sqlite3

import pytest
from core_storefront.sqlite_client import SQLiteClient as CoreSQLiteClient

from arkhai_bare_metal_storefront.sqlite_client import SQLiteClient


MIGRATION_ID = "bare-metal-storefront-0001-agreement-payloads"


@pytest.mark.asyncio
async def test_bare_metal_migration_upgrades_existing_core_database(tmp_path) -> None:
    path = tmp_path / "storefront.db"
    core = CoreSQLiteClient(str(path))
    await core.upsert_listing(
        listing_id="listing-existing",
        status="open",
        created_at="now",
        updated_at="now",
        offer_resource={"kind": "legacy"},
        fulfillment_resource=None,
        max_duration_seconds=None,
        seller="seller",
    )
    del core

    SQLiteClient(str(path))
    SQLiteClient(str(path))

    conn = sqlite3.connect(path)
    try:
        table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='bare_metal_agreement_payloads'",
        ).fetchone()
        applied = conn.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE id = ?",
            (MIGRATION_ID,),
        ).fetchone()[0]
        listing = conn.execute(
            "SELECT listing_id FROM listings WHERE listing_id = ?",
            ("listing-existing",),
        ).fetchone()
    finally:
        conn.close()

    assert table == ("bare_metal_agreement_payloads",)
    assert applied == 1
    assert listing == ("listing-existing",)
