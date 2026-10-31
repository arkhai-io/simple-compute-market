"""Release by what a reservation's fulfillment proves, against real SQLite.

The site ledger, the job rows, and the fulfillment aggregate share one
database, as they do in the provisioning service, so the release guard reads
all three inside the ledger's own transaction. A fake teardown port stands in
for the fulfillment service's teardown entry point in the executor's tests; the
teardown port's own tests drive the real fulfillment orchestrator, with only
the provider faked.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from market_core import VersionedEnvelope
from market_fulfillment import (
    CREATE_COMPENSATION,
    FulfillmentConflictError,
    FulfillmentOrchestrator,
    ProviderConfigInvalidError,
    ProviderRegistry,
    SettlementEntityNotFoundError,
    SettlementRecordState,
    SqlAlchemyFulfillmentUnitOfWork,
)
from market_fulfillment.db import Base as FulfillmentBase
from market_fulfillment.db import SettlementRecord
from market_fulfillment.settlement_repository import SettlementRepository
from market_resource_pools import ResourcePoolService
from market_resource_pools.db import DEFAULT_POOL_ID, ResourcePool
from market_resource_pools.db import Base as PoolsBase
from market_site.db import Base as SiteBase
from market_site.ledger import CapacityLedgerService
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool, StaticPool

from compute_provisioning import ReleaseEffects
from compute_provisioning.jobs.db import Base as JobsBase
from compute_provisioning.jobs.db import JobRecord
from compute_provisioning.release import (
    FulfillmentReleaseExecutor,
    FulfillmentReleaseGuard,
    FulfillmentReleaseStatusPort,
    FulfillmentServiceTeardownPort,
    ReleaseAction,
    ReleaseProgress,
    TeardownRefused,
)

_State = SettlementRecordState

# A job-backed create's metadata, as its dispatch acknowledgement records it.
# Synthetic development values.
_CREATE_METADATA = {
    "create_job_id": "job-1",
    "current_job_id": "job-1",
    "operation": "create",
    "host_id": "host-1",
    "executor_target": "target-1",
}
_TEARDOWN = VersionedEnvelope(
    kind="test.teardown", schema_version=1, payload={"undo": "job-1"}
)


class _TeardownPort:
    def __init__(self, session_factory):
        self._session_factory = session_factory
        self.begun: list[str] = []

    async def begin_teardown(self, fulfillment_id: str) -> str:
        self.begun.append(fulfillment_id)
        return fulfillment_id

    def get_status(self, fulfillment_id: str):
        with self._session_factory() as db:
            record = SettlementRepository().get_by_fulfillment_id(db, fulfillment_id)
            if record is None:
                raise SettlementEntityNotFoundError(fulfillment_id)
            return record


@pytest.fixture
def world():
    return _world()


def _world(release_effects=None):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    for base in (PoolsBase, SiteBase, JobsBase, FulfillmentBase):
        base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db, db.begin():
        db.add(
            ResourcePool(
                id=DEFAULT_POOL_ID,
                label="default",
                provider="test",
                policy_tags={"deliverable_modes": ["vm"]},
            )
        )
    repository = SettlementRepository()
    ledger = CapacityLedgerService(
        factory,
        unit_claim_keys=("units", "gpu_count"),
        mirror_dimension="gpu_count",
        release_guard=FulfillmentReleaseGuard(repository),
        release_effect=release_effects,
    )
    ledger.register_resource(resource_id="r1", total_units=4, pool_id=DEFAULT_POOL_ID)
    port = _TeardownPort(factory)
    executor = FulfillmentReleaseExecutor(
        settlement_repository=repository, session_factory=factory, teardown_port=port
    )
    return factory, ledger, executor, port


def _leased(ledger) -> str:
    reservation_id = ledger.reserve(
        claim={"offering_mode": "vm", "gpu_count": 1}, deal_ref={"market": "vms"}
    )["capacity_reservation_id"]
    ledger.commit(capacity_reservation_id=reservation_id, lease_end_utc="2099-01-01 00:00")
    return reservation_id


def _aggregate(
    factory,
    reservation_id: str,
    state: str,
    *,
    fulfillment_id: str | None = "f-1",
    failure_reason: str | None = None,
    provider_metadata: dict | None = None,
):
    with factory() as db, db.begin():
        db.add(
            SettlementRecord(
                capacity_reservation_id=reservation_id,
                fulfillment_id=fulfillment_id,
                market="vms",
                scheduling_requirements={"offering_mode": "vm", "resource_kind": "vm"},
                settlement_resource_id="r1",
                pool_id=DEFAULT_POOL_ID,
                provider="test",
                resource_host_id="host-1",
                provider_metadata=provider_metadata or {},
                state=state,
                failure_reason=failure_reason,
                failure_message="create failed" if state == _State.failed.value else None,
            )
        )


def _compensable_failed(factory, reservation_id: str, **fields):
    _aggregate(
        factory,
        reservation_id,
        _State.failed.value,
        failure_reason="provider_reported_failure",
        provider_metadata=_CREATE_METADATA,
        **fields,
    )


def _job_for(factory, reservation_id: str) -> None:
    with factory() as db, db.begin():
        db.add(
            JobRecord(
                id="job-1",
                status="succeeded",
                params={},
                capacity_reservation_id=reservation_id,
                action_kind="create",
                idempotency_key=f"{reservation_id}:create",
            )
        )


def _state(factory, reservation_id: str) -> str:
    with factory() as db:
        record = SettlementRepository().get(db, reservation_id)
        return None if record is None else record.state


# ----------------------------------------------------------------------
# The guard: the site frees capacity only on fulfillment's proof
# ----------------------------------------------------------------------


def test_a_lease_with_no_aggregate_and_nothing_dispatched_is_freed(world):
    factory, ledger, _, _ = world
    reservation_id = _leased(ledger)

    assert ledger.release(capacity_reservation_id=reservation_id)["state"] == "released"


def test_an_assigned_aggregate_is_abandoned_as_its_capacity_is_freed(world):
    factory, ledger, _, _ = world
    reservation_id = _leased(ledger)
    _aggregate(factory, reservation_id, _State.assigned.value, fulfillment_id=None)

    assert ledger.release(capacity_reservation_id=reservation_id)["state"] == "released"
    assert _state(factory, reservation_id) == _State.abandoned.value


@pytest.mark.parametrize(
    "state",
    [_State.dispatch_pending, _State.dispatching, _State.active, _State.failed, _State.tearing_down],
)
def test_capacity_with_a_dispatched_or_delivered_aggregate_is_not_freed(world, state):
    factory, ledger, _, _ = world
    reservation_id = _leased(ledger)
    _aggregate(factory, reservation_id, state.value)

    assert ledger.release(capacity_reservation_id=reservation_id) is None
    assert ledger.get_reservation(reservation_id)["state"] == "leased"


def test_a_torn_down_aggregate_proves_the_capacity_free(world):
    factory, ledger, _, _ = world
    reservation_id = _leased(ledger)
    _aggregate(factory, reservation_id, _State.torn_down.value)

    assert ledger.release(capacity_reservation_id=reservation_id)["state"] == "released"


@pytest.mark.parametrize("evidence", ["create_handle", "job"])
def test_dispatch_provenance_without_an_aggregate_refuses_and_abandons_nothing(world, evidence):
    """An assigned aggregate whose reservation records a create handle, or has
    a job bound to it, proves nothing: the guard refuses and writes nothing."""
    factory, ledger, _, _ = world
    reservation_id = _leased(ledger)
    _aggregate(factory, reservation_id, _State.assigned.value, fulfillment_id=None)
    if evidence == "job":
        _job_for(factory, reservation_id)
    else:
        with factory() as db:
            ledger.record_create_handle_in_session(db, reservation_id, "job-0")
            db.commit()

    assert ledger.release(capacity_reservation_id=reservation_id) is None
    assert _state(factory, reservation_id) == _State.assigned.value


# ----------------------------------------------------------------------
# Release effects: what a deployment returns with the capacity
# ----------------------------------------------------------------------


def _effects_world(effect):
    effects = ReleaseEffects()
    effects.register(effect)
    effects.freeze()
    return _world(release_effects=effects)


def test_an_abandoning_release_runs_the_effect_in_the_reclaiming_transaction():
    """The guard abandons the hold and the ledger frees its capacity in one
    transaction, and the effect writes in it too."""
    calls = []

    def effect(db, capacity_reservation_id, state):
        calls.append((capacity_reservation_id, state))
        db.add(
            JobRecord(
                id=f"effect-{capacity_reservation_id}",
                status="succeeded",
                params={},
                action_kind="effect",
                idempotency_key=f"effect:{capacity_reservation_id}",
            )
        )

    factory, ledger, _, _ = _effects_world(effect)
    reservation_id = _leased(ledger)
    _aggregate(factory, reservation_id, _State.assigned.value, fulfillment_id=None)

    assert ledger.release(capacity_reservation_id=reservation_id)["state"] == "released"
    assert calls == [(reservation_id, "released")]
    assert _state(factory, reservation_id) == _State.abandoned.value
    with factory() as db:
        assert db.get(JobRecord, f"effect-{reservation_id}") is not None


def test_a_failing_effect_aborts_the_reclaim_and_abandons_nothing():
    def failing(db, capacity_reservation_id, state):
        raise RuntimeError("effect failed")

    factory, ledger, _, _ = _effects_world(failing)
    reservation_id = _leased(ledger)
    _aggregate(factory, reservation_id, _State.assigned.value, fulfillment_id=None)

    with pytest.raises(RuntimeError, match="effect failed"):
        ledger.release(capacity_reservation_id=reservation_id)
    assert _state(factory, reservation_id) == _State.assigned.value
    assert ledger.get_reservation(reservation_id)["state"] == "leased"


def test_a_failed_fulfillment_keeps_what_it_holds_until_an_operator_forces_release():
    """A failed fulfillment may have left something running, so the guard
    refuses and nothing is returned; the operator's forced release returns
    the capacity and the effect together."""
    calls = []
    factory, ledger, _, _ = _effects_world(lambda db, rid, state: calls.append(state))
    reservation_id = _leased(ledger)
    _aggregate(factory, reservation_id, _State.failed.value)

    assert ledger.release(capacity_reservation_id=reservation_id) is None
    assert calls == []

    ledger.release(capacity_reservation_id=reservation_id, forced=True)
    assert calls == ["force_released"]


class _DispatchWinsRepository(SettlementRepository):
    """Lets a concurrent ``begin`` win between the guard's proof and its abandon.

    Just before the guard's compare-and-set, another connection moves the
    aggregate to ``dispatch_pending`` and commits, as a ``begin`` that read it
    ``assigned`` at the same moment would. The compare-and-set then finds it
    moved.
    """

    def __init__(self, other_connection_factory) -> None:
        super().__init__()
        self._other = other_connection_factory

    def abandon_if_assigned(self, db, capacity_reservation_id: str) -> bool:
        with self._other() as racing, racing.begin():
            record = racing.get(SettlementRecord, capacity_reservation_id)
            assert record.state == _State.assigned.value
            record.state = _State.dispatch_pending.value
        return super().abandon_if_assigned(db, capacity_reservation_id)


def test_a_dispatch_that_wins_the_race_with_the_guard_keeps_the_capacity(tmp_path):
    """The guard proves nothing was dispatched, then abandons the aggregate by
    compare-and-set. A dispatch committed in between makes the compare-and-set
    miss: the guard refuses, the reservation stays leased, and the aggregate
    keeps the dispatch's state."""
    engine = create_engine(f"sqlite:///{tmp_path / 'race.db'}", poolclass=NullPool)
    for base in (PoolsBase, SiteBase, JobsBase, FulfillmentBase):
        base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db, db.begin():
        db.add(
            ResourcePool(
                id=DEFAULT_POOL_ID,
                label="default",
                provider="test",
                policy_tags={"deliverable_modes": ["vm"]},
            )
        )
    ledger = CapacityLedgerService(
        factory,
        unit_claim_keys=("units", "gpu_count"),
        mirror_dimension="gpu_count",
        release_guard=FulfillmentReleaseGuard(_DispatchWinsRepository(factory)),
    )
    ledger.register_resource(resource_id="r1", total_units=4, pool_id=DEFAULT_POOL_ID)
    reservation_id = _leased(ledger)
    _aggregate(factory, reservation_id, _State.assigned.value, fulfillment_id=None)

    released = ledger.release(capacity_reservation_id=reservation_id)

    assert released is None
    assert ledger.get_reservation(reservation_id)["state"] == "leased"
    assert _state(factory, reservation_id) == _State.dispatch_pending.value


