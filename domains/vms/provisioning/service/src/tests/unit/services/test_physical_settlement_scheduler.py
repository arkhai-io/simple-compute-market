"""Unit tests for deterministic Capacity Settlement Assignment scheduling."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from compute_provisioning import (
    CapacityReservationExpiredError,
    NoEligibleSettlementResourceError,
    PhysicalSettlementRequest,
    SettlementEntityNotFoundError,
    SettlementRequestMismatchError,
)
from market_resource_pools import PoolCreate, ResourcePoolService
from market_resource_pools.db import Base as PoolsBase
from market_site.db import Base as SiteBase
from market_site.ledger import CapacityLedgerService
from services.physical_settlement_scheduler import PhysicalSettlementScheduler


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
    ledger = CapacityLedgerService(factory)
    scheduler = PhysicalSettlementScheduler(pools, ledger)
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
    return result["allocation_id"]


def _request(allocation_id: str, **kwargs):
    return PhysicalSettlementRequest(
        allocation_id=allocation_id,
        agreement_id=kwargs.pop("agreement_id", "agreement-1"),
        market="vms",
        **kwargs,
    )


def test_unknown_allocation_is_rejected(services):
    _, _, scheduler = services
    with pytest.raises(SettlementEntityNotFoundError):
        scheduler.select_resource(_request("missing"))


def test_agreement_mismatch_is_rejected(services):
    pools, ledger, scheduler = services
    _pool(pools, "pool-a")
    _resource(ledger, "r1", "pool-a")
    allocation_id = _reserve(ledger)
    with pytest.raises(SettlementRequestMismatchError):
        scheduler.select_resource(_request(allocation_id, agreement_id="other"))


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
        scheduler.select_resource(_request(result["allocation_id"]))


def test_retry_is_idempotent_and_does_not_rerun_policy(services):
    pools, ledger, scheduler = services
    _pool(pools, "pool-a")
    _pool(pools, "pool-b")
    _resource(ledger, "a1", "pool-a")
    _resource(ledger, "b1", "pool-b")
    allocation_id = _reserve(ledger)
    first = scheduler.select_resource(_request(allocation_id))
    second = scheduler.select_resource(_request(allocation_id))
    assert first == second


def test_round_robin_is_deterministic_across_pools(services):
    pools, ledger, scheduler = services
    _pool(pools, "pool-a")
    _pool(pools, "pool-b")
    _resource(ledger, "a1", "pool-a", units=10)
    _resource(ledger, "b1", "pool-b", units=10)
    ids = [_reserve(ledger, agreement=f"agreement-{i}") for i in range(1, 4)]
    selected = [
        scheduler.select_resource(_request(aid, agreement_id=f"agreement-{i}" )).pool_id
        for i, aid in enumerate(ids, 1)
    ]
    assert selected == ["pool-a", "pool-b", "pool-a"]


def test_round_robin_is_deterministic_within_pool(services):
    pools, ledger, scheduler = services
    _pool(pools, "pool-a")
    _resource(ledger, "r1", "pool-a", units=10)
    _resource(ledger, "r2", "pool-a", units=10)
    ids = [_reserve(ledger, agreement=f"agreement-{i}") for i in range(1, 3)]
    selected = [
        scheduler.select_resource(_request(aid, agreement_id=f"agreement-{i}")).settlement_resource_id
        for i, aid in enumerate(ids, 1)
    ]
    assert selected == ["r1", "r2"]


def test_explicit_resource_bypasses_policy_not_eligibility(services):
    pools, ledger, scheduler = services
    _pool(pools, "pool-a", enabled=False)
    _resource(ledger, "r1", "pool-a")
    allocation_id = _reserve(ledger)
    with pytest.raises(NoEligibleSettlementResourceError):
        scheduler.select_resource(_request(allocation_id, resource_id="r1"))


def test_resource_without_pool_is_not_schedulable(services):
    pools, ledger, scheduler = services
    _pool(pools, "pool-a")
    ledger.register_resource(resource_id="orphan", total_units=4, attributes={})
    allocation_id = _reserve(ledger)
    with pytest.raises(NoEligibleSettlementResourceError):
        scheduler.select_resource(_request(allocation_id))


def test_disabling_pool_does_not_depend_on_existing_assignment(services):
    pools, ledger, scheduler = services
    _pool(pools, "pool-a")
    _resource(ledger, "r1", "pool-a")
    allocation_id = _reserve(ledger)
    scheduler.select_resource(_request(allocation_id))
    disabled = pools.disable_pool("pool-a")
    assert disabled.enabled is False

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
    return result["allocation_id"]


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
    allocation_id = _reserve_with_dimensions(ledger, dims)
    # Pinning the RAM-short resource explicitly must fail eligibility,
    # checked before any assignment memoizes a different resource.
    with pytest.raises(NoEligibleSettlementResourceError):
        scheduler.select_resource(_request(
            allocation_id, requirements={"dimensions": dims}, resource_id="ram-short",
        ))
    resource = scheduler.select_resource(
        _request(allocation_id, requirements={"dimensions": dims})
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
    allocation_id = _reserve_with_dimensions(ledger, dims)
    resource = scheduler.select_resource(
        _request(allocation_id, requirements={"dimensions": dims})
    )
    assert resource.settlement_resource_id == "r1"


def test_scheduler_still_schedules_legacy_gpu_only_requests(services):
    """Reservations made before pass 1 (no dimensions) keep scheduling
    exactly as they did under round-robin."""
    pools, ledger, scheduler = services
    _pool(pools, "pool-a")
    _resource(ledger, "r1", "pool-a", units=10)
    allocation_id = _reserve(ledger)
    resource = scheduler.select_resource(_request(allocation_id))
    assert resource.settlement_resource_id == "r1"


def test_scheduler_credit_back_covers_full_capacity_legacy_allocation(services):
    """A legacy allocation reserving *all* of a resource's capacity must
    still be schedulable: the eligibility scan credits the allocation's
    own held quantity back before checking fit, and that credit-back must
    not silently become a no-op for an allocation whose claim never
    mentioned "dimensions", but locking the invariant in with a test at
    the layer that actually depends on it)."""
    pools, ledger, scheduler = services
    _pool(pools, "pool-a")
    _resource(ledger, "r1", "pool-a", units=4)
    result = ledger.reserve(claim={"gpu_count": 4}, deal_ref={
        "agreement_id": "agreement-1", "market": "vms",
    })
    assert result is not None
    resource = scheduler.select_resource(_request(result["allocation_id"]))
    assert resource.settlement_resource_id == "r1"
