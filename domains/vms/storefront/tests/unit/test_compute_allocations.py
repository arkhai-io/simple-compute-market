from __future__ import annotations

import sqlite3

import pytest

from domains.vms.listings.reconciler import available_compute_slices
from market_storefront.utils.sqlite_client import SQLiteClient


@pytest.fixture
def client(tmp_path):
    return SQLiteClient(db_path=str(tmp_path / "agent.db"))


async def _seed_compute_pool(client: SQLiteClient, *, gpu_count: int = 4) -> None:
    await client.upsert_resource(
        resource_id="pool-h200-1",
        resource_type="compute.gpu",
        resource_subtype="h200",
        unit="count",
        value=gpu_count,
        state="available",
        attributes={
            "gpu_model": "H200",
            "sla": 99.0,
            "region": "California, US",
            "vm_host": "host-1",
        },
    )


async def _seed_fungible_compute_pool(client: SQLiteClient) -> None:
    for resource_id, host in (
        ("pool-h200-a", "host-a"),
        ("pool-h200-b", "host-b"),
    ):
        await client.upsert_resource(
            resource_id=resource_id,
            resource_type="compute.gpu",
            resource_subtype="h200",
            unit="count",
            value=4,
            state="available",
            attributes={
                "pool_id": "pool-h200-shared",
                "gpu_model": "H200",
                "sla": 99.0,
                "region": "California, US",
                "vm_host": host,
            },
        )


def test_sqlite_schema_includes_derived_compute_listings(client):
    conn = sqlite3.connect(client.db_path)
    try:
        cols = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(derived_compute_listings)"
            ).fetchall()
        }
    finally:
        conn.close()

    assert {
        "listing_id",
        "resource_id",
        "gpu_count",
        "status",
        "derivation_key",
        "last_reconciled_at",
    } <= cols


def test_sqlite_schema_includes_compute_allocation_correlation_fields(client):
    conn = sqlite3.connect(client.db_path)
    try:
        cols = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(compute_allocations)"
            ).fetchall()
        }
    finally:
        conn.close()

    assert {
        "provider_id",
        "provider_job_id",
        "provider_lease_id",
        "provider_resource_id",
        "vm_host",
        "vm_target",
        "lease_end_utc",
        "failure_reason",
        "failure_message",
        "logs_ref",
        "check_job_id",
    } <= cols


def test_sqlite_migration_backfills_compute_allocation_correlation_fields(tmp_path):
    db_path = tmp_path / "legacy-agent.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE resources (
              resource_id TEXT PRIMARY KEY,
              resource_type TEXT,
              resource_subtype TEXT,
              unit TEXT,
              value NUMERIC,
              state TEXT,
              attributes TEXT,
              updated_at TEXT
            )
            """
        )
        conn.execute(
            """
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
        )
        conn.commit()
    finally:
        conn.close()

    SQLiteClient(db_path=str(db_path))

    conn = sqlite3.connect(db_path)
    try:
        cols = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(compute_allocations)"
            ).fetchall()
        }
        migration_ids = {
            row[0]
            for row in conn.execute("SELECT id FROM schema_migrations").fetchall()
        }
    finally:
        conn.close()

    assert {
        "provider_id",
        "provider_job_id",
        "provider_lease_id",
        "provider_resource_id",
        "vm_host",
        "vm_target",
        "lease_end_utc",
        "failure_reason",
        "failure_message",
        "logs_ref",
        "check_job_id",
    } <= cols
    assert "20260604_001_compute_allocation_callback_metadata" in migration_ids