# ----------------------------------------------------------------------
# The executor: what a release does, by the aggregate's state
# ----------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("state", "action"),
    [
        (None, ReleaseAction.FREE),
        (_State.assigned, ReleaseAction.FREE),
        (_State.abandoned, ReleaseAction.FREE),
        (_State.torn_down, ReleaseAction.FREE),
        (_State.dispatch_pending, ReleaseAction.CREATE_IN_FLIGHT),
        (_State.dispatching, ReleaseAction.CREATE_IN_FLIGHT),
        (_State.active, ReleaseAction.TEARDOWN),
        (_State.teardown_dispatch_pending, ReleaseAction.TEARDOWN),
        (_State.tearing_down, ReleaseAction.TEARDOWN),
        (_State.teardown_failed, ReleaseAction.TEARDOWN),
        (_State.failed, ReleaseAction.UNRELEASABLE),
        ("compensable", ReleaseAction.TEARDOWN),
    ],
)
async def test_the_release_decision_follows_the_aggregate_state_and_writes_nothing(
    world, state, action
):
    factory, ledger, executor, port = world
    reservation_id = _leased(ledger)
    if state == "compensable":
        _compensable_failed(factory, reservation_id)
    elif state is not None:
        assigned = state is _State.assigned
        _aggregate(factory, reservation_id, state.value, fulfillment_id=None if assigned else "f-1")

    decision = await executor.submit_release({"capacity_reservation_id": reservation_id})

    assert decision.action is action
    # Deciding writes nothing: the lifecycle begins teardown once the release
    # is recorded.
    assert port.begun == []
    if action is ReleaseAction.TEARDOWN:
        assert decision.fulfillment_id == "f-1"
    if action is ReleaseAction.UNRELEASABLE:
        assert (decision.reason, decision.message) == ("fulfillment_failed", "create failed")


