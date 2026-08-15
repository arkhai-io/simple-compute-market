"""Verify the compute_inventory_pools -> compute_capacity_pools rename
migration, rather than assume SQLite's ALTER TABLE ... RENAME TO
correctly rewrites compute_pool_members' foreign key."""

from __future__ import annotations

import sqlite3
import asyncio
import json
from datetime import datetime
import pytest

from market_identity import Ed25519Signer

from market_storefront.domain_runtime import build_vm_storefront_domain
from market_storefront.utils.sqlite_client import SQLiteClient
from market_storefront.utils import sqlite_client as sqlite_module

from market_storefront.utils.migrations import (
    _migrate_rename_compute_capacity_pools,
)


def test_rename_migration_preserves_data_and_pool_members_fk(tmp_path):
    """A database still on the old table name: the rename must not lose
    rows, and compute_pool_members' FK must resolve through the new name."""
    conn = sqlite3.connect(str(tmp_path / "rename.db"))
    try:
        conn.execute(
            """
            CREATE TABLE compute_inventory_pools (
              pool_id TEXT PRIMARY KEY,
              gpu_model TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE compute_pool_members (
              member_id TEXT PRIMARY KEY,
              pool_id TEXT NOT NULL,
              resource_id TEXT NOT NULL UNIQUE,
              FOREIGN KEY(pool_id) REFERENCES compute_inventory_pools(pool_id)
            )
            """
        )
        conn.execute(
            "INSERT INTO compute_inventory_pools(pool_id, gpu_model) "
            "VALUES ('pool-A', 'H200')"
        )
        conn.execute(
            "INSERT INTO compute_pool_members(member_id, pool_id, resource_id) "
            "VALUES ('m1', 'pool-A', 'res-1')"
        )
        conn.commit()

        _migrate_rename_compute_capacity_pools(conn)
        conn.commit()

        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert "compute_capacity_pools" in tables
        assert "compute_inventory_pools" not in tables

        assert conn.execute(
            "SELECT gpu_model FROM compute_capacity_pools WHERE pool_id = 'pool-A'"
        ).fetchone() == ("H200",)

        # The FK's target survived the rename: SQLite rewrites the
        # foreign-key clause in compute_pool_members' schema text as part
        # of ALTER TABLE ... RENAME TO — verified here rather than assumed.
        fk_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' "
            "AND name='compute_pool_members'"
        ).fetchone()[0]
        assert "compute_capacity_pools" in fk_sql
        assert "compute_inventory_pools" not in fk_sql

        joined = conn.execute(
            """
            SELECT m.resource_id FROM compute_pool_members m
            JOIN compute_capacity_pools p ON p.pool_id = m.pool_id
            """
        ).fetchall()
        assert joined == [("res-1",)]

        conn.execute("PRAGMA foreign_keys = ON")
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        conn.close()


def test_rename_migration_is_noop_on_fresh_database(tmp_path):
    """A fresh database, where the inventory-pools migration already
    created compute_capacity_pools directly, must not error when the
    rename migration also runs against it."""
    conn = sqlite3.connect(str(tmp_path / "fresh.db"))
    try:
        conn.execute("CREATE TABLE compute_capacity_pools (pool_id TEXT PRIMARY KEY)")
        conn.commit()

        _migrate_rename_compute_capacity_pools(conn)  # must not raise

        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert tables == {"compute_capacity_pools"}
    finally:
        conn.close()


def test_rename_migration_is_noop_when_neither_table_exists(tmp_path):
    """An empty database (no pools table at all yet) must not error."""
    conn = sqlite3.connect(str(tmp_path / "empty.db"))
    try:
        _migrate_rename_compute_capacity_pools(conn)  # must not raise
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert tables == set()
    finally:
        conn.close()


def test_rename_migration_rejects_ambiguous_two_table_state(tmp_path):
    """Both table names indicate schema drift and must not be silently ignored."""
    conn = sqlite3.connect(str(tmp_path / "ambiguous.db"))
    try:
        conn.execute("CREATE TABLE compute_inventory_pools (pool_id TEXT PRIMARY KEY)")
        conn.execute("CREATE TABLE compute_capacity_pools (pool_id TEXT PRIMARY KEY)")
        conn.commit()

        import pytest

        with pytest.raises(RuntimeError, match="manual reconciliation"):
            _migrate_rename_compute_capacity_pools(conn)
    finally:
        conn.close()


