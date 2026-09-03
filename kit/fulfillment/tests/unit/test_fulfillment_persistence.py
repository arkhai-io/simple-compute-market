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
