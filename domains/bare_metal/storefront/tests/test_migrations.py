from __future__ import annotations

import sqlite3

import pytest
from core_storefront.sqlite_client import SQLiteClient as CoreSQLiteClient
from market_settlement_runtime import settlement_migrations
from market_identity import Ed25519Signer

from arkhai_bare_metal_storefront.migrations import RetiredListingKindError
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
    "bare-metal-storefront-0008-hosted-physical-lifecycle",
    "bare-metal-storefront-0009-refuse-retired-listing-kind",
    "bare-metal-storefront-0010-drop-derived-publications",
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
        listing_resource={"kind": "legacy"},
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
    assert "bare_metal_hosted_lifecycle" in tables
    assert applied == [(migration_id,) for migration_id in sorted(MIGRATION_IDS)]
    assert "derived_bare_metal_listings" not in tables
    assert listing == ("listing-existing",)
    assert operator_state == (1, 0)


def _tables_and_indexes(path) -> set[str]:
    conn = sqlite3.connect(path)
    try:
        return {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'index')"
            )
        }
    finally:
        conn.close()


def test_the_migration_sequence_leaves_no_second_listing_key(tmp_path) -> None:
    """Listings are tracked only by the common binding's derivation key."""
    path = tmp_path / "storefront.db"

    SQLiteClient(str(path))

    names = _tables_and_indexes(path)
    assert "derived_bare_metal_listings" not in names
    assert not {name for name in names if name.startswith("idx_derived_bare_metal")}


def test_a_populated_tracking_table_is_dropped_after_its_rows_are_bound(
    tmp_path,
) -> None:
    """A database 0002 populated keeps each listing's common binding, which
    0006 wrote from the tracking row, and loses the tracking table."""
    path = tmp_path / "storefront.db"
    CoreSQLiteClient(str(path))
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE derived_bare_metal_listings (
              listing_id TEXT PRIMARY KEY,
              site_id TEXT NOT NULL,
              physical_resource_id TEXT NOT NULL,
              host_id TEXT NOT NULL,
              physical_host_id TEXT NOT NULL,
              status TEXT NOT NULL,
              derivation_key TEXT NOT NULL UNIQUE,
              last_reconciled_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO listings(
              listing_id, status, created_at, updated_at, listing_resource,
              storefront_url, seller_scheme, seller_identifier
            ) VALUES (
              'listing-old', 'open', 'now', 'now',
              '{"kind": "bare_metal.v2", "capacity_backing": "backed",
                "host_id": "machine-old", "physical_host_id": "host-old",
                "access_methods": ["ssh"]}',
              'http://seller:8000', 'ed25519', 'seller'
            );
            INSERT INTO derived_bare_metal_listings(
              listing_id, site_id, physical_resource_id, host_id,
              physical_host_id, status, derivation_key
            ) VALUES (
              'listing-old', 'site-a', 'resource-old', 'machine-old',
              'host-old', 'open', 'bare-metal:6:site-a:12:resource-old'
            );
            """,
        )
        conn.commit()
    finally:
        conn.close()

    SQLiteClient(str(path))

    assert "derived_bare_metal_listings" not in _tables_and_indexes(path)
    conn = sqlite3.connect(path)
    try:
        binding = conn.execute(
            "SELECT site_id, pool_id, physical_resource_id, offering_mode "
            "FROM storefront_listing_bindings WHERE listing_id = 'listing-old'"
        ).fetchone()
    finally:
        conn.close()
    assert binding == ("site-a", None, "resource-old", "bare_metal")


def test_a_database_written_under_the_retired_listing_kind_is_refused(tmp_path) -> None:
    """Accepted bare-metal state cannot be rewritten or decoded after the
    listing kind that named the host ``machine_id`` was retired, so startup
    refuses the database and names the remedy instead of failing later on a
    decode."""
    path = tmp_path / "storefront.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE derived_bare_metal_listings "
        "(listing_id TEXT PRIMARY KEY, machine_id TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO derived_bare_metal_listings VALUES ('listing-1', 'bm1')"
    )
    conn.commit()
    conn.close()

    with pytest.raises(RetiredListingKindError, match="Resetting the storefront database"):
        SQLiteClient(str(path))

    conn = sqlite3.connect(path)
    try:
        # Nothing was decoded or rewritten: the retired row is byte-identical.
        assert conn.execute(
            "SELECT listing_id, machine_id FROM derived_bare_metal_listings"
        ).fetchall() == [("listing-1", "bm1")]
    finally:
        conn.close()


def test_a_fresh_database_passes_the_retired_kind_check(tmp_path) -> None:
    path = tmp_path / "storefront.db"

    SQLiteClient(str(path))

    conn = sqlite3.connect(path)
    try:
        assert conn.execute(
            "SELECT 1 FROM schema_migrations "
            "WHERE id='bare-metal-storefront-0009-refuse-retired-listing-kind'"
        ).fetchone() == (1,)
        # The retired schema is gone and nothing replaced it with a table
        # the refusal would have to recognize.
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='derived_bare_metal_listings'"
        ).fetchone() is None
    finally:
        conn.close()
