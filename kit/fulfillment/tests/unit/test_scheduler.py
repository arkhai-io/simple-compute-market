"""Unit tests for deterministic Capacity Settlement Assignment scheduling.

Moved and adapted from ``provisioning/compute/service/tests/unit/services/
test_physical_settlement_scheduler.py`` (tombstoned at its old location).
Adaptations, both required by the fulfillment contract migration:

- ``allocation_id``/``agreement_id`` request fields become
  ``capacity_reservation_id`` only; the old agreement-mismatch test is
  dropped (the scheduler no longer receives an agreement identity to
  mismatch against -- see scheduler.py's module docstring).
- The scheduler fixture now passes ``default_resource_kind="compute.gpu"``
  explicitly, since ``_requirement`` no longer silently defaults it.
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from market_fulfillment import (
    CapacityReservationExpiredError,
    FulfillmentBase,
    MissingResourceKindError,
    NoEligibleSettlementResourceError,
    PhysicalSettlementRequest,
    PhysicalSettlementScheduler,
    SettlementEntityNotFoundError,
    SettlementRequestMismatchError,
    SettlementRepository,
    SqlAlchemySchedulingUnitOfWork,
)
from market_resource_pools import PoolCreate, ResourcePoolService
from market_resource_pools.db import Base as PoolsBase
from market_site.db import Base as SiteBase
from market_site.ledger import CapacityLedgerService


class _Handler:
    provider = "ansible"
    def validate_config(self, config): return dict(config)
    def validate_config_problems(self, config): return dict(config), ()
    def read_config(self, db, pool_id): return {}
    def replace_config(self, db, pool_id, config): pass
    def delete_config(self, db, pool_id): pass


@pytest.fixture
def services():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    PoolsBase.metadata.create_all(bind=engine)
    SiteBase.metadata.create_all(bind=engine)
    FulfillmentBase.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)
    pools = ResourcePoolService(
        factory,
        cast(Any, {"ansible": _Handler()}),
    )
    # This test suite's claims are VM-flavored ("gpu_count"); opt into
    # that alias explicitly the same way the VM composition root does
    # (kit/site's own default is domain-neutral -- see ledger.py).
    ledger = CapacityLedgerService(factory, unit_claim_keys=("units", "gpu_count"))
    scheduler = _scheduler(pools, ledger)
    return pools, ledger, scheduler


def _pool(pools, pool_id: str, enabled: bool = True):
    pools.create_pool(PoolCreate(
        id=pool_id, label=pool_id, provider="ansible", enabled=enabled,
        provider_config={},
    ))


def _resource(ledger, resource_id: str, pool_id: str, *, units: int = 4, enabled=True):
    ledger.register_resource(
        resource_id=resource_id,
        resource_type="compute.gpu",
        total_units=units,
        enabled=enabled,
        pool_id=pool_id,
    )


def _reserve(ledger, agreement="agreement-1", **deal):
    ref = {"agreement_id": agreement, "market": "vms", **deal}
    result = ledger.reserve(claim={"gpu_count": 1}, deal_ref=ref)
    assert result is not None
    return result["capacity_reservation_id"]


def _scheduler(
    pools,
    ledger,
    *,
    default_resource_kind="compute.gpu",
    repository=None,
    unit_of_work=None,
):
    repository = repository or SettlementRepository()
    unit_of_work = unit_of_work or SqlAlchemySchedulingUnitOfWork(
        ledger._session_factory,
        pools,
        ledger,
        repository,
    )
    return PhysicalSettlementScheduler(
        unit_of_work=unit_of_work,
        default_resource_kind=default_resource_kind,
    )


def _request(capacity_reservation_id: str, **kwargs):
    return PhysicalSettlementRequest(
        capacity_reservation_id=capacity_reservation_id,
        market="vms",
        **kwargs,
    )


def test_unknown_reservation_is_rejected(services):
    _, _, scheduler = services
    with pytest.raises(SettlementEntityNotFoundError):
        scheduler.schedule_resource(_request("missing"))


def test_expired_reservation_is_rejected(services):
    pools, ledger, scheduler = services
    _pool(pools, "pool-a")
    _resource(ledger, "r1", "pool-a")
    result = ledger.reserve(
        claim={"gpu_count": 1},
        deal_ref={"agreement_id": "agreement-1", "market": "vms"},
        ttl_seconds=-1,
    )
    with pytest.raises((CapacityReservationExpiredError, SettlementRequestMismatchError)):
        scheduler.schedule_resource(_request(result["capacity_reservation_id"]))


def test_retry_is_idempotent_and_does_not_rerun_policy(services):
    pools, ledger, scheduler = services
    _pool(pools, "pool-a")
    _pool(pools, "pool-b")
    _resource(ledger, "a1", "pool-a")
    _resource(ledger, "b1", "pool-b")
    capacity_reservation_id = _reserve(ledger)
    first = scheduler.schedule_resource(_request(capacity_reservation_id))
    second = scheduler.schedule_resource(_request(capacity_reservation_id))
    assert first == second


def test_same_resource_schedule_persists_site_assignment_marker(services):
    pools, ledger, scheduler = services
    _pool(pools, "pool-a")
    _resource(ledger, "r1", "pool-a")
    capacity_reservation_id = _reserve(ledger)

    selected = scheduler.schedule_resource(_request(capacity_reservation_id))
    reservation = ledger.get_reservation(
        capacity_reservation_id=capacity_reservation_id,
    )

    assert selected.settlement_resource_id == "r1"
    assert reservation is not None
    assert reservation["settlement_resource_id"] == "r1"


def test_exclusive_reservation_does_not_conflict_with_itself(services):
    pools, ledger, scheduler = services
    _pool(pools, "pool-a")
    ledger.register_resource(
        resource_id="bare-metal-1",
        resource_type="bare_metal",
        total_units=1,
        pool_id="pool-a",
        attributes={
            "physical_host_id": "host-1",
            "allocation_mode": "exclusive",
        },
    )
    reserved = ledger.reserve(
        claim={"resource_type": "bare_metal", "units": 1},
        deal_ref={"market": "bare_metal"},
    )
    assert reserved is not None

    selected = scheduler.schedule_resource(
        PhysicalSettlementRequest(
            capacity_reservation_id=reserved["capacity_reservation_id"],
            market="bare_metal",
            requirements={"resource_kind": "bare_metal"},
        ),
    )

    assert selected.settlement_resource_id == "bare-metal-1"


def test_round_robin_is_deterministic_across_pools(services):
    pools, ledger, scheduler = services
    _pool(pools, "pool-a")
    _pool(pools, "pool-b")
    _resource(ledger, "a1", "pool-a", units=10)
    _resource(ledger, "b1", "pool-b", units=10)
    ids = [_reserve(ledger, agreement=f"agreement-{i}") for i in range(1, 4)]
    selected = [
        scheduler.schedule_resource(_request(rid)).pool_id
        for rid in ids
    ]
    assert selected == ["pool-a", "pool-b", "pool-a"]


def test_round_robin_is_deterministic_within_pool(services):
    pools, ledger, scheduler = services
    _pool(pools, "pool-a")
    _resource(ledger, "r1", "pool-a", units=10)
    _resource(ledger, "r2", "pool-a", units=10)
    ids = [_reserve(ledger, agreement=f"agreement-{i}") for i in range(1, 3)]
    selected = [
        scheduler.schedule_resource(_request(rid)).settlement_resource_id
        for rid in ids
    ]
    assert selected == ["r1", "r2"]


def test_explicit_resource_bypasses_policy_not_eligibility(services):
    pools, ledger, scheduler = services
    _pool(pools, "pool-a", enabled=False)
    _resource(ledger, "r1", "pool-a")
    capacity_reservation_id = _reserve(ledger)
    with pytest.raises(NoEligibleSettlementResourceError):
        scheduler.schedule_resource(_request(capacity_reservation_id, resource_id="r1"))


def test_resource_without_pool_is_not_schedulable(services):
    pools, ledger, scheduler = services
    _pool(pools, "pool-a")
    ledger.register_resource(resource_id="orphan", total_units=4, attributes={})
    capacity_reservation_id = _reserve(ledger)
    with pytest.raises(NoEligibleSettlementResourceError):
        scheduler.schedule_resource(_request(capacity_reservation_id))


def test_disabling_pool_does_not_depend_on_existing_assignment(services):
    pools, ledger, scheduler = services
    _pool(pools, "pool-a")
    _resource(ledger, "r1", "pool-a")
    capacity_reservation_id = _reserve(ledger)
    scheduler.schedule_resource(_request(capacity_reservation_id))
    disabled = pools.disable_pool("pool-a")
    assert disabled.enabled is False


def test_missing_resource_kind_raises_when_no_default_configured(services):
    pools, ledger, _ = services
    scheduler = _scheduler(pools, ledger, default_resource_kind=None)
    _pool(pools, "pool-a")
    _resource(ledger, "r1", "pool-a")
    capacity_reservation_id = _reserve(ledger)
    with pytest.raises(MissingResourceKindError):
        scheduler.schedule_resource(_request(capacity_reservation_id))


# ----------------------------------------------------------------------
# multidimensional eligibility
# ----------------------------------------------------------------------

def _resource_with_capacity(ledger, resource_id: str, pool_id: str, *, capacity: dict, enabled=True):
    ledger.register_resource(
        resource_id=resource_id,
        resource_type="compute.gpu",
        total_units=capacity.get("gpu_count", 1),
        enabled=enabled,
        pool_id=pool_id,
        capacity=capacity,
    )


def _reserve_with_dimensions(ledger, dimensions: dict, agreement="agreement-1", **deal):
    ref = {"agreement_id": agreement, "market": "vms", "requirements": {"dimensions": dimensions}, **deal}
    result = ledger.reserve(claim={"dimensions": dimensions}, deal_ref=ref)
    assert result is not None
    return result["capacity_reservation_id"]


def test_scheduler_excludes_candidate_that_fits_gpu_but_not_memory(services):
    """Two resources have enough GPU; only one also has enough RAM. The
    scheduler's own eligibility scan (independent of which resource the
    ledger's admission happened to reserve against) must still exclude
    the RAM-short one, not just prove *some* resource exists."""
    pools, ledger, scheduler = services
    _pool(pools, "pool-a")
    _resource_with_capacity(
        ledger, "roomy", "pool-a",
        capacity={"gpu_count": 8, "vcpu_count": 32, "ram_gb": 256, "disk_gb": 1000},
    )
    _resource_with_capacity(
        ledger, "ram-short", "pool-a",
        capacity={"gpu_count": 8, "vcpu_count": 32, "ram_gb": 16, "disk_gb": 1000},
    )
    dims = {"gpu_count": 1, "ram_gb": 64}
    capacity_reservation_id = _reserve_with_dimensions(ledger, dims)
    # Pinning the RAM-short resource explicitly must fail eligibility,
    # checked before any assignment memoizes a different resource.
    with pytest.raises(NoEligibleSettlementResourceError):
        scheduler.schedule_resource(_request(
            capacity_reservation_id, requirements={"dimensions": dims}, resource_id="ram-short",
        ))
    resource = scheduler.schedule_resource(
        _request(capacity_reservation_id, requirements={"dimensions": dims})
    )
    assert resource.settlement_resource_id == "roomy"


def test_scheduler_selects_candidate_that_fits_every_dimension(services):
    pools, ledger, scheduler = services
    _pool(pools, "pool-a")
    _resource_with_capacity(
        ledger, "r1", "pool-a",
        capacity={"gpu_count": 8, "vcpu_count": 32, "ram_gb": 256, "disk_gb": 1000},
    )
    dims = {"gpu_count": 2, "vcpu_count": 8, "ram_gb": 64, "disk_gb": 200}
    capacity_reservation_id = _reserve_with_dimensions(ledger, dims)
    resource = scheduler.schedule_resource(
        _request(capacity_reservation_id, requirements={"dimensions": dims})
    )
    assert resource.settlement_resource_id == "r1"


def test_scheduler_still_schedules_legacy_gpu_only_requests(services):
    """Reservations made before pass 1 (no dimensions) keep scheduling
    exactly as they did under round-robin."""
    pools, ledger, scheduler = services
    _pool(pools, "pool-a")
    _resource(ledger, "r1", "pool-a", units=10)
    capacity_reservation_id = _reserve(ledger)
    resource = scheduler.schedule_resource(_request(capacity_reservation_id))
    assert resource.settlement_resource_id == "r1"


def test_scheduler_credit_back_covers_full_capacity_legacy_reservation(services):
    """A legacy reservation reserving *all* of a resource's capacity must
    still be schedulable: the eligibility scan credits the reservation's
    own held quantity back before checking fit, and that credit-back must
    not silently become a no-op for an reservation whose claim never
    mentioned "dimensions", but locking the invariant in with a test at
    the layer that actually depends on it)."""
    pools, ledger, scheduler = services
    _pool(pools, "pool-a")
    _resource(ledger, "r1", "pool-a", units=4)
    result = ledger.reserve(claim={"gpu_count": 4}, deal_ref={
        "agreement_id": "agreement-1", "market": "vms",
    })
    assert result is not None
    resource = scheduler.schedule_resource(_request(result["capacity_reservation_id"]))
    assert resource.settlement_resource_id == "r1"


# ----------------------------------------------------------------------
# exceeds-reservation rejection
# ----------------------------------------------------------------------

def _reserve_multi(ledger, dimensions: dict, agreement="agreement-1"):
    """Reserve specific multidimensional capacity without a deal_ref
    requirements mirror, so _require_valid_reservation's separate
    requirements-match check (an exact-equality check against whatever
    the reservation declares) doesn't itself reject a deliberately
    *different*, narrower schedule-time request before the exceeds-check
    below ever runs."""
    result = ledger.reserve(
        claim={"dimensions": dimensions},
        deal_ref={"agreement_id": agreement, "market": "vms"},
    )
    assert result is not None
    return result["capacity_reservation_id"]


def test_schedule_request_narrower_than_reservation_is_permitted(services):
    pools, ledger, scheduler = services
    _pool(pools, "pool-a")
    _resource_with_capacity(
        ledger, "r1", "pool-a", capacity={"gpu_count": 8, "ram_gb": 256},
    )
    capacity_reservation_id = _reserve_multi(ledger, {"gpu_count": 4, "ram_gb": 128})
    resource = scheduler.schedule_resource(_request(
        capacity_reservation_id,
        requirements={"dimensions": {"gpu_count": 2, "ram_gb": 64}},
    ))
    assert resource.settlement_resource_id == "r1"


def test_narrow_request_does_not_select_destination_that_cannot_hold_full_debit(services):
    pools, ledger, scheduler = services
    _pool(pools, "pool-a")
    _resource_with_capacity(
        ledger,
        "a-narrow-only",
        "pool-a",
        capacity={"gpu_count": 2},
    )
    _resource_with_capacity(
        ledger,
        "b-full-reservation",
        "pool-a",
        capacity={"gpu_count": 4},
    )
    capacity_reservation_id = _reserve_multi(ledger, {"gpu_count": 4})

    resource = scheduler.schedule_resource(_request(
        capacity_reservation_id,
        requirements={"dimensions": {"gpu_count": 2}},
    ))

    assert resource.settlement_resource_id == "b-full-reservation"


def test_schedule_request_equal_to_reservation_is_permitted(services):
    pools, ledger, scheduler = services
    _pool(pools, "pool-a")
    _resource_with_capacity(ledger, "r1", "pool-a", capacity={"gpu_count": 8})
    capacity_reservation_id = _reserve_multi(ledger, {"gpu_count": 4})
    resource = scheduler.schedule_resource(_request(
        capacity_reservation_id, requirements={"dimensions": {"gpu_count": 4}},
    ))
    assert resource.settlement_resource_id == "r1"


def test_schedule_request_exceeding_a_governed_dimension_is_rejected(services):
    pools, ledger, scheduler = services
    _pool(pools, "pool-a")
    _resource_with_capacity(
        ledger, "r1", "pool-a", capacity={"gpu_count": 8, "ram_gb": 256},
    )
    capacity_reservation_id = _reserve_multi(ledger, {"gpu_count": 4, "ram_gb": 128})
    with pytest.raises(SettlementRequestMismatchError):
        scheduler.schedule_resource(_request(
            capacity_reservation_id,
            requirements={"dimensions": {"gpu_count": 6, "ram_gb": 64}},
        ))


def test_schedule_request_adding_an_ungoverned_dimension_is_not_rejected(services):
    """A dimension the reservation never mentions isn't governed by it, so
    introducing one in the schedule request isn't an "exceeds" violation
    -- it's a separate eligibility question, decided by whether some
    resource actually has that dimension available."""
    pools, ledger, scheduler = services
    _pool(pools, "pool-a")
    _resource_with_capacity(
        ledger, "r1", "pool-a", capacity={"gpu_count": 8, "vcpu_count": 32},
    )
    capacity_reservation_id = _reserve_multi(ledger, {"gpu_count": 4})
    resource = scheduler.schedule_resource(_request(
        capacity_reservation_id,
        requirements={"dimensions": {"gpu_count": 2, "vcpu_count": 8}},
    ))
    assert resource.settlement_resource_id == "r1"


# ----------------------------------------------------------------------
# durable round-robin cursor
# ----------------------------------------------------------------------

def test_cursor_persists_across_a_fresh_scheduler_instance(services):
    """Unlike the old in-memory cursor, fairness state must survive the
    scheduler object itself being discarded and rebuilt -- e.g. a process
    restart -- because it is now read from and written to the database."""
    pools, ledger, scheduler = services
    _pool(pools, "pool-a")
    _pool(pools, "pool-b")
    _resource(ledger, "a1", "pool-a", units=10)
    _resource(ledger, "b1", "pool-b", units=10)
    first_id = _reserve(ledger, agreement="agreement-1")
    first = scheduler.schedule_resource(_request(first_id))
    assert first.pool_id == "pool-a"

    fresh_scheduler = _scheduler(pools, ledger)
    second_id = _reserve(ledger, agreement="agreement-2")
    second = fresh_scheduler.schedule_resource(_request(second_id))
    assert second.pool_id == "pool-b"


def test_stale_persisted_cursor_recovers_deterministically(services):
    """A cursor may outlive pools or resources that previously participated.

    Scheduling must treat those identifiers as stale history, resume from the
    first sorted eligible pool/resource, and durably replace the active cursor
    position without requiring eager pruning of unrelated historical entries.
    """
    from market_fulfillment import SettlementRepository

    pools, ledger, _ = services
    _pool(pools, "pool-a", enabled=False)
    _pool(pools, "pool-b")
    _pool(pools, "pool-c")
    _resource(ledger, "b1", "pool-b", units=10)
    _resource(ledger, "c1", "pool-c", units=10)

    repository = SettlementRepository()
    with ledger._session_factory() as db:
        repository.save_cursor_in_session(
            db,
            "compute.gpu",
            last_pool_id="deleted-pool",
            last_resource_by_pool={
                "pool-b": "deleted-resource",
                "deleted-pool": "other-deleted-resource",
            },
        )
        db.commit()

    fresh_scheduler = _scheduler(pools, ledger, repository=repository)
    reservation_id = _reserve(ledger, agreement="stale-cursor")
    selected = fresh_scheduler.schedule_resource(_request(reservation_id))

    assert selected.pool_id == "pool-b"
    assert selected.settlement_resource_id == "b1"

    with ledger._session_factory() as db:
        cursor = repository.get_cursor_in_session(db, "compute.gpu")
        assert cursor is not None
        assert cursor.last_pool_id == "pool-b"
        assert cursor.last_resource_by_pool["pool-b"] == "b1"


def test_cursor_is_isolated_per_resource_kind(services):
    """Two resource kinds scheduling concurrently must not perturb each
    other's round-robin position -- a buyer negotiates for one
    resource_kind per reservation, so fairness is scoped that way too."""
    pools, ledger, scheduler = services
    _pool(pools, "pool-a")
    _pool(pools, "pool-b")
    _resource(ledger, "gpu-a1", "pool-a", units=10)
    _resource(ledger, "gpu-b1", "pool-b", units=10)
    ledger.register_resource(
        resource_id="bm-a1", resource_type="bare_metal", total_units=10, pool_id="pool-a",
    )
    ledger.register_resource(
        resource_id="bm-b1", resource_type="bare_metal", total_units=10, pool_id="pool-b",
    )

    def _reserve_kind(resource_type: str, agreement: str) -> str:
        result = ledger.reserve(
            claim={"resource_type": resource_type, "gpu_count": 1},
            deal_ref={"agreement_id": agreement, "market": "vms"},
        )
        assert result is not None
        return result["capacity_reservation_id"]

    def _request_kind(capacity_reservation_id: str, resource_kind: str) -> PhysicalSettlementRequest:
        return PhysicalSettlementRequest(
            capacity_reservation_id=capacity_reservation_id,
            market="vms",
            requirements={"resource_kind": resource_kind},
        )

    gpu_1 = scheduler.schedule_resource(
        _request_kind(_reserve_kind("compute.gpu", "gpu-1"), "compute.gpu")
    )
    bm_1 = scheduler.schedule_resource(
        _request_kind(_reserve_kind("bare_metal", "bm-1"), "bare_metal")
    )
    gpu_2 = scheduler.schedule_resource(
        _request_kind(_reserve_kind("compute.gpu", "gpu-2"), "compute.gpu")
    )
    bm_2 = scheduler.schedule_resource(
        _request_kind(_reserve_kind("bare_metal", "bm-2"), "bare_metal")
    )
    # Each kind still alternates pool-a/pool-b on its own, independent of
    # how many scheduling calls the other kind made in between.
    assert [gpu_1.pool_id, gpu_2.pool_id] == ["pool-a", "pool-b"]
    assert [bm_1.pool_id, bm_2.pool_id] == ["pool-a", "pool-b"]


def test_explicit_resource_does_not_advance_or_consume_cursor(services):
    pools, ledger, scheduler = services
    _pool(pools, "pool-a")
    _pool(pools, "pool-b")
    _resource(ledger, "a1", "pool-a", units=10)
    _resource(ledger, "b1", "pool-b", units=10)
    explicit_id = _reserve(ledger, agreement="agreement-explicit")
    scheduler.schedule_resource(_request(explicit_id, resource_id="a1"))

    automatic_id = _reserve(ledger, agreement="agreement-automatic")
    automatic = scheduler.schedule_resource(_request(automatic_id))
    # The cursor never moved past its starting point: the first automatic
    # selection still lands on the first sorted pool, exactly as if the
    # explicit call had never happened.
    assert automatic.pool_id == "pool-a"


def test_conflicting_schedule_retry_is_rejected(services):
    pools, ledger, scheduler = services
    _pool(pools, "pool-a")
    _resource(ledger, "r1", "pool-a")
    capacity_reservation_id = _reserve(ledger)
    scheduler.schedule_resource(_request(capacity_reservation_id))
    with pytest.raises(SettlementRequestMismatchError):
        scheduler.schedule_resource(
            _request(capacity_reservation_id, resource_id="does-not-exist")
        )


def test_failed_schedule_leaves_no_partial_cursor_or_settlement_state(services):
    """A failure after the cursor is written but before the settlement
    record commits must roll back both together -- proving
    ``schedule_resource``'s one-transaction guarantee rather than assuming
    it from the code structure alone."""
    from market_fulfillment import SettlementRepository

    class _ExplodingRepository(SettlementRepository):
        def schedule(self, *args, **kwargs):
            raise RuntimeError("simulated failure after cursor write")

    pools, ledger, scheduler = services
    _pool(pools, "pool-a")
    _resource(ledger, "r1", "pool-a", units=10)
    capacity_reservation_id = _reserve(ledger)

    failing_scheduler = _scheduler(
        pools,
        ledger,
        repository=_ExplodingRepository(),
    )
    with pytest.raises(RuntimeError):
        failing_scheduler.schedule_resource(_request(capacity_reservation_id))

    # Nothing committed: a plain scheduler, sharing the same database,
    # sees a clean starting cursor and can still schedule this reservation
    # from scratch.
    resource = scheduler.schedule_resource(_request(capacity_reservation_id))
    assert resource.settlement_resource_id == "r1"


def test_independent_sessions_serialize_cursor_updates_deterministically(tmp_path):
    """A controlled transaction barrier proves SQLite writer serialization
    without relying on an uncontrolled race or elapsed-time ordering."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, Lock

    from market_fulfillment import (
        SqlAlchemySchedulingTransaction,
        SqlAlchemySchedulingUnitOfWork,
    )

    database = tmp_path / "scheduling.db"
    engine = create_engine(
        f"sqlite:///{database}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )
    PoolsBase.metadata.create_all(bind=engine)
    SiteBase.metadata.create_all(bind=engine)
    FulfillmentBase.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)
    pools = ResourcePoolService(
        factory,
        cast(Any, {"ansible": _Handler()}),
    )
    ledger = CapacityLedgerService(factory, unit_claim_keys=("units", "gpu_count"))
    _pool(pools, "pool-a")
    _pool(pools, "pool-b")
    _resource(ledger, "a1", "pool-a", units=10)
    _resource(ledger, "b1", "pool-b", units=10)
    first_id = _reserve(ledger, agreement="concurrent-1")
    second_id = _reserve(ledger, agreement="concurrent-2")

    cursor_written = Event()
    allow_first_commit = Event()
    second_transaction_attempted = Event()
    second_transaction_opened = Event()
    ordinal_lock = Lock()
    next_ordinal = 0

    class PausingTransaction(SqlAlchemySchedulingTransaction):
        def __init__(self, *args, **kwargs):
            nonlocal next_ordinal
            super().__init__(*args, **kwargs)
            with ordinal_lock:
                next_ordinal += 1
                self.ordinal = next_ordinal
            if self.ordinal == 2:
                second_transaction_opened.set()

        def save_cursor(self, *args, **kwargs):
            result = super().save_cursor(*args, **kwargs)
            if self.ordinal == 1:
                # Force the cursor mutation to SQL before exposing the barrier.
                # This makes the held SQLite writer slot observable rather than
                # relying on SQLAlchemy's deferred flush behavior.
                self.db.flush()
                cursor_written.set()
                assert allow_first_commit.wait(timeout=5)
            return result

    class ObservedUnitOfWork(SqlAlchemySchedulingUnitOfWork):
        def transaction(self):
            # The first call is already paused when the second scheduling call
            # starts, so this event identifies the second transaction attempt.
            if cursor_written.is_set():
                second_transaction_attempted.set()
            return super().transaction()

    uow = ObservedUnitOfWork(
        factory, pools, ledger, transaction_type=PausingTransaction
    )
    scheduler = PhysicalSettlementScheduler(
        unit_of_work=uow,
        default_resource_kind="compute.gpu",
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(scheduler.schedule_resource, _request(first_id))
        assert cursor_written.wait(timeout=5)
        second_future = executor.submit(scheduler.schedule_resource, _request(second_id))
        assert second_transaction_attempted.wait(timeout=5)
        assert not second_transaction_opened.is_set()
        allow_first_commit.set()
        first = first_future.result(timeout=5)
        second = second_future.result(timeout=5)

    assert second_transaction_opened.is_set()
    assert [first.pool_id, second.pool_id] == ["pool-a", "pool-b"]


def test_independent_session_rollback_restores_first_fairness_turn(tmp_path):
    """A blocked follower observes none of a failed writer's flushed state."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from market_fulfillment import (
        SqlAlchemySchedulingTransaction,
        SqlAlchemySchedulingUnitOfWork,
    )

    database = tmp_path / "rollback-scheduling.db"
    engine = create_engine(
        f"sqlite:///{database}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )
    PoolsBase.metadata.create_all(bind=engine)
    SiteBase.metadata.create_all(bind=engine)
    FulfillmentBase.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)
    pools = ResourcePoolService(
        factory,
        cast(Any, {"ansible": _Handler()}),
    )
    ledger = CapacityLedgerService(
        factory,
        unit_claim_keys=("units", "gpu_count"),
    )
    repository = SettlementRepository()
    _pool(pools, "pool-a")
    _pool(pools, "pool-b")
    _resource(ledger, "b1", "pool-b", units=10)
    failed_id = _reserve(ledger, agreement="rollback-writer")
    _resource(ledger, "a1", "pool-a", units=10)
    follower_id = _reserve(ledger, agreement="rollback-follower")

    writer_mutated = Event()
    release_writer = Event()
    follower_attempted = Event()
    follower_entered = Event()

    class FailingTransaction(SqlAlchemySchedulingTransaction):
        def schedule_assignment(self, **kwargs):
            result = super().schedule_assignment(**kwargs)
            if kwargs["capacity_reservation_id"] == failed_id:
                self.db.flush()
                writer_mutated.set()
                assert release_writer.wait(timeout=5)
                raise RuntimeError("controlled scheduling rollback")
            return result

    class ObservedUnitOfWork(SqlAlchemySchedulingUnitOfWork):
        def transaction(self):
            if writer_mutated.is_set():
                follower_attempted.set()
            context = super().transaction()

            class _ObservedContext:
                def __enter__(self):
                    transaction = context.__enter__()
                    if follower_attempted.is_set():
                        follower_entered.set()
                    return transaction

                def __exit__(self, *args):
                    return context.__exit__(*args)

            return _ObservedContext()

    uow = ObservedUnitOfWork(
        factory,
        pools,
        ledger,
        repository,
        transaction_type=FailingTransaction,
    )
    scheduler = PhysicalSettlementScheduler(
        unit_of_work=uow,
        default_resource_kind="compute.gpu",
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        failed_future = executor.submit(
            scheduler.schedule_resource,
            _request(failed_id),
        )
        assert writer_mutated.wait(timeout=5)
        follower_future = executor.submit(
            scheduler.schedule_resource,
            _request(follower_id),
        )
        assert follower_attempted.wait(timeout=5)
        assert not follower_entered.is_set()
        release_writer.set()
        with pytest.raises(RuntimeError, match="controlled scheduling rollback"):
            failed_future.result(timeout=5)
        follower = follower_future.result(timeout=5)

    assert follower_entered.is_set()
    assert (follower.pool_id, follower.settlement_resource_id) == (
        "pool-a",
        "a1",
    )
    assert ledger.get_reservation_backing_resource_id(failed_id) == "b1"
    failed_reservation = ledger.get_reservation(
        capacity_reservation_id=failed_id,
    )
    assert failed_reservation is not None
    assert failed_reservation["settlement_resource_id"] is None
    with factory() as db:
        assert repository.get(db, failed_id) is None
        assert repository.get(db, follower_id) is not None
        cursor = repository.get_cursor_in_session(db, "compute.gpu")
        assert cursor.last_pool_id == "pool-a"
        assert cursor.last_resource_by_pool == {"pool-a": "a1"}


def test_independent_sessions_serialize_distinct_resource_kind_cursors(tmp_path):
    """SQLite serializes writers while each resource kind keeps its own turn."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from market_fulfillment import (
        SqlAlchemySchedulingTransaction,
        SqlAlchemySchedulingUnitOfWork,
    )

    database = tmp_path / "resource-kind-scheduling.db"
    engine = create_engine(
        f"sqlite:///{database}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )
    PoolsBase.metadata.create_all(bind=engine)
    SiteBase.metadata.create_all(bind=engine)
    FulfillmentBase.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)
    pools = ResourcePoolService(
        factory,
        cast(Any, {"ansible": _Handler()}),
    )
    ledger = CapacityLedgerService(
        factory,
        unit_claim_keys=("units", "gpu_count"),
    )
    repository = SettlementRepository()
    _pool(pools, "pool-a")
    _pool(pools, "pool-b")
    _resource(ledger, "gpu-a1", "pool-a", units=10)
    _resource(ledger, "gpu-b1", "pool-b", units=10)
    ledger.register_resource(
        resource_id="bm-a1",
        resource_type="bare_metal",
        total_units=1,
        pool_id="pool-a",
    )
    ledger.register_resource(
        resource_id="bm-b1",
        resource_type="bare_metal",
        total_units=1,
        pool_id="pool-b",
    )
    gpu_id = _reserve(ledger, agreement="gpu-writer")
    bare_metal_reservation = ledger.reserve(
        claim={"resource_type": "bare_metal", "units": 1},
        deal_ref={"market": "bare_metal"},
    )
    assert bare_metal_reservation is not None
    bare_metal_id = bare_metal_reservation["capacity_reservation_id"]

    gpu_mutated = Event()
    release_gpu = Event()
    bare_metal_attempted = Event()
    bare_metal_entered = Event()

    class PausingTransaction(SqlAlchemySchedulingTransaction):
        def schedule_assignment(self, **kwargs):
            result = super().schedule_assignment(**kwargs)
            if kwargs["capacity_reservation_id"] == gpu_id:
                self.db.flush()
                gpu_mutated.set()
                assert release_gpu.wait(timeout=5)
            return result

    class ObservedUnitOfWork(SqlAlchemySchedulingUnitOfWork):
        def transaction(self):
            if gpu_mutated.is_set():
                bare_metal_attempted.set()
            context = super().transaction()

            class _ObservedContext:
                def __enter__(self):
                    transaction = context.__enter__()
                    if bare_metal_attempted.is_set():
                        bare_metal_entered.set()
                    return transaction

                def __exit__(self, *args):
                    return context.__exit__(*args)

            return _ObservedContext()

    uow = ObservedUnitOfWork(
        factory,
        pools,
        ledger,
        repository,
        transaction_type=PausingTransaction,
    )
    scheduler = PhysicalSettlementScheduler(
        unit_of_work=uow,
        default_resource_kind="compute.gpu",
    )
    bare_metal_request = PhysicalSettlementRequest(
        capacity_reservation_id=bare_metal_id,
        market="bare_metal",
        requirements={"resource_kind": "bare_metal"},
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        gpu_future = executor.submit(
            scheduler.schedule_resource,
            _request(gpu_id),
        )
        assert gpu_mutated.wait(timeout=5)
        bare_metal_future = executor.submit(
            scheduler.schedule_resource,
            bare_metal_request,
        )
        assert bare_metal_attempted.wait(timeout=5)
        assert not bare_metal_entered.is_set()
        release_gpu.set()
        gpu = gpu_future.result(timeout=5)
        bare_metal = bare_metal_future.result(timeout=5)

    assert bare_metal_entered.is_set()
    assert (gpu.pool_id, gpu.settlement_resource_id) == (
        "pool-a",
        "gpu-a1",
    )
    assert (bare_metal.pool_id, bare_metal.settlement_resource_id) == (
        "pool-a",
        "bm-a1",
    )
    with factory() as db:
        gpu_cursor = repository.get_cursor_in_session(db, "compute.gpu")
        bare_metal_cursor = repository.get_cursor_in_session(db, "bare_metal")
        assert gpu_cursor.last_resource_by_pool == {"pool-a": "gpu-a1"}
        assert bare_metal_cursor.last_resource_by_pool == {
            "pool-a": "bm-a1",
        }
