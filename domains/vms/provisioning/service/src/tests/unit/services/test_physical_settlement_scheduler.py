"""Unit tests for PhysicalSettlementScheduler.

Covers: idempotency by allocation_id, disabled/exhausted pool exclusion,
explicit resource_id binding without substitution, no-match errors, and
dimension-agnostic bottleneck-normalized pool selection.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from compute_provisioning import PhysicalSettlementRequest
from db.models import Base, Host
from market_resource_pools import PoolCreate, ResourcePoolService
from market_resource_pools.db import Base as PoolsBase
from market_site.db import Base as SiteBase
from market_site.ledger import CapacityLedgerService
from services.physical_settlement_scheduler import (
    NoEligiblePoolError,
    PhysicalSettlementScheduler,
    ResourceNotFoundError,
)


class _StubPoolConfigHandler:
    provider = "ansible"

    def validate_config(self, config):
        return dict(config)

    def validate_config_problems(self, config):
        return dict(config), ()

    def read_config(self, db, pool_id):
        return {}

    def replace_config(self, db, pool_id, config):
        pass

    def delete_config(self, db, pool_id):
        pass


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # resource_pools must exist before Base's Host.pool_id FK resolves.
    PoolsBase.metadata.create_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    SiteBase.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)


@pytest.fixture
def pool_service(session_factory):
    return ResourcePoolService(
        session_factory=session_factory,
        handlers={"ansible": _StubPoolConfigHandler()},
    )


@pytest.fixture
def capacity_ledger(session_factory):
    return CapacityLedgerService(session_factory=session_factory)


@pytest.fixture
def scheduler(pool_service, capacity_ledger, session_factory):
    return PhysicalSettlementScheduler(
        pool_service=pool_service,
        capacity_ledger=capacity_ledger,
        session_factory=session_factory,
    )


def _add_host(session_factory, name: str, pool_id: str) -> None:
    with session_factory() as db:
        db.add(Host(
            name=name, kvm_host="10.0.0.1", ssh_user="ubuntu",
            ssh_key_type="path", ssh_key_value="/key", pool_id=pool_id,
        ))
        db.commit()


def _request(allocation_id="alloc-1", **kwargs) -> PhysicalSettlementRequest:
    return PhysicalSettlementRequest(
        allocation_id=allocation_id, agreement_id="agree-1", market="vms", **kwargs
    )


class TestIdempotency:
    def test_repeated_calls_return_the_same_binding(
        self, scheduler, pool_service, capacity_ledger, session_factory
    ):
        pool_service.create_pool(
            PoolCreate(id="pool-a", label="A", provider="ansible", provider_config={})
        )
        _add_host(session_factory, "kvm1", "pool-a")
        capacity_ledger.register_resource(
            resource_id="kvm1", total_units=4, attributes={"vm_host": "kvm1"},
        )

        first = scheduler.select_resource(_request())
        second = scheduler.select_resource(_request())
        assert first == second
        assert first.settlement_resource_id == "kvm1"
        assert first.pool_id == "pool-a"


class TestPoolExclusion:
    def test_disabled_pool_is_excluded(
        self, scheduler, pool_service, capacity_ledger, session_factory
    ):
        pool_service.create_pool(
            PoolCreate(id="pool-a", label="A", provider="ansible", provider_config={})
        )
        pool_service.disable_pool("pool-a")
        _add_host(session_factory, "kvm1", "pool-a")
        capacity_ledger.register_resource(
            resource_id="kvm1", total_units=4, attributes={"vm_host": "kvm1"},
        )

        with pytest.raises(NoEligiblePoolError):
            scheduler.select_resource(_request())

    def test_exhausted_pool_is_excluded(
        self, scheduler, pool_service, capacity_ledger, session_factory
    ):
        pool_service.create_pool(
            PoolCreate(id="pool-a", label="A", provider="ansible", provider_config={})
        )
        _add_host(session_factory, "kvm1", "pool-a")
        capacity_ledger.register_resource(
            resource_id="kvm1", total_units=1, attributes={"vm_host": "kvm1"},
        )
        capacity_ledger.reserve(claim={"gpu_count": 1}, deal_ref={"escrow_uid": "0x1"})

        with pytest.raises(NoEligiblePoolError):
            scheduler.select_resource(_request())

    def test_explicit_pool_id_restricts_selection(
        self, scheduler, pool_service, capacity_ledger, session_factory
    ):
        pool_service.create_pool(
            PoolCreate(id="pool-a", label="A", provider="ansible", provider_config={})
        )
        pool_service.create_pool(
            PoolCreate(id="pool-b", label="B", provider="ansible", provider_config={})
        )
        _add_host(session_factory, "kvm1", "pool-a")
        _add_host(session_factory, "kvm2", "pool-b")
        capacity_ledger.register_resource(
            resource_id="kvm1", total_units=4, attributes={"vm_host": "kvm1"},
        )
        capacity_ledger.register_resource(
            resource_id="kvm2", total_units=4, attributes={"vm_host": "kvm2"},
        )

        bound = scheduler.select_resource(_request(pool_id="pool-b"))
        assert bound.pool_id == "pool-b"
        assert bound.settlement_resource_id == "kvm2"


class TestExplicitResourceId:
    def test_binds_exactly_the_requested_resource(
        self, scheduler, pool_service, capacity_ledger, session_factory
    ):
        pool_service.create_pool(
            PoolCreate(id="pool-a", label="A", provider="ansible", provider_config={})
        )
        _add_host(session_factory, "kvm1", "pool-a")
        capacity_ledger.register_resource(
            resource_id="kvm1", total_units=4, attributes={"vm_host": "kvm1"},
        )

        bound = scheduler.select_resource(_request(resource_id="kvm1"))
        assert bound.settlement_resource_id == "kvm1"
        assert bound.pool_id == "pool-a"

    def test_unknown_resource_id_raises(self, scheduler):
        with pytest.raises(ResourceNotFoundError):
            scheduler.select_resource(_request(resource_id="does-not-exist"))

    def test_disabled_resource_raises(
        self, scheduler, pool_service, capacity_ledger, session_factory
    ):
        pool_service.create_pool(
            PoolCreate(id="pool-a", label="A", provider="ansible", provider_config={})
        )
        _add_host(session_factory, "kvm1", "pool-a")
        capacity_ledger.register_resource(
            resource_id="kvm1", total_units=4, attributes={"vm_host": "kvm1"},
            enabled=False,
        )

        with pytest.raises(ResourceNotFoundError):
            scheduler.select_resource(_request(resource_id="kvm1"))


class TestBottleneckNormalizedSelection:
    def test_prefers_pool_with_lower_bottleneck_dimension(
        self, scheduler, pool_service, capacity_ledger, session_factory
    ):
        """pool-a is 90% utilized on one resource_type; pool-b is 50%
        utilized. Even though both pools have only one resource each,
        this exercises the utilization comparison rather than a
        first-match/round-robin fallback."""
        pool_service.create_pool(
            PoolCreate(id="pool-a", label="A", provider="ansible", provider_config={})
        )
        pool_service.create_pool(
            PoolCreate(id="pool-b", label="B", provider="ansible", provider_config={})
        )
        _add_host(session_factory, "kvm1", "pool-a")
        _add_host(session_factory, "kvm2", "pool-b")
        capacity_ledger.register_resource(
            resource_id="kvm1", total_units=10, attributes={"vm_host": "kvm1"},
        )
        capacity_ledger.register_resource(
            resource_id="kvm2", total_units=10, attributes={"vm_host": "kvm2"},
        )
        # Reserve 9/10 on kvm1 (pool-a) — 90% utilized. Pinned by
        # resource_id so the test doesn't depend on the ledger's own
        # candidate-selection order between two equally-sized resources.
        capacity_ledger.reserve(
            claim={"gpu_count": 9, "resource_id": "kvm1"},
            deal_ref={"escrow_uid": "0xa"},
        )

        bound = scheduler.select_resource(_request())
        assert bound.pool_id == "pool-b"
