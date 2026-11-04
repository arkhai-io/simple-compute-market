"""Library integration tests for a failed fulfillment's compensating teardown.

Real file-backed SQLite with independent sessions: the operation's single
write transaction, its serialization against other writers, and the recovery
diagnostics a compensated aggregate reports as convergence moves it.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from market_core import VersionedEnvelope
from market_fulfillment import (
    CREATE_COMPENSATION,
    CompensationRefusedError,
    FulfillmentConflictError,
    FulfillmentOrchestrator,
    ProviderConfigInvalidError,
    ProviderRegistry,
    ProviderUnavailableError,
    SettlementRecordState,
)
from market_fulfillment.db import Base as FulfillmentBase
from market_fulfillment.fulfillment_persistence import (
    SqlAlchemyFulfillmentTransaction,
    SqlAlchemyFulfillmentUnitOfWork,
)
from market_fulfillment.settlement_repository import SettlementRepository
from market_fulfillment.settlement_types import SettlementRequirement, SettlementResource
from market_resource_pools import ResourcePoolService
from market_resource_pools.db import Base as PoolsBase
from market_resource_pools_contracts import PoolCreate

CREATE_FAILURE = "create reported no delivery evidence"
TEARDOWN = VersionedEnvelope(
    kind="vm.ansible.teardown.v1", schema_version=1, payload={"prepared": "teardown"}
)


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
        return self.read_config(db, pool_id)

    def replace_config(self, db, pool_id, config):
        pass


@pytest.fixture
def database(tmp_path):
    """One failed fulfillment, as convergence leaves a create that failed."""

    engine = create_engine(
        f"sqlite:///{tmp_path / 'fulfillment.db'}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )
    PoolsBase.metadata.create_all(bind=engine)
    FulfillmentBase.metadata.create_all(bind=engine)
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
    repository = SettlementRepository()
    with factory() as db:
        repository.schedule(
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
        record = repository.accept_fulfillment(
            db,
            capacity_reservation_id="cr-1",
            market="vms",
            fulfillment_request=VersionedEnvelope(
                kind="vm.fulfillment.request", schema_version=1, payload={}
            ),
        )
        fulfillment_id = record.fulfillment_id
        repository.transition(
            db,
            "cr-1",
            SettlementRecordState.dispatching.value,
            provider_metadata={"operation": "create", "job_id": "job-1"},
        )
        repository.transition(
            db,
            "cr-1",
            SettlementRecordState.failed.value,
            failure_reason="provider_reported_failure",
            failure_message=CREATE_FAILURE,
        )
        db.commit()
    yield factory, pools, repository, fulfillment_id
    engine.dispose()


def _provider():
    provider = _ProviderMock()
    provider.prepare_teardown.return_value = TEARDOWN
    return provider


def _orchestrator(uow, provider):
    return FulfillmentOrchestrator(
        provider_registry=ProviderRegistry({"ansible": provider}), unit_of_work=uow
    )


def _record(factory, repository):
    with factory() as db:
        record = repository.get(db, "cr-1")
        db.expunge(record)
        return record


@pytest.mark.parametrize(
    ("authorized", "preparation_error", "raised"),
    [
        (False, None, CompensationRefusedError),
        (True, ProviderConfigInvalidError("create job job-1 not found"), CompensationRefusedError),
        (True, ProviderUnavailableError("job store down"), ProviderUnavailableError),
    ],
)
def test_a_compensation_that_does_not_begin_writes_nothing(
    database, authorized, preparation_error, raised
):
    """Refused or failed, the transaction rolls back and releases the writer
    slot: the row is as convergence left it, and a later compensation can
    still begin.
    """

    factory, pools, repository, fulfillment_id = database
    provider = _provider()
    provider.prepare_teardown.side_effect = preparation_error
    orchestrator = _orchestrator(
        SqlAlchemyFulfillmentUnitOfWork(factory, pools, repository=repository),
        provider,
    )

    with pytest.raises(raised):
        asyncio.run(
            orchestrator.begin_compensating_teardown(
                fulfillment_id, authorize=lambda candidate: authorized
            )
        )

    record = _record(factory, repository)
    assert record.state == SettlementRecordState.failed.value
    assert record.prepared_teardown_operation is None
    assert record.failure_reason == "provider_reported_failure"
    assert record.failure_message == CREATE_FAILURE

    provider.prepare_teardown.side_effect = None
    begun = asyncio.run(
        orchestrator.begin_compensating_teardown(
            fulfillment_id, authorize=lambda candidate: True
        )
    )
    assert begun.state == SettlementRecordState.teardown_dispatch_pending.value


def test_a_concurrent_ordinary_teardown_settles_on_the_compensations_teardown(database):
    """The ordinary request reads the committed ``failed`` row while the
    compensation holds the writer slot, and refuses without writing; once the
    compensation commits, the same request adopts it. Nothing is prepared
    twice, and the marker survives the adoption.
    """

    factory, pools, repository, fulfillment_id = database
    compensation_written = Event()
    allow_commit = Event()

    class PausingTransaction(SqlAlchemyFulfillmentTransaction):
        def begin_compensating_teardown(self, *args, **kwargs):
            result = super().begin_compensating_teardown(*args, **kwargs)
            self.db.flush()
            compensation_written.set()
            assert allow_commit.wait(timeout=5)
            return result

    provider = _provider()
    compensating = _orchestrator(
        SqlAlchemyFulfillmentUnitOfWork(
            factory, pools, repository=repository, transaction_type=PausingTransaction
        ),
        provider,
    )
    ordinary = _orchestrator(
        SqlAlchemyFulfillmentUnitOfWork(factory, pools, repository=repository),
        provider,
    )

    def _compensate():
        return asyncio.run(
            compensating.begin_compensating_teardown(
                fulfillment_id, authorize=lambda candidate: True
            )
        )

    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(_compensate)
        assert compensation_written.wait(timeout=5)
        with pytest.raises(FulfillmentConflictError):
            asyncio.run(ordinary.begin_fulfillment_teardown(fulfillment_id))
        allow_commit.set()
        compensated = pending.result(timeout=5)

    adopted = asyncio.run(ordinary.begin_fulfillment_teardown(fulfillment_id))

    assert compensated.state == SettlementRecordState.teardown_dispatch_pending.value
    assert adopted == compensated
    assert provider.prepare_teardown.call_count == 1
    record = _record(factory, repository)
    assert record.state == SettlementRecordState.teardown_dispatch_pending.value
    assert record.prepared_teardown_operation == TEARDOWN.model_dump(mode="json")
    assert record.failure_reason == CREATE_COMPENSATION
    assert record.failure_message == CREATE_FAILURE


def test_concurrent_compensations_serialize_on_the_writer_slot(database):
    """A second request cannot read the row while the first holds the writer
    slot, so it never judges the ``failed`` row the first already judged.

    The second request's connection does not wait for the slot, so the test
    observes the refusal itself rather than how long the request blocked: it
    fails before ``authorize`` or preparation runs. Once the first commits,
    a repeated request adopts the begun teardown.
    """

    factory, pools, repository, fulfillment_id = database
    first_written = Event()
    allow_first_commit = Event()

    class PausingTransaction(SqlAlchemyFulfillmentTransaction):
        def begin_compensating_teardown(self, *args, **kwargs):
            result = super().begin_compensating_teardown(*args, **kwargs)
            self.db.flush()
            first_written.set()
            assert allow_first_commit.wait(timeout=5)
            return result

    impatient_engine = create_engine(
        factory.kw["bind"].url,
        connect_args={"check_same_thread": False, "timeout": 0},
    )
    provider = _provider()
    authorize = MagicMock(return_value=True)
    first = _orchestrator(
        SqlAlchemyFulfillmentUnitOfWork(
            factory, pools, repository=repository, transaction_type=PausingTransaction
        ),
        provider,
    )
    impatient = _orchestrator(
        SqlAlchemyFulfillmentUnitOfWork(
            sessionmaker(bind=impatient_engine), pools, repository=repository
        ),
        provider,
    )

    def _compensate(orchestrator):
        return asyncio.run(
            orchestrator.begin_compensating_teardown(fulfillment_id, authorize=authorize)
        )

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            first_future = executor.submit(_compensate, first)
            assert first_written.wait(timeout=5)
            with pytest.raises(OperationalError, match="database is locked"):
                _compensate(impatient)
            assert authorize.call_count == 1
            assert provider.prepare_teardown.call_count == 1
            allow_first_commit.set()
            begun = first_future.result(timeout=5)

        adopted = _compensate(impatient)
    finally:
        impatient_engine.dispose()

    assert begun.state == SettlementRecordState.teardown_dispatch_pending.value
    assert adopted == begun
    assert authorize.call_count == 1
    assert provider.prepare_teardown.call_count == 1


def test_recovery_diagnostics_follow_a_compensation_through_failure_and_retry(database):
    """A compensated row leaves ``failed`` when compensation begins, counts in
    its teardown states and under ``teardown_failed`` while its teardown has
    failed, and is counted as no failure once ``torn_down``.

    The teardown's progress is written through the repository's transitions,
    as convergence writes it, keeping ``create_compensation`` on its failure.
    """

    factory, pools, repository, fulfillment_id = database
    provider = _provider()
    orchestrator = _orchestrator(
        SqlAlchemyFulfillmentUnitOfWork(factory, pools, repository=repository),
        provider,
    )

    def diagnostics():
        with factory() as db:
            snapshot = repository.recovery_diagnostics(db)
        counted = {
            state: entry.total
            for state, entry in snapshot.per_state.items()
            if entry.total
        }
        return counted, snapshot.failed_count, snapshot.teardown_failed_count

    def converge(target, **updates):
        with factory() as db:
            repository.transition(db, "cr-1", target, **updates)
            db.commit()

    assert diagnostics() == ({}, 1, 0)

    asyncio.run(
        orchestrator.begin_compensating_teardown(
            fulfillment_id, authorize=lambda candidate: True
        )
    )
    assert diagnostics() == (
        {SettlementRecordState.teardown_dispatch_pending.value: 1},
        0,
        0,
    )

    converge(
        SettlementRecordState.tearing_down.value,
        teardown_provider_metadata={"job_id": "cr-1:teardown"},
    )
    assert diagnostics() == ({SettlementRecordState.tearing_down.value: 1}, 0, 0)

    converge(
        SettlementRecordState.teardown_failed.value,
        failure_message="teardown job failed",
    )
    assert diagnostics() == ({}, 0, 1)

    converge(SettlementRecordState.teardown_dispatch_pending.value)
    converge(SettlementRecordState.tearing_down.value)
    assert diagnostics() == ({SettlementRecordState.tearing_down.value: 1}, 0, 0)

    converge(SettlementRecordState.torn_down.value)
    assert diagnostics() == ({}, 0, 0)
    record = _record(factory, repository)
    assert record.state == SettlementRecordState.torn_down.value
    assert record.failure_reason == CREATE_COMPENSATION
    assert record.failure_message == "teardown job failed"

    repeated = asyncio.run(
        orchestrator.begin_compensating_teardown(
            fulfillment_id, authorize=lambda candidate: True
        )
    )
    assert repeated.state == SettlementRecordState.torn_down.value
    assert provider.prepare_teardown.call_count == 1
