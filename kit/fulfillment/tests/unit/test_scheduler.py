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

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from market_fulfillment import (
    CapacityReservationExpiredError,
    MissingResourceKindError,
    NoEligibleSettlementResourceError,
    PhysicalSettlementRequest,
    PhysicalSettlementScheduler,
    SettlementEntityNotFoundError,
    SettlementRequestMismatchError,
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
    factory = sessionmaker(bind=engine)
    pools = ResourcePoolService(factory, {"ansible": _Handler()})
    # This test suite's claims are VM-flavored ("gpu_count"); opt into
    # that alias explicitly the same way the VM composition root does
    # (kit/site's own default is domain-neutral -- see ledger.py).
    ledger = CapacityLedgerService(factory, unit_claim_keys=("units", "gpu_count"))
    scheduler = PhysicalSettlementScheduler(pools, ledger, default_resource_kind="compute.gpu")
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
        attributes={"pool_id": pool_id},
    )


def _reserve(ledger, agreement="agreement-1", **deal):
    ref = {"agreement_id": agreement, "market": "vms", **deal}
    result = ledger.reserve(claim={"gpu_count": 1}, deal_ref=ref)
    assert result is not None
    return result["capacity_reservation_id"]


def _request(capacity_reservation_id: str, **kwargs):
    return PhysicalSettlementRequest(
        capacity_reservation_id=capacity_reservation_id,
        market="vms",
        **kwargs,
    )


def test_unknown_reservation_is_rejected(services):
    _, _, scheduler = services
    with pytest.raises(SettlementEntityNotFoundError):
        scheduler.select_resource(_request("missing"))


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
        scheduler.select_resource(_request(result["capacity_reservation_id"]))


def test_retry_is_idempotent_and_does_not_rerun_policy(services):
    pools, ledger, scheduler = services
    _pool(pools, "pool-a")
    _pool(pools, "pool-b")
    _resource(ledger, "a1", "pool-a")
    _resource(ledger, "b1", "pool-b")
    capacity_reservation_id = _reserve(ledger)
    first = scheduler.select_resource(_request(capacity_reservation_id))
    second = scheduler.select_resource(_request(capacity_reservation_id))
    assert first == second


def test_round_robin_is_deterministic_across_pools(services):
    pools, ledger, scheduler = services
    _pool(pools, "pool-a")
    _pool(pools, "pool-b")
    _resource(ledger, "a1", "pool-a", units=10)
    _resource(ledger, "b1", "pool-b", units=10)
    ids = [_reserve(ledger, agreement=f"agreement-{i}") for i in range(1, 4)]
    selected = [
        scheduler.select_resource(_request(rid)).pool_id
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
        scheduler.select_resource(_request(rid)).settlement_resource_id
        for rid in ids
    ]
    assert selected == ["r1", "r2"]


def test_explicit_resource_bypasses_policy_not_eligibility(services):
    pools, ledger, scheduler = services
    _pool(pools, "pool-a", enabled=False)
    _resource(ledger, "r1", "pool-a")
    capacity_reservation_id = _reserve(ledger)
    with pytest.raises(NoEligibleSettlementResourceError):
        scheduler.select_resource(_request(capacity_reservation_id, resource_id="r1"))


def test_resource_without_pool_is_not_schedulable(services):
    pools, ledger, scheduler = services
    _pool(pools, "pool-a")
    ledger.register_resource(resource_id="orphan", total_units=4, attributes={})
    capacity_reservation_id = _reserve(ledger)
    with pytest.raises(NoEligibleSettlementResourceError):
        scheduler.select_resource(_request(capacity_reservation_id))


def test_disabling_pool_does_not_depend_on_existing_assignment(services):
    pools, ledger, scheduler = services
    _pool(pools, "pool-a")
    _resource(ledger, "r1", "pool-a")
    capacity_reservation_id = _reserve(ledger)
    scheduler.select_resource(_request(capacity_reservation_id))
    disabled = pools.disable_pool("pool-a")
    assert disabled.enabled is False


def test_missing_resource_kind_raises_when_no_default_configured(services):
    pools, ledger, _ = services
    scheduler = PhysicalSettlementScheduler(pools, ledger)  # no default_resource_kind
    _pool(pools, "pool-a")
    _resource(ledger, "r1", "pool-a")
    capacity_reservation_id = _reserve(ledger)
    with pytest.raises(MissingResourceKindError):
        scheduler.select_resource(_request(capacity_reservation_id))


# ----------------------------------------------------------------------
# multidimensional eligibility
# ----------------------------------------------------------------------

def _resource_with_capacity(ledger, resource_id: str, pool_id: str, *, capacity: dict, enabled=True):
    ledger.register_resource(
        resource_id=resource_id,
        resource_type="compute.gpu",
        total_units=capacity.get("gpu_count", 1),
        enabled=enabled,
        attributes={"pool_id": pool_id},
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
        scheduler.select_resource(_request(
            capacity_reservation_id, requirements={"dimensions": dims}, resource_id="ram-short",
        ))
    resource = scheduler.select_resource(
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
    resource = scheduler.select_resource(
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
    resource = scheduler.select_resource(_request(capacity_reservation_id))
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
    resource = scheduler.select_resource(_request(result["capacity_reservation_id"]))
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
    resource = scheduler.select_resource(_request(
        capacity_reservation_id,
        requirements={"dimensions": {"gpu_count": 2, "ram_gb": 64}},
    ))
    assert resource.settlement_resource_id == "r1"


def test_schedule_request_equal_to_reservation_is_permitted(services):
    pools, ledger, scheduler = services
    _pool(pools, "pool-a")
    _resource_with_capacity(ledger, "r1", "pool-a", capacity={"gpu_count": 8})
    capacity_reservation_id = _reserve_multi(ledger, {"gpu_count": 4})
    resource = scheduler.select_resource(_request(
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
        scheduler.select_resource(_request(
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
    resource = scheduler.select_resource(_request(
        capacity_reservation_id,
        requirements={"dimensions": {"gpu_count": 2, "vcpu_count": 8}},
    ))
    assert resource.settlement_resource_id == "r1"