def test_sqlite_migration_accepts_pre_compute_inventory_schema(tmp_path):
    db_path = tmp_path / "pre-compute-agent.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE listings (
              listing_id TEXT PRIMARY KEY,
              status TEXT NOT NULL,
              offer_resource TEXT,
              seller TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE resources (
              resource_id TEXT PRIMARY KEY,
              resource_type TEXT,
              resource_subtype TEXT,
              unit TEXT,
              value NUMERIC,
              state TEXT,
              attributes TEXT
            )
            """
        )
        conn.commit()
    finally:
        conn.close()

    SQLiteClient(db_path=str(db_path))

    conn = sqlite3.connect(db_path)
    try:
        listing_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(listings)").fetchall()
        }
        resource_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(resources)").fetchall()
        }
        allocation_cols = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(compute_allocations)"
            ).fetchall()
        }
        migration_ids = {
            row[0]
            for row in conn.execute("SELECT id FROM schema_migrations").fetchall()
        }
    finally:
        conn.close()

    assert {"created_at", "updated_at"} <= listing_cols
    assert {"created_at", "updated_at"} <= resource_cols
    assert {
        "provider_id",
        "provider_job_id",
        "provider_lease_id",
        "provider_resource_id",
    } <= allocation_cols
    assert "20260604_000_listing_resource_timestamps" in migration_ids
    assert "20260604_001_compute_allocation_callback_metadata" in migration_ids







@pytest.mark.asyncio
async def test_fungible_pool_derives_one_listing_set_across_members(client):
    await _seed_fungible_compute_pool(client)

    rows = available_compute_slices(client.db_path)

    assert [row["gpu_count"] for row in rows] == [1, 2, 3, 4]
    assert {row["resource_key"] for row in rows} == {
        "pool:pool-h200-shared:gpus:1",
        "pool:pool-h200-shared:gpus:2",
        "pool:pool-h200-shared:gpus:3",
        "pool:pool-h200-shared:gpus:4",
    }
    assert {row["resource_id"] for row in rows} == {None}
    assert {row["pool_id"] for row in rows} == {"pool-h200-shared"}



@pytest.mark.asyncio
async def test_member_availability_view_governs_slices(client):
    """Remote-capacity mode: consumption comes from the aggregated site
    snapshots keyed (site, resource_id); totals and market attributes
    stay local. Members without a site tag match the home-site (None)
    key."""
    await _seed_fungible_compute_pool(client)

    # Site ledgers say one member is fully consumed, the other has 2 free.
    rows = available_compute_slices(
        client.db_path,
        member_availability={
            (None, "pool-h200-a"): 0,
            (None, "pool-h200-b"): 2,
        },
    )
    assert [row["gpu_count"] for row in rows] == [1, 2]
    assert rows[0]["available_gpu_count"] == 2
    assert rows[0]["total_gpu_count"] == 8  # totals are still local

    # The view is capped by the member's local total, and an uncovered
    # member is not reservable anywhere — it counts as 0.
    rows = available_compute_slices(
        client.db_path,
        member_availability={
            (None, "pool-h200-a"): 99,   # capped to the member's 4
            # pool-h200-b not covered → 0
        },
    )
    assert [row["gpu_count"] for row in rows] == [1, 2, 3, 4]
    assert rows[0]["available_gpu_count"] == 4


@pytest.mark.asyncio
async def test_member_at_another_site_keys_by_site_name(client):
    """Members tagged with a site use (site, resource_id) — a same-named
    resource at the home site must not satisfy them."""
    await _seed_compute_pool(client)
    # Tag the member as living at dc-b via the resource attributes.
    await client.upsert_resource(
        resource_id="pool-h200-1",
        resource_type="compute.gpu",
        resource_subtype="h200",
        unit="count",
        value=4,
        state="available",
        attributes={
            "gpu_model": "H200",
            "sla": 99.0,
            "region": "California, US",
            "vm_host": "host-1",
            "site": "dc-b",
        },
    )

    wrong_site_only = available_compute_slices(
        client.db_path,
        member_availability={(None, "pool-h200-1"): 4},  # wrong site
    )
    assert wrong_site_only == []  # the member's own site says nothing → 0

    free_at_dc_b = available_compute_slices(
        client.db_path,
        member_availability={("dc-b", "pool-h200-1"): 3},
    )
    assert [row["gpu_count"] for row in free_at_dc_b] == [1, 2, 3]




@pytest.mark.asyncio
async def test_capacity_hold_bookkeeping_round_trip(client):
    await client.save_capacity_hold(
        negotiation_id="neg-1",
        listing_id="lst-1",
        allocation_id="alloc-1",
        payload={"resource_id": "r1", "vm_host": "kvm1"},
        expires_at="2099-01-01T00:00:00+00:00",
    )
    hold = await client.load_capacity_hold(negotiation_id="neg-1")
    assert hold["allocation_id"] == "alloc-1"
    assert hold["payload"]["vm_host"] == "kvm1"

    await client.delete_capacity_hold(negotiation_id="neg-1")
    assert await client.load_capacity_hold(negotiation_id="neg-1") is None
