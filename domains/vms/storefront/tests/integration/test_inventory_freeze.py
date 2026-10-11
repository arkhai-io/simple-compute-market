"""The storefront neither creates nor alters its retired inventory tables.

Physical inventory is declared at each site's provisioning service. A fresh
storefront database has no ``resources``, ``hosts``, ``compute_capacity_pools``,
``compute_pool_members``, or ``resource_transition_events`` table. One an older
storefront created keeps those tables, their triggers, indexes, rows, transition
history, and recorded migration IDs exactly as they were, through every
initialization and status read: the retained rows are input an operator may
extract into provisioning, so nothing rewrites them.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from market_identity import Ed25519Signer

from market_storefront.domain_runtime import (
    build_vm_storefront_domain,
    build_vm_storefront_registry,
)
from market_storefront.services.system_service import SystemService
from market_storefront.utils.sqlite_client import SQLiteClient

# Migrations that only ever created or altered the retired tables. A database
# may have recorded any of them, depending on when it was last initialized.
_POOLS_ID = "20260604_002_compute_inventory_pools"
_MEMBER_SITES_ID = "20260611_006_pool_member_sites"
_RENAME_ID = "20260716_008_rename_compute_capacity_pools"
_CLAUSES_ID = "20260813_010_resource_settlement_clauses"
_RETIRED_IDS = (_POOLS_ID, _MEMBER_SITES_ID, _RENAME_ID, _CLAUSES_ID)
# The core timestamp migration an older storefront applied at the same
# initialization that created its inventory tables.
_TIMESTAMPS_ID = "20260604_000_listing_resource_timestamps"

_RETIRED_TABLES = (
    "resources",
    "hosts",
    "resource_transition_events",
    "compute_capacity_pools",
    "compute_inventory_pools",
    "compute_pool_members",
)

_SCHEMA_MIGRATIONS = """
CREATE TABLE schema_migrations (
  id TEXT PRIMARY KEY,
  applied_at TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now'))
)
"""

_RESOURCES = """
CREATE TABLE resources (
  pk INTEGER PRIMARY KEY AUTOINCREMENT,
  resource_id TEXT NOT NULL UNIQUE,
  resource_type TEXT NOT NULL,
  resource_subtype TEXT,
  unit TEXT,
  value NUMERIC,
  state TEXT,
  attributes TEXT,
  min_price TEXT,
  token TEXT,
  max_duration_seconds INTEGER,
  accepted_escrows TEXT,
  settlements TEXT,
  created_at TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now'))
)
"""

# Deliberately not the text a later storefront wrote: a bootstrap that drops
# and recreates the trigger would replace it, which the snapshot then shows.
_RESOURCES_TRIGGER = """
CREATE TRIGGER trg_resources_updated_at
AFTER UPDATE ON resources
FOR EACH ROW
WHEN NEW.updated_at = OLD.updated_at
BEGIN
  UPDATE resources SET updated_at = STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')
  WHERE pk = NEW.pk;
END
"""

_HOSTS = """
CREATE TABLE hosts (
  name TEXT PRIMARY KEY,
  cpu_type TEXT,
  total_gpu_count INTEGER,
  gpu_model TEXT,
  region TEXT,
  attributes TEXT,
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now'))
)
"""

_HOSTS_TRIGGER = """
CREATE TRIGGER trg_hosts_updated_at
AFTER UPDATE ON hosts
FOR EACH ROW
WHEN NEW.updated_at = OLD.updated_at
BEGIN
  UPDATE hosts SET updated_at = STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')
  WHERE name = NEW.name;
