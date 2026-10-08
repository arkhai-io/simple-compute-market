"""Convergence keeps recording the targets active fulfillments' leases lack.

Against the real site ledger, with the fulfillment and site tables in one SQLite
database as the provisioning service composes them. Activation records a lease's
target in its own transaction; a target its data prevented recording is recorded
by a later sweep once it can be, and what cannot be recorded, or disagrees with
what the site records, is counted and never overwritten.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from market_fulfillment import ProviderRegistry, SettlementRecordState, SettlementRepository
from market_fulfillment.db import SettlementRecord
from market_site.db import CapacityReservation
from market_site.ledger import CapacityLedgerService
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from compute_provisioning_service.db.database import run_migrations
from compute_provisioning_service.services.fulfillment_convergence import (
    FulfillmentConvergenceWatchdog,
)

_State = SettlementRecordState


def _metadata(target: str) -> dict:
    return {
        "create_job_id": "job-1",
        "teardown_job_id": None,
        "current_job_id": "job-1",
        "operation": "create",
        "host_id": "kvm1",
        "executor_target": target,
    }


@pytest.fixture
def world():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    run_migrations(engine)
    factory = sessionmaker(bind=engine)
    ledger = CapacityLedgerService(
        factory, unit_claim_keys=("units", "gpu_count"), mirror_dimension="gpu_count"
    )
    ledger.register_resource(
        resource_id="kvm1-gpus", total_units=16, host_id="kvm1", attributes={}, pool_id="default"
    )
    watchdog = FulfillmentConvergenceWatchdog(
        session_factory=factory,
        repository=SettlementRepository(),
        provider_registry=ProviderRegistry({}),
        settings=SimpleNamespace(
            fulfillment_convergence_batch_size=10,
            fulfillment_convergence_backoff_initial_seconds=1.0,
            fulfillment_convergence_backoff_multiplier=2.0,
            fulfillment_convergence_backoff_max_seconds=60.0,
            fulfillment_convergence_backoff_jitter_fraction=0.0,
        ),
        capacity_ledger=ledger,
    )
    return factory, ledger, watchdog


def _committed(ledger) -> str:
    reserved = ledger.reserve(
        claim={"offering_mode": "vm", "gpu_count": 1, "host_id": "kvm1"},
        deal_ref={"listing_id": "listing-1"},
    )
    assert reserved is not None
    ledger.commit(
        capacity_reservation_id=reserved["capacity_reservation_id"],
        lease_end_utc="2099-01-01 01:00",
    )
    return reserved["capacity_reservation_id"]


def _fulfillment(factory, reservation_id: str, *, metadata: dict, state=_State.active):
    with factory() as db, db.begin():
        db.add(
            SettlementRecord(
                capacity_reservation_id=reservation_id,
                fulfillment_id=f"f-{reservation_id}",
                market="vms",
                scheduling_requirements={},
                provider="ansible",
                provider_metadata=metadata,
                state=state.value,
            )
        )


def _record_target(factory, ledger, reservation_id: str, target: str) -> None:
    with factory() as db:
        ledger.record_executor_target_in_session(db, reservation_id, target)
        db.commit()


def test_a_missing_target_is_recorded_once(world):
    factory, ledger, watchdog = world
    reservation_id = _committed(ledger)
    _fulfillment(factory, reservation_id, metadata=_metadata("tenant-guest-1"))

    first = watchdog.reconcile_lease_targets()
    second = watchdog.reconcile_lease_targets()

    assert ledger.get_reservation(reservation_id)["executor_target"] == "tenant-guest-1"
    assert (first["repaired"], second["repaired"]) == (1, 0)


def test_a_different_recorded_target_is_counted_and_never_overwritten(world):
    factory, ledger, watchdog = world
    reservation_id = _committed(ledger)
    _record_target(factory, ledger, reservation_id, "tenant-recorded-earlier")
    _fulfillment(factory, reservation_id, metadata=_metadata("tenant-guest-1"))

    counts = watchdog.reconcile_lease_targets()

    assert counts["different_target_recorded"] == 1
    assert counts["repaired"] == 0
    assert ledger.get_reservation(reservation_id)["executor_target"] == "tenant-recorded-earlier"


def test_what_cannot_be_recorded_is_counted_by_reason(world):
    factory, ledger, watchdog = world
    foreign = _committed(ledger)
    _fulfillment(factory, foreign, metadata={"job": "1"})
    refused = _committed(ledger)
    with factory() as db:
        db.get(CapacityReservation, refused).offering_mode = None
        db.commit()
    _fulfillment(factory, refused, metadata=_metadata("tenant-guest-2"))
    _fulfillment(factory, "r-without-reservation", metadata=_metadata("tenant-guest-3"))

    counts = watchdog.reconcile_lease_targets()

    assert counts["unrecordable"] == {
        "metadata": 1,
        "reservation_refused": 1,
        "no_reservation": 1,
    }
    assert counts["repaired"] == 0
    assert ledger.get_reservation(refused)["executor_target"] is None


def test_a_terminal_reservation_and_an_inactive_fulfillment_are_left_alone(world):
    factory, ledger, watchdog = world
    released = _committed(ledger)
    ledger.release(capacity_reservation_id=released)
    _fulfillment(factory, released, metadata=_metadata("tenant-guest-4"))
    dispatching = _committed(ledger)
    _fulfillment(
        factory, dispatching, metadata=_metadata("tenant-guest-5"), state=_State.dispatching
    )

    counts = watchdog.reconcile_lease_targets()

    assert counts == {
        "repaired": 0,
        "unrecordable": {"metadata": 0, "reservation_refused": 0, "no_reservation": 0},
        "different_target_recorded": 0,
    }
    assert ledger.get_reservation(released)["executor_target"] is None
    assert ledger.get_reservation(dispatching)["executor_target"] is None
