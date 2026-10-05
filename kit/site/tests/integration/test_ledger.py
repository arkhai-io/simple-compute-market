"""CapacityLedgerService: reserve/commit/release mechanics + event feed."""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool, StaticPool
from market_resource_pools.db import (
    Base as ResourcePoolBase,
    DEFAULT_POOL_ID,
    ResourcePool,
)

from market_site.db import HELD_RESERVATION_STATES, Base, CapacityReservation
from market_site.ledger import (
    ALLOCATION_MODE_EXCLUSIVE,
    ALLOCATION_MODE_SHAREABLE,
    CapacityConflictError,
    CapacityLedgerService,
    UndeclaredOfferingModeError,
    UnknownPoolError,
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
    kwargs.setdefault("mirror_dimension", "gpu_count")
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
    ledger.register_resource(host_id="kvm1", 
        resource_id="compute-kvm1-001",
        total_units=8,
        resource_subtype="h200",
        attributes={"gpu_model": "H200", "region": "us-west"},
        pool_id="default",
    )
    return ledger


def test_snapshot_reports_availability(seeded: CapacityLedgerService):
    rows = seeded.snapshot()
    assert len(rows) == 1
    assert rows[0]["resource_id"] == "compute-kvm1-001"
    assert rows[0]["available_units"] == 8
    assert rows[0]["state"] == "available"


def test_probe_consumes_nothing(seeded: CapacityLedgerService):
    match = seeded.probe(claim={"offering_mode": "vm", **{"gpu_model": "H200", "gpu_count": 2}})
    assert match is not None
    assert match["host_id"] == "kvm1"
    assert match["allocated_gpu_count"] == 2
    assert seeded.snapshot()[0]["available_units"] == 8


def test_probe_mismatched_claim_returns_none(seeded: CapacityLedgerService):
    assert seeded.probe(claim={"offering_mode": "vm", **{"gpu_model": "A100"}}) is None
    assert seeded.probe(claim={"offering_mode": "vm", **{"gpu_count": 9}}) is None


def test_vm_claim_with_vm_host_does_not_match_hostless_resource(
    ledger: CapacityLedgerService,
):
    ledger.register_resource(
        resource_id="hostless", total_units=8, attributes={"gpu_model": "H200"},
        pool_id="default",
    )
    assert ledger.probe(claim={"offering_mode": "vm", **{"gpu_count": 1, "host_id": "kvm1"}}) is None
    assert ledger.probe(claim={"offering_mode": "vm", **{"gpu_count": 1}}) is not None


def _register_dual_mode_host(ledger: CapacityLedgerService) -> None:
    ledger.register_resource(host_id="kvm1", 
        resource_id="compute-host-1",
        total_units=8,
        resource_subtype="h200",
        attributes={
            "gpu_model": "H200",
            "physical_host_id": "physical-host-1",
            "allocation_mode": ALLOCATION_MODE_SHAREABLE,
        },
        pool_id="default",
    )
    ledger.register_resource(
        resource_id="bare-metal-host-1",
        total_units=1,
        resource_subtype="h200",
        host_id="node-1",
        attributes={
            "gpu_model": "H200",
            "physical_host_id": "physical-host-1",
            "allocation_mode": ALLOCATION_MODE_EXCLUSIVE,
        },
        pool_id="default",
    )


def test_dual_mode_host_snapshot_exposes_vm_and_bare_metal_when_free(
    ledger: CapacityLedgerService,
):
    _register_dual_mode_host(ledger)

    by_id = {row["resource_id"]: row for row in ledger.snapshot()}

    assert by_id["compute-host-1"]["available_units"] == 8
    assert by_id["bare-metal-host-1"]["available_units"] == 1
    assert ledger.probe(claim={"offering_mode": "vm", **{"gpu_count": 2, "host_id": "kvm1"}})["resource_id"] == "compute-host-1"
    assert ledger.probe(claim={
        "offering_mode": "bare_metal",
        "physical_host_id": "physical-host-1",
        "allocation_mode": ALLOCATION_MODE_EXCLUSIVE,
    })["resource_id"] == "bare-metal-host-1"


def test_vm_slice_reservation_blocks_bare_metal_on_same_physical_host(
    ledger: CapacityLedgerService,
):
    _register_dual_mode_host(ledger)

    vm = ledger.reserve(claim={"offering_mode": "vm", **{"gpu_count": 2, "host_id": "kvm1"}}, deal_ref={"escrow_uid": "0xvm"},)

    assert vm is not None
    by_id = {row["resource_id"]: row for row in ledger.snapshot()}
    assert by_id["compute-host-1"]["available_units"] == 6
    assert by_id["bare-metal-host-1"]["available_units"] == 0
    assert by_id["bare-metal-host-1"]["state"] == "leased"
    assert ledger.probe(claim={
        "offering_mode": "bare_metal",
        "physical_host_id": "physical-host-1",
        "allocation_mode": ALLOCATION_MODE_EXCLUSIVE,
    }) is None

    second_vm = ledger.reserve(claim={"offering_mode": "vm", **{"gpu_count": 6, "host_id": "kvm1"}}, deal_ref={"escrow_uid": "0xvm2"},)
    assert second_vm is not None
    assert second_vm["resource_id"] == "compute-host-1"

def test_pool_mode_permission_does_not_replace_cross_mode_physical_conflict(
    ledger: CapacityLedgerService,
):
    _register_dual_mode_host(ledger)
    assert ledger.reserve(
        claim={"offering_mode": "vm", "gpu_count": 1, "host_id": "kvm1"},
        deal_ref={"escrow_uid": "0xvm-independent"},
    ) is not None
    bare_metal_claim = {
        "offering_mode": "bare_metal",
        "physical_host_id": "physical-host-1",
        "allocation_mode": ALLOCATION_MODE_EXCLUSIVE,
    }

    with ledger._session_factory() as db, db.begin():
        pool = db.get(ResourcePool, DEFAULT_POOL_ID)
        pool.policy_tags = {"deliverable_modes": ["vm"]}
    with pytest.raises(UndeclaredOfferingModeError, match="'bare_metal'"):
        ledger.reserve(claim=bare_metal_claim, deal_ref={})

    with ledger._session_factory() as db, db.begin():
        pool = db.get(ResourcePool, DEFAULT_POOL_ID)
        pool.policy_tags = {"deliverable_modes": ["bare_metal", "vm"]}
    assert ledger.reserve(claim=bare_metal_claim, deal_ref={}) is None


def test_bare_metal_reservation_blocks_vm_slices_on_same_physical_host(
    ledger: CapacityLedgerService,
):
    _register_dual_mode_host(ledger)

    bare_metal = ledger.reserve(
        claim={
            "offering_mode": "bare_metal",
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
    assert ledger.probe(claim={"offering_mode": "vm", **{"gpu_count": 1, "host_id": "kvm1"}}) is None


def test_releasing_cross_mode_reservation_keeps_sibling_capacity_blocked(
    ledger: CapacityLedgerService,
):
    _register_dual_mode_host(ledger)
    bare_metal = ledger.reserve(
        claim={
            "offering_mode": "bare_metal",
            "physical_host_id": "physical-host-1",
            "allocation_mode": ALLOCATION_MODE_EXCLUSIVE,
        },
        deal_ref={"escrow_uid": "0xbm"},
    )

    ledger.update_reservation_state(bare_metal["capacity_reservation_id"], state="releasing")

    by_id = {row["resource_id"]: row for row in ledger.snapshot()}
    assert by_id["compute-host-1"]["available_units"] == 0
    assert ledger.probe(claim={"offering_mode": "vm", **{"gpu_count": 1, "host_id": "kvm1"}}) is None


def test_release_restores_cross_mode_sibling_capacity(
    ledger: CapacityLedgerService,
):
    _register_dual_mode_host(ledger)
    vm = ledger.reserve(claim={"offering_mode": "vm", **{"gpu_count": 2, "host_id": "kvm1"}}, deal_ref={"escrow_uid": "0xvm"},)

    ledger.release(capacity_reservation_id=vm["capacity_reservation_id"])

    by_id = {row["resource_id"]: row for row in ledger.snapshot()}
    assert by_id["compute-host-1"]["available_units"] == 8
    assert by_id["bare-metal-host-1"]["available_units"] == 1


def test_required_attributes_remains_available_as_local_guard():
    guarded = _make_ledger(required_attributes=("host_id",))
    guarded.register_resource(
        resource_id="hostless", total_units=8, attributes={"gpu_model": "H200"},
        pool_id="default",
    )
    assert guarded.probe(claim={"offering_mode": "vm", **{"gpu_count": 1}}) is None


def test_generic_ledger_has_no_attribute_requirement():
    # A host without an eligibility invariant (the tokens service)
    # matches attribute-less resources and speaks the generic unit key.
    generic = _make_ledger()
    generic.register_resource(
        resource_id="svc-quota", total_units=1000, resource_type="api_credits",
        pool_id="default",
    )
    match = generic.probe(claim={"offering_mode": "vm", **{"units": 250}})
    assert match is not None
    assert match["allocated_units"] == 250
    assert match["available_units"] == 1000  # probe consumes nothing

    reserved = generic.reserve(claim={"offering_mode": "vm", **{"units": 250}}, deal_ref={"escrow_uid": "0xq"},)
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
        generic.probe(claim={"offering_mode": "vm", **{"units": 0}})



def test_missing_offering_mode_is_never_inferred_from_vm_resource(
    seeded: CapacityLedgerService,
):
    with pytest.raises(ValueError, match="offering_mode"):
        seeded.reserve(claim={"gpu_count": 1}, deal_ref={})
    with pytest.raises(ValueError, match="offering_mode"):
        seeded.probe(claim={"gpu_count": 1})


def test_absent_or_mismatched_pool_declaration_delivers_nothing(
    seeded: CapacityLedgerService,
):
    with seeded._session_factory() as db, db.begin():
        pool = db.get(ResourcePool, DEFAULT_POOL_ID)
        pool.policy_tags = {}

    with pytest.raises(UndeclaredOfferingModeError, match="'vm'"):
        seeded.reserve(
            claim={"offering_mode": "vm", "gpu_count": 1},
            deal_ref={},
        )
    assert seeded.snapshot()[0]["available_units"] == 8

    with seeded._session_factory() as db, db.begin():
        pool = db.get(ResourcePool, DEFAULT_POOL_ID)
        pool.policy_tags = {"deliverable_modes": ["bare_metal"]}

    with pytest.raises(UndeclaredOfferingModeError, match="'vm'"):
        seeded.reserve(
            claim={"offering_mode": "vm", "gpu_count": 1},
            deal_ref={},
        )
    assert seeded.snapshot()[0]["available_units"] == 8


def test_undeclared_mode_refusal_is_independent_of_live_availability(
    seeded: CapacityLedgerService,
):
    reserved = seeded.reserve(
        claim={"offering_mode": "vm", "gpu_count": 8},
        deal_ref={"escrow_uid": "0xfull"},
    )
    assert reserved is not None
    assert seeded.snapshot()[0]["available_units"] == 0

    with seeded._session_factory() as db, db.begin():
        pool = db.get(ResourcePool, DEFAULT_POOL_ID)
        pool.policy_tags = {"deliverable_modes": ["bare_metal"]}

    with pytest.raises(UndeclaredOfferingModeError, match="'vm'"):
        seeded.reserve(
            claim={"offering_mode": "vm", "gpu_count": 1},
            deal_ref={"escrow_uid": "0xpolicy-before-availability"},
        )


def test_reserve_derives_executor_ref_but_records_the_requested_mode(
    seeded: CapacityLedgerService,
):
    """The matched resource supplies executor placement, never its mode.

    ``reserve()`` writes ``executor_ref`` from the resource's ``host_id``
    attribute while persisting the claim's explicit ``offering_mode``. Its
    immediate return is the opaque match view; the durable reservation view
    exposes the recorded executor identity.
    """
    reserved = seeded.reserve(claim={"offering_mode": "vm", **{"gpu_count": 1}}, deal_ref={"escrow_uid": "0xn"})
    assert reserved is not None
    assert reserved["host_id"] == "kvm1"  # _match_payload, from the resource's own attributes

    row = seeded.get_reservation(reserved["capacity_reservation_id"])
    assert row["executor_ref"] == {"host_id": "kvm1"}
    assert row["offering_mode"] == "vm"
    assert row["host_id"] == "kvm1"  # _reservation_payload, now sourced from executor_ref


def test_reserve_decrements_and_releases_restore(seeded: CapacityLedgerService):
    reserved = seeded.reserve(claim={"offering_mode": "vm", **{"gpu_count": 3}}, deal_ref={"listing_id": "lst-1", "escrow_uid": "0xesc"},)
    assert reserved is not None
    assert reserved["allocated_gpu_count"] == 3
    assert reserved["available_gpu_count"] == 5
    assert seeded.snapshot()[0]["available_units"] == 5

    # Second reservation cannot exceed the remainder.
    assert seeded.reserve(claim={"offering_mode": "vm", **{"gpu_count": 6}}, deal_ref={}) is None

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
    first = seeded.reserve(claim={"offering_mode": "vm", **{"gpu_count": 3}}, deal_ref={"listing_id": "lst-1", "escrow_uid": "0xidempotent"},)
    assert first is not None
    assert seeded.snapshot()[0]["available_units"] == 5

    second = seeded.reserve(claim={"offering_mode": "vm", **{"gpu_count": 3}}, deal_ref={"listing_id": "lst-1", "escrow_uid": "0xidempotent"},)
    assert second is not None
    assert second["capacity_reservation_id"] == first["capacity_reservation_id"]
    # Capacity was not consumed a second time.
    assert seeded.snapshot()[0]["available_units"] == 5


def test_reserve_idempotent_hit_includes_resource_id(seeded: CapacityLedgerService):
    """The idempotent-hit payload must be byte-compatible with a fresh
    reservation's payload for callers that read resource_id directly
    (e.g. vm_fulfillment_service.py)."""
    first = seeded.reserve(claim={"offering_mode": "vm", **{"gpu_count": 1}}, deal_ref={"escrow_uid": "0xres"})
    second = seeded.reserve(claim={"offering_mode": "vm", **{"gpu_count": 1}}, deal_ref={"escrow_uid": "0xres"})
    assert second["resource_id"] == first["resource_id"] == "compute-kvm1-001"
    assert second["host_id"] == first["host_id"] == "kvm1"


def test_reserve_idempotency_finds_a_committed_reservation_too(
    seeded: CapacityLedgerService,
):
    """Idempotency must not be limited to the TTL-hold (``reserved``)
    state -- a caller retrying after the first attempt already progressed
    to a committed lease must still find it, not double-reserve."""
    reserved = seeded.reserve(claim={"offering_mode": "vm", **{"gpu_count": 1}}, deal_ref={"escrow_uid": "0xcommitted"})
    seeded.commit(
        resource_id=reserved["resource_id"],
        capacity_reservation_id=reserved["capacity_reservation_id"],
        lease_end_utc="2099-01-01 00:00",
    )
    retried = seeded.reserve(claim={"offering_mode": "vm", **{"gpu_count": 1}}, deal_ref={"escrow_uid": "0xcommitted"})
    assert retried["capacity_reservation_id"] == reserved["capacity_reservation_id"]
    assert retried["state"] == "leased"


def test_reserve_without_escrow_uid_is_never_idempotent(seeded: CapacityLedgerService):
    """No escrow_uid means no idempotency key -- every call reserves
    fresh, matching pre-existing behavior for callers that don't supply
    one."""
    first = seeded.reserve(claim={"offering_mode": "vm", **{"gpu_count": 1}}, deal_ref={})
    second = seeded.reserve(claim={"offering_mode": "vm", **{"gpu_count": 1}}, deal_ref={})
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

    first = seeded.reserve(claim={"offering_mode": "vm", **{"gpu_count": 1}}, deal_ref={"escrow_uid": "0xexpired"}, ttl_seconds=60,)
    with seeded._session_factory() as db:
        row = db.get(CapacityReservation, first["capacity_reservation_id"])
        row.hold_expires_at = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        ).isoformat()
        db.commit()

    second = seeded.reserve(claim={"offering_mode": "vm", **{"gpu_count": 1}}, deal_ref={"escrow_uid": "0xexpired"})
    assert second is not None
    assert second["capacity_reservation_id"] != first["capacity_reservation_id"]


def test_future_reservation_ignores_non_overlapping_current_lease(seeded: CapacityLedgerService):
    first = seeded.reserve(claim={"offering_mode": "vm", **{"gpu_count": 8}}, deal_ref={"escrow_uid": "0xnow"},
    lease_start_utc="2030-01-01T00:00:00Z",
    lease_duration_seconds=3600,)
    assert first is not None

    assert seeded.reserve(claim={"offering_mode": "vm", **{"gpu_count": 1}}, deal_ref={"escrow_uid": "0xoverlap"},
    lease_start_utc="2030-01-01T00:30:00Z",
    lease_duration_seconds=3600,) is None

    later = seeded.reserve(claim={"offering_mode": "vm", **{"gpu_count": 8}}, deal_ref={"escrow_uid": "0xlater"},
    lease_start_utc="2030-01-01T02:00:00Z",
    lease_duration_seconds=3600,)
    assert later is not None
    assert later["allocated_gpu_count"] == 8

    # Future bookings do not consume the current snapshot.
    assert seeded.snapshot()[0]["available_units"] == 8


def test_commit_marks_leased_and_sets_window(seeded: CapacityLedgerService):
    reserved = seeded.reserve(claim={"offering_mode": "vm", **{"gpu_count": 1}}, deal_ref={"escrow_uid": "0xa"})
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
    with_resource_id = seeded.reserve(claim={"offering_mode": "vm", **{"gpu_count": 1}}, deal_ref={"escrow_uid": "0xb1"})
    without_resource_id = seeded.reserve(claim={"offering_mode": "vm", **{"gpu_count": 1}}, deal_ref={"escrow_uid": "0xb2"})

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
    third = seeded.reserve(claim={"offering_mode": "vm", **{"gpu_count": 1}}, deal_ref={"escrow_uid": "0xb3"})
    committed_omitted = seeded.commit(
        capacity_reservation_id=third["capacity_reservation_id"],
        lease_start_utc="2099-01-01T00:00:00Z",
        lease_end_utc="2099-01-01T01:00:00Z",
        idempotency_ref="0xb3",
    )
    assert committed_omitted["state"] == "leased"


def test_ttl_hold_expires_without_commit(seeded: CapacityLedgerService):
    reserved = seeded.reserve(claim={"offering_mode": "vm", **{"gpu_count": 8}}, deal_ref={"escrow_uid": "0xttl"}, ttl_seconds=60,)
    assert reserved["hold_expires_at"] is not None
    assert seeded.reserve(claim={"offering_mode": "vm", **{"gpu_count": 1}}, deal_ref={}) is None

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
    reserved = seeded.reserve(claim={"offering_mode": "vm", **{"gpu_count": 8}}, deal_ref={"escrow_uid": "0xwatchdog"}, ttl_seconds=60,)
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
    reserved = seeded.reserve(claim={"offering_mode": "vm", **{"gpu_count": 2}}, deal_ref={"escrow_uid": "0xkeep"}, ttl_seconds=60,)
    seeded.commit(
        resource_id=reserved["resource_id"],
        capacity_reservation_id=reserved["capacity_reservation_id"],
        lease_end_utc="2099-01-01 00:00",
    )
    committed = seeded.get_reservation(reserved["capacity_reservation_id"])
    assert committed["hold_expires_at"] is None
    assert seeded.snapshot()[0]["available_units"] == 6


def _committed(seeded: CapacityLedgerService, escrow: str, end: str = "2099-01-01 00:00") -> str:
    reserved = seeded.reserve(
        claim={"offering_mode": "vm", "gpu_count": 1}, deal_ref={"escrow_uid": escrow}
    )
    seeded.commit(
        capacity_reservation_id=reserved["capacity_reservation_id"],
        lease_start_utc="2026-01-01T00:00:00+00:00",
        lease_end_utc=end,
    )
    return reserved["capacity_reservation_id"]


def test_truncate_lease_moves_a_leased_end_earlier_and_only_earlier(
    seeded: CapacityLedgerService,
):
    reservation_id = _committed(seeded, "0xt")

    truncated = seeded.truncate_lease(
        capacity_reservation_id=reservation_id, lease_end_utc="2027-01-01 00:00"
    )
    assert (truncated["lease_end_utc"], truncated["state"]) == ("2027-01-01 00:00", "leased")
    assert seeded.truncate_lease(
        capacity_reservation_id=reservation_id, lease_end_utc="2028-01-01 00:00"
    ) is None
    assert seeded.get_reservation(reservation_id)["lease_end_utc"] == "2027-01-01 00:00"
    assert seeded.truncate_lease(
        capacity_reservation_id="missing", lease_end_utc="2026-01-01 00:00",
    ) is None


def test_truncate_lease_refuses_an_uncommitted_hold_and_the_lifecycle_states(
    seeded: CapacityLedgerService,
):
    """An uncommitted hold is released, not truncated, and a lease the lifecycle
    is releasing keeps the state and handle the lifecycle recorded."""
    reserved = seeded.reserve(
        claim={"offering_mode": "vm", "gpu_count": 1}, deal_ref={"escrow_uid": "0xhold"}
    )
    assert seeded.truncate_lease(
        capacity_reservation_id=reserved["capacity_reservation_id"],
        lease_end_utc="2026-01-01 00:00",
    ) is None
    assert seeded.get_reservation(reserved["capacity_reservation_id"])["state"] == "reserved"

    releasing = _committed(seeded, "0xreleasing")
    seeded.begin_releasing(releasing, release_job_id="fulfillment-1")
    assert seeded.truncate_lease(
        capacity_reservation_id=releasing, lease_end_utc="2026-01-01 00:00"
    ) is None
    row = seeded.get_reservation(releasing)
    assert (row["state"], row["release_job_id"]) == ("releasing", "fulfillment-1")


def test_a_first_registration_records_the_tail_on_a_committed_lease(
    seeded: CapacityLedgerService,
):
    """``commit`` leaves a reservation ``leased`` before any storefront
    registers, so a first registration applies to it. Registration emits no
    capacity event: availability moved at commit."""
    reservation_id = _committed(seeded, "0xl")
    events_before, _ = seeded.events_after(0)

    attached = seeded.attach_lease(
        capacity_reservation_id=reservation_id,
        executor_target="tenant-abcd",
        executor_ref={"host_id": "kvm1"},
        lease_start_utc="2026-01-01T00:00:00+00:00",
        lease_end_utc="2099-01-01 00:00",
    )

    assert attached["state"] == "leased"
    assert attached["vm_target"] == "tenant-abcd"  # payload key, sourced from executor_target
    assert attached["offering_mode"] == "vm"
    assert attached["executor_target"] == "tenant-abcd"
    assert attached["executor_ref"] == {"host_id": "kvm1"}
    assert attached["create_job_id"] is None
    events_after, _ = seeded.events_after(0)
    assert len(events_after) == len(events_before)
    assert seeded.attach_lease(
        capacity_reservation_id="missing", executor_target="tenant-abcd"
    ) is None


def test_a_first_registration_on_an_uncommitted_hold_leases_it(
    seeded: CapacityLedgerService,
):
    reserved = seeded.reserve(
        claim={"offering_mode": "vm", "gpu_count": 1}, deal_ref={"escrow_uid": "0xr"}
    )

    attached = seeded.attach_lease(
        capacity_reservation_id=reserved["capacity_reservation_id"],
        executor_target="tenant-r",
        lease_end_utc="2099-01-01 00:00",
    )

    assert (attached["state"], attached["executor_target"]) == ("leased", "tenant-r")


def test_a_repeated_registration_never_moves_the_end(seeded: CapacityLedgerService):
    """A storefront re-registering with the deal's original window after a
    truncation gets the truncated lease back."""
    reservation_id = _committed(seeded, "0xrepeat")
    first = dict(
        capacity_reservation_id=reservation_id,
        executor_target="tenant-x",
        lease_start_utc="2026-01-01T00:00:00+00:00",
        lease_end_utc="2099-01-01 00:00",
    )
    seeded.attach_lease(**first)
    seeded.truncate_lease(capacity_reservation_id=reservation_id, lease_end_utc="2027-01-01 00:00")

    again = seeded.attach_lease(**first)

    assert again["lease_end_utc"] == "2027-01-01 00:00"


def test_a_late_first_registration_cannot_restore_a_truncated_end(
    seeded: CapacityLedgerService,
):
    """The committed window is the site's: a first registration arriving after
    a truncation, naming the deal's original end, leaves the truncated one."""
    reservation_id = _committed(seeded, "0xlate", end="2099-01-01 00:00")
    seeded.truncate_lease(capacity_reservation_id=reservation_id, lease_end_utc="2027-01-01 00:00")

    registered = seeded.attach_lease(
        capacity_reservation_id=reservation_id,
        executor_target="tenant-late",
        lease_start_utc="2026-01-01T00:00:00+00:00",
        lease_end_utc="2099-01-01 00:00",
    )

    assert registered["lease_end_utc"] == "2027-01-01 00:00"
    assert registered["executor_target"] == "tenant-late"


def test_a_first_registration_writes_a_window_only_where_none_is_recorded(
    seeded: CapacityLedgerService,
):
    reserved = seeded.reserve(
        claim={"offering_mode": "vm", "gpu_count": 1}, deal_ref={"listing_id": "l-open"}
    )

    registered = seeded.attach_lease(
        capacity_reservation_id=reserved["capacity_reservation_id"],
        executor_target="tenant-open",
        lease_start_utc="2026-01-01T00:00:00+00:00",
        lease_end_utc="2099-01-01 00:00",
    )

    assert registered["lease_end_utc"] == "2099-01-01 00:00"


def test_a_registration_records_the_deal_s_escrow_once(seeded: CapacityLedgerService):
    """A hold placed before the deal had an escrow is correlated with it at
    registration, as ``reserve`` would have; a recorded escrow is never
    replaced."""
    held = seeded.reserve(
        claim={"offering_mode": "vm", "gpu_count": 1}, deal_ref={"listing_id": "l-hold"}
    )
    reservation_id = held["capacity_reservation_id"]
    seeded.commit(capacity_reservation_id=reservation_id, lease_end_utc="2099-01-01 00:00")

    seeded.attach_lease(
        capacity_reservation_id=reservation_id,
        executor_target="tenant-esc",
        deal_ref={"escrow_uid": "0xlate-escrow"},
    )
    seeded.attach_lease(
        capacity_reservation_id=reservation_id,
        executor_target="tenant-esc",
        deal_ref={"escrow_uid": "0xother"},
    )

    found = seeded.get_reservation_by_escrow("0xlate-escrow")
    assert found["capacity_reservation_id"] == reservation_id
    assert seeded.get_reservation(reservation_id)["escrow_uid"] == "0xlate-escrow"


def test_entering_releasing_records_when_the_release_began(seeded: CapacityLedgerService):
    """Each release attempt is timed from its own start: recording the handle
    again keeps it, and a retry after ``release_failed`` begins a new one."""
    reservation_id = _committed(seeded, "0xbegan")

    first = seeded.begin_releasing(reservation_id, release_job_id="f-1")
    again = seeded.begin_releasing(reservation_id, release_job_id="f-1")
    seeded.update_reservation_state(
        reservation_id, state="release_failed", failure_reason="teardown_failed"
    )
    retried = seeded.begin_releasing(reservation_id, release_job_id="f-1")

    assert first["release_requested_at"] is not None
    assert again["release_requested_at"] == first["release_requested_at"]
    assert retried["release_requested_at"] >= first["release_requested_at"]
    assert retried["state"] == "releasing"


@pytest.mark.parametrize(
    "change",
    [{"executor_target": "tenant-other"}, {"lease_start_utc": "2026-02-01T00:00:00+00:00"}],
    ids=["target", "start"],
)
def test_a_registration_naming_another_target_or_start_is_refused(
    seeded: CapacityLedgerService, change
):
    reservation_id = _committed(seeded, f"0xchange-{sorted(change)[0]}")
    registration = dict(
        capacity_reservation_id=reservation_id,
        executor_target="tenant-x",
        lease_start_utc="2026-01-01T00:00:00+00:00",
        lease_end_utc="2099-01-01 00:00",
    )
    seeded.attach_lease(**registration)

    with pytest.raises(CapacityConflictError):
        seeded.attach_lease(**{**registration, **change})

    assert seeded.get_reservation(reservation_id)["executor_target"] == "tenant-x"


def test_a_registration_on_a_releasing_lease_is_refused_and_changes_nothing(
    seeded: CapacityLedgerService,
):
    reservation_id = _committed(seeded, "0xrel")
    seeded.begin_releasing(reservation_id, release_job_id="fulfillment-1")

    with pytest.raises(CapacityConflictError):
        seeded.attach_lease(capacity_reservation_id=reservation_id, executor_target="tenant-x")

    assert seeded.get_reservation(reservation_id)["state"] == "releasing"


def test_a_commit_moves_an_unregistered_window_and_leaves_a_registered_one(
    seeded: CapacityLedgerService,
):
    """Before registration the window is the commit's, so a storefront may move
    it to provision-complete plus the duration; once registered, only
    truncation moves it."""
    reservation_id = _committed(seeded, "0xwindow")

    moved = seeded.commit(
        capacity_reservation_id=reservation_id,
        lease_start_utc="2026-01-02T00:00:00+00:00",
        lease_end_utc="2099-01-02 00:00",
    )
    assert (moved["lease_start_utc"], moved["lease_end_utc"]) == (
        "2026-01-02T00:00:00+00:00",
        "2099-01-02 00:00",
    )

    seeded.attach_lease(capacity_reservation_id=reservation_id, executor_target="tenant-w")
    kept = seeded.commit(
        capacity_reservation_id=reservation_id,
        lease_start_utc="2026-03-01T00:00:00+00:00",
        lease_end_utc="2099-03-01 00:00",
    )
    assert (kept["lease_start_utc"], kept["lease_end_utc"]) == (
        "2026-01-02T00:00:00+00:00",
        "2099-01-02 00:00",
    )


def test_a_commit_of_a_releasing_lease_is_refused_and_changes_nothing(
    seeded: CapacityLedgerService,
):
    reservation_id = _committed(seeded, "0xcommit-releasing")
    seeded.begin_releasing(reservation_id, release_job_id="fulfillment-1")

    with pytest.raises(CapacityConflictError):
        seeded.commit(capacity_reservation_id=reservation_id, lease_end_utc="2099-01-01 00:00")

    assert seeded.get_reservation(reservation_id)["state"] == "releasing"


def test_event_feed_is_versioned_and_anonymous(seeded: CapacityLedgerService):
    reserved = seeded.reserve(claim={"offering_mode": "vm", **{}}, deal_ref={"escrow_uid": "0xsecret"})
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


def test_find_active_lease_by_vm_target_matches_via_executor_ref(seeded: CapacityLedgerService):
    """host_id is matched through executor_ref's JSON payload
    (func.json_extract) and vm_target through executor_target -- neither
    is a dedicated column. Previously untested -- this is new coverage,
    not just a migration of an existing test."""
    reserved = seeded.reserve(claim={"offering_mode": "vm", **{"gpu_count": 1}}, deal_ref={"escrow_uid": "0xm"})
    seeded.attach_lease(
        capacity_reservation_id=reserved["capacity_reservation_id"],
        executor_target="tenant-find-me",
        executor_ref={"host_id": "kvm1"},
        lease_end_utc="2099-01-01 00:00",
    )

    found = seeded.find_active_lease_by_vm_target("kvm1", "tenant-find-me")
    assert found is not None
    assert found["capacity_reservation_id"] == reserved["capacity_reservation_id"]

    # A different host_id must not match, even with the same vm_target --
    # proves the filter actually discriminates on the JSON value rather
    # than matching any row with a non-null executor_ref.
    assert seeded.find_active_lease_by_vm_target("kvm-wrong-host", "tenant-find-me") is None
    # A different vm_target must not match either.
    assert seeded.find_active_lease_by_vm_target("kvm1", "tenant-someone-else") is None
    seeded.release(capacity_reservation_id=reserved["capacity_reservation_id"])
    assert seeded.find_active_lease_by_vm_target("kvm1", "tenant-find-me") is None


def test_a_vm_release_handle_has_one_name(seeded: CapacityLedgerService):
    """A VM reservation's release handle is ``release_job_id``, with no
    VM-named copy on the payload or on the stored row."""
    reserved = seeded.reserve(
        claim={"offering_mode": "vm"}, deal_ref={"escrow_uid": "0xhandle"},
    )
    seeded.commit(
        resource_id=reserved["resource_id"],
        capacity_reservation_id=reserved["capacity_reservation_id"],
        lease_start_utc="2020-01-01T00:00:00Z",
        lease_end_utc="2020-01-01 00:00",
    )

    releasing = seeded.begin_releasing(
        reserved["capacity_reservation_id"], release_job_id="fulfillment-1",
    )

    assert releasing["offering_mode"] == "vm"
    assert releasing["release_job_id"] == "fulfillment-1"
    assert "vm_remove_job_id" not in releasing
    assert "vm_remove_job_id" not in CapacityReservation.__table__.columns


def test_list_lease_due_and_begin_releasing(seeded: CapacityLedgerService):
    reserved = seeded.reserve(claim={"offering_mode": "vm", **{}}, deal_ref={"escrow_uid": "0xdue"})
    seeded.commit(
        resource_id=reserved["resource_id"],
        capacity_reservation_id=reserved["capacity_reservation_id"],
        lease_start_utc="2020-01-01T00:00:00Z",
        lease_end_utc="2020-01-01 00:00",
    )
    due = seeded.list_lease_due(datetime.now(timezone.utc))
    assert [a["capacity_reservation_id"] for a in due] == [reserved["capacity_reservation_id"]]

    releasing = seeded.begin_releasing(
        reserved["capacity_reservation_id"], release_job_id="check-1",
    )
    assert releasing["state"] == "releasing"
    assert releasing["release_job_id"] == "check-1"
    # releasing still holds the units and is no longer "due".
    assert seeded.snapshot()[0]["available_units"] == 7
    assert seeded.list_lease_due(datetime.now(timezone.utc)) == []

    # Future leases are not due.
    future = seeded.reserve(claim={"offering_mode": "vm", **{}}, deal_ref={})
    seeded.commit(
        resource_id=future["resource_id"],
        capacity_reservation_id=future["capacity_reservation_id"],
        lease_start_utc="2099-01-01T00:00:00Z",
        lease_end_utc="2099-01-01 00:00",
    )
    assert seeded.list_lease_due(datetime.now(timezone.utc)) == []


def test_release_failed_still_holds_capacity(seeded: CapacityLedgerService):
    reserved = seeded.reserve(claim={"offering_mode": "vm", **{"gpu_count": 2}}, deal_ref={})
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
    ledger.register_resource(host_id="kvm1", 
        resource_id="host-1-vm-gpus",
        total_units=8,
        attributes={
            "physical_host_id": "host-1",
            "allocation_mode": ALLOCATION_MODE_SHAREABLE,
            "gpu_model": "H200",
        },
        pool_id="default",
    )
    ledger.register_resource(
        resource_id="host-1-bare-metal",
        total_units=1,
        host_id="bm-node-1",
        attributes={
            "physical_host_id": "host-1",
            "allocation_mode": ALLOCATION_MODE_EXCLUSIVE,
            "gpu_model": "H200",
        },
        pool_id="default",
    )
    return ledger


def test_exclusive_bare_metal_claim_fails_after_vm_slice_reservation():
    ledger = _shared_host_ledger()
    vm = ledger.reserve(claim={"offering_mode": "vm", **{"allocation_mode": ALLOCATION_MODE_SHAREABLE, "gpu_count": 2}}, deal_ref={"escrow_uid": "0xvm"},)
    assert vm is not None

    assert ledger.probe(
        claim={
            "offering_mode": "bare_metal",
            "allocation_mode": ALLOCATION_MODE_EXCLUSIVE,
        }
    ) is None
    assert ledger.reserve(
        claim={
            "offering_mode": "bare_metal",
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
            "offering_mode": "bare_metal",
            "allocation_mode": ALLOCATION_MODE_EXCLUSIVE,
        },
        deal_ref={"escrow_uid": "0xbm"},
    )
    assert bare_metal is not None

    assert ledger.probe(claim={"offering_mode": "vm", **{"allocation_mode": ALLOCATION_MODE_SHAREABLE, "gpu_count": 1}}) is None
    assert ledger.reserve(claim={"offering_mode": "vm", **{"allocation_mode": ALLOCATION_MODE_SHAREABLE, "gpu_count": 1}}, deal_ref={"escrow_uid": "0xvm"},) is None

    by_id = {row["resource_id"]: row for row in ledger.snapshot()}
    assert by_id["host-1-vm-gpus"]["available_units"] == 0
    assert by_id["host-1-vm-gpus"]["state"] == "leased"
    assert by_id["host-1-bare-metal"]["available_units"] == 0


def test_compatible_vm_slice_claims_still_share_units():
    ledger = _shared_host_ledger()
    first = ledger.reserve(claim={"offering_mode": "vm", **{"allocation_mode": ALLOCATION_MODE_SHAREABLE, "gpu_count": 2}}, deal_ref={"escrow_uid": "0xvm1"},)
    second = ledger.reserve(claim={"offering_mode": "vm", **{"allocation_mode": ALLOCATION_MODE_SHAREABLE, "gpu_count": 3}}, deal_ref={"escrow_uid": "0xvm2"},)

    assert first is not None
    assert second is not None
    by_id = {row["resource_id"]: row for row in ledger.snapshot()}
    assert by_id["host-1-vm-gpus"]["available_units"] == 3
    assert by_id["host-1-bare-metal"]["available_units"] == 0
    assert by_id["host-1-bare-metal"]["state"] == "leased"


def test_released_shared_host_reservation_restores_cross_mode_availability():
    ledger = _shared_host_ledger()
    vm = ledger.reserve(claim={"offering_mode": "vm", **{"allocation_mode": ALLOCATION_MODE_SHAREABLE, "gpu_count": 8}}, deal_ref={"escrow_uid": "0xvm"},)
    assert ledger.reserve(
        claim={
            "offering_mode": "bare_metal",
            "allocation_mode": ALLOCATION_MODE_EXCLUSIVE,
        },
        deal_ref={"escrow_uid": "0xbm-blocked"},
    ) is None

    ledger.release(capacity_reservation_id=vm["capacity_reservation_id"])

    bare_metal = ledger.reserve(
        claim={
            "offering_mode": "bare_metal",
            "allocation_mode": ALLOCATION_MODE_EXCLUSIVE,
        },
        deal_ref={"escrow_uid": "0xbm"},
    )
    assert bare_metal is not None


def test_release_failed_shared_host_reservation_blocks_cross_mode_claims():
    ledger = _shared_host_ledger()
    vm = ledger.reserve(claim={"offering_mode": "vm", **{"allocation_mode": ALLOCATION_MODE_SHAREABLE, "gpu_count": 2}}, deal_ref={"escrow_uid": "0xvm"},)
    ledger.update_reservation_state(
        vm["capacity_reservation_id"],
        state="release_failed",
        failure_reason="release_submit_failed",
    )

    assert ledger.reserve(
        claim={
            "offering_mode": "bare_metal",
            "allocation_mode": ALLOCATION_MODE_EXCLUSIVE,
        },
        deal_ref={"escrow_uid": "0xbm"},
    ) is None
    by_id = {row["resource_id"]: row for row in ledger.snapshot()}
    assert by_id["host-1-bare-metal"]["available_units"] == 0
    assert by_id["host-1-bare-metal"]["state"] == "leased"


def test_release_can_mark_force_released(seeded: CapacityLedgerService):
    reserved = seeded.reserve(claim={"offering_mode": "vm", **{}}, deal_ref={})
    seeded.begin_releasing(reserved["capacity_reservation_id"])
    forced = seeded.release(capacity_reservation_id=reserved["capacity_reservation_id"], state="force_released")
    assert forced["state"] == "force_released"
    assert seeded.snapshot()[0]["available_units"] == 8


def test_claim_matches_top_level_fields(seeded: CapacityLedgerService):
    assert seeded.probe(claim={"offering_mode": "vm", **{"resource_subtype": "h200"}}) is not None
    assert seeded.probe(claim={"offering_mode": "vm", **{"resource_id": "compute-kvm1-001"}}) is not None
    assert seeded.probe(claim={"offering_mode": "vm", **{"resource_id": "other"}}) is None
    assert seeded.probe(claim={"offering_mode": "vm", **{"pool_id": "default"}}) is not None
    assert seeded.probe(claim={"offering_mode": "vm", **{"pool_id": "other-pool"}}) is None


def test_gpu_count_validation(seeded: CapacityLedgerService):
    with pytest.raises(ValueError):
        seeded.probe(claim={"offering_mode": "vm", **{"gpu_count": "many"}})
    with pytest.raises(ValueError):
        seeded.reserve(claim={"offering_mode": "vm", **{"gpu_count": 0}}, deal_ref={})


# ----------------------------------------------------------------------
# multidimensional capacity
# ----------------------------------------------------------------------

@pytest.fixture
def multidim(ledger: CapacityLedgerService) -> CapacityLedgerService:
    ledger.register_resource(host_id="kvm2", 
        resource_id="compute-kvm2-001",
        total_units=8,
        resource_subtype="h200",
        attributes={"gpu_model": "H200", "region": "us-west"},
        capacity={"gpu_count": 8, "vcpu_count": 64, "ram_gb": 512, "disk_gb": 4000},
        pool_id="default",
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
    reserved = multidim.reserve(claim={"offering_mode": "vm", **{"dimensions": {"gpu_count": 2, "vcpu_count": 8, "ram_gb": 64, "disk_gb": 500}}}, deal_ref={"escrow_uid": "0xdim"},)
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
    assert multidim.probe(claim={"offering_mode": "vm", **{"dimensions": {"gpu_count": 1, "ram_gb": 9999}}}) is None
    assert multidim.reserve(claim={"offering_mode": "vm", **{"dimensions": {"gpu_count": 1, "ram_gb": 9999}}}, deal_ref={"escrow_uid": "0xtoobig"},) is None
    # Capacity is untouched by the rejected attempt.
    assert multidim.snapshot()[0]["available"]["ram_gb"] == 512


def test_dimension_claim_rejected_for_dimension_resource_never_declares(
    multidim: CapacityLedgerService,
):
    """A dimension the candidate never mentions can't be assumed to have
    room -- distinct from "declared but full"."""
    assert multidim.probe(claim={"offering_mode": "vm", **{"dimensions": {"gpu_count": 1, "network_bandwidth_gbps": 10}}}) is None


def test_concurrent_shareable_holds_accumulate_per_dimension(
    multidim: CapacityLedgerService,
):
    """Two separate holds on one shareable resource must both be counted
    against RAM, not just against GPU count -- the correctness gap a
    declared-capacity-only gate would have missed."""
    first = multidim.reserve(claim={"offering_mode": "vm", **{"dimensions": {"gpu_count": 1, "ram_gb": 300}}}, deal_ref={"escrow_uid": "0xfirst"},)
    assert first is not None
    # A second hold that alone would fit RAM's remainder does fit...
    second = multidim.reserve(claim={"offering_mode": "vm", **{"dimensions": {"gpu_count": 1, "ram_gb": 200}}}, deal_ref={"escrow_uid": "0xsecond"},)
    assert second is not None
    # ...but a third that would push combined RAM over capacity must not.
    assert multidim.reserve(claim={"offering_mode": "vm", **{"dimensions": {"gpu_count": 1, "ram_gb": 50}}}, deal_ref={"escrow_uid": "0xthird"},) is None
    assert multidim.snapshot()[0]["available"]["ram_gb"] == 12


def test_legacy_claim_without_dimensions_still_works_on_multidim_resource(
    multidim: CapacityLedgerService,
):
    reserved = multidim.reserve(claim={"offering_mode": "vm", **{"gpu_count": 3}}, deal_ref={"escrow_uid": "0xlegacy"},)
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
    assert seeded.probe(claim={"offering_mode": "vm", **{"dimensions": {"gpu_count": 1}}}) is not None
    assert seeded.probe(claim={"offering_mode": "vm", **{"dimensions": {"gpu_count": 1, "ram_gb": 1}}}) is None


def test_release_restores_every_dimension(multidim: CapacityLedgerService):
    reserved = multidim.reserve(claim={"offering_mode": "vm", **{"dimensions": {"gpu_count": 2, "vcpu_count": 8, "ram_gb": 64, "disk_gb": 500}}}, deal_ref={"escrow_uid": "0xrelease"},)
    multidim.release(capacity_reservation_id=reserved["capacity_reservation_id"])
    row = multidim.snapshot()[0]
    assert row["available"] == {"gpu_count": 8, "vcpu_count": 64, "ram_gb": 512, "disk_gb": 4000}


def test_capacity_events_carry_signed_per_dimension_deltas(
    multidim: CapacityLedgerService,
):
    reserved = multidim.reserve(claim={"offering_mode": "vm", **{"dimensions": {"gpu_count": 2, "ram_gb": 64}}}, deal_ref={"escrow_uid": "0xevt"},)
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
        pool_id="default",
    )
    ledger.register_resource(
        resource_id="growing", total_units=4, capacity={"gpu_count": 4, "ram_gb": 100},
        pool_id="default",
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
        seeded.probe(claim={"offering_mode": "vm", **{"dimensions": {}}})
    with pytest.raises(ValueError):
        seeded.reserve(claim={"offering_mode": "vm", **{"dimensions": {}}}, deal_ref={})


@pytest.mark.parametrize("raw", [[], "not-a-mapping", None, 5])
def test_malformed_dimensions_types_are_rejected(seeded: CapacityLedgerService, raw):
    with pytest.raises(ValueError):
        seeded.probe(claim={"offering_mode": "vm", **{"dimensions": raw}})


@pytest.mark.parametrize("value", [0, -1, "not-a-number"])
def test_dimensions_values_must_be_positive_numbers(
    seeded: CapacityLedgerService, value,
):
    with pytest.raises(ValueError):
        seeded.probe(claim={"offering_mode": "vm", **{"dimensions": {"gpu_count": value}}})


def test_dimensions_reject_nan_and_infinity(seeded: CapacityLedgerService):
    """NaN/Infinity parse cleanly into Decimal but raise InvalidOperation
    on comparison -- must surface as the same clean ValueError as any
    other malformed quantity, not an uncaught decimal.InvalidOperation
    """
    with pytest.raises(ValueError):
        seeded.probe(claim={"offering_mode": "vm", **{"dimensions": {"gpu_count": float("nan")}}})
    with pytest.raises(ValueError):
        seeded.probe(claim={"offering_mode": "vm", **{"dimensions": {"gpu_count": float("inf")}}})


def test_register_resource_rejects_conflicting_total_units_and_capacity(
    ledger: CapacityLedgerService,
):
    """total_units is documented as a mirror of capacity['gpu_count']; two
    disagreeing values is a caller bug, not something to silently resolve
    in capacity's favor."""
    with pytest.raises(ValueError):
        ledger.register_resource(
            resource_id="conflicted", total_units=8, capacity={"gpu_count": 4},
            pool_id="default",
        )
    # Consistent values are fine.
    ledger.register_resource(
        resource_id="consistent", total_units=8, capacity={"gpu_count": 8, "ram_gb": 64},
        pool_id="default",
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
        pool_id="default",
    )
    ledger.register_resource(
        resource_id="host-1", total_units=8, capacity={"gpu_count": 8, "ram_gb": 128},
        pool_id="default",
    )
    events, _ = ledger.events_after(0)
    kinds = [e["kind"] for e in events if e["resource_id"] == "host-1"]
    assert kinds == ["released", "capacity_changed"]


def test_pure_grow_and_pure_shrink_keep_their_kind(ledger: CapacityLedgerService):
    ledger.register_resource(
        resource_id="r", total_units=4, capacity={"gpu_count": 4, "ram_gb": 100},
        pool_id="default",
    )
    ledger.register_resource(
        resource_id="r", total_units=8, capacity={"gpu_count": 8, "ram_gb": 200},
        pool_id="default",
    )
    ledger.register_resource(
        resource_id="r", total_units=2, capacity={"gpu_count": 2, "ram_gb": 50},
        pool_id="default",
    )
    events, _ = ledger.events_after(0)
    kinds = [e["kind"] for e in events if e["resource_id"] == "r"]
    assert kinds == ["released", "released", "reserved"]


def test_disabling_alone_is_reserved_even_with_unchanged_capacity(
    ledger: CapacityLedgerService,
):
    ledger.register_resource(resource_id="r", total_units=4, enabled=True, pool_id="default")
    ledger.register_resource(resource_id="r", total_units=4, enabled=False, pool_id="default")
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
    ledger.register_resource(resource_id="r1", total_units=4, pool_id="default")
    reserved = ledger.reserve(claim={"offering_mode": "vm", **{"gpu_count": 4}}, deal_ref={})
    reservation = ledger.get_reservation(reserved["capacity_reservation_id"])
    assert reservation["dimensions"] == {"gpu_count": 4}


# ---------------------------------------------------------------------------
# pool_id
# ---------------------------------------------------------------------------

def test_registered_resource_carries_the_real_pool_id():
    ledger = _make_ledger()
    _declare_pool(ledger, "pool-a", "vm")
    resource = ledger.register_resource(resource_id="r1", total_units=4, pool_id="pool-a")
    assert resource["pool_id"] == "pool-a"
    assert ledger.list_resources()[0]["pool_id"] == "pool-a"


def test_a_declaration_must_name_its_pool():
    """Registration replaces the whole declaration, so a pool left out would
    move the resource rather than leave it where it was."""
    ledger = _make_ledger()
    with pytest.raises(TypeError):
        ledger.register_resource(resource_id="r1", total_units=4)
    with pytest.raises(ValueError, match="pool_id"):
        ledger.register_resource(resource_id="r1", total_units=4, pool_id="")


def test_re_registering_updates_pool_id():
    ledger = _make_ledger()
    _declare_pool(ledger, "pool-a", "vm")
    _declare_pool(ledger, "pool-b", "vm")
    ledger.register_resource(resource_id="r1", total_units=4, pool_id="pool-a")
    resource = ledger.register_resource(resource_id="r1", total_units=4, pool_id="pool-b")
    assert resource["pool_id"] == "pool-b"


def test_attribute_view_prefers_real_pool_id_over_attributes_json():
    """A row stored before registration refused declaration fields as
    attributes may carry both; the column must win. Registration can no
    longer write such a row, so the test stores it directly."""
    from market_site.db import CapacityBucket

    ledger = _make_ledger()
    _declare_pool(ledger, "pool-a", "vm")
    ledger.register_resource(resource_id="r1", total_units=4, pool_id="pool-a")
    with ledger._session_factory() as db, db.begin():
        db.query(CapacityBucket).filter_by(backing_resource_id="r1").one().attributes = {
            "pool_id": "pool-stale-json-value"
        }
    match = ledger.probe(claim={"offering_mode": "vm", **{"pool_id": "pool-a", "gpu_count": 1}})
    assert match is not None
    assert ledger.probe(claim={"offering_mode": "vm", **{"pool_id": "pool-stale-json-value", "gpu_count": 1}}) is None


def test_attribute_view_falls_back_to_resource_id_when_pool_id_unset():
    """A legacy row stored with no pool: a claim addressing the resource by
    its own id as a pool still matches. Registration can no longer write such
    a row, so the test stores it directly."""
    from market_site.db import CapacityBucket

    ledger = _make_ledger()
    ledger.register_resource(resource_id="r1", total_units=4, pool_id="default")
    with ledger._session_factory() as db:
        db.query(CapacityBucket).filter_by(backing_resource_id="r1").one().pool_id = None
        db.commit()
    match = ledger.probe(claim={"offering_mode": "vm", **{"pool_id": "r1", "gpu_count": 1}})
    assert match is not None


# ----------------------------------------------------------------------
# resize_reservation
# ----------------------------------------------------------------------

def test_resize_reservation_supersedes_with_a_new_id():
    ledger = _make_ledger()
    ledger.register_resource(resource_id="r1", total_units=4, pool_id="default")
    old = ledger.reserve(claim={"offering_mode": "vm", **{"gpu_count": 2}}, deal_ref={"market": "vms"})
    assert old is not None
    old_id = old["capacity_reservation_id"]

    resized = ledger.resize_reservation(old_capacity_reservation_id=old_id, new_claim={"offering_mode": "vm", **{"gpu_count": 3}}, deal_ref={"market": "vms"},)
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
    ledger.register_resource(resource_id="r1", total_units=4, pool_id="default")
    old = ledger.reserve(claim={"offering_mode": "vm", **{"gpu_count": 4}}, deal_ref={"market": "vms"})
    assert old is not None
    resized = ledger.resize_reservation(old_capacity_reservation_id=old["capacity_reservation_id"], new_claim={"offering_mode": "vm", **{"gpu_count": 4}}, deal_ref={"market": "vms"},)
    assert resized is not None
    assert resized["settlement_resource_id"] is None  # not yet scheduled
    assert ledger.get_reservation(resized["capacity_reservation_id"])["units"] == 4


def test_resize_reservation_rolls_back_fully_when_new_shape_is_unavailable():
    """If the new shape has no eligible candidate, the whole transaction
    rolls back: the old reservation is left exactly as it was, still held,
    never actually released -- not two independently-reversible steps."""
    ledger = _make_ledger()
    ledger.register_resource(resource_id="r1", total_units=4, pool_id="default")
    old = ledger.reserve(claim={"offering_mode": "vm", **{"gpu_count": 4}}, deal_ref={"market": "vms"})
    assert old is not None
    old_id = old["capacity_reservation_id"]

    resized = ledger.resize_reservation(old_capacity_reservation_id=old_id, new_claim={"offering_mode": "vm", **{"gpu_count": 5}}, # exceeds the only resource's total capacity
    deal_ref={"market": "vms"},)
    assert resized is None

    old_after = ledger.get_reservation(old_id)
    assert old_after["state"] == "reserved"
    assert old_after["failure_reason"] is None


def test_resize_reservation_of_unknown_or_unheld_reservation_is_a_no_op():
    ledger = _make_ledger()
    assert ledger.resize_reservation(old_capacity_reservation_id="missing", new_claim={"offering_mode": "vm", **{"gpu_count": 1}}, ) is None


# ----------------------------------------------------------------------
# The release guard: every capacity reclaim asks the composition first
# ----------------------------------------------------------------------


class _Guard:
    """Permits or refuses, recording each reservation it is asked about."""

    def __init__(self, permit: bool = True) -> None:
        self.permit = permit
        self.asked: list[str] = []

    def __call__(self, db, capacity_reservation_id: str) -> bool:
        self.asked.append(capacity_reservation_id)
        return self.permit


def _guarded(permit: bool = True) -> tuple[CapacityLedgerService, _Guard]:
    guard = _Guard(permit)
    ledger = _make_ledger(release_guard=guard)
    ledger.register_resource(resource_id="r1", total_units=4, pool_id="default")
    return ledger, guard


def test_a_release_the_guard_permits_frees_the_capacity_and_a_retry_still_asks():
    ledger, guard = _guarded()
    reservation_id = ledger.reserve(
        claim={"offering_mode": "vm", "gpu_count": 1}, deal_ref={"market": "vms"}
    )["capacity_reservation_id"]

    assert ledger.release(capacity_reservation_id=reservation_id)["state"] == "released"
    # An idempotent retry frees nothing more, but still offers the guard the
    # reservation so it can abandon an assignment an earlier release stranded.
    assert ledger.release(capacity_reservation_id=reservation_id)["state"] == "released"
    assert guard.asked == [reservation_id, reservation_id]


def test_a_release_the_guard_refuses_changes_nothing():
    ledger, guard = _guarded(permit=False)
    reservation_id = ledger.reserve(
        claim={"offering_mode": "vm", "gpu_count": 1}, deal_ref={"market": "vms"}
    )["capacity_reservation_id"]
    ledger.commit(capacity_reservation_id=reservation_id, lease_end_utc="2099-01-01 00:00")
    events_before, _ = ledger.events_after(0)

    assert ledger.release(capacity_reservation_id=reservation_id) is None

    assert ledger.get_reservation(reservation_id)["state"] == "leased"
    assert ledger.snapshot()[0]["available_units"] == 3
    assert ledger.events_after(0)[0] == events_before


def test_a_forced_release_is_the_operator_s_override_and_is_not_guarded():
    ledger, guard = _guarded(permit=False)
    reservation_id = ledger.reserve(
        claim={"offering_mode": "vm", "gpu_count": 1}, deal_ref={"market": "vms"}
    )["capacity_reservation_id"]

    forced = ledger.release(capacity_reservation_id=reservation_id, state="force_released")

    assert forced["state"] == "force_released"
    assert guard.asked == []


def test_an_expired_hold_the_guard_refuses_waits_for_a_later_sweep():
    ledger, guard = _guarded(permit=False)
    reservation_id = ledger.reserve(
        claim={"offering_mode": "vm", "gpu_count": 1},
        deal_ref={"market": "vms"},
        ttl_seconds=-1,
    )["capacity_reservation_id"]

    ledger.expire_due_holds()
    assert ledger.get_reservation(reservation_id)["state"] == "reserved"

    guard.permit = True
    ledger.expire_due_holds()
    assert ledger.get_reservation(reservation_id)["state"] == "released"
    assert guard.asked == [reservation_id, reservation_id]


def test_a_resize_asks_the_guard_for_the_old_reservation_and_a_refusal_keeps_it():
    ledger, guard = _guarded()
    old_id = ledger.reserve(
        claim={"offering_mode": "vm", "gpu_count": 2}, deal_ref={"market": "vms"}
    )["capacity_reservation_id"]

    assert ledger.resize_reservation(
        old_capacity_reservation_id=old_id,
        new_claim={"offering_mode": "vm", "gpu_count": 3},
        deal_ref={"market": "vms"},
    ) is not None
    assert guard.asked == [old_id]

    refused_ledger, refusing = _guarded(permit=False)
    kept_id = refused_ledger.reserve(
        claim={"offering_mode": "vm", "gpu_count": 2}, deal_ref={"market": "vms"}
    )["capacity_reservation_id"]
    assert refused_ledger.resize_reservation(
        old_capacity_reservation_id=kept_id,
        new_claim={"offering_mode": "vm", "gpu_count": 3},
        deal_ref={"market": "vms"},
    ) is None
    assert refused_ledger.get_reservation(kept_id)["state"] == "reserved"


def test_a_resize_rolled_back_for_want_of_capacity_releases_nothing():
    """A guard that wrote while permitting has its write rolled back with the
    resize: the old reservation stays held."""
    ledger, guard = _guarded()
    old_id = ledger.reserve(
        claim={"offering_mode": "vm", "gpu_count": 4}, deal_ref={"market": "vms"}
    )["capacity_reservation_id"]

    assert ledger.resize_reservation(
        old_capacity_reservation_id=old_id,
        new_claim={"offering_mode": "vm", "gpu_count": 5},
        deal_ref={"market": "vms"},
    ) is None
    assert ledger.get_reservation(old_id)["state"] == "reserved"


def test_with_no_guard_every_reclaim_is_permitted():
    """A composition supplying no guard, as the API-credit service does, frees
    capacity as it always has."""
    ledger = _make_ledger()
    ledger.register_resource(resource_id="r1", total_units=4, pool_id="default")
    reservation_id = ledger.reserve(
        claim={"offering_mode": "vm", "gpu_count": 1}, deal_ref={"market": "vms"}
    )["capacity_reservation_id"]
    ledger.commit(capacity_reservation_id=reservation_id, lease_end_utc="2099-01-01 00:00")

    assert ledger.release(capacity_reservation_id=reservation_id)["state"] == "released"


# ---------------------------------------------------------------------------
# The create handle: written once, inside the caller's transaction
#
# Fulfillment records it from inside a transaction that has already written,
# so on SQLite it holds the single writer slot; a ledger call opening its own
# session would wait out the busy timeout. The write takes the caller's session.
# ---------------------------------------------------------------------------


def _held(ledger: CapacityLedgerService) -> str:
    ledger.register_resource(resource_id="lease-r1", total_units=4, pool_id="default")
    reservation = ledger.reserve(
        claim={"offering_mode": "vm", "gpu_count": 1},
        deal_ref={"market": "vms"},
    )
    assert reservation is not None
    return reservation["capacity_reservation_id"]


def test_a_create_handle_is_recorded_once_and_never_replaced():
    ledger = _make_ledger()
    capacity_reservation_id = _held(ledger)

    with ledger._session_factory() as db:
        ledger.record_create_handle_in_session(db, capacity_reservation_id, "job-7")
        ledger.record_create_handle_in_session(db, capacity_reservation_id, "job-8")
        db.commit()

    assert ledger.get_reservation(capacity_reservation_id)["create_job_id"] == "job-7"


def test_the_create_handle_write_leaves_the_commit_to_the_caller():
    ledger = _make_ledger()
    capacity_reservation_id = _held(ledger)

    with ledger._session_factory() as db:
        ledger.record_create_handle_in_session(db, capacity_reservation_id, "job-7")
        db.rollback()

    assert ledger.get_reservation(capacity_reservation_id)["create_job_id"] is None


def test_no_create_handle_is_recorded_on_a_terminal_reservation():
    ledger = _make_ledger()
    capacity_reservation_id = _held(ledger)
    ledger.release(capacity_reservation_id=capacity_reservation_id)

    with ledger._session_factory() as db:
        assert ledger.record_create_handle_in_session(
            db, capacity_reservation_id, "job-7"
        ) is None


# ----------------------------------------------------------------------
# A capacity declaration names no mandatory dimension
# ----------------------------------------------------------------------

def _neutral_ledger() -> CapacityLedgerService:
    """A ledger composed with the kit's own defaults, as a non-VM domain is."""
    return _make_ledger(unit_claim_keys=("units",), mirror_dimension="units")


def test_a_declaration_naming_no_compute_dimension_is_stored_as_declared():
    ledger = _neutral_ledger()

    resource = ledger.register_resource(
        resource_id="quota", pool_id="default", capacity={"tokens": 1000},
    )

    assert resource["capacity"] == {"tokens": 1000}
    assert "gpu_count" not in resource["capacity"]
    # No mirror dimension named, so no scalar total: absent, not zero.
    assert resource["value"] is None
    assert resource["available_units"] is None


def test_the_legacy_scalar_maps_to_the_composition_mirror_dimension():
    neutral = _neutral_ledger()
    vm = _make_ledger()

    assert neutral.register_resource(
        resource_id="q", pool_id="default", total_units=5,
    )["capacity"] == {"units": 5}
    assert vm.register_resource(
        resource_id="h", pool_id="default", total_units=5,
    )["capacity"] == {"gpu_count": 5}


def test_a_legacy_claim_requests_the_composition_mirror_dimension():
    vm = _make_ledger()
    vm.register_resource(
        resource_id="h", pool_id="default", capacity={"gpu_count": 4, "ram_gb": 64},
    )

    reserved = vm.reserve(claim={"offering_mode": "vm", "gpu_count": 2}, deal_ref={})

    assert reserved["dimensions"] == {"gpu_count": 2}
    assert reserved["allocated_gpu_count"] == 2


def test_admission_matches_the_unit_total_only_under_the_composition_mirror():
    """A claim attribute naming another domain's dimension is a requirement no
    resource declares. Under the kit defaults ``gpu_count`` is such a name, so
    a claim requiring it must not match a resource merely because its unit
    total happens to be equal; the VM composition's scheduling view carries
    the total under ``gpu_count`` and the neutral one does not."""
    neutral = _neutral_ledger()
    neutral.register_resource(resource_id="q", pool_id="default", capacity={"units": 3})

    assert neutral.reserve(
        claim={"offering_mode": "vm", "units": 1, "gpu_count": 3}, deal_ref={}
    ) is None

    vm = _make_ledger()
    vm.register_resource(resource_id="h", pool_id="default", total_units=3)
    with neutral._session_factory() as db:
        (neutral_view,) = neutral.iter_scheduling_candidates_in_session(
            db, resource_kind="compute.gpu", exclude_reservation_id=""
        )
    with vm._session_factory() as db:
        (vm_view,) = vm.iter_scheduling_candidates_in_session(
            db, resource_kind="compute.gpu", exclude_reservation_id=""
        )
    assert "gpu_count" not in neutral_view.attributes
    assert neutral_view.attributes["units"] == 3
    assert vm_view.attributes["gpu_count"] == 3

def test_an_explicit_declaration_gets_no_mirror_dimension_added():
    vm = _make_ledger()

    resource = vm.register_resource(
        resource_id="h", pool_id="default", capacity={"ram_gb": 64},
    )

    assert resource["capacity"] == {"ram_gb": 64}


@pytest.mark.parametrize(
    "key", ["resource_id", "pool_id", "host_id", "resource_type", "resource_subtype"]
)
def test_an_attribute_naming_a_declaration_field_is_refused(key: str):
    ledger = _make_ledger()

    with pytest.raises(ValueError, match=key):
        ledger.register_resource(
            resource_id="r1", pool_id="default", total_units=1,
            attributes={key: "restated", "gpu_model": "H200"},
        )

    assert ledger.snapshot() == []

def test_a_declaration_naming_no_dimension_is_refused():
    with pytest.raises(ValueError, match="at least one dimension"):
        _neutral_ledger().register_resource(resource_id="empty", pool_id="default")


# ----------------------------------------------------------------------
# A capacity resource does not move pools under live obligations
# ----------------------------------------------------------------------

def test_a_held_resource_cannot_change_pool_until_it_is_drained():
    """One test covers both halves, so a refusal cannot be mistaken for a
    resource that could never move."""
    ledger = _make_ledger()
    _declare_pool(ledger, "pool-b", "vm")
    ledger.register_resource(resource_id="r1", pool_id="default", total_units=4)
    reserved = ledger.reserve(claim={"offering_mode": "vm", "gpu_count": 1}, deal_ref={})

    with pytest.raises(CapacityConflictError, match="cannot move"):
        ledger.register_resource(resource_id="r1", pool_id="pool-b", total_units=4)
    # Refused outright: nothing moved.
    assert ledger.snapshot()[0]["pool_id"] == "default"

    ledger.release(capacity_reservation_id=reserved["capacity_reservation_id"])
    moved = ledger.register_resource(resource_id="r1", pool_id="pool-b", total_units=4)
    assert moved["pool_id"] == "pool-b"


def test_restating_the_same_pool_is_not_a_move():
    ledger = _make_ledger()
    ledger.register_resource(resource_id="r1", pool_id="default", total_units=4)
    ledger.reserve(claim={"offering_mode": "vm", "gpu_count": 1}, deal_ref={})

    updated = ledger.register_resource(
        resource_id="r1", pool_id="default", total_units=6,
    )

    assert updated["capacity"] == {"gpu_count": 6}


def test_a_legacy_row_with_no_stored_pool_is_in_the_default_pool():
    from market_site.db import CapacityBucket

    ledger = _make_ledger()
    ledger.register_resource(resource_id="r1", pool_id="default", total_units=4)
    with ledger._session_factory() as db:
        db.query(CapacityBucket).filter_by(backing_resource_id="r1").one().pool_id = None
        db.commit()
    ledger.reserve(claim={"offering_mode": "vm", "gpu_count": 1}, deal_ref={})

    # Naming the default pool explicitly restates where the row already was.
    restated = ledger.register_resource(resource_id="r1", pool_id="default", total_units=4)
    assert restated["pool_id"] == "default"


# ----------------------------------------------------------------------
# Administration is serialized through its caller's commit
# ----------------------------------------------------------------------

def test_an_in_session_mutator_outside_the_serialized_region_is_refused():
    """A caller writing into its own transaction must hold the ledger's lock
    around it; otherwise the mutator refuses before writing anything."""
    ledger = _make_ledger()

    with ledger._session_factory() as db:
        with pytest.raises(RuntimeError, match="serialized"):
            ledger.register_resource_in_session(
                db, resource_id="r1", pool_id="default", total_units=1
            )

    assert ledger.snapshot() == []


def _pause_after_the_obligation_check(ledger, monkeypatch):
    """Make a pool move stop just after it has checked live obligations,
    until released. Returns (checked, release) events."""
    checked, release = threading.Event(), threading.Event()
    refuse = ledger._refuse_reassignment_under_obligation

    def refuse_then_wait(db, bucket, new_pool_id):
        refuse(db, bucket, new_pool_id)
        checked.set()
        assert release.wait(timeout=10), "test never released the pool move"

    monkeypatch.setattr(ledger, "_refuse_reassignment_under_obligation", refuse_then_wait)
    return checked, release


def _move_in_one_transaction(ledger, resource_id: str, pool_id: str) -> None:
    """A caller composing a pool move into its own transaction, as the
    document importer does: serialized through its commit."""
    with ledger.serialized(), ledger._session_factory() as db:
        ledger.register_resource_in_session(
            db, resource_id=resource_id, pool_id=pool_id, total_units=4
        )
        db.commit()


def test_the_lock_is_held_from_the_obligation_check_through_the_commit(monkeypatch):
    """Deterministic: while a pool move is paused between checking live
    obligations and committing, no other thread can take the ledger's lock,
    so no admission can run in that window."""
    ledger = _make_ledger()
    _declare_pool(ledger, "pool-b", "vm")
    ledger.register_resource(resource_id="r1", pool_id="default", total_units=4)
    checked, release = _pause_after_the_obligation_check(ledger, monkeypatch)
    mover = threading.Thread(target=_move_in_one_transaction, args=(ledger, "r1", "pool-b"))

    mover.start()
    assert checked.wait(timeout=10), "the pool move never reached its check"
    try:
        acquired = ledger._lock.acquire(blocking=False)
        if acquired:
            ledger._lock.release()
        assert not acquired, "another thread could enter the ledger mid-move"
    finally:
        release.set()
        mover.join(timeout=10)

    assert ledger.snapshot()[0]["pool_id"] == "pool-b"


def test_a_reservation_racing_a_pool_move_never_survives_against_the_moved_resource(
    tmp_path, monkeypatch
):
    """Independent sessions on a file-backed database. The move is paused
    after its obligation check while a reserve for the same resource starts.
    Whatever the order, no committed state has a live reservation on a
    resource that now sits in a pool unable to deliver it."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'ledger.db'}",
        connect_args={"check_same_thread": False, "timeout": 30},
        poolclass=NullPool,
    )
    Base.metadata.create_all(bind=engine)
    ResourcePoolBase.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as db, db.begin():
        db.add_all([
            ResourcePool(id=DEFAULT_POOL_ID, label="Default", provider="test",
                         enabled=True, policy_tags={"deliverable_modes": ["vm"]}),
            ResourcePool(id="pool-b", label="B", provider="test",
                         enabled=True, policy_tags={"deliverable_modes": []}),
        ])
    ledger = CapacityLedgerService(
        session_factory, unit_claim_keys=("units", "gpu_count"),
        mirror_dimension="gpu_count",
    )
    ledger.register_resource(resource_id="r1", pool_id="default", total_units=4)
    checked, release = _pause_after_the_obligation_check(ledger, monkeypatch)
    outcomes: dict[str, object] = {}

    def reserve():
        try:
            outcomes["reserve"] = ledger.reserve(
                claim={"offering_mode": "vm", "gpu_count": 1, "resource_id": "r1"},
                deal_ref={},
            )
        except Exception as exc:  # the refusal is an acceptable outcome
            outcomes["reserve"] = exc

    mover = threading.Thread(target=_move_in_one_transaction, args=(ledger, "r1", "pool-b"))
    reserver = threading.Thread(target=reserve)
    mover.start()
    assert checked.wait(timeout=10)
    reserver.start()
    # Give the reserve the whole pause to run in. Serialized, it cannot
    # finish while the move holds the lock, so this wait expires and the
    # move resumes; unserialized, it would finish here and commit against
    # the old pool before the move writes. The assertion below does not
    # depend on this wait, only whether the counterfactual is exercised.
    reserver.join(timeout=1)
    release.set()
    mover.join(timeout=10)
    reserver.join(timeout=10)

    (resource,) = ledger.snapshot()
    live = [
        row for row in ledger.list_reservations()
        if row["state"] in HELD_RESERVATION_STATES
    ]
    assert resource["pool_id"] == "pool-b"
    assert live == [], f"a reservation survived the move: {outcomes['reserve']!r}"



def test_a_declaration_naming_an_unknown_pool_is_refused():
    ledger = _make_ledger()

    with pytest.raises(UnknownPoolError, match="no-such-pool"):
        ledger.register_resource(resource_id="r1", pool_id="no-such-pool", total_units=1)

    assert ledger.snapshot() == []


def test_a_settlement_assignment_outside_the_serialized_region_is_refused():
    """Assignment creates the live obligation a pool move checks for, so it
    writes only under the lock that serializes it with that check."""
    ledger = _make_ledger()
    ledger.register_resource(resource_id="r1", pool_id="default", total_units=4)
    reserved = ledger.reserve(claim={"offering_mode": "vm", "gpu_count": 1}, deal_ref={})

    with ledger._session_factory() as db:
        with pytest.raises(RuntimeError, match="serialized"):
            ledger.assign_settlement_resource_in_session(
                db,
                capacity_reservation_id=reserved["capacity_reservation_id"],
                settlement_resource_id="r1",
            )

    assert ledger.get_reservation(reserved["capacity_reservation_id"])["settlement_resource_id"] is None


# ----------------------------------------------------------------------
# The lease lifecycle's writes are conditional transitions: a write resting on
# a stale read is refused once an operator or a completed release has acted.
# ----------------------------------------------------------------------


def test_a_stale_begin_cannot_take_back_a_lease_an_operator_took_over(
    seeded: CapacityLedgerService,
):
    reservation_id = _committed(seeded, "0xstale-begin")
    seeded.record_unmanaged(reservation_id, reason="oversight_released", message="manual")

    assert seeded.begin_releasing(reservation_id, release_job_id="f-1") is None
    assert seeded.get_reservation(reservation_id)["state"] == "unmanaged"


def test_a_stale_failure_cannot_undo_a_force_release(seeded: CapacityLedgerService):
    reservation_id = _committed(seeded, "0xstale-failure")
    seeded.begin_releasing(reservation_id, release_job_id="f-1")
    seeded.release(capacity_reservation_id=reservation_id, state="force_released")
    capacity_after_force_release = seeded.snapshot()

    refused = seeded.record_release_failed(
        reservation_id, reason="teardown_failed", release_job_id="f-1"
    )

    assert refused is None
    assert seeded.get_reservation(reservation_id)["state"] == "force_released"
    assert seeded.snapshot() == capacity_after_force_release


def test_only_a_force_release_frees_a_lease_an_operator_took_over(
    seeded: CapacityLedgerService,
):
    reservation_id = _committed(seeded, "0xstale-release")
    seeded.record_unmanaged(reservation_id, reason="oversight_released")

    assert seeded.release(capacity_reservation_id=reservation_id) is None
    assert seeded.get_reservation(reservation_id)["state"] == "unmanaged"
    forced = seeded.release(capacity_reservation_id=reservation_id, state="force_released")
    assert forced["state"] == "force_released"


def test_begin_releasing_is_idempotent_under_its_handle_and_refused_under_another(
    seeded: CapacityLedgerService,
):
    reservation_id = _committed(seeded, "0xhandle")
    first = seeded.begin_releasing(reservation_id, release_job_id="f-1")

    again = seeded.begin_releasing(reservation_id, release_job_id="f-1")
    other = seeded.begin_releasing(reservation_id, release_job_id="f-2")

    assert again["release_requested_at"] == first["release_requested_at"]
    assert other is None
    assert seeded.get_reservation(reservation_id)["release_job_id"] == "f-1"


def test_a_failure_lands_only_on_the_release_attempt_it_was_observed_for(
    seeded: CapacityLedgerService,
):
    reservation_id = _committed(seeded, "0xattempt")
    seeded.begin_releasing(reservation_id, release_job_id="f-1")

    assert (
        seeded.record_release_failed(reservation_id, reason="teardown_failed", release_job_id="f-2")
        is None
    )
    failed = seeded.record_release_failed(
        reservation_id, reason="teardown_failed", release_job_id="f-1"
    )
    assert failed["state"] == "release_failed"


@pytest.mark.parametrize("state", ["releasing", "released"])
def test_oversight_is_refused_once_the_lease_is_not_leased(
    seeded: CapacityLedgerService, state: str
):
    reservation_id = _committed(seeded, f"0xoversight-{state}")
    seeded.begin_releasing(reservation_id, release_job_id="f-1")
    if state == "released":
        seeded.release(capacity_reservation_id=reservation_id)

    assert seeded.record_unmanaged(reservation_id, reason="oversight_released") is None
    assert seeded.get_reservation(reservation_id)["state"] == state
