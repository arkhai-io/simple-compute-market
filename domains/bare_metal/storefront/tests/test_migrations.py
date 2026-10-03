from __future__ import annotations

import sqlite3

from arkhai_bare_metal_storefront.sqlite_client import SQLiteClient
from core_storefront.sqlite_client import SQLiteClient as CoreSQLiteClient
from market_settlement_runtime import settlement_migrations

SETTLEMENT_MIGRATION_IDS = tuple(migration.id for migration in settlement_migrations())
BARE_METAL_MIGRATION_IDS = (
    "bare-metal-storefront-0001-agreement-payloads",
    "bare-metal-storefront-0002-derived-publications",
    "bare-metal-storefront-0003-operator-state",
    "bare-metal-storefront-0004-selected-site-bindings",
    "bare-metal-storefront-0005-fulfillment-lifecycle",
    "bare-metal-storefront-0006-common-domain-bindings",
    "bare-metal-storefront-0007-selected-site-immutability",
    "bare-metal-storefront-0008-settlement-records",
)
MIGRATION_IDS = (*SETTLEMENT_MIGRATION_IDS, *BARE_METAL_MIGRATION_IDS)


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
