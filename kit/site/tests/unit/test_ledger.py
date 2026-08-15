"""CapacityLedgerService: reserve/commit/release mechanics + event feed."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from market_resource_pools.db import (
    Base as ResourcePoolBase,
    DEFAULT_POOL_ID,
    ResourcePool,
)

from market_site.db import Base
from market_site.ledger import (
    ALLOCATION_MODE_EXCLUSIVE,
    ALLOCATION_MODE_SHAREABLE,
    CapacityConflictError,
    CapacityLedgerService,
    UndeclaredOfferingModeError,
)


def _make_ledger(**kwargs) -> CapacityLedgerService:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    ResourcePoolBase.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as db, db.begin():
        db.add(
            ResourcePool(
                id=DEFAULT_POOL_ID,
                label="Default Pool",
                provider="test",
                enabled=True,
                policy_tags={"deliverable_modes": ["bare_metal", "vm"]},
            )
        )
    # This suite exercises VM-flavored claim shapes ("gpu_count"-only
    # reservations, "compute-kvm1-001"-style resource ids), so it opts into
    # the "gpu_count" unit-claim alias explicitly the same way the VM
    # composition root does — the ledger's own default is domain-neutral
    # ("units",).
    kwargs.setdefault("unit_claim_keys", ("units", "gpu_count"))
    return CapacityLedgerService(session_factory, **kwargs)

def _declare_pool(
    ledger: CapacityLedgerService,
    pool_id: str,
    *modes: str,
) -> None:
    with ledger._session_factory() as db, db.begin():
        db.add(
            ResourcePool(
                id=pool_id,
                label=pool_id,
                provider="test",
                enabled=True,
                policy_tags={"deliverable_modes": list(modes)},
            )
        )


@pytest.fixture
def ledger() -> CapacityLedgerService:
    return _make_ledger()


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
    match = seeded.probe(claim={"executor_kind": "vm", **{"gpu_model": "H200", "gpu_count": 2}})
    assert match is not None
    assert match["vm_host"] == "kvm1"
    assert match["allocated_gpu_count"] == 2
    assert seeded.snapshot()[0]["available_units"] == 8


def test_probe_mismatched_claim_returns_none(seeded: CapacityLedgerService):
    assert seeded.probe(claim={"executor_kind": "vm", **{"gpu_model": "A100"}}) is None
    assert seeded.probe(claim={"executor_kind": "vm", **{"gpu_count": 9}}) is None


def test_vm_claim_with_vm_host_does_not_match_hostless_resource(
    ledger: CapacityLedgerService,
):
    ledger.register_resource(
        resource_id="hostless", total_units=8, attributes={"gpu_model": "H200"},
    )
    assert ledger.probe(claim={"executor_kind": "vm", **{"gpu_count": 1, "vm_host": "kvm1"}}) is None
    assert ledger.probe(claim={"executor_kind": "vm", **{"gpu_count": 1}}) is not None


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
    assert ledger.probe(claim={"executor_kind": "vm", **{"gpu_count": 2, "vm_host": "kvm1"}})["resource_id"] == "compute-host-1"
    assert ledger.probe(claim={
        "executor_kind": "bare_metal",
        "physical_host_id": "physical-host-1",
        "allocation_mode": ALLOCATION_MODE_EXCLUSIVE,
    })["resource_id"] == "bare-metal-host-1"


def test_vm_slice_reservation_blocks_bare_metal_on_same_physical_host(
    ledger: CapacityLedgerService,
):
    _register_dual_mode_host(ledger)

    vm = ledger.reserve(claim={"executor_kind": "vm", **{"gpu_count": 2, "vm_host": "kvm1"}}, deal_ref={"escrow_uid": "0xvm"},)

    assert vm is not None
    by_id = {row["resource_id"]: row for row in ledger.snapshot()}
    assert by_id["compute-host-1"]["available_units"] == 6
    assert by_id["bare-metal-host-1"]["available_units"] == 0
    assert by_id["bare-metal-host-1"]["state"] == "leased"
    assert ledger.probe(claim={
        "executor_kind": "bare_metal",
        "physical_host_id": "physical-host-1",
        "allocation_mode": ALLOCATION_MODE_EXCLUSIVE,
    }) is None

    second_vm = ledger.reserve(claim={"executor_kind": "vm", **{"gpu_count": 6, "vm_host": "kvm1"}}, deal_ref={"escrow_uid": "0xvm2"},)
    assert second_vm is not None
    assert second_vm["resource_id"] == "compute-host-1"


def test_bare_metal_reservation_blocks_vm_slices_on_same_physical_host(
    ledger: CapacityLedgerService,
):
    _register_dual_mode_host(ledger)

    bare_metal = ledger.reserve(
        claim={
            "executor_kind": "bare_metal",
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
    assert ledger.probe(claim={"executor_kind": "vm", **{"gpu_count": 1, "vm_host": "kvm1"}}) is None


def test_releasing_cross_mode_reservation_keeps_sibling_capacity_blocked(
    ledger: CapacityLedgerService,
):
    _register_dual_mode_host(ledger)
    bare_metal = ledger.reserve(
        claim={
            "executor_kind": "bare_metal",
            "physical_host_id": "physical-host-1",
            "allocation_mode": ALLOCATION_MODE_EXCLUSIVE,
        },
        deal_ref={"escrow_uid": "0xbm"},
    )

    ledger.update_reservation_state(bare_metal["capacity_reservation_id"], state="releasing")

    by_id = {row["resource_id"]: row for row in ledger.snapshot()}
    assert by_id["compute-host-1"]["available_units"] == 0
    assert ledger.probe(claim={"executor_kind": "vm", **{"gpu_count": 1, "vm_host": "kvm1"}}) is None


def test_release_restores_cross_mode_sibling_capacity(
    ledger: CapacityLedgerService,
):
    _register_dual_mode_host(ledger)
    vm = ledger.reserve(claim={"executor_kind": "vm", **{"gpu_count": 2, "vm_host": "kvm1"}}, deal_ref={"escrow_uid": "0xvm"},)

    ledger.release(capacity_reservation_id=vm["capacity_reservation_id"])

    by_id = {row["resource_id"]: row for row in ledger.snapshot()}
    assert by_id["compute-host-1"]["available_units"] == 8
    assert by_id["bare-metal-host-1"]["available_units"] == 1


def test_required_attributes_remains_available_as_local_guard():
    guarded = _make_ledger(required_attributes=("vm_host",))
    guarded.register_resource(
        resource_id="hostless", total_units=8, attributes={"gpu_model": "H200"},
    )
    assert guarded.probe(claim={"executor_kind": "vm", **{"gpu_count": 1}}) is None


def test_generic_ledger_has_no_attribute_requirement():
    # A host without an eligibility invariant (the tokens service)
    # matches attribute-less resources and speaks the generic unit key.
    generic = _make_ledger()
    generic.register_resource(
        resource_id="svc-quota", total_units=1000, resource_type="api_credits",
    )
    match = generic.probe(claim={"executor_kind": "vm", **{"units": 250}})
    assert match is not None
    assert match["allocated_units"] == 250
    assert match["available_units"] == 1000  # probe consumes nothing

    reserved = generic.reserve(claim={"executor_kind": "vm", **{"units": 250}}, deal_ref={"escrow_uid": "0xq"},)
    assert reserved["allocated_units"] == 250
    assert reserved["available_units"] == 750
    assert generic.snapshot()[0]["available_units"] == 750

    # Open-ended commit: leased with no lease tail, never watchdog-due.
    committed = generic.commit(
        resource_id=reserved["resource_id"],
        capacity_reservation_id=reserved["capacity_reservation_id"],
    )
    assert committed["state"] == "leased"
    assert committed["lease_end_utc"] is None
    assert generic.list_lease_due(datetime.now(timezone.utc)) == []

    with pytest.raises(ValueError):
        generic.probe(claim={"executor_kind": "vm", **{"units": 0}})



def test_missing_executor_kind_is_never_inferred_from_vm_resource(
    seeded: CapacityLedgerService,
):
    with pytest.raises(ValueError, match="executor_kind"):
        seeded.reserve(claim={"gpu_count": 1}, deal_ref={})


def test_absent_or_mismatched_pool_declaration_delivers_nothing(
    seeded: CapacityLedgerService,
):
    with seeded._session_factory() as db, db.begin():
        pool = db.get(ResourcePool, DEFAULT_POOL_ID)
        pool.policy_tags = {}

    with pytest.raises(UndeclaredOfferingModeError, match="'vm'"):
        seeded.reserve(
            claim={"executor_kind": "vm", "gpu_count": 1},
            deal_ref={},
        )
    assert seeded.snapshot()[0]["available_units"] == 8

    with seeded._session_factory() as db, db.begin():
        pool = db.get(ResourcePool, DEFAULT_POOL_ID)
        pool.policy_tags = {"deliverable_modes": ["bare_metal"]}

    with pytest.raises(UndeclaredOfferingModeError, match="'vm'"):
        seeded.reserve(
            claim={"executor_kind": "vm", "gpu_count": 1},
            deal_ref={},
        )
    assert seeded.snapshot()[0]["available_units"] == 8

def test_reserve_derives_executor_ref_from_resource_vm_host(seeded: CapacityLedgerService):
    """reserve() writes executor_ref (not a dedicated vm_host column) from
    the matched resource's vm_host attribute, and derives executor_kind
    alongside it.

    reserve()'s own return payload is assembled from _match_payload (the
    resource's live attributes at match time), not _reservation_payload,
    so it never includes executor_ref/executor_kind directly. The durable
    row itself, read back via get_reservation (which does use
    _reservation_payload), is where the write actually lands.
    """
    reserved = seeded.reserve(claim={"executor_kind": "vm", **{"gpu_count": 1}}, deal_ref={"escrow_uid": "0xn"})
    assert reserved is not None
    assert reserved["vm_host"] == "kvm1"  # _match_payload, from the resource's own attributes

    row = seeded.get_reservation(reserved["capacity_reservation_id"])
    assert row["executor_ref"] == {"vm_host": "kvm1"}
    assert row["executor_kind"] == "vm"
    assert row["vm_host"] == "kvm1"  # _reservation_payload, now sourced from executor_ref


def test_reserve_decrements_and_releases_restore(seeded: CapacityLedgerService):
    reserved = seeded.reserve(claim={"executor_kind": "vm", **{"gpu_count": 3}}, deal_ref={"listing_id": "lst-1", "escrow_uid": "0xesc"},)
    assert reserved is not None
    assert reserved["allocated_gpu_count"] == 3
    assert reserved["available_gpu_count"] == 5
    assert seeded.snapshot()[0]["available_units"] == 5

    # Second reservation cannot exceed the remainder.
    assert seeded.reserve(claim={"executor_kind": "vm", **{"gpu_count": 6}}, deal_ref={}) is None

    released = seeded.release(deal_ref={"escrow_uid": "0xesc"})
    assert released is not None and released["state"] == "released"
    assert seeded.snapshot()[0]["available_units"] == 8

    # Idempotent: duplicate release returns the authoritative terminal row
    # without advancing the anonymous capacity event version.
    _, version_before = seeded.events_after(0)
    duplicate = seeded.release(capacity_reservation_id=reserved["capacity_reservation_id"])
    _, version_after = seeded.events_after(0)
    assert duplicate == released
    assert version_after == version_before


def test_reserve_is_idempotent_by_escrow_uid(seeded: CapacityLedgerService):
    """A repeat reserve() call for the same escrow_uid (e.g. a caller
    retrying after a crash, before it durably recorded the first
    reservation's identity elsewhere) must return the existing held
    reservation rather than minting a second one and double-consuming
    capacity."""
    first = seeded.reserve(claim={"executor_kind": "vm", **{"gpu_count": 3}}, deal_ref={"listing_id": "lst-1", "escrow_uid": "0xidempotent"},)
    assert first is not None
    assert seeded.snapshot()[0]["available_units"] == 5

    second = seeded.reserve(claim={"executor_kind": "vm", **{"gpu_count": 3}}, deal_ref={"listing_id": "lst-1", "escrow_uid": "0xidempotent"},)
    assert second is not None
    assert second["capacity_reservation_id"] == first["capacity_reservation_id"]
    # Capacity was not consumed a second time.
    assert seeded.snapshot()[0]["available_units"] == 5


def test_reserve_idempotent_hit_includes_resource_id(seeded: CapacityLedgerService):
    """The idempotent-hit payload must be byte-compatible with a fresh
    reservation's payload for callers that read resource_id directly
    (e.g. vm_fulfillment_service.py)."""
    first = seeded.reserve(claim={"executor_kind": "vm", **{"gpu_count": 1}}, deal_ref={"escrow_uid": "0xres"})
    second = seeded.reserve(claim={"executor_kind": "vm", **{"gpu_count": 1}}, deal_ref={"escrow_uid": "0xres"})
    assert second["resource_id"] == first["resource_id"] == "compute-kvm1-001"
    assert second["vm_host"] == first["vm_host"] == "kvm1"


def test_reserve_idempotency_finds_a_committed_reservation_too(
    seeded: CapacityLedgerService,
):
    """Idempotency must not be limited to the TTL-hold (``reserved``)
    state -- a caller retrying after the first attempt already progressed
    to a committed lease must still find it, not double-reserve."""
    reserved = seeded.reserve(claim={"executor_kind": "vm", **{"gpu_count": 1}}, deal_ref={"escrow_uid": "0xcommitted"})
    seeded.commit(
        resource_id=reserved["resource_id"],
        capacity_reservation_id=reserved["capacity_reservation_id"],
        lease_end_utc="2099-01-01 00:00",
    )
    retried = seeded.reserve(claim={"executor_kind": "vm", **{"gpu_count": 1}}, deal_ref={"escrow_uid": "0xcommitted"})
    assert retried["capacity_reservation_id"] == reserved["capacity_reservation_id"]
    assert retried["state"] == "leased"


def test_reserve_without_escrow_uid_is_never_idempotent(seeded: CapacityLedgerService):
    """No escrow_uid means no idempotency key -- every call reserves
    fresh, matching pre-existing behavior for callers that don't supply
    one."""
    first = seeded.reserve(claim={"executor_kind": "vm", **{"gpu_count": 1}}, deal_ref={})
    second = seeded.reserve(claim={"executor_kind": "vm", **{"gpu_count": 1}}, deal_ref={})
    assert first["capacity_reservation_id"] != second["capacity_reservation_id"]
    assert seeded.snapshot()[0]["available_units"] == 6


def test_reserve_after_hold_expiry_reserves_fresh_for_the_same_escrow_uid(
    seeded: CapacityLedgerService,
):
    """An escrow_uid whose prior hold already expired (moved out of
    HELD_RESERVATION_STATES by _expire_stale_holds) must not be treated
    as an idempotent hit -- a genuinely new attempt after expiry reserves
    fresh, exactly as it did before this idempotency check existed."""
    from market_site.db import CapacityReservation

    first = seeded.reserve(claim={"executor_kind": "vm", **{"gpu_count": 1}}, deal_ref={"escrow_uid": "0xexpired"}, ttl_seconds=60,)
    with seeded._session_factory() as db:
        row = db.get(CapacityReservation, first["capacity_reservation_id"])
        row.hold_expires_at = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        ).isoformat()
        db.commit()

    second = seeded.reserve(claim={"executor_kind": "vm", **{"gpu_count": 1}}, deal_ref={"escrow_uid": "0xexpired"})
    assert second is not None
    assert second["capacity_reservation_id"] != first["capacity_reservation_id"]


def test_future_reservation_ignores_non_overlapping_current_lease(seeded: CapacityLedgerService):
    first = seeded.reserve(claim={"executor_kind": "vm", **{"gpu_count": 8}}, deal_ref={"escrow_uid": "0xnow"},
    lease_start_utc="2030-01-01T00:00:00Z",
    lease_duration_seconds=3600,)
    assert first is not None

    assert seeded.reserve(claim={"executor_kind": "vm", **{"gpu_count": 1}}, deal_ref={"escrow_uid": "0xoverlap"},
    lease_start_utc="2030-01-01T00:30:00Z",
    lease_duration_seconds=3600,) is None

    later = seeded.reserve(claim={"executor_kind": "vm", **{"gpu_count": 8}}, deal_ref={"escrow_uid": "0xlater"},
    lease_start_utc="2030-01-01T02:00:00Z",
    lease_duration_seconds=3600,)
    assert later is not None
    assert later["allocated_gpu_count"] == 8

    # Future bookings do not consume the current snapshot.
    assert seeded.snapshot()[0]["available_units"] == 8


def test_commit_marks_leased_and_sets_window(seeded: CapacityLedgerService):
    reserved = seeded.reserve(claim={"executor_kind": "vm", **{"gpu_count": 1}}, deal_ref={"escrow_uid": "0xa"})
    committed = seeded.commit(
        resource_id=reserved["resource_id"],
        capacity_reservation_id=reserved["capacity_reservation_id"],
        lease_start_utc="2099-01-01T00:00:00Z",
        lease_end_utc="2099-01-01T01:00:00Z",
        idempotency_ref="0xa",
    )
    assert committed["state"] == "leased"
    assert committed["lease_start_utc"] == "2099-01-01T00:00:00+00:00"
    assert committed["lease_end_utc"] == "2099-01-01T01:00:00Z"

    # Committing a released reservation conflicts.
    seeded.release(capacity_reservation_id=reserved["capacity_reservation_id"])
    with pytest.raises(CapacityConflictError):
        seeded.commit(
            resource_id=reserved["resource_id"],
            capacity_reservation_id=reserved["capacity_reservation_id"],
            lease_end_utc="2099-01-01 00:00",
        )


def test_commit_with_no_resource_id_behaves_identically_to_supplying_it(
    seeded: CapacityLedgerService,
):
    """commit() already ignores resource_id whenever capacity_reservation_id
    is supplied -- confirms that holds for every caller, not just callers
    that omit it explicitly, and stays true if it is ever omitted entirely
    rather than passed as None."""
    with_resource_id = seeded.reserve(claim={"executor_kind": "vm", **{"gpu_count": 1}}, deal_ref={"escrow_uid": "0xb1"})
    without_resource_id = seeded.reserve(claim={"executor_kind": "vm", **{"gpu_count": 1}}, deal_ref={"escrow_uid": "0xb2"})

    committed_with = seeded.commit(
        resource_id=with_resource_id["resource_id"],
        capacity_reservation_id=with_resource_id["capacity_reservation_id"],
        lease_start_utc="2099-01-01T00:00:00Z",
        lease_end_utc="2099-01-01T01:00:00Z",
        idempotency_ref="0xb1",
    )
    committed_without = seeded.commit(
        resource_id=None,
        capacity_reservation_id=without_resource_id["capacity_reservation_id"],
        lease_start_utc="2099-01-01T00:00:00Z",
        lease_end_utc="2099-01-01T01:00:00Z",
        idempotency_ref="0xb2",
    )

    assert committed_with["state"] == committed_without["state"] == "leased"
    assert (
        committed_with["lease_start_utc"]
        == committed_without["lease_start_utc"]
        == "2099-01-01T00:00:00+00:00"
    )
    assert (
        committed_with["lease_end_utc"]
        == committed_without["lease_end_utc"]
        == "2099-01-01T01:00:00Z"
    )

    # And omitting the keyword argument entirely (not even passing None)
    # is the same call, since resource_id already defaults to None.
    third = seeded.reserve(claim={"executor_kind": "vm", **{"gpu_count": 1}}, deal_ref={"escrow_uid": "0xb3"})
    committed_omitted = seeded.commit(
        capacity_reservation_id=third["capacity_reservation_id"],
        lease_start_utc="2099-01-01T00:00:00Z",
        lease_end_utc="2099-01-01T01:00:00Z",
        idempotency_ref="0xb3",
    )
    assert committed_omitted["state"] == "leased"


def test_ttl_hold_expires_without_commit(seeded: CapacityLedgerService):
    reserved = seeded.reserve(claim={"executor_kind": "vm", **{"gpu_count": 8}}, deal_ref={"escrow_uid": "0xttl"}, ttl_seconds=60,)
    assert reserved["hold_expires_at"] is not None
    assert seeded.reserve(claim={"executor_kind": "vm", **{"gpu_count": 1}}, deal_ref={}) is None

    # Backdate the hold past its TTL; the next read lapses it.
    from market_site.db import CapacityReservation
    with seeded._session_factory() as db:
        row = db.get(CapacityReservation, reserved["capacity_reservation_id"])
        row.hold_expires_at = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        ).isoformat()
        db.commit()

    assert seeded.snapshot()[0]["available_units"] == 8
    lapsed = seeded.get_reservation(reserved["capacity_reservation_id"])
    assert lapsed["state"] == "released"
    assert lapsed["failure_reason"] == "hold_expired"


def test_expire_due_holds_reclaims_without_another_ledger_call(
    seeded: CapacityLedgerService,
):
    """The watchdog's public entry point, exercised directly rather than
    via the lazy sweep every reserve/commit/release already runs."""
    reserved = seeded.reserve(claim={"executor_kind": "vm", **{"gpu_count": 8}}, deal_ref={"escrow_uid": "0xwatchdog"}, ttl_seconds=60,)
    assert reserved["hold_expires_at"] is not None

    from market_site.db import CapacityReservation
    with seeded._session_factory() as db:
        row = db.get(CapacityReservation, reserved["capacity_reservation_id"])
        row.hold_expires_at = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        ).isoformat()
        db.commit()

    # No reserve/commit/release/probe call in between — only the public
    # sweep entry point a periodic watchdog would call.
    seeded.expire_due_holds()

    lapsed = seeded.get_reservation(reserved["capacity_reservation_id"])
    assert lapsed["state"] == "released"
    assert lapsed["failure_reason"] == "hold_expired"


def test_committed_hold_survives_ttl(seeded: CapacityLedgerService):
    reserved = seeded.reserve(claim={"executor_kind": "vm", **{"gpu_count": 2}}, deal_ref={"escrow_uid": "0xkeep"}, ttl_seconds=60,)
    seeded.commit(
        resource_id=reserved["resource_id"],
        capacity_reservation_id=reserved["capacity_reservation_id"],
        lease_end_utc="2099-01-01 00:00",
    )
    committed = seeded.get_reservation(reserved["capacity_reservation_id"])
    assert committed["hold_expires_at"] is None
    assert seeded.snapshot()[0]["available_units"] == 6


def test_truncate_lease_rewrites_expiry(seeded: CapacityLedgerService):
    reserved = seeded.reserve(claim={"executor_kind": "vm", **{}}, deal_ref={"escrow_uid": "0xt"})
    seeded.commit(
        resource_id=reserved["resource_id"],
        capacity_reservation_id=reserved["capacity_reservation_id"],
        lease_end_utc="2099-01-01 00:00",
    )
    truncated = seeded.truncate_lease(
        capacity_reservation_id=reserved["capacity_reservation_id"],
        lease_end_utc="2026-01-01 00:00",
    )
    assert truncated["lease_end_utc"] == "2026-01-01 00:00"
    assert truncated["state"] == "leased"
    assert seeded.truncate_lease(
        capacity_reservation_id="missing", lease_end_utc="2026-01-01 00:00",
    ) is None


def test_event_feed_is_versioned_and_anonymous(seeded: CapacityLedgerService):
    reserved = seeded.reserve(claim={"executor_kind": "vm", **{}}, deal_ref={"escrow_uid": "0xsecret"})
    seeded.commit(
        resource_id=reserved["resource_id"],
        capacity_reservation_id=reserved["capacity_reservation_id"],
        lease_end_utc="2099-01-01 00:00",
    )
    seeded.release(capacity_reservation_id=reserved["capacity_reservation_id"])

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


def test_attach_lease_records_tail_on_reservation(seeded: CapacityLedgerService):
    """CapacityReservation carries no VM-domain-specific column names --
    callers pass executor_kind/executor_target/executor_ref directly (as
    kit/site/authority.py's adapter already does); attach_lease no longer
    accepts or self-heals a vm_host/vm_target kwarg.
    """
    reserved = seeded.reserve(claim={"executor_kind": "vm", **{"gpu_count": 1}}, deal_ref={"escrow_uid": "0xl"})
    attached = seeded.attach_lease(
        capacity_reservation_id=reserved["capacity_reservation_id"],
        executor_kind="vm",
        executor_target="tenant-abcd",
        executor_ref={"vm_host": "kvm1"},
        lease_end_utc="2099-01-01 00:00",
        create_job_id="job-1",
    )
    assert attached["state"] == "leased"
    assert attached["vm_target"] == "tenant-abcd"  # payload key, sourced from executor_target
    assert attached["executor_kind"] == "vm"
    assert attached["executor_target"] == "tenant-abcd"
    assert attached["executor_ref"] == {"vm_host": "kvm1"}
    assert attached["create_job_id"] == "job-1"
    # No availability change: attach emits no capacity event.
    events, _ = seeded.events_after(0)
    assert [e["kind"] for e in events] == ["released", "reserved"]

    # Unknown / no-longer-held reservations fall back to the legacy table.
    assert seeded.attach_lease(capacity_reservation_id="missing") is None


def test_find_active_lease_by_vm_target_matches_via_executor_ref(seeded: CapacityLedgerService):
    """vm_host is matched through executor_ref's JSON payload
    (func.json_extract) and vm_target through executor_target -- neither
    is a dedicated column. Previously untested -- this is new coverage,
    not just a migration of an existing test."""
    reserved = seeded.reserve(claim={"executor_kind": "vm", **{"gpu_count": 1}}, deal_ref={"escrow_uid": "0xm"})
    seeded.attach_lease(
        capacity_reservation_id=reserved["capacity_reservation_id"],
        executor_kind="vm",
        executor_target="tenant-find-me",
        executor_ref={"vm_host": "kvm1"},
        lease_end_utc="2099-01-01 00:00",
    )

    found = seeded.find_active_lease_by_vm_target("kvm1", "tenant-find-me")
    assert found is not None
    assert found["capacity_reservation_id"] == reserved["capacity_reservation_id"]

    # A different vm_host must not match, even with the same vm_target --
    # proves the filter actually discriminates on the JSON value rather
    # than matching any row with a non-null executor_ref.
    assert seeded.find_active_lease_by_vm_target("kvm-wrong-host", "tenant-find-me") is None
    # A different vm_target must not match either.
    assert seeded.find_active_lease_by_vm_target("kvm1", "tenant-someone-else") is None
    seeded.release(capacity_reservation_id=reserved["capacity_reservation_id"])
    assert seeded.attach_lease(capacity_reservation_id=reserved["capacity_reservation_id"]) is None


def test_list_lease_due_and_begin_releasing(seeded: CapacityLedgerService):
    reserved = seeded.reserve(claim={"executor_kind": "vm", **{}}, deal_ref={"escrow_uid": "0xdue"})
    seeded.commit(
        resource_id=reserved["resource_id"],
        capacity_reservation_id=reserved["capacity_reservation_id"],
        lease_start_utc="2020-01-01T00:00:00Z",
        lease_end_utc="2020-01-01 00:00",
    )
    due = seeded.list_lease_due(datetime.now(timezone.utc))
    assert [a["capacity_reservation_id"] for a in due] == [reserved["capacity_reservation_id"]]

    releasing = seeded.begin_releasing(
        reserved["capacity_reservation_id"], vm_remove_job_id="check-1",
    )
    assert releasing["state"] == "releasing"
    assert releasing["vm_remove_job_id"] == "check-1"
    assert releasing["release_job_id"] == "check-1"
    # releasing still holds the units and is no longer "due".
    assert seeded.snapshot()[0]["available_units"] == 7
    assert seeded.list_lease_due(datetime.now(timezone.utc)) == []

    # Future leases are not due.
    future = seeded.reserve(claim={"executor_kind": "vm", **{}}, deal_ref={})
    seeded.commit(
        resource_id=future["resource_id"],
        capacity_reservation_id=future["capacity_reservation_id"],
        lease_start_utc="2099-01-01T00:00:00Z",
        lease_end_utc="2099-01-01 00:00",
    )
    assert seeded.list_lease_due(datetime.now(timezone.utc)) == []


def test_release_failed_still_holds_capacity(seeded: CapacityLedgerService):
    reserved = seeded.reserve(claim={"executor_kind": "vm", **{"gpu_count": 2}}, deal_ref={})
    seeded.commit(
        resource_id=reserved["resource_id"],
        capacity_reservation_id=reserved["capacity_reservation_id"],
        lease_start_utc="2020-01-01T00:00:00Z",
        lease_end_utc="2020-01-01 00:00",
    )
    seeded.update_reservation_state(
        reserved["capacity_reservation_id"],
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


def test_exclusive_bare_metal_claim_fails_after_vm_slice_reservation():
    ledger = _shared_host_ledger()
    vm = ledger.reserve(claim={"executor_kind": "vm", **{"allocation_mode": ALLOCATION_MODE_SHAREABLE, "gpu_count": 2}}, deal_ref={"escrow_uid": "0xvm"},)
    assert vm is not None

    assert ledger.probe(
        claim={
            "executor_kind": "bare_metal",
            "allocation_mode": ALLOCATION_MODE_EXCLUSIVE,
        }
    ) is None
    assert ledger.reserve(
        claim={
            "executor_kind": "bare_metal",
            "allocation_mode": ALLOCATION_MODE_EXCLUSIVE,
        },
        deal_ref={"escrow_uid": "0xbm"},
    ) is None

    by_id = {row["resource_id"]: row for row in ledger.snapshot()}
    assert by_id["host-1-vm-gpus"]["available_units"] == 6
    assert by_id["host-1-bare-metal"]["available_units"] == 0
    assert by_id["host-1-bare-metal"]["state"] == "leased"


def test_vm_slice_claim_fails_after_exclusive_bare_metal_reservation():
    ledger = _shared_host_ledger()
    bare_metal = ledger.reserve(
        claim={
            "executor_kind": "bare_metal",
            "allocation_mode": ALLOCATION_MODE_EXCLUSIVE,
        },
        deal_ref={"escrow_uid": "0xbm"},
    )
    assert bare_metal is not None

    assert ledger.probe(claim={"executor_kind": "vm", **{"allocation_mode": ALLOCATION_MODE_SHAREABLE, "gpu_count": 1}}) is None
    assert ledger.reserve(claim={"executor_kind": "vm", **{"allocation_mode": ALLOCATION_MODE_SHAREABLE, "gpu_count": 1}}, deal_ref={"escrow_uid": "0xvm"},) is None

    by_id = {row["resource_id"]: row for row in ledger.snapshot()}
    assert by_id["host-1-vm-gpus"]["available_units"] == 0
    assert by_id["host-1-vm-gpus"]["state"] == "leased"
    assert by_id["host-1-bare-metal"]["available_units"] == 0


def test_compatible_vm_slice_claims_still_share_units():
    ledger = _shared_host_ledger()
    first = ledger.reserve(claim={"executor_kind": "vm", **{"allocation_mode": ALLOCATION_MODE_SHAREABLE, "gpu_count": 2}}, deal_ref={"escrow_uid": "0xvm1"},)
    second = ledger.reserve(claim={"executor_kind": "vm", **{"allocation_mode": ALLOCATION_MODE_SHAREABLE, "gpu_count": 3}}, deal_ref={"escrow_uid": "0xvm2"},)

    assert first is not None
    assert second is not None
    by_id = {row["resource_id"]: row for row in ledger.snapshot()}
    assert by_id["host-1-vm-gpus"]["available_units"] == 3
    assert by_id["host-1-bare-metal"]["available_units"] == 0
    assert by_id["host-1-bare-metal"]["state"] == "leased"


def test_released_shared_host_reservation_restores_cross_mode_availability():
    ledger = _shared_host_ledger()
    vm = ledger.reserve(claim={"executor_kind": "vm", **{"allocation_mode": ALLOCATION_MODE_SHAREABLE, "gpu_count": 8}}, deal_ref={"escrow_uid": "0xvm"},)
    assert ledger.reserve(
        claim={
            "executor_kind": "bare_metal",
            "allocation_mode": ALLOCATION_MODE_EXCLUSIVE,
        },
        deal_ref={"escrow_uid": "0xbm-blocked"},
    ) is None

    ledger.release(capacity_reservation_id=vm["capacity_reservation_id"])

    bare_metal = ledger.reserve(
        claim={
            "executor_kind": "bare_metal",
            "allocation_mode": ALLOCATION_MODE_EXCLUSIVE,
        },
        deal_ref={"escrow_uid": "0xbm"},
    )
    assert bare_metal is not None


def test_release_failed_shared_host_reservation_blocks_cross_mode_claims():
    ledger = _shared_host_ledger()
    vm = ledger.reserve(claim={"executor_kind": "vm", **{"allocation_mode": ALLOCATION_MODE_SHAREABLE, "gpu_count": 2}}, deal_ref={"escrow_uid": "0xvm"},)
    ledger.update_reservation_state(
        vm["capacity_reservation_id"],
        state="release_failed",
        failure_reason="release_submit_failed",
    )

    assert ledger.reserve(
        claim={
            "executor_kind": "bare_metal",
            "allocation_mode": ALLOCATION_MODE_EXCLUSIVE,
        },
        deal_ref={"escrow_uid": "0xbm"},
    ) is None
    by_id = {row["resource_id"]: row for row in ledger.snapshot()}
    assert by_id["host-1-bare-metal"]["available_units"] == 0
    assert by_id["host-1-bare-metal"]["state"] == "leased"


def test_release_can_mark_force_released(seeded: CapacityLedgerService):
    reserved = seeded.reserve(claim={"executor_kind": "vm", **{}}, deal_ref={})
    seeded.begin_releasing(reserved["capacity_reservation_id"])
    forced = seeded.release(capacity_reservation_id=reserved["capacity_reservation_id"], state="force_released")
    assert forced["state"] == "force_released"
    assert seeded.snapshot()[0]["available_units"] == 8


def test_claim_matches_top_level_fields(seeded: CapacityLedgerService):
    assert seeded.probe(claim={"executor_kind": "vm", **{"resource_subtype": "h200"}}) is not None
    assert seeded.probe(claim={"executor_kind": "vm", **{"resource_id": "compute-kvm1-001"}}) is not None
    assert seeded.probe(claim={"executor_kind": "vm", **{"resource_id": "other"}}) is None
    # Un-pooled inventory: the degenerate pool is keyed by resource_id,
    # which is what storefront claims carry as pool_id.
    assert seeded.probe(claim={"executor_kind": "vm", **{"pool_id": "compute-kvm1-001"}}) is not None
    assert seeded.probe(claim={"executor_kind": "vm", **{"pool_id": "other-pool"}}) is None


def test_gpu_count_validation(seeded: CapacityLedgerService):
    with pytest.raises(ValueError):
        seeded.probe(claim={"executor_kind": "vm", **{"gpu_count": "many"}})
    with pytest.raises(ValueError):
        seeded.reserve(claim={"executor_kind": "vm", **{"gpu_count": 0}}, deal_ref={})


# ----------------------------------------------------------------------
# multidimensional capacity
# ----------------------------------------------------------------------

@pytest.fixture
def multidim(ledger: CapacityLedgerService) -> CapacityLedgerService:
    ledger.register_resource(
        resource_id="compute-kvm2-001",
        total_units=8,
        resource_subtype="h200",
        attributes={"vm_host": "kvm2", "gpu_model": "H200", "region": "us-west"},
        capacity={"gpu_count": 8, "vcpu_count": 64, "ram_gb": 512, "disk_gb": 4000},
    )
    return ledger


def test_register_resource_reports_multidimensional_capacity(
    multidim: CapacityLedgerService,
):
    row = multidim.snapshot()[0]
    assert row["capacity"] == {"gpu_count": 8, "vcpu_count": 64, "ram_gb": 512, "disk_gb": 4000}
    assert row["available"] == {"gpu_count": 8, "vcpu_count": 64, "ram_gb": 512, "disk_gb": 4000}
    # total_units mirrors capacity["gpu_count"] for payload compatibility.
    assert row["available_units"] == 8


def test_dimension_claim_fits_and_holds_every_dimension(
    multidim: CapacityLedgerService,
):
    reserved = multidim.reserve(claim={"executor_kind": "vm", **{"dimensions": {"gpu_count": 2, "vcpu_count": 8, "ram_gb": 64, "disk_gb": 500}}}, deal_ref={"escrow_uid": "0xdim"},)
    assert reserved is not None
    assert reserved["dimensions"] == {"gpu_count": 2, "vcpu_count": 8, "ram_gb": 64, "disk_gb": 500}
    assert reserved["available"] == {
        "gpu_count": 6, "vcpu_count": 56, "ram_gb": 448, "disk_gb": 3500,
    }
    row = multidim.snapshot()[0]
    assert row["available"] == {
        "gpu_count": 6, "vcpu_count": 56, "ram_gb": 448, "disk_gb": 3500,
    }
    # Legacy single-quantity fields still mirror the primary dimension.
    assert reserved["allocated_gpu_count"] == 2
    assert reserved["available_gpu_count"] == 6


def test_dimension_claim_rejected_when_secondary_dimension_does_not_fit(
    multidim: CapacityLedgerService,
):
    """GPU count alone would fit; RAM would not -- must still be rejected.
    """
    assert multidim.probe(claim={"executor_kind": "vm", **{"dimensions": {"gpu_count": 1, "ram_gb": 9999}}}) is None
    assert multidim.reserve(claim={"executor_kind": "vm", **{"dimensions": {"gpu_count": 1, "ram_gb": 9999}}}, deal_ref={"escrow_uid": "0xtoobig"},) is None
    # Capacity is untouched by the rejected attempt.
    assert multidim.snapshot()[0]["available"]["ram_gb"] == 512


def test_dimension_claim_rejected_for_dimension_resource_never_declares(
    multidim: CapacityLedgerService,
):
    """A dimension the candidate never mentions can't be assumed to have
    room -- distinct from "declared but full"."""
    assert multidim.probe(claim={"executor_kind": "vm", **{"dimensions": {"gpu_count": 1, "network_bandwidth_gbps": 10}}}) is None


def test_concurrent_shareable_holds_accumulate_per_dimension(
    multidim: CapacityLedgerService,
):
    """Two separate holds on one shareable resource must both be counted
    against RAM, not just against GPU count -- the correctness gap a
    declared-capacity-only gate would have missed."""
    first = multidim.reserve(claim={"executor_kind": "vm", **{"dimensions": {"gpu_count": 1, "ram_gb": 300}}}, deal_ref={"escrow_uid": "0xfirst"},)
    assert first is not None
    # A second hold that alone would fit RAM's remainder does fit...
    second = multidim.reserve(claim={"executor_kind": "vm", **{"dimensions": {"gpu_count": 1, "ram_gb": 200}}}, deal_ref={"escrow_uid": "0xsecond"},)
    assert second is not None
    # ...but a third that would push combined RAM over capacity must not.
    assert multidim.reserve(claim={"executor_kind": "vm", **{"dimensions": {"gpu_count": 1, "ram_gb": 50}}}, deal_ref={"escrow_uid": "0xthird"},) is None
    assert multidim.snapshot()[0]["available"]["ram_gb"] == 12


def test_legacy_claim_without_dimensions_still_works_on_multidim_resource(
    multidim: CapacityLedgerService,
):
    reserved = multidim.reserve(claim={"executor_kind": "vm", **{"gpu_count": 3}}, deal_ref={"escrow_uid": "0xlegacy"},)
    assert reserved is not None
    assert reserved["allocated_gpu_count"] == 3
    assert reserved["available_gpu_count"] == 5
    # Legacy claims never mention the secondary dimensions, so they are
    # not checked or held -- documented pass-1 scope, not a regression:
    # legacy claims behave exactly as they did before this change.
    assert multidim.snapshot()[0]["available"]["ram_gb"] == 512


def test_pre_migration_resource_falls_back_to_gpu_count_only_capacity(
    seeded: CapacityLedgerService,
):
    """A resource registered without ``capacity`` only ever declares
    gpu_count. Any other requested dimension correctly fails to fit
    rather than being silently ignored."""
    assert seeded.probe(claim={"executor_kind": "vm", **{"dimensions": {"gpu_count": 1}}}) is not None
    assert seeded.probe(claim={"executor_kind": "vm", **{"dimensions": {"gpu_count": 1, "ram_gb": 1}}}) is None


def test_release_restores_every_dimension(multidim: CapacityLedgerService):
    reserved = multidim.reserve(claim={"executor_kind": "vm", **{"dimensions": {"gpu_count": 2, "vcpu_count": 8, "ram_gb": 64, "disk_gb": 500}}}, deal_ref={"escrow_uid": "0xrelease"},)
    multidim.release(capacity_reservation_id=reserved["capacity_reservation_id"])
    row = multidim.snapshot()[0]
    assert row["available"] == {"gpu_count": 8, "vcpu_count": 64, "ram_gb": 512, "disk_gb": 4000}


def test_capacity_events_carry_signed_per_dimension_deltas(
    multidim: CapacityLedgerService,
):
    reserved = multidim.reserve(claim={"executor_kind": "vm", **{"dimensions": {"gpu_count": 2, "ram_gb": 64}}}, deal_ref={"escrow_uid": "0xevt"},)
    multidim.release(capacity_reservation_id=reserved["capacity_reservation_id"])
    events, _ = multidim.events_after(0)
    by_kind = {e["kind"]: e for e in events}
    assert by_kind["reserved"]["dimensions"] == {"gpu_count": -2, "ram_gb": -64}
    assert by_kind["released"]["dimensions"] == {"gpu_count": 2, "ram_gb": 64}


def test_registration_event_delta_is_capacity_minus_previous_capacity(
    ledger: CapacityLedgerService,
):
    ledger.register_resource(
        resource_id="growing", total_units=2, capacity={"gpu_count": 2, "ram_gb": 100},
    )
    ledger.register_resource(
        resource_id="growing", total_units=4, capacity={"gpu_count": 4, "ram_gb": 100},
    )
    events, _ = ledger.events_after(0)
    deltas = [e["dimensions"] for e in events if e["resource_id"] == "growing"]
    assert deltas[0] == {"gpu_count": 2, "ram_gb": 100}
    assert deltas[1] == {"gpu_count": 2, "ram_gb": 0}

def test_explicit_empty_dimensions_map_is_rejected(seeded: CapacityLedgerService):
    """{"dimensions": {}} declares nothing to request -- must fail loudly,
    not silently fall through to the legacy single-quantity default of 1.
    Presence, not truthiness, is what must be checked here."""
    with pytest.raises(ValueError):
        seeded.probe(claim={"executor_kind": "vm", **{"dimensions": {}}})
    with pytest.raises(ValueError):
        seeded.reserve(claim={"executor_kind": "vm", **{"dimensions": {}}}, deal_ref={})


@pytest.mark.parametrize("raw", [[], "not-a-mapping", None, 5])
def test_malformed_dimensions_types_are_rejected(seeded: CapacityLedgerService, raw):
    with pytest.raises(ValueError):
        seeded.probe(claim={"executor_kind": "vm", **{"dimensions": raw}})


@pytest.mark.parametrize("value", [0, -1, "not-a-number"])
def test_dimensions_values_must_be_positive_numbers(
    seeded: CapacityLedgerService, value,
):
    with pytest.raises(ValueError):
        seeded.probe(claim={"executor_kind": "vm", **{"dimensions": {"gpu_count": value}}})


def test_dimensions_reject_nan_and_infinity(seeded: CapacityLedgerService):
    """NaN/Infinity parse cleanly into Decimal but raise InvalidOperation
    on comparison -- must surface as the same clean ValueError as any
    other malformed quantity, not an uncaught decimal.InvalidOperation
    """
    with pytest.raises(ValueError):
        seeded.probe(claim={"executor_kind": "vm", **{"dimensions": {"gpu_count": float("nan")}}})
    with pytest.raises(ValueError):
        seeded.probe(claim={"executor_kind": "vm", **{"dimensions": {"gpu_count": float("inf")}}})


def test_register_resource_rejects_conflicting_total_units_and_capacity(
    ledger: CapacityLedgerService,
):
    """total_units is documented as a mirror of capacity['gpu_count']; two
    disagreeing values is a caller bug, not something to silently resolve
    in capacity's favor."""
    with pytest.raises(ValueError):
        ledger.register_resource(
            resource_id="conflicted", total_units=8, capacity={"gpu_count": 4},
        )
    # Consistent values are fine.
    ledger.register_resource(
        resource_id="consistent", total_units=8, capacity={"gpu_count": 8, "ram_gb": 64},
    )
    assert ledger.snapshot()[0]["capacity"]["gpu_count"] == 8


def test_mixed_direction_capacity_change_gets_neutral_event_kind(
    ledger: CapacityLedgerService,
):
    """GPU count growing while RAM shrinks has no single grew/shrank
    direction -- must not be mislabeled "released" (implying availability
    only increased) or "reserved"."""
    ledger.register_resource(
        resource_id="host-1", total_units=4, capacity={"gpu_count": 4, "ram_gb": 512},
    )
    ledger.register_resource(
        resource_id="host-1", total_units=8, capacity={"gpu_count": 8, "ram_gb": 128},
    )
    events, _ = ledger.events_after(0)
    kinds = [e["kind"] for e in events if e["resource_id"] == "host-1"]
    assert kinds == ["released", "capacity_changed"]


def test_pure_grow_and_pure_shrink_keep_their_kind(ledger: CapacityLedgerService):
    ledger.register_resource(
        resource_id="r", total_units=4, capacity={"gpu_count": 4, "ram_gb": 100},
    )
    ledger.register_resource(
        resource_id="r", total_units=8, capacity={"gpu_count": 8, "ram_gb": 200},
    )
    ledger.register_resource(
        resource_id="r", total_units=2, capacity={"gpu_count": 2, "ram_gb": 50},
    )
    events, _ = ledger.events_after(0)
    kinds = [e["kind"] for e in events if e["resource_id"] == "r"]
    assert kinds == ["released", "released", "reserved"]


def test_disabling_alone_is_reserved_even_with_unchanged_capacity(
    ledger: CapacityLedgerService,
):
    ledger.register_resource(resource_id="r", total_units=4, enabled=True)
    ledger.register_resource(resource_id="r", total_units=4, enabled=False)
    events, _ = ledger.events_after(0)
    kinds = [e["kind"] for e in events if e["resource_id"] == "r"]
    assert kinds == ["released", "reserved"]


def test_scheduler_credit_back_covers_full_capacity_legacy_reservation():
    """Ledger-level regression test for the scheduler-level one in
    kit/fulfillment/tests/unit/test_scheduler.py: reserving *all* of a
    resource's capacity via a legacy gpu_count-only claim must still
    report a fully-populated dimensions map, since the scheduler's
    credit-back logic depends on it never being empty for a
    pre-migration-style reservation."""
    ledger = _make_ledger()
    ledger.register_resource(resource_id="r1", total_units=4)
    reserved = ledger.reserve(claim={"executor_kind": "vm", **{"gpu_count": 4}}, deal_ref={})
    reservation = ledger.get_reservation(reserved["capacity_reservation_id"])
    assert reservation["dimensions"] == {"gpu_count": 4}


# ---------------------------------------------------------------------------
# pool_id
# ---------------------------------------------------------------------------

def test_registered_resource_carries_the_real_pool_id():
    ledger = _make_ledger()
    resource = ledger.register_resource(resource_id="r1", total_units=4, pool_id="pool-a")
    assert resource["pool_id"] == "pool-a"
    assert ledger.list_resources()[0]["pool_id"] == "pool-a"


def test_pool_id_defaults_to_none_when_not_supplied():
    """apicredits' resources carry no pool concept -- pool_id stays None,
    not a silently-invented value."""
    ledger = _make_ledger()
    resource = ledger.register_resource(resource_id="r1", total_units=4)
    assert resource["pool_id"] is None


def test_re_registering_updates_pool_id():
    ledger = _make_ledger()
    ledger.register_resource(resource_id="r1", total_units=4, pool_id="pool-a")
    resource = ledger.register_resource(resource_id="r1", total_units=4, pool_id="pool-b")
    assert resource["pool_id"] == "pool-b"


def test_attribute_view_prefers_real_pool_id_over_attributes_json():
    """During the transition before the storefront's attributes-JSON-only
    push is retired, a row could in principle carry both -- the real
    column must win."""
    ledger = _make_ledger()
    _declare_pool(ledger, "pool-a", "vm")
    ledger.register_resource(
        resource_id="r1", total_units=4, pool_id="pool-a",
        attributes={"pool_id": "pool-stale-json-value"},
    )
    match = ledger.probe(claim={"executor_kind": "vm", **{"pool_id": "pool-a", "gpu_count": 1}})
    assert match is not None
    assert ledger.probe(claim={"executor_kind": "vm", **{"pool_id": "pool-stale-json-value", "gpu_count": 1}}) is None


def test_attribute_view_falls_back_to_resource_id_when_pool_id_unset():
    """The degenerate single-resource pool: a claim addressing the
    resource by its own id as a pool still matches when pool_id is None."""
    ledger = _make_ledger()
    ledger.register_resource(resource_id="r1", total_units=4)
    match = ledger.probe(claim={"executor_kind": "vm", **{"pool_id": "r1", "gpu_count": 1}})
    assert match is not None


# ----------------------------------------------------------------------
# resize_reservation
# ----------------------------------------------------------------------

def test_resize_reservation_supersedes_with_a_new_id():
    ledger = _make_ledger()
    ledger.register_resource(resource_id="r1", total_units=4)
    old = ledger.reserve(claim={"executor_kind": "vm", **{"gpu_count": 2}}, deal_ref={"market": "vms"})
    assert old is not None
    old_id = old["capacity_reservation_id"]

    resized = ledger.resize_reservation(old_capacity_reservation_id=old_id, new_claim={"executor_kind": "vm", **{"gpu_count": 3}}, deal_ref={"market": "vms"},)
    assert resized is not None
    assert resized["capacity_reservation_id"] != old_id
    assert resized["superseded_capacity_reservation_id"] == old_id

    old_after = ledger.get_reservation(old_id)
    assert old_after["state"] == "released"
    assert old_after["failure_reason"] == "superseded"


def test_resize_reservation_sees_capacity_the_old_hold_was_consuming():
    """The new shape's availability is evaluated as if the old hold had
    already cleared: a single 4-unit resource can resize a 4-unit
    reservation up to a claim that still only needs 4 units total, even
    though the old hold is nominally still "using" all 4 until this call."""
    ledger = _make_ledger()
    ledger.register_resource(resource_id="r1", total_units=4)
    old = ledger.reserve(claim={"executor_kind": "vm", **{"gpu_count": 4}}, deal_ref={"market": "vms"})
    assert old is not None
    resized = ledger.resize_reservation(old_capacity_reservation_id=old["capacity_reservation_id"], new_claim={"executor_kind": "vm", **{"gpu_count": 4}}, deal_ref={"market": "vms"},)
    assert resized is not None
    assert resized["settlement_resource_id"] is None  # not yet scheduled
    assert ledger.get_reservation(resized["capacity_reservation_id"])["units"] == 4


def test_resize_reservation_rolls_back_fully_when_new_shape_is_unavailable():
    """If the new shape has no eligible candidate, the whole transaction
    rolls back: the old reservation is left exactly as it was, still held,
    never actually released -- not two independently-reversible steps."""
    ledger = _make_ledger()
    ledger.register_resource(resource_id="r1", total_units=4)
    old = ledger.reserve(claim={"executor_kind": "vm", **{"gpu_count": 4}}, deal_ref={"market": "vms"})
    assert old is not None
    old_id = old["capacity_reservation_id"]

    resized = ledger.resize_reservation(old_capacity_reservation_id=old_id, new_claim={"executor_kind": "vm", **{"gpu_count": 5}}, # exceeds the only resource's total capacity
    deal_ref={"market": "vms"},)
    assert resized is None

    old_after = ledger.get_reservation(old_id)
    assert old_after["state"] == "reserved"
    assert old_after["failure_reason"] is None


def test_resize_reservation_of_unknown_or_unheld_reservation_is_a_no_op():
    ledger = _make_ledger()
    assert ledger.resize_reservation(old_capacity_reservation_id="missing", new_claim={"executor_kind": "vm", **{"gpu_count": 1}}, ) is None


# ----------------------------------------------------------------------
# settlement-abandonment hook
# ----------------------------------------------------------------------

def test_release_invokes_the_abandonment_hook_unconditionally():
    calls = []
    ledger = _make_ledger(settlement_abandonment_hook=lambda db, rid: calls.append(rid))
    ledger.register_resource(resource_id="r1", total_units=4)
    result = ledger.reserve(claim={"executor_kind": "vm", **{"gpu_count": 1}}, deal_ref={"market": "vms"})
    assert result is not None
    reservation_id = result["capacity_reservation_id"]

    ledger.release(capacity_reservation_id=reservation_id)
    assert calls == [reservation_id]

    # Idempotent re-release does not duplicate capacity mutations, but it
    # still gives fulfillment a chance to reconcile stranded assigned state.
    ledger.release(capacity_reservation_id=reservation_id)
    assert calls == [reservation_id, reservation_id]


def test_expired_hold_lapse_invokes_the_abandonment_hook():
    calls = []
    ledger = _make_ledger(settlement_abandonment_hook=lambda db, rid: calls.append(rid))
    ledger.register_resource(resource_id="r1", total_units=4)
    result = ledger.reserve(claim={"executor_kind": "vm", **{"gpu_count": 1}}, deal_ref={"market": "vms"}, ttl_seconds=-1,)
    assert result is not None
    reservation_id = result["capacity_reservation_id"]

    ledger.expire_due_holds()
    assert calls == [reservation_id]


def test_resize_reservation_invokes_the_abandonment_hook_for_the_old_reservation():
    calls = []
    ledger = _make_ledger(settlement_abandonment_hook=lambda db, rid: calls.append(rid))
    ledger.register_resource(resource_id="r1", total_units=4)
    old = ledger.reserve(claim={"executor_kind": "vm", **{"gpu_count": 2}}, deal_ref={"market": "vms"})
    assert old is not None
    old_id = old["capacity_reservation_id"]

    resized = ledger.resize_reservation(old_capacity_reservation_id=old_id, new_claim={"executor_kind": "vm", **{"gpu_count": 3}}, deal_ref={"market": "vms"},)
    assert resized is not None
    assert calls == [old_id]


def test_resize_reservation_rollback_does_not_invoke_the_abandonment_hook():
    """The hook only fires on the transaction that actually commits: a
    resize that rolls back because the new shape is unavailable must not
    report the old reservation as abandoned."""
    calls = []
    ledger = _make_ledger(settlement_abandonment_hook=lambda db, rid: calls.append(rid))
    ledger.register_resource(resource_id="r1", total_units=4)
    old = ledger.reserve(claim={"executor_kind": "vm", **{"gpu_count": 4}}, deal_ref={"market": "vms"})
    assert old is not None

    resized = ledger.resize_reservation(old_capacity_reservation_id=old["capacity_reservation_id"], new_claim={"executor_kind": "vm", **{"gpu_count": 5}}, deal_ref={"market": "vms"},)
    assert resized is None
    assert calls == []


def test_no_hook_configured_is_a_silent_no_op():
    """The default (no hook wired) must not raise -- most tests in this
    file construct a ledger with no hook at all."""
    ledger = _make_ledger()
    ledger.register_resource(resource_id="r1", total_units=4)
    result = ledger.reserve(claim={"executor_kind": "vm", **{"gpu_count": 1}}, deal_ref={"market": "vms"})
    assert result is not None
    ledger.release(capacity_reservation_id=result["capacity_reservation_id"])


