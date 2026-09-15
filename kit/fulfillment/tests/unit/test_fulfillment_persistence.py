"""Tests for fulfillment transaction idempotency and session ownership."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from market_fulfillment import (
    FulfillmentConflictError,
    SettlementRecordState,
    VersionedEnvelope,
)
from market_fulfillment.fulfillment_persistence import SqlAlchemyFulfillmentTransaction
from market_fulfillment.settlement_repository import begin_sqlite_write_transaction


def _record(**overrides):
    values = {
        "state": SettlementRecordState.dispatch_pending.value,
        "provider_metadata": {},
        "prepared_create_operation": None,
        "prepared_teardown_operation": None,
        "fulfillment_id": "fulfillment-1",
        "capacity_reservation_id": "reservation-1",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_get_pool_uses_callers_session_and_the_execution_read():
    """Dispatch needs provider secrets the redacted read withholds.

    Asserting which read is used, not merely that a pool comes back: the two
    differ only in whether credentials are present, so a call to the redacted
    one would fail later, at the point a tunnel client is configured without a
    token, rather than here.
    """
    db = MagicMock()
    pool_service = MagicMock()
    pool_service.get_pool_for_execution.return_value = object()
    tx = SqlAlchemyFulfillmentTransaction(db, pool_service, MagicMock())

    result = tx.get_pool("pool-1")

    pool_service.get_pool_for_execution.assert_called_once_with(db, "pool-1")
    pool_service.get_pool_in_session.assert_not_called()
    assert result is pool_service.get_pool_for_execution.return_value


def test_identical_prepared_operation_is_idempotent():
    prepared = VersionedEnvelope(kind="test", schema_version=1, payload={"x": 1})
    record = _record(prepared_create_operation=prepared.model_dump(mode="json"))
    repository = MagicMock()
    repository.get.return_value = record
    db = MagicMock()
    tx = SqlAlchemyFulfillmentTransaction(db, MagicMock(), repository)

    assert tx.persist_prepared_create("reservation-1", prepared) is record


def test_conflicting_prepared_operation_is_rejected():
    record = _record(
        prepared_create_operation={"kind": "test", "schema_version": 1, "payload": {"x": 1}}
    )
    repository = MagicMock()
    repository.get.return_value = record
    tx = SqlAlchemyFulfillmentTransaction(MagicMock(), MagicMock(), repository)

    with pytest.raises(FulfillmentConflictError):
        tx.persist_prepared_create(
            "reservation-1",
            VersionedEnvelope(kind="test", schema_version=1, payload={"x": 2}),
        )


def test_identical_acknowledgement_in_dispatching_state_is_idempotent():
    record = _record(
        state=SettlementRecordState.dispatching.value,
        provider_metadata={"job_id": "job-1"},
    )
    repository = MagicMock()
    repository.get.return_value = record
    tx = SqlAlchemyFulfillmentTransaction(MagicMock(), MagicMock(), repository)

    assert tx.acknowledge_create("reservation-1", {"job_id": "job-1"}) is record
    repository.transition.assert_not_called()


def test_conflicting_acknowledgement_is_rejected():
    record = _record(provider_metadata={"job_id": "job-1"})
    repository = MagicMock()
    repository.get.return_value = record
    tx = SqlAlchemyFulfillmentTransaction(MagicMock(), MagicMock(), repository)

    with pytest.raises(FulfillmentConflictError):
        tx.acknowledge_create("reservation-1", {"job_id": "job-2"})


def test_begin_teardown_transitions_via_the_repository():
    prepared = VersionedEnvelope(kind="teardown-test", schema_version=1, payload={"x": 1})
    record = _record(state=SettlementRecordState.active.value)
    repository = MagicMock()
    repository.get_by_fulfillment_id.return_value = record
    repository.transition.return_value = SimpleNamespace(
        state=SettlementRecordState.teardown_dispatch_pending.value
    )
    db = MagicMock()
    tx = SqlAlchemyFulfillmentTransaction(db, MagicMock(), repository)

    result = tx.begin_teardown("fulfillment-1", prepared)

    repository.get_by_fulfillment_id.assert_called_once_with(db, "fulfillment-1")
    repository.transition.assert_called_once_with(
        db,
        "reservation-1",
        SettlementRecordState.teardown_dispatch_pending.value,
        prepared_teardown_operation=prepared.model_dump(mode="json"),
    )
    assert result.state == SettlementRecordState.teardown_dispatch_pending.value


def test_begin_teardown_reusing_an_identical_prepared_operation_is_idempotent():
    prepared = VersionedEnvelope(kind="teardown-test", schema_version=1, payload={"x": 1})
    record = _record(
        state=SettlementRecordState.active.value,
        prepared_teardown_operation=prepared.model_dump(mode="json"),
    )
    repository = MagicMock()
    repository.get_by_fulfillment_id.return_value = record
    tx = SqlAlchemyFulfillmentTransaction(MagicMock(), MagicMock(), repository)

    tx.begin_teardown("fulfillment-1", prepared)

    repository.transition.assert_called_once_with(
        tx.db,
        "reservation-1",
        SettlementRecordState.teardown_dispatch_pending.value,
        prepared_teardown_operation=prepared.model_dump(mode="json"),
    )


def test_begin_teardown_conflicting_prepared_operation_is_rejected():
    record = _record(
        state=SettlementRecordState.active.value,
        prepared_teardown_operation={"kind": "teardown-test", "schema_version": 1, "payload": {"x": 1}},
    )
    repository = MagicMock()
    repository.get_by_fulfillment_id.return_value = record
    tx = SqlAlchemyFulfillmentTransaction(MagicMock(), MagicMock(), repository)

    with pytest.raises(FulfillmentConflictError):
        tx.begin_teardown(
            "fulfillment-1",
            VersionedEnvelope(kind="teardown-test", schema_version=1, payload={"x": 2}),
        )
    repository.transition.assert_not_called()


def test_begin_teardown_unknown_fulfillment_id_raises_lookup_error():
    repository = MagicMock()
    repository.get_by_fulfillment_id.return_value = None
    tx = SqlAlchemyFulfillmentTransaction(MagicMock(), MagicMock(), repository)

    with pytest.raises(LookupError):
        tx.begin_teardown(
            "no-such-fulfillment",
            VersionedEnvelope(kind="teardown-test", schema_version=1, payload={}),
        )


# ---------------------------------------------------------------------------
# attach_executor_job, against a real ledger
#
# The orchestrator-level tests for this used a fake transaction, so they
# asserted that the call was made and never that it lands. The method name on
# the real service was wrong -- `update_reservation_fields` does not exist --
# and nothing caught it: the fake never ran, `capacity_ledger` is typed loosely
# enough that no checker objected, and the failure is swallowed by design
# because a missing diagnostic handle must not fail a working fulfillment.
#
# So the write is exercised end to end here, through a real
# `CapacityLedgerService` against a real SQLite ledger.
# ---------------------------------------------------------------------------


@pytest.fixture
def ledger_services(tmp_path):
    from market_resource_pools import PoolCreate, ResourcePoolService
    from market_resource_pools.db import Base as PoolsBase
    from market_site.db import Base as SiteBase
    from market_site.ledger import CapacityLedgerService
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    PoolsBase.metadata.create_all(bind=engine)
    SiteBase.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)
    ledger = CapacityLedgerService(
        factory, unit_claim_keys=("units", "gpu_count")
    )

    class _Handler:
        provider = "ansible"

        def validate_config(self, config):
            return dict(config)

        def validate_config_problems(self, config):
            return dict(config), ()

        def read_config(self, db, pool_id):
            return {}

        def read_config_for_execution(self, db, pool_id):
            return {}

        def replace_config(self, db, pool_id, config):
            pass

        def delete_config(self, db, pool_id):
            pass

    pools = ResourcePoolService(factory, {"ansible": _Handler()})
    # Declared, because admission refuses a claim whose offering mode no
    # matching pool delivers -- the reservation this test attaches to has to
    # be one the ledger would really have created.
    pools.create_pool(PoolCreate(
        id="pool-a",
        label="pool-a",
        provider="ansible",
        enabled=True,
        policy_tags={"deliverable_modes": ["vm"]},
        provider_config={},
    ))
    return ledger, factory


def _reserved(ledger):
    ledger.register_resource(
        resource_id="resource-1",
        resource_type="compute.gpu",
        total_units=4,
        pool_id="pool-a",
    )
    reservation = ledger.reserve(
        claim={"offering_mode": "vm", "gpu_count": 1},
        deal_ref={"escrow_uid": "0xabc"},
    )
    assert reservation is not None
    return reservation["capacity_reservation_id"]


def test_attach_executor_job_lands_on_the_reservation(ledger_services):
    """The assertion the fake transaction could not make.

    Reads the value back off the ledger rather than trusting the call, because
    the defect this covers was a wrong method name on a duck-typed
    collaborator -- invisible to any test that only checks the call happened.

    The session is real because the write now goes through it. A ``MagicMock``
    here would absorb the write silently and this assertion would fail, which
    is the correct signal: with the write inside the caller's transaction,
    there is no such thing as exercising it without a session.
    """
    ledger, factory = ledger_services
    capacity_reservation_id = _reserved(ledger)

    with factory() as db:
        tx = SqlAlchemyFulfillmentTransaction(
            db, MagicMock(), MagicMock(), ledger
        )

        tx.attach_executor_job(capacity_reservation_id, "ansible-job-7")

        db.commit()

    reservation = ledger.get_reservation(capacity_reservation_id)
    assert reservation["create_job_id"] == "ansible-job-7"


def test_attach_executor_job_is_a_no_op_without_a_ledger(ledger_services):
    """A transaction composed without a ledger must not raise.

    The settlement-record half of this transaction is used standalone, and a
    fulfillment that otherwise succeeded should not fail for want of a
    cross-reference.
    """
    tx = SqlAlchemyFulfillmentTransaction(
        MagicMock(), MagicMock(), MagicMock(), None
    )

    tx.attach_executor_job("reservation-1", "ansible-job-7")


def test_attach_executor_job_swallows_a_ledger_failure(ledger_services):
    """Best-effort, and asserted to stay that way.

    Deliberate: the fulfillment is already acknowledged by the time this runs.
    It is also what hid the wrong method name from the e2e run for a cycle, so
    the warning it logs is the only signal -- worth knowing that is the trade.
    """
    ledger, _ = ledger_services
    broken = MagicMock()
    broken.update_lease_fields_in_session.side_effect = RuntimeError(
        "ledger unavailable"
    )
    tx = SqlAlchemyFulfillmentTransaction(
        MagicMock(), MagicMock(), MagicMock(), broken
    )

    tx.attach_executor_job("reservation-1", "ansible-job-7")

    broken.update_lease_fields_in_session.assert_called_once()


# ---------------------------------------------------------------------------
# attach_executor_job while the caller already holds SQLite's writer slot
#
# The real call site (`FulfillmentOrchestrator.begin_fulfillment`) invokes
# this from inside a transaction that has already written -- so that session
# holds SQLite's single writer slot. A ledger call that opens its own session
# to commit cannot then acquire that slot: it waits out the busy timeout and
# raises `database is locked`, the failure is swallowed by design, and the
# only visible symptom is that `/fulfillment/begin` returns one busy timeout
# later than it should. In the e2e that pushed `provision`/`job_submitted`
# 30s past settlement and timed out stage 08b.
#
# The fixtures above cannot show this: a `MagicMock()` session holds no slot,
# and a `StaticPool` in-memory engine shares one connection across every
# session, so no two connections ever contend. Both halves of the
# precondition have to be real -- a file-backed engine (one connection per
# session) and a genuinely held write transaction.
# ---------------------------------------------------------------------------


@pytest.fixture
def contended_ledger_services(tmp_path):
    """Like ``ledger_services``, but able to reproduce writer-slot contention.

    File-backed so each session gets its own connection, and a 1s busy
    timeout so a self-deadlock fails this test in about a second instead of
    the 30s the provisioning service is configured for.
    """
    from market_resource_pools import PoolCreate, ResourcePoolService
    from market_resource_pools.db import Base as PoolsBase
    from market_site.db import Base as SiteBase
    from market_site.ledger import CapacityLedgerService
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(
        f"sqlite:///{tmp_path / 'ledger.db'}",
        connect_args={"check_same_thread": False, "timeout": 1},
    )
    PoolsBase.metadata.create_all(bind=engine)
    SiteBase.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)
    ledger = CapacityLedgerService(factory, unit_claim_keys=("units", "gpu_count"))

    class _Handler:
        provider = "ansible"

        def validate_config(self, config):
            return dict(config)

        def validate_config_problems(self, config):
            return dict(config), ()

        def read_config(self, db, pool_id):
            return {}

        def read_config_for_execution(self, db, pool_id):
            return {}

        def replace_config(self, db, pool_id, config):
            pass

        def delete_config(self, db, pool_id):
            pass

    pools = ResourcePoolService(factory, {"ansible": _Handler()})
    pools.create_pool(PoolCreate(
        id="pool-a",
        label="pool-a",
        provider="ansible",
        enabled=True,
        policy_tags={"deliverable_modes": ["vm"]},
        provider_config={},
    ))
    return ledger, factory


def test_attach_executor_job_lands_while_the_caller_holds_the_writer_slot(
    contended_ledger_services,
):
    """The handle must land from inside the acknowledging transaction.

    `begin_fulfillment` attaches the job handle in the same transaction as
    `acknowledge_create`, by design, so that a reservation never references a
    create the settlement row does not also record. This asserts the write
    actually survives that placement rather than being swallowed -- reading
    the value back off the ledger, because the failure mode here logs a
    warning and returns normally.
    """
    ledger, factory = contended_ledger_services
    capacity_reservation_id = _reserved(ledger)

    with factory() as db:
        # What acknowledge_create's flush leaves behind: this session owns
        # SQLite's writer slot for the rest of the block.
        begin_sqlite_write_transaction(db)
        tx = SqlAlchemyFulfillmentTransaction(
            db, MagicMock(), MagicMock(), ledger
        )

        tx.attach_executor_job(capacity_reservation_id, "ansible-job-7")

        db.commit()

    reservation = ledger.get_reservation(capacity_reservation_id)
    assert reservation["create_job_id"] == "ansible-job-7"


def test_attach_executor_job_does_not_commit_the_callers_transaction(
    contended_ledger_services,
):
    """The ledger write joins the caller's transaction, it does not escape it.

    If the handle were still written through a session of the ledger's own it
    would commit independently, and a caller that rolled back would leave a
    reservation pointing at a create no settlement row records -- the exact
    inconsistency same-transaction placement exists to prevent.
    """
    from market_site.db import CapacityReservation

    ledger, factory = contended_ledger_services
    capacity_reservation_id = _reserved(ledger)

    with factory() as db:
        begin_sqlite_write_transaction(db)
        tx = SqlAlchemyFulfillmentTransaction(
            db, MagicMock(), MagicMock(), ledger
        )
        tx.attach_executor_job(capacity_reservation_id, "ansible-job-7")

        # Visible here, or the write never happened and the assertion after
        # the rollback would hold for the wrong reason.
        pending = db.get(CapacityReservation, capacity_reservation_id)
        assert pending.create_job_id == "ansible-job-7"

        db.rollback()

    reservation = ledger.get_reservation(capacity_reservation_id)
    assert reservation["create_job_id"] is None
