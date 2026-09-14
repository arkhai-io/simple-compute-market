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
    """
    ledger, factory = ledger_services
    capacity_reservation_id = _reserved(ledger)
    tx = SqlAlchemyFulfillmentTransaction(
        MagicMock(), MagicMock(), MagicMock(), ledger
    )

    tx.attach_executor_job(capacity_reservation_id, "ansible-job-7")

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
    broken.update_lease_fields.side_effect = RuntimeError("ledger unavailable")
    tx = SqlAlchemyFulfillmentTransaction(
        MagicMock(), MagicMock(), MagicMock(), broken
    )

    tx.attach_executor_job("reservation-1", "ansible-job-7")

    broken.update_lease_fields.assert_called_once()
