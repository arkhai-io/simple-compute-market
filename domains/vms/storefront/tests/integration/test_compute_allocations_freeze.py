"""The storefront neither creates nor alters the ``compute_allocations`` table.

The site authority's capacity reservation is the allocation record. A fresh
storefront database has no allocation table; one an older storefront created
keeps its schema, rows, and migration history exactly as they were, through
every initialization and every resource transition.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from market_storefront.domain_runtime import (
    build_vm_storefront_domain,
    build_vm_storefront_registry,
)
from market_storefront.utils.sqlite_client import SQLiteClient

# Migrations that only ever added columns to the allocation table. A database
# may have recorded either, both, or neither, depending on when it was last
# initialized by a storefront that still listed them.
_COLUMNS_ID = "20260604_001_compute_allocation_callback_metadata"
_HOLD_EXPIRY_ID = "20260611_007_allocation_hold_expiry"
_RETIRED_IDS = (_COLUMNS_ID, _HOLD_EXPIRY_ID)

_SCHEMA_MIGRATIONS = """
CREATE TABLE schema_migrations (
  id TEXT PRIMARY KEY,
  applied_at TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now'))
)
"""

# The table as storefronts created it before any allocation migration.
_PRE_COLUMNS_TABLE = """
CREATE TABLE compute_allocations (
  allocation_id TEXT PRIMARY KEY,
  resource_id TEXT NOT NULL,
  listing_id TEXT,
  escrow_uid TEXT,
  gpu_count INTEGER NOT NULL,
  state TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  released_at TEXT
)
"""

_CORRELATION_COLUMNS = """,
  pool_id TEXT,
  member_id TEXT,
  provider_id TEXT,
  provider_job_id TEXT,
  provider_lease_id TEXT,
  provider_resource_id TEXT,
  vm_host TEXT,
  vm_target TEXT,
  lease_end_utc TEXT,
  failure_reason TEXT,
  failure_message TEXT,
  logs_ref TEXT,
  vm_remove_job_id TEXT"""

# After the correlation-column migration, before hold expiry.
_COLUMNS_TABLE = _PRE_COLUMNS_TABLE.replace(
    "  released_at TEXT\n)", "  released_at TEXT" + _CORRELATION_COLUMNS + "\n)"
)

# The last shape a storefront created.
_CURRENT_TABLE = _COLUMNS_TABLE.replace(
    "  vm_remove_job_id TEXT\n)", "  vm_remove_job_id TEXT,\n  hold_expires_at TEXT\n)"
)

_TRIGGER = """
CREATE TRIGGER trg_compute_allocations_updated_at
AFTER UPDATE ON compute_allocations
FOR EACH ROW
WHEN NEW.updated_at = OLD.updated_at
BEGIN
  UPDATE compute_allocations
  SET updated_at = STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')
  WHERE allocation_id = NEW.allocation_id;
END
"""

_RESOURCE_INDEX = (
    "CREATE INDEX idx_compute_allocations_resource_state "
    "ON compute_allocations(resource_id, state)"
)
_POOL_INDEXES = (
    "CREATE INDEX idx_compute_allocations_pool_state ON compute_allocations(pool_id, state)",
    "CREATE INDEX idx_compute_allocations_member_state ON compute_allocations(member_id, state)",
)
_ESCROW_INDEX = (
    "CREATE INDEX idx_compute_allocations_escrow_uid ON compute_allocations(escrow_uid)"
)

_HISTORIES = {
    "both-recorded": (
        _CURRENT_TABLE,
        (_RESOURCE_INDEX, *_POOL_INDEXES, _ESCROW_INDEX),
        _RETIRED_IDS,
    ),
    "columns-only-recorded": (
        _COLUMNS_TABLE,
        (_RESOURCE_INDEX, *_POOL_INDEXES),
        (_COLUMNS_ID,),
    ),
    "neither-recorded": (_PRE_COLUMNS_TABLE, (_RESOURCE_INDEX,), ()),
}

_ALLOCATION_ROWS = (
    ("alloc-held", "res-1", "listing-1", "escrow-1", 2, "leased", "2026-05-01", "2026-05-01", None),
    ("alloc-done", "res-1", "listing-2", "escrow-2", 1, "released", "2026-05-02", "2026-05-03", "2026-05-03"),
)


def _client(db_path: Path) -> SQLiteClient:
    return SQLiteClient(
        db_path=str(db_path),
        registry=build_vm_storefront_registry(build_vm_storefront_domain()),
    )


def _seed_history(db_path: Path, history: str) -> None:
    table, indexes, recorded = _HISTORIES[history]
    with sqlite3.connect(db_path) as conn:
        conn.execute(_SCHEMA_MIGRATIONS)
        conn.execute(table)
        conn.execute(_TRIGGER)
        for index in indexes:
            conn.execute(index)
        conn.executemany(
            "INSERT INTO compute_allocations("
            " allocation_id, resource_id, listing_id, escrow_uid, gpu_count,"
            " state, created_at, updated_at, released_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            _ALLOCATION_ROWS,
        )
        conn.executemany(
            "INSERT INTO schema_migrations(id, applied_at) VALUES (?, '2026-06-30')",
            [(migration_id,) for migration_id in recorded],
        )
    conn.close()


def _snapshot(db_path: Path) -> dict[str, list[tuple]]:
    """Everything the freeze must leave byte-identical."""
    conn = sqlite3.connect(db_path)
    try:
        snapshot = {
            "schema": conn.execute(
                "SELECT type, name, sql FROM sqlite_master"
                " WHERE tbl_name = 'compute_allocations' ORDER BY type, name"
            ).fetchall(),
            "retired_migrations": conn.execute(
                "SELECT id, applied_at FROM schema_migrations"
                f" WHERE id IN ({', '.join('?' for _ in _RETIRED_IDS)}) ORDER BY id",
                _RETIRED_IDS,
            ).fetchall(),
        }
        if snapshot["schema"]:
            snapshot["rows"] = conn.execute(
                "SELECT * FROM compute_allocations ORDER BY allocation_id"
            ).fetchall()
        return snapshot
    finally:
        conn.close()


def test_a_fresh_database_has_no_allocation_ledger(tmp_path):
    db_path = tmp_path / "fresh.db"

    _client(db_path)
    _client(db_path)

    assert _snapshot(db_path) == {"schema": [], "retired_migrations": []}


@pytest.mark.parametrize("history", sorted(_HISTORIES))
def test_initialization_leaves_an_existing_ledger_exactly_as_it_was(tmp_path, history):
    db_path = tmp_path / f"{history}.db"
    _seed_history(db_path, history)
    before = _snapshot(db_path)
    assert before["rows"] and before["schema"]

    _client(db_path)
    assert _snapshot(db_path) == before

    _client(db_path)
    assert _snapshot(db_path) == before


@pytest.mark.parametrize("history", [None, "both-recorded"])
async def test_a_release_transition_writes_no_allocation(tmp_path, history):
    db_path = tmp_path / "transition.db"
    if history is not None:
        _seed_history(db_path, history)
    client = _client(db_path)
    await client.upsert_resource(
        resource_id="res-1", resource_type="compute.gpu", state="leased"
    )
    before = _snapshot(db_path)

    result = await client.apply_resource_transition(
        resource_id="res-1",
        event_type="reservation_released_by_admin",
        idempotency_key="release-res-1",
        set_state="available",
    )

    assert result["applied"] is True
    assert _snapshot(db_path) == before