# ----------------------------------------------------------------------
# The status port: a releasing lease's progress
# ----------------------------------------------------------------------


def _status_port(factory):
    return FulfillmentReleaseStatusPort(
        settlement_repository=SettlementRepository(), session_factory=factory
    )


@pytest.mark.parametrize(
    ("state", "progress", "reason"),
    [
        (_State.torn_down, ReleaseProgress.TORN_DOWN, None),
        (_State.teardown_failed, ReleaseProgress.FAILED, "teardown_failed"),
        (_State.teardown_dispatch_pending, ReleaseProgress.TEARING_DOWN, None),
        (_State.tearing_down, ReleaseProgress.TEARING_DOWN, None),
        (_State.active, ReleaseProgress.READY_FOR_TEARDOWN, None),
        (_State.dispatch_pending, ReleaseProgress.CREATE_IN_FLIGHT, None),
        (_State.dispatching, ReleaseProgress.CREATE_IN_FLIGHT, None),
        ("compensable", ReleaseProgress.READY_FOR_TEARDOWN, None),
        (_State.failed, ReleaseProgress.FAILED, "fulfillment_failed"),
        (_State.assigned, ReleaseProgress.TEARING_DOWN, None),
        (_State.abandoned, ReleaseProgress.TEARING_DOWN, None),
    ],
)
def test_release_progress_is_read_from_the_aggregate(world, state, progress, reason):
    factory, ledger, _, _ = world
    reservation_id = _leased(ledger)
    if state == "compensable":
        _compensable_failed(factory, reservation_id)
    else:
        _aggregate(factory, reservation_id, state.value)

    status = _status_port(factory).get_status("f-1")

    assert (status.progress, status.reason) == (progress, reason)


