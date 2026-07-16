"""POOLS-4: verify the compute_inventory_pools -> compute_capacity_pools
rename migration, rather than assume SQLite's ALTER TABLE ... RENAME TO
correctly rewrites compute_pool_members' foreign key."""

from __future__ import annotations

import sqlite3

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
    """A fresh database, where the (post-POOLS-4) inventory-pools migration
    already created compute_capacity_pools directly, must not error when
    the rename migration also runs against it."""
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