def test_restart_preserves_schema_and_all_persisted_identifiers(tmp_path) -> None:
    db_path = str(tmp_path / "pre-parameterization.db")
    domain = build_vm_storefront_domain()
    seller = Ed25519Signer(b"\x31" * 32).identity
    buyer = Ed25519Signer(b"\x32" * 32).identity
    client = SQLiteClient(db_path, domain=domain)
    now = datetime.now().isoformat()

    asyncio.run(
        client.upsert_listing(
            listing_id="listing-stable",
            status="open",
            created_at=now,
            updated_at=now,
            offer_resource={
                "resource_type": "compute",
                "resource_id": "resource-stable",
                "gpu_model": "H200",
                "gpu_count": 1,
                "region": "test",
                "sla": 99.0,
            },
            fulfillment_resource=None,
            max_duration_seconds=3600,
            storefront_url="http://seller.test",
            seller_principal=seller,
        )
    )
    asyncio.run(
        client.create_negotiation_thread(
            negotiation_id="negotiation-stable",
            our_listing_id="listing-stable",
            their_listing_id="",
            our_agent_id="http://seller.test",
            their_agent_id="http://buyer.test",
            buyer_principal=buyer,
            seller_principal=seller,
            owner_id="seller",
        )
    )
    asyncio.run(
        client.insert_escrow(
            escrow_uid="settlement-stable",
            negotiation_id="negotiation-stable",
            chain_name="anvil",
            escrow_address="0x" + "11" * 20,
        )
    )
    asyncio.run(
        client.bind_escrow_obligation(
            escrow_uid="settlement-stable",
            obligation_ref="obligation-stable",
            obligation_index=0,
        )
    )
    asyncio.run(
        client.update_escrow(
            escrow_uid="settlement-stable",
            fulfillment_uid="fulfillment-stable",
        )
    )

    principal = json.dumps(seller.model_dump(mode="json"), sort_keys=True)
    obligation = json.dumps({"mechanism": "alkahest.v1"}, sort_keys=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            """
            INSERT INTO settlement_obligations (
              obligation_ref, agreement_ref, obligation_index, obligation_hash,
              obligation, payer_principal, claimant_principal, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "operation-obligation-stable",
                "negotiation-stable",
                1,
                "sha256:stable",
                obligation,
                principal,
                principal,
                now,
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO settlement_operations (
              obligation_ref, operation, request_hash, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                "operation-obligation-stable",
                "collect",
                "sha256:operation-stable",
                now,
                now,
            ),
        )
        conn.commit()
        schema_before = conn.execute(
            "SELECT name, type, sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        ).fetchall()

    reopened = SQLiteClient(db_path, domain=domain)

    assert reopened.market_domain is domain
    assert asyncio.run(
        reopened.load_listing(listing_id="listing-stable")
    )["listing_id"] == "listing-stable"
    assert asyncio.run(
        reopened.load_negotiation_thread_row(
            negotiation_id="negotiation-stable"
        )
    )["negotiation_id"] == "negotiation-stable"
    escrow = asyncio.run(reopened.load_escrow(escrow_uid="settlement-stable"))
    assert escrow["obligation_ref"] == "obligation-stable"
    assert escrow["fulfillment_uid"] == "fulfillment-stable"

    with sqlite3.connect(db_path) as conn:
        assert conn.execute(
            "SELECT obligation_ref, operation FROM settlement_operations"
        ).fetchall() == [("operation-obligation-stable", "collect")]
        schema_after = conn.execute(
            "SELECT name, type, sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        ).fetchall()
    assert schema_after == schema_before


def test_settings_singleton_rejects_a_different_contract_object(
    tmp_path,
    monkeypatch,
) -> None:
    first = build_vm_storefront_domain()
    second = build_vm_storefront_domain()
    signer = Ed25519Signer(b"\x33" * 32)
    monkeypatch.setattr(
        sqlite_module.settings,
        "db_path",
        str(tmp_path / "singleton.db"),
        raising=False,
    )
    monkeypatch.setattr(sqlite_module, "resolve_marketplace_signer", lambda: signer)
    monkeypatch.setattr(sqlite_module, "_sqlite_client", None)

    resolved = sqlite_module.get_sqlite_client(domain=first)

    assert resolved.market_domain is first
    with pytest.raises(RuntimeError, match="different market-domain contract object"):
        sqlite_module.get_sqlite_client(domain=second)