END
"""

_TRANSITIONS = """
CREATE TABLE resource_transition_events (
  pk INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id TEXT NOT NULL UNIQUE,
  resource_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  set_value NUMERIC,
  set_state TEXT,
  set_attribute_json TEXT,
  idempotency_key TEXT NOT NULL UNIQUE,
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')),
  FOREIGN KEY(resource_id) REFERENCES resources(resource_id)
)
"""

_POOLS = """
CREATE TABLE {name} (
  pool_id TEXT PRIMARY KEY,
  gpu_model TEXT,
  region TEXT,
  sla NUMERIC,
  total_gpu_count INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'active',
  min_price TEXT,
  token TEXT,
  max_duration_seconds INTEGER,
  accepted_escrows TEXT{settlements}
)
"""

_MEMBERS = """
CREATE TABLE compute_pool_members (
  member_id TEXT PRIMARY KEY,
  pool_id TEXT NOT NULL,
  resource_id TEXT NOT NULL UNIQUE,
  gpu_count INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'active'{site},
  FOREIGN KEY(pool_id) REFERENCES {pools}(pool_id)
)
"""

_INDEXES = (
    "CREATE INDEX idx_resources_resource_id ON resources(resource_id)",
    "CREATE INDEX idx_resources_type_subtype ON resources(resource_type, resource_subtype)",
    "CREATE INDEX idx_resources_state ON resources(state)",
    "CREATE INDEX idx_resources_updated_at ON resources(updated_at)",
    "CREATE INDEX idx_resource_transition_events_resource_time"
    " ON resource_transition_events(resource_id, occurred_at)",
    "CREATE INDEX idx_resource_transition_events_type_time"
    " ON resource_transition_events(event_type, occurred_at)",
    "CREATE INDEX idx_compute_pool_members_pool ON compute_pool_members(pool_id, status)",
)

# The last shape a storefront created, and one that never applied the later
# pool migrations: its pool table keeps its original name and its members
# carry no site.
_HISTORIES = {
    "all-recorded": ("compute_capacity_pools", True, _RETIRED_IDS),
    "pools-only-recorded": ("compute_inventory_pools", False, (_POOLS_ID,)),
}


def _client(db_path: Path) -> SQLiteClient:
    return SQLiteClient(
        db_path=str(db_path),
        registry=build_vm_storefront_registry(build_vm_storefront_domain()),
    )


def _seed_history(db_path: Path, history: str) -> None:
    pools, current, recorded = _HISTORIES[history]
    conn = sqlite3.connect(db_path)
    with conn:
        conn.execute(_SCHEMA_MIGRATIONS)
        conn.execute(_RESOURCES)
        conn.execute(_RESOURCES_TRIGGER)
        conn.execute(_HOSTS)
        conn.execute(_HOSTS_TRIGGER)
        conn.execute(_TRANSITIONS)
        conn.execute(
            _POOLS.format(name=pools, settlements=",\n  settlements TEXT" if current else "")
        )
        conn.execute(_MEMBERS.format(site=",\n  site TEXT" if current else "", pools=pools))
        for index in _INDEXES:
            conn.execute(index)
        conn.execute(
            "INSERT INTO resources(resource_id, resource_type, value, state, attributes,"
            " created_at, updated_at) VALUES ('res-1', 'compute.gpu', 4, 'leased',"
            " '{\"gpu_model\": \"H200\", \"vm_host\": \"kvm1\"}', '2026-05-01', '2026-05-02')"
        )
        conn.execute(
            "INSERT INTO hosts(name, total_gpu_count, gpu_model, created_at, updated_at)"
            " VALUES ('kvm1', 8, 'H200', '2026-05-01', '2026-05-01')"
        )
        conn.executemany(
            "INSERT INTO resource_transition_events(event_id, resource_id, event_type,"
            " set_state, idempotency_key, occurred_at) VALUES (?, 'res-1', ?, ?, ?, ?)",
            [
                ("evt-1", "reserved", "reserved", "key-1", "2026-05-01T00:00:00Z"),
                ("evt-2", "leased", "leased", "key-2", "2026-05-02T00:00:00Z"),
            ],
        )
        conn.execute(
            f"INSERT INTO {pools}(pool_id, gpu_model, region, sla, total_gpu_count)"
            " VALUES ('pool-1', 'H200', 'California, US', 99.0, 4)"
        )
        conn.execute(
            "INSERT INTO compute_pool_members(member_id, pool_id, resource_id, gpu_count)"
            " VALUES ('member-1', 'pool-1', 'res-1', 4)"
        )
        conn.executemany(
            "INSERT INTO schema_migrations(id, applied_at) VALUES (?, '2026-06-30')",
            [(migration_id,) for migration_id in (_TIMESTAMPS_ID, *recorded)],
        )
    conn.close()


def _snapshot(db_path: Path) -> dict[str, object]:
    """Everything the freeze must leave byte-identical."""
    conn = sqlite3.connect(db_path)
    try:
        placeholders = ", ".join("?" for _ in _RETIRED_TABLES)
        schema = conn.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master"
            f" WHERE tbl_name IN ({placeholders}) ORDER BY type, name",
            _RETIRED_TABLES,
        ).fetchall()
        tables = sorted({row[2] for row in schema})
        rows = {
            table: conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
            for table in tables
        }
        recorded = conn.execute(
            "SELECT id, applied_at FROM schema_migrations"
            f" WHERE id IN ({', '.join('?' for _ in _RETIRED_IDS)}) ORDER BY id",
            _RETIRED_IDS,
        ).fetchall()
        return {"schema": schema, "rows": rows, "retired_migrations": recorded}
    finally:
        conn.close()


def test_a_fresh_database_has_no_inventory_schema(tmp_path):
    db_path = tmp_path / "fresh.db"

    _client(db_path)
    _client(db_path)

    assert _snapshot(db_path) == {"schema": [], "rows": {}, "retired_migrations": []}


@pytest.mark.parametrize("history", sorted(_HISTORIES))
def test_initialization_leaves_retained_inventory_exactly_as_it_was(tmp_path, history):
    db_path = tmp_path / f"{history}.db"
    _seed_history(db_path, history)
    before = _snapshot(db_path)
    assert before["rows"]["resource_transition_events"]
    assert any(row[1] == "trg_resources_updated_at" for row in before["schema"])

    _client(db_path)
    assert _snapshot(db_path) == before

    _client(db_path)
    assert _snapshot(db_path) == before


async def test_status_reads_nothing_from_retained_inventory(tmp_path):
    db_path = tmp_path / "status.db"
    _seed_history(db_path, "all-recorded")
    before = _snapshot(db_path)
    client = _client(db_path)

    service = SystemService(
        sqlite_client=client,
        # Development fixture key; never used on a public network.
        marketplace_signer=Ed25519Signer(b"\x41" * 32),
    )

    status = await service.get_health(include_registry=True)

    assert status["checks"]["database"] == "ok"
    assert "resource_count" not in status
    assert _snapshot(db_path) == before
