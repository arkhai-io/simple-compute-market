"""Release by what a reservation's fulfillment proves, against real SQLite.

The site ledger, the job rows, and the fulfillment aggregate share one
database, as they do in the provisioning service, so the release guard reads
all three inside the ledger's own transaction. A fake teardown port stands in
for the fulfillment service's teardown entry point.
"""

from __future__ import annotations

import pytest
from market_fulfillment import SettlementEntityNotFoundError, SettlementRecordState
from market_fulfillment.db import Base as FulfillmentBase
from market_fulfillment.db import SettlementRecord
from market_fulfillment.settlement_repository import SettlementRepository
from market_resource_pools.db import DEFAULT_POOL_ID, ResourcePool
from market_resource_pools.db import Base as PoolsBase
from market_site.db import Base as SiteBase
from market_site.ledger import CapacityLedgerService
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool, StaticPool

from compute_provisioning import FulfillmentTerminalHooks
from compute_provisioning.jobs.db import Base as JobsBase
from compute_provisioning.jobs.db import JobRecord
from compute_provisioning.release import (
    FulfillmentReleaseExecutor,
    FulfillmentReleaseGuard,
    FulfillmentReleaseStatusPort,
    ReleaseAction,
    ReleaseProgress,
)

_State = SettlementRecordState


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


def _world(terminal_hooks=None):
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
        release_guard=FulfillmentReleaseGuard(repository, terminal_hooks=terminal_hooks),
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


def _aggregate(factory, reservation_id: str, state: str, *, fulfillment_id: str | None = "f-1"):
    with factory() as db, db.begin():
        db.add(
            SettlementRecord(
                capacity_reservation_id=reservation_id,
                fulfillment_id=fulfillment_id,
                market="vms",
                scheduling_requirements={},
                provider_metadata={},
                state=state,
                failure_message="create failed" if state == _State.failed.value else None,
            )
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
# Terminal effects: abandoning makes the record terminal
# ----------------------------------------------------------------------


def _hooked_world(hook):
    hooks = FulfillmentTerminalHooks()
    hooks.register(hook)
    hooks.freeze()
    return _world(terminal_hooks=hooks)


def test_abandoning_runs_the_terminal_effects_in_the_reclaiming_transaction():
    """The effect writes in the guard's session, so it commits with the
    abandonment and the freed capacity."""
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

    factory, ledger, _, _ = _hooked_world(effect)
    reservation_id = _leased(ledger)
    _aggregate(factory, reservation_id, _State.assigned.value, fulfillment_id=None)

    assert ledger.release(capacity_reservation_id=reservation_id)["state"] == "released"
    assert calls == [(reservation_id, _State.abandoned.value)]
    with factory() as db:
        assert db.get(JobRecord, f"effect-{reservation_id}") is not None


def test_a_failing_effect_aborts_the_reclaim_and_abandons_nothing():
    def failing(db, capacity_reservation_id, state):
        raise RuntimeError("effect failed")

    factory, ledger, _, _ = _hooked_world(failing)
    reservation_id = _leased(ledger)
    _aggregate(factory, reservation_id, _State.assigned.value, fulfillment_id=None)

    with pytest.raises(RuntimeError, match="effect failed"):
        ledger.release(capacity_reservation_id=reservation_id)
    assert _state(factory, reservation_id) == _State.assigned.value
    assert ledger.get_reservation(reservation_id)["state"] == "leased"


@pytest.mark.parametrize("aggregate", [None, _State.active.value, _State.torn_down.value])
def test_no_effect_runs_when_nothing_is_abandoned(aggregate):
    """A refusal writes nothing, and freeing capacity behind an absent or
    already-terminal aggregate makes nothing terminal."""
    calls = []
    factory, ledger, _, _ = _hooked_world(lambda db, rid, state: calls.append(rid))
    reservation_id = _leased(ledger)
    if aggregate is not None:
        _aggregate(factory, reservation_id, aggregate)

    ledger.release(capacity_reservation_id=reservation_id)

    assert calls == []


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
    ],
)
async def test_the_release_decision_follows_the_aggregate_state_and_writes_nothing(
    world, state, action
):
    factory, ledger, executor, port = world
    reservation_id = _leased(ledger)
    if state is not None:
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


@pytest.mark.parametrize(
    ("state", "progress"),
    [
        (_State.torn_down, ReleaseProgress.TORN_DOWN),
        (_State.teardown_failed, ReleaseProgress.FAILED),
        (_State.failed, ReleaseProgress.FAILED),
        (_State.active, ReleaseProgress.READY_FOR_TEARDOWN),
        (_State.dispatch_pending, ReleaseProgress.CREATE_IN_FLIGHT),
        (_State.dispatching, ReleaseProgress.CREATE_IN_FLIGHT),
        (_State.tearing_down, ReleaseProgress.TEARING_DOWN),
        (_State.teardown_dispatch_pending, ReleaseProgress.TEARING_DOWN),
    ],
)
def test_release_progress_is_read_from_the_aggregate(world, state, progress):
    factory, ledger, _, port = world
    reservation_id = _leased(ledger)
    _aggregate(factory, reservation_id, state.value)

    status = FulfillmentReleaseStatusPort(port).get_status("f-1")

    assert status.progress is progress


def test_a_release_handle_naming_no_fulfillment_reads_as_failed(world):
    _, _, _, port = world

    status = FulfillmentReleaseStatusPort(port).get_status("missing")

    assert (status.progress, status.reason) == (ReleaseProgress.FAILED, "teardown_failed")
