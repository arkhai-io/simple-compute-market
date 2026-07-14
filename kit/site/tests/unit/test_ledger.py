"""CapacityLedgerService: reserve/commit/release mechanics + event feed."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from market_site.db import Base
from market_site.ledger import (
    ALLOCATION_MODE_EXCLUSIVE,
    ALLOCATION_MODE_SHAREABLE,
    CapacityConflictError,
    CapacityLedgerService,
)


def _make_ledger(**kwargs) -> CapacityLedgerService:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return CapacityLedgerService(sessionmaker(bind=engine), **kwargs)


def _gpu_devices(count: int, *, start: int = 0) -> list[dict[str, str]]:
    return [
        {
            "pci_bdf": f"0000:{3 + start + index:02x}:00.0",
            "gpu_uuid": f"GPU-test-{start + index:04d}",
        }
        for index in range(count)
    ]


@pytest.fixture
def ledger() -> CapacityLedgerService:
    return _make_ledger()


@pytest.fixture
def seeded(ledger: CapacityLedgerService) -> CapacityLedgerService:
    ledger.register_resource(
        resource_id="compute-kvm1-001",
        total_units=8,
        resource_subtype="h200",
        attributes={
            "vm_host": "kvm1",
            "gpu_model": "H200",
            "region": "us-west",
            "gpu_devices": _gpu_devices(8),
        },
    )
    return ledger


def test_snapshot_reports_availability(seeded: CapacityLedgerService):
    rows = seeded.snapshot()
    assert len(rows) == 1
    assert rows[0]["resource_id"] == "compute-kvm1-001"
    assert rows[0]["available_units"] == 8
    assert rows[0]["state"] == "available"
    assert rows[0]["attributes"]["gpu_devices"] == _gpu_devices(8)


@pytest.mark.parametrize(
    ("devices", "message"),
    [
        (None, "gpu_devices to be a list"),
        ([], "exactly total_units"),
        (
            [{"pci_bdf": "not-a-bdf"}],
            "canonical PCI BDF",
        ),
        (
            [{"pci_bdf": "0000:03:00.0"}, {"pci_bdf": "0000:03:00.0"}],
            "duplicate pci_bdf",
        ),
        (
            [
                {"pci_bdf": "0000:03:00.0", "gpu_uuid": "GPU-same"},
                {"pci_bdf": "0000:04:00.0", "gpu_uuid": "GPU-same"},
            ],
            "duplicate gpu_uuid",
        ),
    ],
)
def test_vm_resource_registration_requires_exact_device_inventory(
    ledger: CapacityLedgerService,
    devices,
    message: str,
):
    total = 1 if devices is None or len(devices) == 1 else 2
    with pytest.raises(ValueError, match=message):
        ledger.register_resource(
            resource_id="invalid-vm",
            total_units=total,
            attributes={"vm_host": "kvm1", "gpu_devices": devices},
        )


def test_probe_consumes_nothing(seeded: CapacityLedgerService):
    match = seeded.probe(claim={"gpu_model": "H200", "gpu_count": 2})
    assert match is not None
    assert match["vm_host"] == "kvm1"
    assert match["allocated_gpu_count"] == 2
    assert seeded.snapshot()[0]["available_units"] == 8


def test_probe_mismatched_claim_returns_none(seeded: CapacityLedgerService):
    assert seeded.probe(claim={"gpu_model": "A100"}) is None
    assert seeded.probe(claim={"gpu_count": 9}) is None


def test_vm_claim_with_vm_host_does_not_match_hostless_resource(
    ledger: CapacityLedgerService,
):
    ledger.register_resource(
        resource_id="hostless", total_units=8, attributes={"gpu_model": "H200"},
    )
    assert ledger.probe(claim={"gpu_count": 1, "vm_host": "kvm1"}) is None
    assert ledger.probe(claim={"gpu_count": 1}) is not None


def _register_dual_mode_host(ledger: CapacityLedgerService) -> None:
    ledger.register_resource(
        resource_id="compute-host-1",
        total_units=8,
        resource_subtype="h200",
        attributes={
            "vm_host": "kvm1",
            "gpu_model": "H200",
            "physical_host_id": "physical-host-1",
            "allocation_mode": ALLOCATION_MODE_SHAREABLE,
            "gpu_devices": _gpu_devices(8),
        },
    )
    ledger.register_resource(
        resource_id="bare-metal-host-1",
        total_units=1,
        resource_subtype="h200",
        attributes={
            "machine_id": "node-1",
            "gpu_model": "H200",
            "physical_host_id": "physical-host-1",
            "allocation_mode": ALLOCATION_MODE_EXCLUSIVE,
        },
    )


def test_dual_mode_host_snapshot_exposes_vm_and_bare_metal_when_free(
    ledger: CapacityLedgerService,
):
    _register_dual_mode_host(ledger)

    by_id = {row["resource_id"]: row for row in ledger.snapshot()}

    assert by_id["compute-host-1"]["available_units"] == 8
    assert by_id["bare-metal-host-1"]["available_units"] == 1
    assert ledger.probe(
        claim={"gpu_count": 2, "vm_host": "kvm1"},
    )["resource_id"] == "compute-host-1"
    assert ledger.probe(
        claim={
            "physical_host_id": "physical-host-1",
            "allocation_mode": ALLOCATION_MODE_EXCLUSIVE,
        },
    )["resource_id"] == "bare-metal-host-1"


def test_vm_slice_allocation_blocks_bare_metal_on_same_physical_host(
    ledger: CapacityLedgerService,
):
    _register_dual_mode_host(ledger)

    vm = ledger.reserve(
        claim={"gpu_count": 2, "vm_host": "kvm1"},
        deal_ref={"escrow_uid": "0xvm"},
    )

    assert vm is not None
    by_id = {row["resource_id"]: row for row in ledger.snapshot()}
    assert by_id["compute-host-1"]["available_units"] == 6
    assert by_id["bare-metal-host-1"]["available_units"] == 0
    assert by_id["bare-metal-host-1"]["state"] == "leased"
    assert ledger.probe(
        claim={
            "physical_host_id": "physical-host-1",
            "allocation_mode": ALLOCATION_MODE_EXCLUSIVE,
        },
    ) is None

    second_vm = ledger.reserve(
        claim={"gpu_count": 6, "vm_host": "kvm1"},
        deal_ref={"escrow_uid": "0xvm2"},
    )
    assert second_vm is not None
    assert second_vm["resource_id"] == "compute-host-1"


def test_bare_metal_allocation_blocks_vm_slices_on_same_physical_host(
    ledger: CapacityLedgerService,
):
    _register_dual_mode_host(ledger)

    bare_metal = ledger.reserve(
        claim={
            "physical_host_id": "physical-host-1",
            "allocation_mode": ALLOCATION_MODE_EXCLUSIVE,
        },
        deal_ref={"escrow_uid": "0xbm"},
    )

    assert bare_metal is not None
    by_id = {row["resource_id"]: row for row in ledger.snapshot()}
    assert by_id["bare-metal-host-1"]["available_units"] == 0
    assert by_id["compute-host-1"]["available_units"] == 0
    assert by_id["compute-host-1"]["state"] == "leased"
    assert ledger.probe(claim={"gpu_count": 1, "vm_host": "kvm1"}) is None


def test_releasing_cross_mode_allocation_keeps_sibling_capacity_blocked(
    ledger: CapacityLedgerService,
):
    _register_dual_mode_host(ledger)
    bare_metal = ledger.reserve(
        claim={
            "physical_host_id": "physical-host-1",
            "allocation_mode": ALLOCATION_MODE_EXCLUSIVE,
        },
        deal_ref={"escrow_uid": "0xbm"},
    )

    ledger.update_allocation_state(bare_metal["allocation_id"], state="releasing")

    by_id = {row["resource_id"]: row for row in ledger.snapshot()}
    assert by_id["compute-host-1"]["available_units"] == 0
    assert ledger.probe(claim={"gpu_count": 1, "vm_host": "kvm1"}) is None


def test_release_restores_cross_mode_sibling_capacity(
    ledger: CapacityLedgerService,
):
    _register_dual_mode_host(ledger)
    vm = ledger.reserve(
        claim={"gpu_count": 2, "vm_host": "kvm1"},
        deal_ref={"escrow_uid": "0xvm"},
    )

    ledger.release(allocation_id=vm["allocation_id"])

    by_id = {row["resource_id"]: row for row in ledger.snapshot()}
    assert by_id["compute-host-1"]["available_units"] == 8
    assert by_id["bare-metal-host-1"]["available_units"] == 1


def test_required_attributes_remains_available_as_local_guard():
    guarded = _make_ledger(required_attributes=("vm_host",))
    guarded.register_resource(
        resource_id="hostless", total_units=8, attributes={"gpu_model": "H200"},
    )
    assert guarded.probe(claim={"gpu_count": 1}) is None


def test_generic_ledger_has_no_attribute_requirement():
    # A host without an eligibility invariant (the tokens service)
    # matches attribute-less resources and speaks the generic unit key.
    generic = _make_ledger()
    generic.register_resource(
        resource_id="svc-quota", total_units=1000, resource_type="api_credits",
    )
    match = generic.probe(claim={"units": 250})
    assert match is not None
    assert match["allocated_units"] == 250
    assert match["available_units"] == 1000  # probe consumes nothing

    reserved = generic.reserve(
        claim={"units": 250}, deal_ref={"escrow_uid": "0xq"},
    )
    assert reserved["allocated_units"] == 250
    assert reserved["available_units"] == 750
    assert generic.snapshot()[0]["available_units"] == 750

    # Open-ended commit: leased with no lease tail, never watchdog-due.
    committed = generic.commit(
        resource_id=reserved["resource_id"],
        allocation_id=reserved["allocation_id"],
    )
    assert committed["state"] == "leased"
    assert committed["lease_end_utc"] is None
    assert generic.list_lease_due(datetime.now(timezone.utc)) == []

    with pytest.raises(ValueError):
        generic.probe(claim={"units": 0})


def test_reserve_decrements_and_releases_restore(seeded: CapacityLedgerService):
    reserved = seeded.reserve(
        claim={"gpu_count": 3},
        deal_ref={"listing_id": "lst-1", "escrow_uid": "0xesc"},
    )
    assert reserved is not None
    assert reserved["allocated_gpu_count"] == 3
    assert reserved["available_gpu_count"] == 5
    assert reserved["gpu_devices"] == _gpu_devices(3)
    assert reserved["executor_ref"] == {
        "vm_host": "kvm1",
        "gpu_devices": _gpu_devices(3),
    }
    persisted = seeded.get_allocation(reserved["allocation_id"])
    assert persisted["gpu_devices"] == _gpu_devices(3)
    assert persisted["executor_ref"] == reserved["executor_ref"]
    assert seeded.snapshot()[0]["available_units"] == 5

    # Second reservation cannot exceed the remainder.
    assert seeded.reserve(claim={"gpu_count": 6}, deal_ref={}) is None

    released = seeded.release(deal_ref={"escrow_uid": "0xesc"})
    assert released is not None and released["state"] == "released"
    assert seeded.snapshot()[0]["available_units"] == 8

    # Idempotent: a second release finds nothing held.
    assert seeded.release(deal_ref={"escrow_uid": "0xesc"}) is None


def test_synchronized_buyers_cannot_double_allocate_one_gpu(
    ledger: CapacityLedgerService,
):
    """The site authority is the atomic admission point for buyer waves."""
    ledger.register_resource(
        resource_id="compute-kvm1-gpu",
        total_units=1,
        attributes={
            "vm_host": "kvm1",
            "gpu_model": "RTX 3090",
            "gpu_devices": _gpu_devices(1),
        },
    )
    release = Barrier(2)

    def reserve(escrow_uid: str):
        release.wait(timeout=5)
        return ledger.reserve(
            claim={"vm_host": "kvm1", "gpu_count": 1},
            deal_ref={"escrow_uid": escrow_uid},
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(reserve, ("0xbuyer-1", "0xbuyer-2"))
        )

    winners = [result for result in results if result is not None]
    assert len(winners) == 1
    assert ledger.snapshot()[0]["available_units"] == 0
    assert ledger.reserve(
        claim={"vm_host": "kvm1", "gpu_count": 1},
        deal_ref={"escrow_uid": "0xbuyer-3"},
    ) is None

    ledger.release(allocation_id=winners[0]["allocation_id"])
    assert ledger.snapshot()[0]["available_units"] == 1
    reused = ledger.reserve(
        claim={"vm_host": "kvm1", "gpu_count": 1},
        deal_ref={"escrow_uid": "0xbuyer-3"},
    )
    assert reused["gpu_devices"] == winners[0]["gpu_devices"]


def test_concurrent_allocations_receive_distinct_exact_gpu_devices(
    ledger: CapacityLedgerService,
):
    ledger.register_resource(
        resource_id="compute-kvm1-two-gpus",
        total_units=2,
        attributes={
            "vm_host": "kvm1",
            "gpu_model": "H200",
            "gpu_devices": _gpu_devices(2),
        },
    )
    release = Barrier(2)

    def reserve(escrow_uid: str):
        release.wait(timeout=5)
        return ledger.reserve(
            claim={"vm_host": "kvm1", "gpu_count": 1},
            deal_ref={"escrow_uid": escrow_uid},
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(reserve, ("0xbuyer-a", "0xbuyer-b")))

    assert all(result is not None for result in results)
    bdfs = [result["gpu_devices"][0]["pci_bdf"] for result in results]
    assert len(set(bdfs)) == 2
    assert set(bdfs) == {"0000:03:00.0", "0000:04:00.0"}


def test_resource_update_cannot_remove_an_allocated_exact_device(
    ledger: CapacityLedgerService,
):
    ledger.register_resource(
        resource_id="compute-kvm1-two-gpus",
        total_units=2,
        attributes={"vm_host": "kvm1", "gpu_devices": _gpu_devices(2)},
    )
    reserved = ledger.reserve(
        claim={"gpu_count": 1}, deal_ref={"escrow_uid": "0xheld"},
    )
    assert reserved["gpu_devices"] == _gpu_devices(1)

    with pytest.raises(CapacityConflictError, match="cannot remove allocated GPU"):
        ledger.register_resource(
            resource_id="compute-kvm1-two-gpus",
            total_units=1,
            attributes={"vm_host": "kvm1", "gpu_devices": _gpu_devices(1, start=1)},
        )

    # The rejected upsert leaves the original authoritative inventory intact.
    assert ledger.snapshot()[0]["attributes"]["gpu_devices"] == _gpu_devices(2)


@pytest.mark.parametrize(
    "executor_ref",
    [
        {"vm_host": "kvm1"},
        {"vm_host": "kvm1", "gpu_devices": None},
    ],
)
def test_legacy_held_vm_allocation_without_exact_devices_blocks_resource(
    ledger: CapacityLedgerService,
    executor_ref: dict,
):
    ledger.register_resource(
        resource_id="compute-kvm1-two-gpus",
        total_units=2,
        attributes={"vm_host": "kvm1", "gpu_devices": _gpu_devices(2)},
    )
    reserved = ledger.reserve(claim={"gpu_count": 1}, deal_ref={})

    from market_site.db import SiteAllocation
    with ledger._session_factory() as db:
        row = db.get(SiteAllocation, reserved["allocation_id"])
        row.executor_ref = executor_ref
        db.commit()

    assert ledger.get_allocation(reserved["allocation_id"])["gpu_devices"] == []
    assert ledger.probe(claim={"gpu_count": 1}) is None
    assert ledger.snapshot()[0]["available_units"] == 0


def test_lease_update_cannot_reassign_frozen_gpu_devices(
    seeded: CapacityLedgerService,
):
    reserved = seeded.reserve(claim={"gpu_count": 1}, deal_ref={})

    with pytest.raises(CapacityConflictError, match="GPU devices are frozen"):
        seeded.attach_lease(
            allocation_id=reserved["allocation_id"],
            executor_ref={
                "vm_host": "kvm1",
                "gpu_devices": _gpu_devices(1, start=1),
            },
        )

    assert seeded.get_allocation(reserved["allocation_id"])["executor_ref"] == (
        reserved["executor_ref"]
    )


def test_lease_update_cannot_clear_frozen_gpu_devices(
    seeded: CapacityLedgerService,
):
    reserved = seeded.reserve(claim={"gpu_count": 1}, deal_ref={})

    with pytest.raises(CapacityConflictError, match="GPU devices are frozen"):
        seeded.update_lease_fields(
            reserved["allocation_id"],
            executor_ref={"gpu_devices": None},
        )

    assert seeded.get_allocation(reserved["allocation_id"])["executor_ref"] == (
        reserved["executor_ref"]
    )


def test_shareable_sibling_resources_cannot_reuse_a_physical_gpu(
    ledger: CapacityLedgerService,
):
    shared = {
        "vm_host": "kvm1",
        "physical_host_id": "host-physical-1",
        "allocation_mode": ALLOCATION_MODE_SHAREABLE,
        "gpu_devices": _gpu_devices(2),
    }
    ledger.register_resource(
        resource_id="h200-hourly",
        total_units=2,
        resource_subtype="h200",
        attributes={**shared, "gpu_model": "H200"},
    )
    ledger.register_resource(
        resource_id="h200-discount",
        total_units=2,
        resource_subtype="h200",
        attributes={**shared, "gpu_model": "H200"},
    )

    first = ledger.reserve(
        claim={"resource_id": "h200-hourly", "gpu_count": 1}, deal_ref={},
    )
    second = ledger.reserve(
        claim={"resource_id": "h200-discount", "gpu_count": 1}, deal_ref={},
    )

    assert first["gpu_devices"] == _gpu_devices(1)
    assert second["gpu_devices"] == _gpu_devices(1, start=1)
    by_id = {row["resource_id"]: row for row in ledger.snapshot()}
    assert by_id["h200-hourly"]["available_units"] == 0
    assert by_id["h200-discount"]["available_units"] == 0


def test_idle_sibling_cannot_split_scope_while_shared_gpu_is_allocated(
    ledger: CapacityLedgerService,
):
    shared = {
        "vm_host": "kvm1",
        "physical_host_id": "host-physical-1",
        "allocation_mode": ALLOCATION_MODE_SHAREABLE,
        "gpu_devices": _gpu_devices(2),
    }
    ledger.register_resource(
        resource_id="h200-hourly",
        total_units=2,
        attributes={**shared, "gpu_model": "H200"},
    )
    ledger.register_resource(
        resource_id="h200-discount",
        total_units=2,
        attributes={**shared, "gpu_model": "H200"},
    )
    assert ledger.reserve(
        claim={"resource_id": "h200-hourly", "gpu_count": 1}, deal_ref={},
    ) is not None

    with pytest.raises(CapacityConflictError, match="physical GPU scope"):
        ledger.register_resource(
            resource_id="h200-discount",
            total_units=2,
            attributes={
                **shared,
                "physical_host_id": "forged-independent-host",
                "gpu_model": "H200",
            },
        )

    by_id = {row["resource_id"]: row for row in ledger.snapshot()}
    assert (
        by_id["h200-discount"]["attributes"]["physical_host_id"]
        == "host-physical-1"
    )


def test_future_reservation_ignores_non_overlapping_current_lease(seeded: CapacityLedgerService):
    first = seeded.reserve(
        claim={"gpu_count": 8},
        deal_ref={"escrow_uid": "0xnow"},
        lease_start_utc="2030-01-01T00:00:00Z",
        lease_duration_seconds=3600,
    )
    assert first is not None

    assert seeded.reserve(
        claim={"gpu_count": 1},
        deal_ref={"escrow_uid": "0xoverlap"},
        lease_start_utc="2030-01-01T00:30:00Z",
        lease_duration_seconds=3600,
    ) is None

    later = seeded.reserve(
        claim={"gpu_count": 8},
        deal_ref={"escrow_uid": "0xlater"},
        lease_start_utc="2030-01-01T02:00:00Z",
        lease_duration_seconds=3600,
    )
    assert later is not None
    assert later["allocated_gpu_count"] == 8
    assert later["gpu_devices"] == first["gpu_devices"]

    # Future bookings do not consume the current snapshot.
    assert seeded.snapshot()[0]["available_units"] == 8


def test_commit_marks_leased_and_sets_window(seeded: CapacityLedgerService):
    reserved = seeded.reserve(claim={"gpu_count": 1}, deal_ref={"escrow_uid": "0xa"})
    committed = seeded.commit(
        resource_id=reserved["resource_id"],
        allocation_id=reserved["allocation_id"],
        lease_start_utc="2099-01-01T00:00:00Z",
        lease_end_utc="2099-01-01T01:00:00Z",
        idempotency_ref="0xa",
    )
    assert committed["state"] == "leased"
    assert committed["lease_start_utc"] == "2099-01-01T00:00:00+00:00"
    assert committed["lease_end_utc"] == "2099-01-01T01:00:00Z"

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
    from market_site.db import SiteAllocation
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
    assert attached["executor_kind"] == "vm"
    assert attached["executor_target"] == "tenant-abcd"
    assert attached["executor_ref"] == {
        "vm_host": "kvm1",
        "gpu_devices": _gpu_devices(1),
    }
    assert attached["gpu_devices"] == _gpu_devices(1)
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
        lease_start_utc="2020-01-01T00:00:00Z",
        lease_end_utc="2020-01-01 00:00",
    )
    due = seeded.list_lease_due(datetime.now(timezone.utc))
    assert [a["allocation_id"] for a in due] == [reserved["allocation_id"]]

    releasing = seeded.begin_releasing(
        reserved["allocation_id"], vm_remove_job_id="check-1",
    )
    assert releasing["state"] == "releasing"
    assert releasing["vm_remove_job_id"] == "check-1"
    assert releasing["release_job_id"] == "check-1"
    # releasing still holds the units and is no longer "due".
    assert seeded.snapshot()[0]["available_units"] == 7
    assert seeded.list_lease_due(datetime.now(timezone.utc)) == []

    # Future leases are not due.
    future = seeded.reserve(claim={}, deal_ref={})
    seeded.commit(
        resource_id=future["resource_id"],
        allocation_id=future["allocation_id"],
        lease_start_utc="2099-01-01T00:00:00Z",
        lease_end_utc="2099-01-01 00:00",
    )
    assert seeded.list_lease_due(datetime.now(timezone.utc)) == []


def test_release_failed_still_holds_capacity(seeded: CapacityLedgerService):
    reserved = seeded.reserve(claim={"gpu_count": 2}, deal_ref={})
    seeded.commit(
        resource_id=reserved["resource_id"],
        allocation_id=reserved["allocation_id"],
        lease_start_utc="2020-01-01T00:00:00Z",
        lease_end_utc="2020-01-01 00:00",
    )
    seeded.update_allocation_state(
        reserved["allocation_id"],
        state="release_failed",
        failure_reason="vm_remove_failed",
    )
    assert seeded.snapshot()[0]["available_units"] == 6


def _shared_host_ledger() -> CapacityLedgerService:
    ledger = _make_ledger()
    ledger.register_resource(
        resource_id="host-1-vm-gpus",
        total_units=8,
        attributes={
            "physical_host_id": "host-1",
            "allocation_mode": ALLOCATION_MODE_SHAREABLE,
            "vm_host": "kvm1",
            "gpu_model": "H200",
            "gpu_devices": _gpu_devices(8),
        },
    )
    ledger.register_resource(
        resource_id="host-1-bare-metal",
        total_units=1,
        attributes={
            "physical_host_id": "host-1",
            "allocation_mode": ALLOCATION_MODE_EXCLUSIVE,
            "machine_id": "bm-node-1",
            "gpu_model": "H200",
        },
    )
    return ledger


def test_exclusive_bare_metal_claim_fails_after_vm_slice_allocation():
    ledger = _shared_host_ledger()
    vm = ledger.reserve(
        claim={"allocation_mode": ALLOCATION_MODE_SHAREABLE, "gpu_count": 2},
        deal_ref={"escrow_uid": "0xvm"},
    )
    assert vm is not None

    assert ledger.probe(claim={"allocation_mode": ALLOCATION_MODE_EXCLUSIVE}) is None
    assert ledger.reserve(
        claim={"allocation_mode": ALLOCATION_MODE_EXCLUSIVE},
        deal_ref={"escrow_uid": "0xbm"},
    ) is None

    by_id = {row["resource_id"]: row for row in ledger.snapshot()}
    assert by_id["host-1-vm-gpus"]["available_units"] == 6
    assert by_id["host-1-bare-metal"]["available_units"] == 0
    assert by_id["host-1-bare-metal"]["state"] == "leased"


def test_vm_slice_claim_fails_after_exclusive_bare_metal_allocation():
    ledger = _shared_host_ledger()
    bare_metal = ledger.reserve(
        claim={"allocation_mode": ALLOCATION_MODE_EXCLUSIVE},
        deal_ref={"escrow_uid": "0xbm"},
    )
    assert bare_metal is not None

    assert ledger.probe(
        claim={"allocation_mode": ALLOCATION_MODE_SHAREABLE, "gpu_count": 1},
    ) is None
    assert ledger.reserve(
        claim={"allocation_mode": ALLOCATION_MODE_SHAREABLE, "gpu_count": 1},
        deal_ref={"escrow_uid": "0xvm"},
    ) is None

    by_id = {row["resource_id"]: row for row in ledger.snapshot()}
    assert by_id["host-1-vm-gpus"]["available_units"] == 0
    assert by_id["host-1-vm-gpus"]["state"] == "leased"
    assert by_id["host-1-bare-metal"]["available_units"] == 0


def test_compatible_vm_slice_claims_still_share_units():
    ledger = _shared_host_ledger()
    first = ledger.reserve(
        claim={"allocation_mode": ALLOCATION_MODE_SHAREABLE, "gpu_count": 2},
        deal_ref={"escrow_uid": "0xvm1"},
    )
    second = ledger.reserve(
        claim={"allocation_mode": ALLOCATION_MODE_SHAREABLE, "gpu_count": 3},
        deal_ref={"escrow_uid": "0xvm2"},
    )

    assert first is not None
    assert second is not None
    by_id = {row["resource_id"]: row for row in ledger.snapshot()}
    assert by_id["host-1-vm-gpus"]["available_units"] == 3
    assert by_id["host-1-bare-metal"]["available_units"] == 0
    assert by_id["host-1-bare-metal"]["state"] == "leased"


def test_released_shared_host_allocation_restores_cross_mode_availability():
    ledger = _shared_host_ledger()
    vm = ledger.reserve(
        claim={"allocation_mode": ALLOCATION_MODE_SHAREABLE, "gpu_count": 8},
        deal_ref={"escrow_uid": "0xvm"},
    )
    assert ledger.reserve(
        claim={"allocation_mode": ALLOCATION_MODE_EXCLUSIVE},
        deal_ref={"escrow_uid": "0xbm-blocked"},
    ) is None

    ledger.release(allocation_id=vm["allocation_id"])

    bare_metal = ledger.reserve(
        claim={"allocation_mode": ALLOCATION_MODE_EXCLUSIVE},
        deal_ref={"escrow_uid": "0xbm"},
    )
    assert bare_metal is not None


def test_release_failed_shared_host_allocation_blocks_cross_mode_claims():
    ledger = _shared_host_ledger()
    vm = ledger.reserve(
        claim={"allocation_mode": ALLOCATION_MODE_SHAREABLE, "gpu_count": 2},
        deal_ref={"escrow_uid": "0xvm"},
    )
    ledger.update_allocation_state(
        vm["allocation_id"],
        state="release_failed",
        failure_reason="release_submit_failed",
    )

    assert ledger.reserve(
        claim={"allocation_mode": ALLOCATION_MODE_EXCLUSIVE},
        deal_ref={"escrow_uid": "0xbm"},
    ) is None
    by_id = {row["resource_id"]: row for row in ledger.snapshot()}
    assert by_id["host-1-bare-metal"]["available_units"] == 0
    assert by_id["host-1-bare-metal"]["state"] == "leased"


def test_release_can_mark_force_released(seeded: CapacityLedgerService):
    reserved = seeded.reserve(claim={}, deal_ref={})
    seeded.begin_releasing(reserved["allocation_id"])
    forced = seeded.release(allocation_id=reserved["allocation_id"], state="force_released")
    assert forced["state"] == "force_released"
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