def test_a_release_handle_naming_no_fulfillment_reads_as_failed(world):
    factory, _, _, _ = world

    status = _status_port(factory).get_status("missing")

    assert (status.progress, status.reason) == (ReleaseProgress.FAILED, "teardown_failed")


# ----------------------------------------------------------------------
# The teardown port: begins what the aggregate's state calls for when asked
# ----------------------------------------------------------------------


class _ProviderMock(MagicMock):
    needs_host = True


class _PoolHandler:
    provider = "test"

    def read_config(self, db, pool_id):
        return {}

    def read_config_for_execution(self, db, pool_id):
        return {}


def _orchestrator(factory, provider):
    return FulfillmentOrchestrator(
        provider_registry=ProviderRegistry({"test": provider}),
        unit_of_work=SqlAlchemyFulfillmentUnitOfWork(
            factory,
            ResourcePoolService(factory, {"test": _PoolHandler()}),
            repository=SettlementRepository(),
        ),
    )


def _teardown_world(world, *, prepare_error: Exception | None = None):
    factory, ledger, _, _ = world
    provider = _ProviderMock()
    provider.prepare_teardown.return_value = _TEARDOWN
    provider.prepare_teardown.side_effect = prepare_error
    service = _orchestrator(factory, provider)
    return factory, ledger, provider, service


