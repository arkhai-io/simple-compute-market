"""Library integration tests for independent-session fulfillment acceptance."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from market_core import VersionedEnvelope
from market_fulfillment import (
    FulfillmentOrchestrator, FulfillmentResult, ProviderRegistry, SettlementRecordState,
)
from market_fulfillment.fulfillment_persistence import (
    SqlAlchemyFulfillmentTransaction, SqlAlchemyFulfillmentUnitOfWork,
)
from market_fulfillment.migrations import BASELINE as FULFILLMENT_BASELINE
from market_fulfillment.settlement_repository import SettlementRepository
from market_fulfillment.settlement_types import SettlementRequirement, SettlementResource
from market_resource_pools import ResourcePoolService
from market_resource_pools.migrations import BASELINE as POOLS_BASELINE
from market_resource_pools_contracts import PoolCreate


class _ProviderMock(MagicMock):
    needs_host = True


class _Handler:
    provider = "ansible"

    def validate_config(self, config):
        return dict(config)

    def validate_config_problems(self, config):
        return dict(config), ()

    def read_config(self, db, pool_id):
        return {}

    def read_config_for_execution(self, db, pool_id):
        # Dispatch reads through this one; a handler that omits it fails
        # loudly here rather than returning configuration with its secrets
        # silently missing.
        return self.read_config(db, pool_id)

    def replace_config(self, db, pool_id, config):
        pass


def test_independent_sessions_serialize_fulfillment_acceptance_deterministically(tmp_path):
    """A controlled transaction barrier proves SQLite writer serialization
    for fulfillment acceptance without relying on an uncontrolled race or
    elapsed-time ordering -- mirrors test_scheduler.py's
    ``test_independent_sessions_serialize_cursor_updates_deterministically``
    for ``SchedulingUnitOfWork``.
    """
    database = tmp_path / "fulfillment.db"
    engine = create_engine(
        f"sqlite:///{database}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )
    with engine.begin() as connection:
        POOLS_BASELINE.apply(connection)
        FULFILLMENT_BASELINE.apply(connection)
    factory = sessionmaker(bind=engine)
    pools = ResourcePoolService(factory, {"ansible": _Handler()})
    pools.create_pool(
        PoolCreate(
            id="pool-a",
            label="pool-a",
            provider="ansible",
            policy_tags={"advertisable_modes": ["vm"], "capacity_backing": "backed", "deliverable_modes": ["vm"]},
            provider_config={},
        )
    )

    repo = SettlementRepository()
    with factory() as db:
        for capacity_reservation_id, resource_id in (("cr-1", "r1"), ("cr-2", "r2")):
            repo.schedule(
                db,
                capacity_reservation_id=capacity_reservation_id,
                market="vms",
                scheduling_requirements=SettlementRequirement(
                    offering_mode="vm",
                    resource_kind="vm", dimensions={"gpu_count": 1}
                ),
                resource=SettlementResource(
                    settlement_resource_id=resource_id,
                    offering_mode="vm",
                    pool_id="pool-a",
                    resource_kind="vm",
                    provider="ansible",
                ),
            )
        db.commit()

    accept_persisted = Event()
    allow_first_commit = Event()
    second_transaction_attempted = Event()
    second_transaction_opened = Event()
    ordinal_lock = Lock()
    next_ordinal = 0

    class PausingTransaction(SqlAlchemyFulfillmentTransaction):
        def __init__(self, *args, **kwargs):
            nonlocal next_ordinal
            super().__init__(*args, **kwargs)
            with ordinal_lock:
                next_ordinal += 1
                self.ordinal = next_ordinal

        def accept(self, *args, **kwargs):
            result = super().accept(*args, **kwargs)
            if self.ordinal == 2:
                # Reaching here means this session's BEGIN IMMEDIATE (issued
                # inside accept_fulfillment) actually completed -- only
                # possible once the first session released the writer slot.
                second_transaction_opened.set()
            return result

        def persist_prepared_create(self, *args, **kwargs):
            result = super().persist_prepared_create(*args, **kwargs)
            if self.ordinal == 1:
                # Force the write to SQL before exposing the barrier, so the
                # held SQLite writer slot is observable rather than relying
                # on SQLAlchemy's deferred flush behavior.
                self.db.flush()
                accept_persisted.set()
                assert allow_first_commit.wait(timeout=5)
            return result

    class ObservedUnitOfWork(SqlAlchemyFulfillmentUnitOfWork):
        def transaction(self):
            # The first call is already paused when the second begin_fulfillment
            # call starts, so this event identifies the second attempt.
            if accept_persisted.is_set():
                second_transaction_attempted.set()
            return super().transaction()

    uow = ObservedUnitOfWork(
        factory, pools, repository=repo, transaction_type=PausingTransaction
    )
    provider = _ProviderMock()
    provider.resolve_executor_job_id.return_value = None
    provider.prepare_create.return_value = VersionedEnvelope(
        kind="vm.ansible.create.v1", schema_version=1, payload={"prepared": True},
    )
    provider.dispatch_create = AsyncMock(return_value=FulfillmentResult({"job_id": "job-1"}))
    orchestrator = FulfillmentOrchestrator(
        provider_registry=ProviderRegistry({"ansible": provider}), unit_of_work=uow,
    )
    request = VersionedEnvelope(
        kind="vm.fulfillment.request", schema_version=1, payload={"vm_target": "vm-1"},
    )

    def _begin(capacity_reservation_id: str):
        return asyncio.run(
            orchestrator.begin_fulfillment(capacity_reservation_id, "vms", request)
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(_begin, "cr-1")
        assert accept_persisted.wait(timeout=5)
        second_future = executor.submit(_begin, "cr-2")
        assert second_transaction_attempted.wait(timeout=5)
        assert not second_transaction_opened.is_set()
        allow_first_commit.set()
        first = first_future.result(timeout=5)
        second = second_future.result(timeout=5)

    assert second_transaction_opened.is_set()
    assert {first.capacity_reservation_id, second.capacity_reservation_id} == {
        "cr-1",
        "cr-2",
    }
    assert first.state == second.state == SettlementRecordState.dispatching.value


def _sessions_starting_with(first, factory):
    """A session factory that hands out ``first`` once, then fresh sessions."""
    pending = [first]

    def open_session():
        return pending.pop() if pending else factory()

    return open_session


def test_an_acceptance_that_read_the_row_before_another_committed_returns_the_first(
    tmp_path,
):
    """An equivalent acceptance judges the row its lock returns, not an earlier read.

    Session 2 reads the reservation's row while it is only scheduled, so its
    identity map holds the row with no ``fulfillment_id``. Session 1 then
    accepts the reservation, dispatches and commits. When session 2 accepts an
    equivalent request, the locked select returns that same identity-mapped
    object: without ``populate_existing`` it comes back unrefreshed, still
    reading ``fulfillment_id is None`` and ``assigned``, and session 2 would
    accept anew under a second fulfillment ID, prepare the create again and
    dispatch it again. The steps run one after another, each on its own
    session, so no thread or timing decides their order.
    """
    engine = create_engine(
        f"sqlite:///{tmp_path / 'fulfillment.db'}", connect_args={"timeout": 1}
    )
    with engine.begin() as connection:
        POOLS_BASELINE.apply(connection)
        FULFILLMENT_BASELINE.apply(connection)
    factory = sessionmaker(bind=engine)
    pools = ResourcePoolService(factory, {"ansible": _Handler()})
    pools.create_pool(
        PoolCreate(
            id="pool-a",
            label="pool-a",
            provider="ansible",
            policy_tags={
                "advertisable_modes": ["vm"],
                "capacity_backing": "backed",
                "deliverable_modes": ["vm"],
            },
            provider_config={},
        )
    )
    repo = SettlementRepository()
    with factory() as db:
        repo.schedule(
            db,
            capacity_reservation_id="cr-1",
            market="vms",
            scheduling_requirements=SettlementRequirement(
                offering_mode="vm", resource_kind="vm", dimensions={"gpu_count": 1}
            ),
            resource=SettlementResource(
                settlement_resource_id="r1",
                offering_mode="vm",
                pool_id="pool-a",
                resource_kind="vm",
                provider="ansible",
            ),
        )
        db.commit()

    prepared = VersionedEnvelope(
        kind="vm.ansible.create.v1", schema_version=1, payload={"prepared": True},
    )
    provider = _ProviderMock()
    provider.resolve_executor_job_id.return_value = None
    provider.prepare_create.return_value = prepared
    provider.dispatch_create = AsyncMock(return_value=FulfillmentResult({"job_id": "job-1"}))
    providers = ProviderRegistry({"ansible": provider})
    request = VersionedEnvelope(
        kind="vm.fulfillment.request", schema_version=1, payload={"vm_target": "vm-1"},
    )

    second_session = factory()
    assert repo.get(second_session, "cr-1").fulfillment_id is None

    first = asyncio.run(
        FulfillmentOrchestrator(
            provider_registry=providers,
            unit_of_work=SqlAlchemyFulfillmentUnitOfWork(factory, pools, repository=repo),
        ).begin_fulfillment("cr-1", "vms", request)
    )
    retried = asyncio.run(
        FulfillmentOrchestrator(
            provider_registry=providers,
            unit_of_work=SqlAlchemyFulfillmentUnitOfWork(
                _sessions_starting_with(second_session, factory), pools, repository=repo
            ),
        ).begin_fulfillment("cr-1", "vms", request)
    )

    assert retried.fulfillment_id == first.fulfillment_id
    assert retried.state == SettlementRecordState.dispatching.value
    assert provider.prepare_create.call_count == 1
    assert provider.dispatch_create.await_count == 1
    with factory() as db:
        record = repo.get(db, "cr-1")
        assert record.fulfillment_id == first.fulfillment_id
        assert record.prepared_create_operation == prepared.model_dump(mode="json")
        assert record.state == SettlementRecordState.dispatching.value
