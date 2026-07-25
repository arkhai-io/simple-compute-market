"""Focused tests for durable fulfillment orchestration."""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from market_fulfillment import (
    FulfillmentCreateFailedError,
    FulfillmentOrchestrator,
    FulfillmentResult,
    ProviderRegistry,
    SettlementRecordState,
    VersionedEnvelope,
)
from market_fulfillment.fulfillment_persistence import FulfillmentAcceptanceDecision


def _request() -> VersionedEnvelope[dict]:
    return VersionedEnvelope(
        kind="vm.fulfillment.request",
        schema_version=1,
        payload={"vm_target": "vm-1"},
    )


def _record(**overrides):
    values = {
        "fulfillment_id": "fulfillment-1",
        "capacity_reservation_id": "reservation-1",
        "state": SettlementRecordState.dispatch_pending.value,
        "market": "compute",
        "pool_id": "pool-1",
        "provider": "ansible",
        "settlement_resource_id": "resource-1",
        "resource_attributes": {"vm_host": "host-1"},
        "scheduling_requirements": {"resource_kind": "vm"},
        "prepared_create_operation": None,
        "provider_metadata": {},
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class FakeTransaction:
    def __init__(self, record, *, dispatch_required=True):
        self.record = record
        self.db = MagicMock()
        self.db.get.return_value = record
        self.pool = SimpleNamespace(provider_config={"playbook_path": "playbook.yml"})
        self.dispatch_required = dispatch_required
        self.persisted = []
        self.acknowledged = []

    def accept(self, **kwargs):
        return FulfillmentAcceptanceDecision(
            record=self.record,
            newly_accepted=True,
            dispatch_required=self.dispatch_required,
        )

    def get_pool(self, pool_id):
        return self.pool

    def persist_prepared_create(self, capacity_reservation_id, prepared):
        self.persisted.append(prepared)
        self.record.prepared_create_operation = prepared.model_dump(mode="json")
        return self.record

    def acknowledge_create(self, capacity_reservation_id, provider_metadata):
        self.acknowledged.append(provider_metadata)
        self.record.provider_metadata = provider_metadata
        self.record.state = SettlementRecordState.dispatching.value
        return self.record


class FakeUnitOfWork:
    def __init__(self, *transactions):
        self.transactions = list(transactions)
        self.write_entries = 0
        self.read_entries = 0

    @contextmanager
    def transaction(self):
        self.write_entries += 1
        yield self.transactions.pop(0)

    @contextmanager
    def read_transaction(self):
        self.read_entries += 1
        yield self.transactions.pop(0)


def _provider():
    provider = MagicMock()
    provider.prepare_create.return_value = VersionedEnvelope(
        kind="vm.ansible.create.v1",
        schema_version=1,
        payload={"prepared": True},
    )
    provider.dispatch_create = AsyncMock(
        return_value=FulfillmentResult({"job_id": "job-1"})
    )
    return provider


def _orchestrator(uow, provider):
    return FulfillmentOrchestrator(
        provider_registry=ProviderRegistry({"ansible": provider}),
        unit_of_work=uow,
    )


def test_validate_uses_read_transaction_and_shared_preparation_path():
    tx = FakeTransaction(_record())
    provider = _provider()
    uow = FakeUnitOfWork(tx)

    result = _orchestrator(uow, provider).validate_fulfillment(
        "reservation-1", "compute", _request()
    )

    assert result.valid
    assert uow.read_entries == 1
    assert uow.write_entries == 0
    provider.prepare_create.assert_called_once()
    assert provider.prepare_create.call_args.kwargs["capacity_reservation_id"] == "reservation-1"


@pytest.mark.asyncio
async def test_begin_persists_then_dispatches_then_acknowledges():
    acceptance_tx = FakeTransaction(_record())
    acknowledgement_tx = FakeTransaction(acceptance_tx.record)
    provider = _provider()
    orchestrator = _orchestrator(
        FakeUnitOfWork(acceptance_tx, acknowledgement_tx),
        provider,
    )

    result = await orchestrator.begin_fulfillment(
        "reservation-1", "compute", _request()
    )

    assert len(acceptance_tx.persisted) == 1
    provider.dispatch_create.assert_awaited_once_with(acceptance_tx.persisted[0])
    assert acknowledgement_tx.acknowledged == [{"job_id": "job-1"}]
    assert result.state == SettlementRecordState.dispatching.value


@pytest.mark.asyncio
async def test_equivalent_acknowledged_retry_does_not_redispatch():
    record = _record(state=SettlementRecordState.dispatching.value)
    tx = FakeTransaction(record, dispatch_required=False)
    provider = _provider()

    result = await _orchestrator(FakeUnitOfWork(tx), provider).begin_fulfillment(
        "reservation-1", "compute", _request()
    )

    provider.prepare_create.assert_not_called()
    provider.dispatch_create.assert_not_awaited()
    assert result.state == SettlementRecordState.dispatching.value


@pytest.mark.asyncio
async def test_pending_retry_reuses_persisted_prepared_operation():
    prepared = VersionedEnvelope(
        kind="vm.ansible.create.v1",
        schema_version=1,
        payload={"frozen": True},
    )
    record = _record(prepared_create_operation=prepared.model_dump(mode="json"))
    acceptance_tx = FakeTransaction(record)
    acknowledgement_tx = FakeTransaction(record)
    provider = _provider()

    await _orchestrator(
        FakeUnitOfWork(acceptance_tx, acknowledgement_tx),
        provider,
    ).begin_fulfillment("reservation-1", "compute", _request())

    provider.prepare_create.assert_not_called()
    provider.dispatch_create.assert_awaited_once_with(prepared)


@pytest.mark.asyncio
async def test_recoverable_dispatch_failure_remains_pending(caplog):
    tx = FakeTransaction(_record())
    provider = _provider()
    provider.dispatch_create.side_effect = FulfillmentCreateFailedError("offline")

    result = await _orchestrator(FakeUnitOfWork(tx), provider).begin_fulfillment(
        "reservation-1", "compute", _request()
    )

    assert result.state == SettlementRecordState.dispatch_pending.value
    assert "dispatch failed after durable acceptance" in caplog.text.lower()


def test_independent_sessions_serialize_fulfillment_acceptance_deterministically(tmp_path):
    """A controlled transaction barrier proves SQLite writer serialization
    for fulfillment acceptance without relying on an uncontrolled race or
    elapsed-time ordering -- mirrors test_scheduler.py's
    ``test_independent_sessions_serialize_cursor_updates_deterministically``
    for ``SchedulingUnitOfWork``.
    """
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, Lock

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from market_fulfillment.db import Base as FulfillmentBase
    from market_fulfillment.fulfillment_persistence import (
        SqlAlchemyFulfillmentTransaction,
        SqlAlchemyFulfillmentUnitOfWork,
    )
    from market_fulfillment.settlement_repository import SettlementRepository
    from market_fulfillment.settlement_types import (
        SettlementRequirement,
        SettlementResource,
    )
    from market_resource_pools import PoolCreate, ResourcePoolService
    from market_resource_pools.db import Base as PoolsBase

    class _Handler:
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

    database = tmp_path / "fulfillment.db"
    engine = create_engine(
        f"sqlite:///{database}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )
    PoolsBase.metadata.create_all(bind=engine)
    FulfillmentBase.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)
    pools = ResourcePoolService(factory, {"ansible": _Handler()})
    pools.create_pool(
        PoolCreate(id="pool-a", label="pool-a", provider="ansible", provider_config={})
    )

    repo = SettlementRepository()
    with factory() as db:
        for capacity_reservation_id, resource_id in (("cr-1", "r1"), ("cr-2", "r2")):
            repo.schedule(
                db,
                capacity_reservation_id=capacity_reservation_id,
                market="vms",
                scheduling_requirements=SettlementRequirement(
                    resource_kind="vm", dimensions={"gpu_count": 1}
                ),
                resource=SettlementResource(
                    settlement_resource_id=resource_id,
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
    provider = _provider()
    orchestrator = _orchestrator(uow, provider)

    def _begin(capacity_reservation_id: str):
        return asyncio.run(
            orchestrator.begin_fulfillment(capacity_reservation_id, "vms", _request())
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
