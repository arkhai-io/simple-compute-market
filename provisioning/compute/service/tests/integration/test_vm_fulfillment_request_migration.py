"""Stored VM fulfillment requests lose the guest name, in every state.

A storefront replays its stored request verbatim, and the fulfillment kit
accepts a repeat only when it equals the stored copy; both sides' copies are
rewritten, so a replay still matches, and an accepted fulfillment keeps the name
its create was prepared with.
"""

from __future__ import annotations

import json

import pytest
from market_core import VersionedEnvelope
from market_fulfillment import FulfillmentConflictError
from market_fulfillment.settlement_repository import SettlementRepository
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from compute_provisioning_service.db.database import run_migrations
from compute_provisioning_service.db.migrations import (
    _migrate_vm_fulfillment_request_names_no_guest,
)

_OLD_PAYLOAD = {"vm_target": "tenant-ab12", "ssh_pubkey": "ssh-ed25519 AAAA"}
_PREPARED = {
    "kind": "compute.job-fulfillment.operation",
    "schema_version": 1,
    "payload": {"executor_target": "tenant-ab12", "parameters": {"vm_target": "tenant-ab12"}},
}
_METADATA = {
    "create_job_id": "job-1", "teardown_job_id": None, "current_job_id": "job-1",
    "operation": "create", "host_id": "kvm1", "executor_target": "tenant-ab12",
}
_STATES = ("dispatch_pending", "dispatching", "active", "failed", "tearing_down", "torn_down")


def _engine():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    run_migrations(engine)
    return engine


def _record(engine, reservation, *, request, state="active", market="vms"):
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO settlement_records (capacity_reservation_id, fulfillment_id, market, "
            "scheduling_requirements, provider, fulfillment_request, prepared_create_operation, "
            "provider_metadata, state, attempt_count) VALUES (:id, :fulfillment, :market, '{}', "
            "'ansible', :request, :prepared, :metadata, :state, 0)"
        ), {
            "id": reservation,
            "fulfillment": f"f-{reservation}",
            "market": market,
            "request": json.dumps(request),
            "prepared": json.dumps(_PREPARED),
            "metadata": json.dumps(_METADATA),
            "state": state,
        })


def _column(engine, reservation, column):
    with engine.connect() as connection:
        value = connection.execute(
            text(f"SELECT {column} FROM settlement_records WHERE capacity_reservation_id = :id"),
            {"id": reservation},
        ).scalar()
    if column == "state":
        return value
    return json.loads(value) if isinstance(value, str) else value


def _vm_request(payload):
    return {"kind": "vm.fulfillment.request", "schema_version": 1, "payload": payload}


@pytest.mark.parametrize("state", _STATES)
def test_every_state_s_stored_request_loses_the_guest_name_and_nothing_else(state):
    engine = _engine()
    _record(engine, "r-1", request=_vm_request(_OLD_PAYLOAD), state=state)

    _migrate_vm_fulfillment_request_names_no_guest(engine)

    assert _column(engine, "r-1", "fulfillment_request") == _vm_request(
        {"ssh_pubkey": "ssh-ed25519 AAAA"}
    )
    # The create keeps the name it was prepared with.
    assert _column(engine, "r-1", "prepared_create_operation") == _PREPARED
    assert _column(engine, "r-1", "provider_metadata") == _METADATA
    assert _column(engine, "r-1", "state") == state


def test_other_requests_are_left_alone_and_a_rerun_changes_nothing():
    engine = _engine()
    other = {"kind": "bare_metal.v2", "schema_version": 1, "payload": {"vm_target": "x"}}
    current = _vm_request({"ssh_pubkey": "ssh-ed25519 AAAA"})
    _record(engine, "r-bm", request=other, market="bare_metal")
    _record(engine, "r-new", request=current)
    _record(engine, "r-old", request=_vm_request(_OLD_PAYLOAD))

    _migrate_vm_fulfillment_request_names_no_guest(engine)
    first = {r: _column(engine, r, "fulfillment_request") for r in ("r-bm", "r-new", "r-old")}
    _migrate_vm_fulfillment_request_names_no_guest(engine)

    assert first == {"r-bm": other, "r-new": current, "r-old": current}
    assert {
        r: _column(engine, r, "fulfillment_request") for r in ("r-bm", "r-new", "r-old")
    } == first


def test_a_replayed_migrated_request_finds_its_accepted_fulfillment():
    """The storefront replays its own migrated copy; it matches provisioning's,
    which returns the fulfillment rather than refusing a different request. An
    unmigrated copy would be refused, which is why both sides are migrated."""
    engine = _engine()
    _record(engine, "r-1", request=_vm_request(_OLD_PAYLOAD), state="dispatching")
    _migrate_vm_fulfillment_request_names_no_guest(engine)
    repository = SettlementRepository()
    factory = sessionmaker(bind=engine)

    with factory() as db:
        record = repository.accept_fulfillment(
            db,
            capacity_reservation_id="r-1",
            market="vms",
            fulfillment_request=VersionedEnvelope.model_validate(
                _vm_request({"ssh_pubkey": "ssh-ed25519 AAAA"})
            ),
        )
        assert record.fulfillment_id == "f-r-1"
        assert record.prepared_create_operation == _PREPARED
        db.rollback()

    with factory() as db, pytest.raises(FulfillmentConflictError):
        repository.accept_fulfillment(
            db,
            capacity_reservation_id="r-1",
            market="vms",
            fulfillment_request=VersionedEnvelope.model_validate(_vm_request(_OLD_PAYLOAD)),
        )