def _record(factory, reservation_id: str) -> SettlementRecord:
    with factory() as db:
        record = SettlementRepository().get(db, reservation_id)
        db.expunge(record)
        return record


@pytest.mark.asyncio
async def test_the_teardown_port_begins_an_active_fulfillment_s_ordinary_teardown(world):
    factory, ledger, provider, service = _teardown_world(world)
    reservation_id = _leased(ledger)
    _aggregate(factory, reservation_id, _State.active.value, provider_metadata=_CREATE_METADATA)

    assert await FulfillmentServiceTeardownPort(lambda: service).begin_teardown("f-1") == "f-1"

    record = _record(factory, reservation_id)
    assert record.state == _State.teardown_dispatch_pending.value
    assert record.failure_reason is None


@pytest.mark.asyncio
async def test_the_teardown_port_adopts_a_begun_teardown(world):
    factory, ledger, provider, service = _teardown_world(world)
    reservation_id = _leased(ledger)
    _aggregate(factory, reservation_id, _State.tearing_down.value)

    await FulfillmentServiceTeardownPort(lambda: service).begin_teardown("f-1")

    assert _record(factory, reservation_id).state == _State.tearing_down.value
    provider.prepare_teardown.assert_not_called()


@pytest.mark.asyncio
async def test_the_teardown_port_compensates_a_compensable_failed_create(world):
    factory, ledger, provider, service = _teardown_world(world)
    reservation_id = _leased(ledger)
    _compensable_failed(factory, reservation_id)
    port = FulfillmentServiceTeardownPort(lambda: service)

    await port.begin_teardown("f-1")
    await port.begin_teardown("f-1")

    record = _record(factory, reservation_id)
    assert record.state == _State.teardown_dispatch_pending.value
    assert record.failure_reason == CREATE_COMPENSATION
    assert record.failure_message == "create failed"
    assert record.prepared_teardown_operation == _TEARDOWN.model_dump(mode="json")
    assert provider.prepare_teardown.call_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure_reason", "provider_metadata", "prepare_error"),
    [
        ("legacy_executor_identity_quarantined", _CREATE_METADATA, None),
        ("provider_reported_failure", {}, None),
        (
            "provider_reported_failure",
            _CREATE_METADATA,
            ProviderConfigInvalidError("create job job-1 was not found"),
        ),
    ],
    ids=["ineligible", "no-metadata", "unpreparable"],
)
async def test_the_teardown_port_refuses_a_compensation_that_cannot_begin(
    world, failure_reason, provider_metadata, prepare_error
):
    factory, ledger, _, service = _teardown_world(world, prepare_error=prepare_error)
    reservation_id = _leased(ledger)
    _aggregate(
        factory,
        reservation_id,
        _State.failed.value,
        failure_reason=failure_reason,
        provider_metadata=provider_metadata,
    )

    with pytest.raises(TeardownRefused) as refused:
        await FulfillmentServiceTeardownPort(lambda: service).begin_teardown("f-1")

    assert refused.value.reason == "compensation_refused"
    record = _record(factory, reservation_id)
    assert (record.state, record.failure_reason) == (_State.failed.value, failure_reason)
    assert record.prepared_teardown_operation is None


