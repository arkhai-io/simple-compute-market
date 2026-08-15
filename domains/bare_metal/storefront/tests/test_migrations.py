from __future__ import annotations

import sqlite3

import pytest
from core_storefront.sqlite_client import SQLiteClient as CoreSQLiteClient
from market_settlement_runtime import settlement_migrations
from market_identity import Ed25519Signer

from arkhai_bare_metal_storefront.sqlite_client import SQLiteClient


SETTLEMENT_MIGRATION_IDS = tuple(migration.id for migration in settlement_migrations())
BARE_METAL_MIGRATION_IDS = (
    "bare-metal-storefront-0001-agreement-payloads",
    "bare-metal-storefront-0002-derived-publications",
    "bare-metal-storefront-0003-operator-state",
    "bare-metal-storefront-0004-selected-site-bindings",
    "bare-metal-storefront-0005-fulfillment-lifecycle",
    "bare-metal-storefront-0006-common-domain-bindings",
    "bare-metal-storefront-0007-selected-site-immutability",
)
MIGRATION_IDS = (*SETTLEMENT_MIGRATION_IDS, *BARE_METAL_MIGRATION_IDS)


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
        storefront_url="http://seller:8000",
        seller_principal=Ed25519Signer(bytes.fromhex("22" * 32)).identity,
    )
    del core

    SQLiteClient(str(path))
    SQLiteClient(str(path))

    conn = sqlite3.connect(path)
    try:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        placeholders = ", ".join("?" for _ in MIGRATION_IDS)
        applied = conn.execute(
            f"SELECT id FROM schema_migrations "
            f"WHERE id IN ({placeholders}) ORDER BY id",
            MIGRATION_IDS,
        ).fetchall()
        derived_columns = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(derived_bare_metal_listings)",
            )
        }
        listing = conn.execute(
            "SELECT listing_id FROM listings WHERE listing_id = ?",
            ("listing-existing",),
        ).fetchone()
        operator_state = conn.execute(
            "SELECT singleton_id, paused FROM bare_metal_operator_state",
        ).fetchone()
    finally:
        conn.close()

    assert "bare_metal_agreement_payloads" not in tables
    assert "storefront_domain_artifacts" in tables
    assert {"settlement_obligations", "settlement_operations"} <= tables
    assert applied == [(migration_id,) for migration_id in sorted(MIGRATION_IDS)]
    assert {
        "site_id",
        "physical_resource_id",
        "machine_id",
        "physical_host_id",
        "derivation_key",
    } <= derived_columns
    assert listing == ("listing-existing",)
    assert operator_state == (1, 0)


def test_publication_migration_closes_unscoped_tracking_rows(tmp_path) -> None:
    path = tmp_path / "storefront.db"
    CoreSQLiteClient(str(path))
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE derived_bare_metal_listings (
              listing_id TEXT PRIMARY KEY,
              machine_id TEXT NOT NULL,
              physical_host_id TEXT NOT NULL,
              status TEXT NOT NULL,
              derivation_key TEXT NOT NULL UNIQUE,
              last_reconciled_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO derived_bare_metal_listings(
              listing_id, machine_id, physical_host_id, status, derivation_key
            ) VALUES (
              'listing-old', 'machine-old', 'host-old', 'open',
              'bare-metal:machine-old'
            );
            """,
        )
        conn.commit()
    finally:
        conn.close()

    SQLiteClient(str(path))

    conn = sqlite3.connect(path)
    try:
        row = conn.execute(
            "SELECT site_id, physical_resource_id, status "
            "FROM derived_bare_metal_listings WHERE listing_id = 'listing-old'",
        ).fetchone()
    finally:
        conn.close()

    assert row == (None, None, "closed")
