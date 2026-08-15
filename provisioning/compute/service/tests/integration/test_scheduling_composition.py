"""Production-composition proof for atomic settlement scheduling.

Every other scheduling test (`kit/fulfillment/tests/unit/test_scheduler.py`)
composes `PhysicalSettlementScheduler` from hand-built services. This file
instead resolves the scheduler, site ledger, resource-pool service,
settlement repository, abandonment hook, and scheduling unit of work through
a real `compute_provisioning_service.container.Container` instance -- the
same provider graph `app_runtime.py` uses at startup -- proving they resolve
to one effective database/session-factory boundary and that a real schedule
commits, or a controlled failure rolls back, together.
"""
from __future__ import annotations

from dependency_injector import providers
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from compute_provisioning_service.container import Container
from compute_provisioning_service.db.models import Base
from market_fulfillment import FulfillmentBase, PhysicalSettlementRequest
from market_resource_pools import PoolCreate
from market_resource_pools.db import Base as PoolsBase
from market_site.db import Base as SiteBase


def _build_container():
    """A fresh `Container` instance wired to an isolated in-memory database.

    `ACTIVE_PROFILES=mock` (set for this whole test run, see Makefile)
    makes `build_vm_runtime` compose `ProgrammableMockAnsibleService`
    instead of a real Ansible client, so resolving the container's VM
    runtime -- required to resolve `resource_pool_service`'s Ansible pool
    config handler -- performs no real network I/O.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    PoolsBase.metadata.create_all(bind=engine)
    SiteBase.metadata.create_all(bind=engine)
    FulfillmentBase.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)

    container = Container()
    container.session_factory.override(providers.Object(session_factory))
    return container, session_factory


def test_real_container_resolves_scheduling_dependencies_to_one_boundary():
    container, session_factory = _build_container()

    scheduler = container.physical_settlement_scheduler()
    pool_service = container.resource_pool_service()
    ledger = container.capacity_ledger_service()
    repository = container.settlement_repository()

    # All four resolve to the same session_factory -- the "one effective
    # database/session-factory boundary" 4.13.1 requires -- rather than
    # each independently constructing its own engine/session.
    assert pool_service._session_factory is session_factory
    assert ledger._session_factory is session_factory
    assert scheduler is container.physical_settlement_scheduler()  # Singleton

    pool_service.create_pool(
        PoolCreate(
            id="pool-a", label="Pool A", provider="ansible",
            policy_tags={"deliverable_modes": ["vm"]},
            provider_config={"playbook_path": "p.yaml"},
        )
    )
    ledger.register_resource(
        resource_id="r1", resource_type="compute.gpu",
        total_units=10, enabled=True, pool_id="pool-a",
    )
    reservation = ledger.reserve(
        claim={"executor_kind": "vm", "gpu_count": 1},
        deal_ref={"agreement_id": "composition-1", "market": "vms"},
    )
    assert reservation is not None
    capacity_reservation_id = reservation["capacity_reservation_id"]

    resource = scheduler.schedule_resource(
        PhysicalSettlementRequest(
            capacity_reservation_id=capacity_reservation_id, market="vms",
        )
    )

    assert resource.pool_id == "pool-a"
    assert resource.settlement_resource_id == "r1"

    with session_factory() as db:
        record = repository.get(db, capacity_reservation_id)
        assert record is not None
        assert record.settlement_resource_id == "r1"
    assert ledger.get_reservation_backing_resource_id(capacity_reservation_id) == "r1"


def test_real_container_composed_schedule_rolls_back_all_participating_tables():
    """Inject a controlled failure after site-capacity and fulfillment
    persistence have both mutated in the same transaction and assert both
    roll back together -- proving the real container-resolved scheduler
    shares one commit/rollback boundary, not two independently-committing
    ones."""
    container, session_factory = _build_container()

    scheduler = container.physical_settlement_scheduler()
    pool_service = container.resource_pool_service()
    ledger = container.capacity_ledger_service()

    pool_service.create_pool(
        PoolCreate(
            id="pool-a", label="Pool A", provider="ansible",
            policy_tags={"deliverable_modes": ["vm"]},
            provider_config={"playbook_path": "p.yaml"},
        )
    )
    pool_service.create_pool(
        PoolCreate(
            id="pool-b", label="Pool B", provider="ansible",
            policy_tags={"deliverable_modes": ["vm"]},
            provider_config={"playbook_path": "p.yaml"},
        )
    )
    ledger.register_resource(
        resource_id="r1", resource_type="compute.gpu",
        total_units=10, enabled=True, pool_id="pool-a",
    )
    ledger.register_resource(
        resource_id="r2", resource_type="compute.gpu",
        total_units=10, enabled=True, pool_id="pool-b",
    )

    # Schedule a first reservation for real (no injected failure) so the
    # durable round-robin cursor advances to pool-b. Admission always binds
    # a reservation's *initial* backing resource independently of the
    # cursor, so the second reservation below admits onto pool-a (the
    # first eligible candidate) while the cursor now points the scheduler
    # at pool-b -- guaranteeing the second call's `rebind_capacity` is a
    # real write, not a same-resource no-op, so its rollback is actually
    # exercised.
    first_reservation = ledger.reserve(
        claim={"executor_kind": "vm", "gpu_count": 1},
        deal_ref={"agreement_id": "composition-rollback-warmup", "market": "vms"},
    )
    assert first_reservation is not None
    scheduler.schedule_resource(
        PhysicalSettlementRequest(
            capacity_reservation_id=first_reservation["capacity_reservation_id"], market="vms",
        )
    )

    reservation = ledger.reserve(
        claim={"executor_kind": "vm", "gpu_count": 1},
        deal_ref={"agreement_id": "composition-rollback-1", "market": "vms"},
    )
    assert reservation is not None
    capacity_reservation_id = reservation["capacity_reservation_id"]
    admission_time_backing = ledger.get_reservation_backing_resource_id(capacity_reservation_id)
    assert admission_time_backing == "r1"  # first eligible candidate, unrelated to the cursor

    unit_of_work = container.scheduling_unit_of_work()
    original_transaction = unit_of_work.transaction_type

    class FailingTransaction(original_transaction):
        def schedule_assignment(self, **kwargs):
            super().schedule_assignment(**kwargs)
            raise RuntimeError("controlled failure after writes, before commit")

    unit_of_work.transaction_type = FailingTransaction
    try:
        try:
            scheduler.schedule_resource(
                PhysicalSettlementRequest(
                    capacity_reservation_id=capacity_reservation_id, market="vms",
                )
            )
            assert False, "expected the controlled failure to propagate"
        except RuntimeError:
            pass
    finally:
        unit_of_work.transaction_type = original_transaction

    # Fulfillment-side write rolled back...
    with session_factory() as db:
        repository = container.settlement_repository()
        assert repository.get(db, capacity_reservation_id) is None
    # ...and so did the site-capacity rebind: the cursor had pointed the
    # scheduler at pool-b/r2 (a genuine change from admission's pool-a/r1),
    # so `rebind_capacity` did run inside the failed transaction, and its
    # write did not survive the rollback -- the reservation is still on
    # its admission-time resource, not partially moved to r2.
    assert ledger.get_reservation_backing_resource_id(capacity_reservation_id) == "r1"

    # The database, and the same container-resolved scheduler, remain
    # usable: a retry succeeds and (since the cursor's own advance rolled
    # back too) deterministically re-selects the same pool-b/r2 turn.
    resource = scheduler.schedule_resource(
        PhysicalSettlementRequest(
            capacity_reservation_id=capacity_reservation_id, market="vms",
        )
    )
    assert resource.settlement_resource_id == "r2"