@pytest.mark.asyncio
async def test_a_preparation_error_that_may_pass_is_not_a_refusal(world):
    factory, ledger, _, service = _teardown_world(
        world, prepare_error=ConnectionError("job store unreachable")
    )
    reservation_id = _leased(ledger)
    _compensable_failed(factory, reservation_id)

    with pytest.raises(ConnectionError):
        await FulfillmentServiceTeardownPort(lambda: service).begin_teardown("f-1")

    assert _record(factory, reservation_id).state == _State.failed.value


class _MovesAfterRead:
    """A fulfillment service whose aggregate another actor moves just after the
    port reads its state, before the kit's write transaction."""

    def __init__(self, service, move):
        self._service = service
        self._move = move

    def get_fulfillment_status(self, fulfillment_id):
        status = self._service.get_fulfillment_status(fulfillment_id)
        self._move()
        return status

    def __getattr__(self, name):
        return getattr(self._service, name)


@pytest.mark.asyncio
async def test_a_compensation_begun_by_another_release_after_the_read_is_adopted(world):
    factory, ledger, provider, service = _teardown_world(world)
    reservation_id = _leased(ledger)
    _compensable_failed(factory, reservation_id)
    uow = SqlAlchemyFulfillmentUnitOfWork(
        factory,
        ResourcePoolService(factory, {"test": _PoolHandler()}),
        repository=SettlementRepository(),
    )

    def compensate_elsewhere():
        with uow.transaction() as tx:
            tx.get_by_fulfillment_id_for_write("f-1")
            tx.begin_compensating_teardown("f-1", _TEARDOWN)

    moving = _MovesAfterRead(service, compensate_elsewhere)

    assert await FulfillmentServiceTeardownPort(lambda: moving).begin_teardown("f-1") == "f-1"

    record = _record(factory, reservation_id)
    assert (record.state, record.failure_reason) == (
        _State.teardown_dispatch_pending.value,
        CREATE_COMPENSATION,
    )
    provider.prepare_teardown.assert_not_called()


@pytest.mark.asyncio
async def test_a_create_that_fails_after_the_read_is_left_for_the_next_cycle(world):
    """The port read ``dispatching`` and asked for an ordinary teardown, which
    refuses the ``failed`` row the create has since become: a conflict, not a
    refusal, so the lease stays releasing and its next cycle compensates."""
    factory, ledger, _, service = _teardown_world(world)
    reservation_id = _leased(ledger)
    _aggregate(
        factory,
        reservation_id,
        _State.dispatching.value,
        provider_metadata=_CREATE_METADATA,
    )

    def create_fails():
        with factory() as db, db.begin():
            SettlementRepository().transition(
                db,
                reservation_id,
                _State.failed.value,
                failure_reason="provider_reported_failure",
                failure_message="create failed",
            )

    moving = _MovesAfterRead(service, create_fails)

    with pytest.raises(FulfillmentConflictError) as raised:
        await FulfillmentServiceTeardownPort(lambda: moving).begin_teardown("f-1")

    assert not isinstance(raised.value, TeardownRefused)
    assert _record(factory, reservation_id).state == _State.failed.value
    assert _status_port(factory).get_status("f-1").progress is (
        ReleaseProgress.READY_FOR_TEARDOWN
    )
