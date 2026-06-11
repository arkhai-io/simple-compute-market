"""The embedded capacity client is the site-authority boundary in miniature.

Same allocation semantics as calling the SQLite ledger directly (it IS
the same ledger), plus the contract pieces the real service will need:
anonymous versioned deltas on every capacity change, subscriber
isolation, and an explicit refusal of TTL holds until two-phase reserve
lands.
"""

from __future__ import annotations

import pytest

from core_storefront.capacity import CapacityClient, CapacityDelta
from market_storefront.services.capacity_client import (
    EmbeddedCapacityClient,
    build_capacity_client,
)
from market_storefront.utils.sqlite_client import SQLiteClient


@pytest.fixture
def db(tmp_path):
    return SQLiteClient(db_path=str(tmp_path / "agent.db"))


@pytest.fixture
def capacity(db):
    return build_capacity_client(lambda: db)


async def _seed_compute_pool(db: SQLiteClient, *, gpu_count: int = 4) -> None:
    await db.upsert_resource(
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


def _collect_deltas(capacity: EmbeddedCapacityClient) -> list[CapacityDelta]:
    seen: list[CapacityDelta] = []

    async def subscriber(delta: CapacityDelta) -> None:
        seen.append(delta)

    capacity.subscribe(subscriber)
    return seen


def test_embedded_client_satisfies_protocol(capacity):
    assert isinstance(capacity, CapacityClient)


@pytest.mark.asyncio
async def test_snapshot_returns_resource_rows(capacity, db):
    await _seed_compute_pool(db)
    rows = await capacity.snapshot()
    assert [r["resource_id"] for r in rows] == ["pool-h200-1"]
    assert rows[0]["state"] == "available"
    assert rows[0]["attributes"]["gpu_model"] == "H200"


@pytest.mark.asyncio
async def test_probe_matches_without_consuming(capacity, db):
    await _seed_compute_pool(db)
    first = await capacity.probe(claim={"gpu_model": "H200"})
    second = await capacity.probe(claim={"gpu_model": "H200"})
    assert first is not None and second is not None
    assert first["resource_id"] == second["resource_id"] == "pool-h200-1"
    assert first["available_gpu_count"] == second["available_gpu_count"] == 4


@pytest.mark.asyncio
async def test_reserve_consumes_capacity_and_records_deal_ref(capacity, db):
    await _seed_compute_pool(db, gpu_count=1)
    deltas = _collect_deltas(capacity)

    reserved = await capacity.reserve(
        claim={"gpu_model": "H200"},
        deal_ref={"listing_id": "L-1", "escrow_uid": "0xesc"},
    )
    assert reserved is not None
    assert reserved["resource_id"] == "pool-h200-1"
    assert reserved["vm_host"] == "host-1"

    # Capacity actually consumed: the same claim no longer matches.
    assert await capacity.probe(claim={"gpu_model": "H200"}) is None
    # And a second reserve refuses rather than double-sells.
    assert await capacity.reserve(claim={"gpu_model": "H200"}) is None

    assert [d.kind for d in deltas] == ["reserved"]
    assert deltas[0].resource_id == "pool-h200-1"


@pytest.mark.asyncio
async def test_deltas_are_anonymous_and_versions_increase(capacity, db):
    await _seed_compute_pool(db, gpu_count=2)
    deltas = _collect_deltas(capacity)

    first = await capacity.reserve(claim={"gpu_model": "H200"}, deal_ref={"escrow_uid": "0xa"})
    second = await capacity.reserve(claim={"gpu_model": "H200"}, deal_ref={"escrow_uid": "0xb"})
    assert first and second

    assert len(deltas) == 2
    assert deltas[1].version > deltas[0].version
    for delta in deltas:
        payload = vars(delta)
        assert "escrow_uid" not in payload
        assert "listing_id" not in payload


@pytest.mark.asyncio
async def test_commit_marks_allocation_leased(capacity, db):
    await _seed_compute_pool(db, gpu_count=1)
    deltas = _collect_deltas(capacity)
    reserved = await capacity.reserve(
        claim={"gpu_model": "H200"}, deal_ref={"escrow_uid": "0xesc"},
    )

    await capacity.commit(
        resource_id=str(reserved["resource_id"]),
        allocation_id=str(reserved["allocation_id"]),
        lease_end_utc="2026-06-10 12:00",
        idempotency_ref="0xesc",
    )

    resource = await db.get_resource(resource_id="pool-h200-1")
    assert resource["state"] == "leased"
    assert resource["attributes"]["lease_end_utc"] == "2026-06-10 12:00"
    assert [d.kind for d in deltas] == ["reserved", "committed"]


@pytest.mark.asyncio
async def test_release_returns_capacity_to_pool(capacity, db):
    await _seed_compute_pool(db, gpu_count=1)
    deltas = _collect_deltas(capacity)
    reserved = await capacity.reserve(claim={"gpu_model": "H200"})

    released = await capacity.release(allocation_id=str(reserved["allocation_id"]))
    assert released is not None
    assert released["state"] == "released"

    assert await capacity.probe(claim={"gpu_model": "H200"}) is not None
    assert [d.kind for d in deltas] == ["reserved", "released"]


@pytest.mark.asyncio
async def test_truncate_lease_moves_lease_end(capacity, db):
    await _seed_compute_pool(db, gpu_count=1)
    reserved = await capacity.reserve(claim={"gpu_model": "H200"})
    await capacity.commit(
        resource_id=str(reserved["resource_id"]),
        allocation_id=str(reserved["allocation_id"]),
        lease_end_utc="2026-06-10 18:00",
    )
    deltas = _collect_deltas(capacity)

    truncated = await capacity.truncate_lease(
        allocation_id=str(reserved["allocation_id"]),
        lease_end_utc="2026-06-10 12:30",
    )
    assert truncated is not None
    assert truncated["lease_end_utc"] == "2026-06-10 12:30"

    resource = await db.get_resource(resource_id="pool-h200-1")
    assert resource["attributes"]["lease_end_utc"] == "2026-06-10 12:30"
    assert [d.kind for d in deltas] == ["lease_truncated"]


@pytest.mark.asyncio
async def test_subscriber_failure_does_not_break_reserve(capacity, db):
    await _seed_compute_pool(db, gpu_count=1)

    async def broken(_delta: CapacityDelta) -> None:
        raise RuntimeError("subscriber exploded")

    capacity.subscribe(broken)
    reserved = await capacity.reserve(claim={"gpu_model": "H200"})
    assert reserved is not None


@pytest.mark.asyncio
async def test_unsubscribe_stops_delivery(capacity, db):
    await _seed_compute_pool(db, gpu_count=2)
    seen: list[CapacityDelta] = []

    async def subscriber(delta: CapacityDelta) -> None:
        seen.append(delta)

    unsubscribe = capacity.subscribe(subscriber)
    await capacity.reserve(claim={"gpu_model": "H200"})
    unsubscribe()
    await capacity.reserve(claim={"gpu_model": "H200"})

    assert len(seen) == 1


@pytest.mark.asyncio
async def test_ttl_holds_pass_through_to_the_local_ledger(capacity, db):
    """Two-phase reserve in embedded mode: the TTL lands on the
    allocation row and the hold consumes capacity until it lapses."""
    await _seed_compute_pool(db)
    held = await capacity.reserve(
        claim={"gpu_model": "H200"}, ttl_seconds=60.0,
    )
    assert held is not None
    assert held["hold_expires_at"]


@pytest.mark.asyncio
async def test_reserve_delta_closes_stale_derived_listings(capacity, db, monkeypatch):
    """The stale-listing reconcile reacts to capacity deltas, not the deal flow."""
    from domains.vms.listings.reconciler import record_derived_listing
    from market_storefront.services import publication_service

    monkeypatch.setattr(publication_service, "get_sqlite_client", lambda: db)

    await _seed_compute_pool(db, gpu_count=2)
    for gpu_count in (1, 2):
        listing_id = f"listing-{gpu_count}x"
        await db.upsert_listing(
            listing_id=listing_id,
            status="open",
            created_at="2026-01-01T00:00:00",
            updated_at="2026-01-01T00:00:00",
            offer_resource={
                "resource_id": "pool-h200-1",
                "gpu_model": "H200",
                "gpu_count": gpu_count,
                "region": "California, US",
                "sla": 99.0,
            },
            accepted_escrows=[],
            demands=[],
            fulfillment_resource=None,
            max_duration_seconds=3600,
            seller="http://seller",
        )
        record_derived_listing(
            db.db_path,
            listing_id=listing_id,
            resource_id="pool-h200-1",
            gpu_count=gpu_count,
        )

    reserved = await capacity.reserve(
        claim={"gpu_model": "H200", "gpu_count": 2},
        deal_ref={"listing_id": "listing-2x", "escrow_uid": "0xesc"},
    )
    assert reserved is not None

    statuses = {
        gpu_count: (await db.load_listing(listing_id=f"listing-{gpu_count}x"))["status"]
        for gpu_count in (1, 2)
    }
    assert statuses == {1: "closed", 2: "closed"}
