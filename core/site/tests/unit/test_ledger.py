"""CapacityLedgerService: reserve/commit/release mechanics + event feed."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core_site.db import Base
from core_site.ledger import CapacityConflictError, CapacityLedgerService


@pytest.fixture
def ledger() -> CapacityLedgerService:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return CapacityLedgerService(sessionmaker(bind=engine))


@pytest.fixture
def seeded(ledger: CapacityLedgerService) -> CapacityLedgerService:
    ledger.register_resource(
        resource_id="compute-kvm1-001",
        total_units=8,
        resource_subtype="h200",
        attributes={"vm_host": "kvm1", "gpu_model": "H200", "region": "us-west"},
    )
    return ledger


def test_snapshot_reports_availability(seeded: CapacityLedgerService):
    rows = seeded.snapshot()
    assert len(rows) == 1
    assert rows[0]["resource_id"] == "compute-kvm1-001"
    assert rows[0]["available_units"] == 8
    assert rows[0]["state"] == "available"


def test_probe_consumes_nothing(seeded: CapacityLedgerService):
    match = seeded.probe(claim={"gpu_model": "H200", "gpu_count": 2})
    assert match is not None
    assert match["vm_host"] == "kvm1"
    assert match["allocated_gpu_count"] == 2
    assert seeded.snapshot()[0]["available_units"] == 8


def test_probe_mismatched_claim_returns_none(seeded: CapacityLedgerService):
    assert seeded.probe(claim={"gpu_model": "A100"}) is None
    assert seeded.probe(claim={"gpu_count": 9}) is None


def test_resource_without_vm_host_is_ineligible(ledger: CapacityLedgerService):
    ledger.register_resource(
        resource_id="hostless", total_units=8, attributes={"gpu_model": "H200"},
    )
    assert ledger.probe(claim=None) is None


def test_reserve_decrements_and_releases_restore(seeded: CapacityLedgerService):
    reserved = seeded.reserve(
        claim={"gpu_count": 3},
        deal_ref={"listing_id": "lst-1", "escrow_uid": "0xesc"},
    )
    assert reserved is not None
    assert reserved["allocated_gpu_count"] == 3
    assert reserved["available_gpu_count"] == 5
    assert seeded.snapshot()[0]["available_units"] == 5

    # Second reservation cannot exceed the remainder.
    assert seeded.reserve(claim={"gpu_count": 6}, deal_ref={}) is None

    released = seeded.release(deal_ref={"escrow_uid": "0xesc"})
    assert released is not None and released["state"] == "released"
    assert seeded.snapshot()[0]["available_units"] == 8

    # Idempotent: a second release finds nothing held.
    assert seeded.release(deal_ref={"escrow_uid": "0xesc"}) is None


def test_commit_marks_leased_and_sets_window(seeded: CapacityLedgerService):
    reserved = seeded.reserve(claim={"gpu_count": 1}, deal_ref={"escrow_uid": "0xa"})
    committed = seeded.commit(
        resource_id=reserved["resource_id"],
        allocation_id=reserved["allocation_id"],
        lease_end_utc="2099-01-01 00:00",
        idempotency_ref="0xa",
    )
    assert committed["state"] == "leased"
    assert committed["lease_end_utc"] == "2099-01-01 00:00"
    assert committed["lease_start_utc"] is not None

    # Committing a released allocation conflicts.
    seeded.release(allocation_id=reserved["allocation_id"])
    with pytest.raises(CapacityConflictError):
        seeded.commit(
            resource_id=reserved["resource_id"],
            allocation_id=reserved["allocation_id"],
            lease_end_utc="2099-01-01 00:00",
        )


def test_ttl_hold_expires_without_commit(seeded: CapacityLedgerService):
    reserved = seeded.reserve(
        claim={"gpu_count": 8}, deal_ref={"escrow_uid": "0xttl"}, ttl_seconds=60,
    )
    assert reserved["hold_expires_at"] is not None
    assert seeded.reserve(claim={"gpu_count": 1}, deal_ref={}) is None

    # Backdate the hold past its TTL; the next read lapses it.
    from core_site.db import SiteAllocation
    with seeded._session_factory() as db:
        row = db.get(SiteAllocation, reserved["allocation_id"])
        row.hold_expires_at = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        ).isoformat()
        db.commit()

    assert seeded.snapshot()[0]["available_units"] == 8
    lapsed = seeded.get_allocation(reserved["allocation_id"])
    assert lapsed["state"] == "released"
    assert lapsed["failure_reason"] == "hold_expired"


def test_committed_hold_survives_ttl(seeded: CapacityLedgerService):
    reserved = seeded.reserve(
        claim={"gpu_count": 2}, deal_ref={"escrow_uid": "0xkeep"}, ttl_seconds=60,
    )
    seeded.commit(
        resource_id=reserved["resource_id"],
        allocation_id=reserved["allocation_id"],
        lease_end_utc="2099-01-01 00:00",
    )
    committed = seeded.get_allocation(reserved["allocation_id"])
    assert committed["hold_expires_at"] is None
    assert seeded.snapshot()[0]["available_units"] == 6


def test_truncate_lease_rewrites_expiry(seeded: CapacityLedgerService):
    reserved = seeded.reserve(claim={}, deal_ref={"escrow_uid": "0xt"})
    seeded.commit(
        resource_id=reserved["resource_id"],
        allocation_id=reserved["allocation_id"],
        lease_end_utc="2099-01-01 00:00",
    )
    truncated = seeded.truncate_lease(
        allocation_id=reserved["allocation_id"],
        lease_end_utc="2026-01-01 00:00",
    )
    assert truncated["lease_end_utc"] == "2026-01-01 00:00"
    assert truncated["state"] == "leased"
    assert seeded.truncate_lease(
        allocation_id="missing", lease_end_utc="2026-01-01 00:00",
    ) is None


def test_event_feed_is_versioned_and_anonymous(seeded: CapacityLedgerService):
    reserved = seeded.reserve(claim={}, deal_ref={"escrow_uid": "0xsecret"})
    seeded.commit(
        resource_id=reserved["resource_id"],
        allocation_id=reserved["allocation_id"],
        lease_end_utc="2099-01-01 00:00",
    )
    seeded.release(allocation_id=reserved["allocation_id"])

    events, latest = seeded.events_after(0)
    kinds = [e["kind"] for e in events]
    # register emits one delta, then reserve/commit/release.
    assert kinds == ["released", "reserved", "committed", "released"]
    versions = [e["version"] for e in events]
    assert versions == sorted(versions) and len(set(versions)) == len(versions)
    assert latest == versions[-1]
    # Anonymous: no deal context on the wire.
    assert all("escrow" not in str(e).lower() for e in events)

    # Paging: after the first two, only the rest come back.
    page, latest_again = seeded.events_after(versions[1])
    assert [e["version"] for e in page] == versions[2:]
    assert latest_again == latest


def test_attach_lease_records_tail_on_allocation(seeded: CapacityLedgerService):
    reserved = seeded.reserve(claim={"gpu_count": 1}, deal_ref={"escrow_uid": "0xl"})
    attached = seeded.attach_lease(
        allocation_id=reserved["allocation_id"],
        vm_host="kvm1",
        vm_target="tenant-abcd",
        lease_end_utc="2099-01-01 00:00",
        create_job_id="job-1",
    )
    assert attached["state"] == "leased"
    assert attached["vm_target"] == "tenant-abcd"
    assert attached["create_job_id"] == "job-1"
    # No availability change: attach emits no capacity event.
    events, _ = seeded.events_after(0)
    assert [e["kind"] for e in events] == ["released", "reserved"]

    # Unknown / no-longer-held allocations fall back to the legacy table.
    assert seeded.attach_lease(allocation_id="missing") is None
    seeded.release(allocation_id=reserved["allocation_id"])
    assert seeded.attach_lease(allocation_id=reserved["allocation_id"]) is None


def test_list_lease_due_and_begin_releasing(seeded: CapacityLedgerService):
    reserved = seeded.reserve(claim={}, deal_ref={"escrow_uid": "0xdue"})
    seeded.commit(
        resource_id=reserved["resource_id"],
        allocation_id=reserved["allocation_id"],
        lease_end_utc="2020-01-01 00:00",  # already expired
    )
    due = seeded.list_lease_due(datetime.now(timezone.utc))
    assert [a["allocation_id"] for a in due] == [reserved["allocation_id"]]

    releasing = seeded.begin_releasing(
        reserved["allocation_id"], check_job_id="check-1",
    )
    assert releasing["state"] == "releasing"
    assert releasing["check_job_id"] == "check-1"
    # releasing still holds the units and is no longer "due".
    assert seeded.snapshot()[0]["available_units"] == 7
    assert seeded.list_lease_due(datetime.now(timezone.utc)) == []

    # Future leases are not due.
    future = seeded.reserve(claim={}, deal_ref={})
    seeded.commit(
        resource_id=future["resource_id"],
        allocation_id=future["allocation_id"],
        lease_end_utc="2099-01-01 00:00",
    )
    assert seeded.list_lease_due(datetime.now(timezone.utc)) == []


def test_release_can_mark_forced(seeded: CapacityLedgerService):
    reserved = seeded.reserve(claim={}, deal_ref={})
    seeded.begin_releasing(reserved["allocation_id"])
    forced = seeded.release(allocation_id=reserved["allocation_id"], state="forced")
    assert forced["state"] == "forced"
    assert seeded.snapshot()[0]["available_units"] == 8


def test_claim_matches_top_level_fields(seeded: CapacityLedgerService):
    assert seeded.probe(claim={"resource_subtype": "h200"}) is not None
    assert seeded.probe(claim={"resource_id": "compute-kvm1-001"}) is not None
    assert seeded.probe(claim={"resource_id": "other"}) is None
    # Un-pooled inventory: the degenerate pool is keyed by resource_id,
    # which is what storefront claims carry as pool_id.
    assert seeded.probe(claim={"pool_id": "compute-kvm1-001"}) is not None
    assert seeded.probe(claim={"pool_id": "other-pool"}) is None


def test_gpu_count_validation(seeded: CapacityLedgerService):
    with pytest.raises(ValueError):
        seeded.probe(claim={"gpu_count": "many"})
    with pytest.raises(ValueError):
        seeded.reserve(claim={"gpu_count": 0}, deal_ref={})
