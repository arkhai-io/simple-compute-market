from __future__ import annotations

import sqlite3

import pytest

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


@pytest.mark.asyncio
async def test_reserve_partial_gpu_capacity_keeps_pool_available(client):
    await _seed_compute_pool(client, gpu_count=4)

    first = await client.reserve_available_compute_vm(
        required_attributes={
            "gpu_model": "H200",
            "region": "California, US",
            "gpu_count": 2,
        },
        listing_id="listing-2x",
        escrow_uid="escrow-1",
    )

    assert first is not None
    assert first["allocated_gpu_count"] == 2
    assert first["available_gpu_count"] == 2
    assert first["state"] == "available"

    selected = await client.select_available_compute_vm(
        required_attributes={"gpu_model": "H200", "gpu_count": 2},
    )
    assert selected is not None
    assert selected["available_gpu_count"] == 2

    oversized = await client.select_available_compute_vm(
        required_attributes={"gpu_model": "H200", "gpu_count": 3},
    )
    assert oversized is None


@pytest.mark.asyncio
async def test_reserve_full_capacity_exposes_legacy_reserved_state(client):
    await _seed_compute_pool(client, gpu_count=4)

    reserved = await client.reserve_available_compute_vm(
        required_attributes={"gpu_model": "H200", "gpu_count": 4},
        escrow_uid="escrow-full",
    )

    assert reserved is not None
    assert reserved["state"] == "reserved"
    row = await client.get_resource(resource_id="pool-h200-1")
    assert row is not None
    assert row["state"] == "reserved"
    assert await client.select_available_compute_vm(
        required_attributes={"gpu_model": "H200", "gpu_count": 1},
    ) is None


@pytest.mark.asyncio
async def test_allocation_lifecycle_updates_resource_aggregate_state(client):
    await _seed_compute_pool(client, gpu_count=1)

    reserved = await client.reserve_available_compute_vm(
        required_attributes={"gpu_model": "H200", "gpu_count": 1},
        escrow_uid="escrow-lease",
    )
    assert reserved is not None

    leased = await client.update_compute_allocation_state(
        allocation_id=reserved["allocation_id"],
        state="leased",
    )
    assert leased is not None
    assert leased["resource_state"] == "leased"
    row = await client.get_resource(resource_id="pool-h200-1")
    assert row is not None
    assert row["state"] == "leased"

    released = await client.update_compute_allocation_state(
        allocation_id=reserved["allocation_id"],
        state="released",
    )
    assert released is not None
    assert released["resource_state"] == "available"
    row = await client.get_resource(resource_id="pool-h200-1")
    assert row is not None
    assert row["state"] == "available"


@pytest.mark.asyncio
async def test_allocation_lifecycle_persists_provider_correlation_fields(client):
    await _seed_compute_pool(client, gpu_count=1)

    reserved = await client.reserve_available_compute_vm(
        required_attributes={"gpu_model": "H200", "gpu_count": 1},
        escrow_uid="escrow-correlation",
    )
    assert reserved is not None

    updated = await client.update_compute_allocation_state(
        allocation_id=reserved["allocation_id"],
        state="leased",
        provider_id="provider-a",
        provider_job_id="job-create-1",
        provider_lease_id="lease-1",
        provider_resource_id="provider-resource-1",
        vm_host="kvm1",
        vm_target="tenant-abcd",
        lease_end_utc="2026-01-01T00:00:00Z",
    )
    assert updated is not None

    conn = sqlite3.connect(client.db_path)
    try:
        row = conn.execute(
            """
            SELECT provider_id, provider_job_id, provider_lease_id,
                   provider_resource_id, vm_host, vm_target, lease_end_utc
            FROM compute_allocations
            WHERE allocation_id = ?
            """,
            (reserved["allocation_id"],),
        ).fetchone()
    finally:
        conn.close()

    assert row == (
        "provider-a",
        "job-create-1",
        "lease-1",
        "provider-resource-1",
        "kvm1",
        "tenant-abcd",
        "2026-01-01T00:00:00Z",
    )


@pytest.mark.asyncio
async def test_resource_release_with_allocation_id_releases_only_that_slice(client):
    await _seed_compute_pool(client, gpu_count=4)
    first = await client.reserve_available_compute_vm(
        required_attributes={"gpu_model": "H200", "gpu_count": 2},
        escrow_uid="escrow-1",
    )
    second = await client.reserve_available_compute_vm(
        required_attributes={"gpu_model": "H200", "gpu_count": 2},
        escrow_uid="escrow-2",
    )
    assert first is not None
    assert second is not None
    assert await client.select_available_compute_vm(
        required_attributes={"gpu_model": "H200", "gpu_count": 1},
    ) is None

    await client.apply_resource_set_transition(
        resource_id="pool-h200-1",
        event_type="lease_released",
        idempotency_key="release-one",
        set_state="available",
        set_attribute={"$.allocation_id": first["allocation_id"]},
    )

    selected = await client.select_available_compute_vm(
        required_attributes={"gpu_model": "H200", "gpu_count": 2},
    )
    assert selected is not None
    assert selected["available_gpu_count"] == 2
    assert await client.select_available_compute_vm(
        required_attributes={"gpu_model": "H200", "gpu_count": 3},
    ) is None
