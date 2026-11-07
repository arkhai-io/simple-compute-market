"""Active fulfillments' targets are recorded on their reservations, once.

Provisioning records a lease's target when its fulfillment becomes active; a
fulfillment that became active before it did, and whose storefront never
registered the lease, has its target recorded by migration.
"""

from __future__ import annotations

import json

from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from compute_provisioning_service.db.database import run_migrations
from compute_provisioning_service.db.migrations import (
    _migrate_active_fulfillment_targets_on_reservations,
)

_METADATA = {
    "create_job_id": "job-1",
    "teardown_job_id": None,
    "current_job_id": "job-1",
    "operation": "create",
    "host_id": "kvm1",
    "executor_target": "tenant-0123456789abcdef01234567",
}


def _engine():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    run_migrations(engine)
    return engine


def _deal(engine, reservation, *, state="active", reservation_state="leased",
          target=None, metadata=_METADATA):
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO capacity_reservations (capacity_reservation_id, units, state, "
            "offering_mode, executor_target) VALUES (:id, 1, :state, 'vm', :target)"
        ), {"id": reservation, "state": reservation_state, "target": target})
        connection.execute(text(
            "INSERT INTO settlement_records (capacity_reservation_id, fulfillment_id, market, "
            "scheduling_requirements, provider, provider_metadata, state, attempt_count) "
            "VALUES (:id, :fulfillment, 'vms', '{}', 'ansible', :metadata, :state, 0)"
        ), {
            "id": reservation,
            "fulfillment": f"f-{reservation}",
            "metadata": json.dumps(metadata),
            "state": state,
        })


def _target(engine, reservation):
    with engine.connect() as connection:
        return connection.execute(
            text(
                "SELECT executor_target FROM capacity_reservations "
                "WHERE capacity_reservation_id = :id"
            ),
            {"id": reservation},
        ).scalar()


def test_each_active_fulfillment_s_target_is_recorded_where_none_is():
    engine = _engine()
    _deal(engine, "r-unregistered")
    _deal(engine, "r-registered", target="tenant-registered")
    _deal(engine, "r-dispatching", state="dispatching")
    _deal(engine, "r-released", reservation_state="released")
    _deal(engine, "r-foreign", metadata={"job": "1"})

    _migrate_active_fulfillment_targets_on_reservations(engine)

    assert _target(engine, "r-unregistered") == _METADATA["executor_target"]
    assert _target(engine, "r-registered") == "tenant-registered"
    assert _target(engine, "r-dispatching") is None
    assert _target(engine, "r-released") is None
    assert _target(engine, "r-foreign") is None


def test_a_rerun_changes_nothing():
    engine = _engine()
    _deal(engine, "r-1")

    _migrate_active_fulfillment_targets_on_reservations(engine)
    _migrate_active_fulfillment_targets_on_reservations(engine)

    assert _target(engine, "r-1") == _METADATA["executor_target"]
