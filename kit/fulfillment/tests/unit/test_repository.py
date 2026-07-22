"""Tests for SettlementRepository: the two independent equivalence scopes,
conflicting-retry rejection, provisioned-resource attachment, and recovery
claims.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from market_fulfillment.db import Base, SettlementRecordState
from market_fulfillment.envelopes import envelope
from market_fulfillment.provider import FulfillmentConflictError
from market_fulfillment.repository import SettlementRepository
from market_fulfillment.settlement_types import (
    SettlementEntityNotFoundError,
    SettlementRequestMismatchError,
    SettlementRequirement,
    SettlementResource,
)


@pytest.fixture
def session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


@pytest.fixture
def repo():
    return SettlementRepository()


def _requirement(**dimensions):
    return SettlementRequirement(
        resource_kind="compute.gpu", dimensions=dimensions or {"gpu_count": 1}
    )


def _resource(settlement_resource_id="host-a"):
    return SettlementResource(
        settlement_resource_id=settlement_resource_id,
        pool_id="pool-1",
        resource_kind="compute.gpu",
        provider="ansible",
    )


# ----------------------------------------------------------------------
# schedule(): scheduling-level equivalence
# ----------------------------------------------------------------------


def test_schedule_creates_assigned_record(session_factory, repo):
    with session_factory() as db:
        record = repo.schedule(
            db,
            capacity_reservation_id="cr-1",
            market="vms",
            scheduling_requirements=_requirement(),
            resource=_resource(),
        )
        db.commit()
        assert record.state == SettlementRecordState.assigned.value
        assert record.settlement_resource_id == "host-a"
        assert record.fulfillment_id is None


def test_schedule_retry_with_equivalent_requirements_returns_existing(session_factory, repo):
    with session_factory() as db:
        first = repo.schedule(
            db,
            capacity_reservation_id="cr-1",
            market="vms",
            scheduling_requirements=_requirement(),
            resource=_resource(),
        )
        db.commit()
        first_id = first.capacity_reservation_id

    with session_factory() as db:
        retried = repo.schedule(
            db,
            capacity_reservation_id="cr-1",
            market="vms",
            scheduling_requirements=_requirement(),
            resource=_resource(),
        )
        db.commit()
        assert retried.capacity_reservation_id == first_id
        assert retried.settlement_resource_id == "host-a"


def test_schedule_retry_with_different_requirements_conflicts(session_factory, repo):
    with session_factory() as db:
        repo.schedule(
            db,
            capacity_reservation_id="cr-1",
            market="vms",
            scheduling_requirements=_requirement(gpu_count=1),
            resource=_resource(),
        )
        db.commit()

    with session_factory() as db:
        with pytest.raises(SettlementRequestMismatchError):
            repo.schedule(
                db,
                capacity_reservation_id="cr-1",
                market="vms",
                scheduling_requirements=_requirement(gpu_count=2),
                resource=_resource(),
            )


def test_schedule_retry_with_consistent_resource_constraint_succeeds(session_factory, repo):
    with session_factory() as db:
        repo.schedule(
            db,
            capacity_reservation_id="cr-1",
            market="vms",
            scheduling_requirements=_requirement(),
            resource=_resource("host-a"),
        )
        db.commit()

    with session_factory() as db:
        retried = repo.schedule(
            db,
            capacity_reservation_id="cr-1",
            market="vms",
            scheduling_requirements=_requirement(),
            resource=_resource("host-a"),
            resource_id_constraint="host-a",
        )
        db.commit()
        assert retried.settlement_resource_id == "host-a"


def test_schedule_retry_with_inconsistent_resource_constraint_conflicts(session_factory, repo):
    with session_factory() as db:
        repo.schedule(
            db,
            capacity_reservation_id="cr-1",
            market="vms",
            scheduling_requirements=_requirement(),
            resource=_resource("host-a"),
        )
        db.commit()

    with session_factory() as db:
        with pytest.raises(SettlementRequestMismatchError):
            repo.schedule(
                db,
                capacity_reservation_id="cr-1",
                market="vms",
                scheduling_requirements=_requirement(),
                resource=_resource("host-a"),
                resource_id_constraint="host-b",
            )


# ----------------------------------------------------------------------
# accept_fulfillment(): fulfillment-level equivalence
# ----------------------------------------------------------------------


def test_accept_fulfillment_requires_prior_scheduling(session_factory, repo):
    with session_factory() as db:
        with pytest.raises(SettlementEntityNotFoundError):
            repo.accept_fulfillment(
                db,
                capacity_reservation_id="cr-missing",
                market="vms",
                fulfillment_request=envelope("vm.fulfillment_request", 1, {}),
            )


def test_accept_fulfillment_generates_fulfillment_id_and_advances_state(session_factory, repo):
    with session_factory() as db:
        repo.schedule(
            db,
            capacity_reservation_id="cr-1",
            market="vms",
            scheduling_requirements=_requirement(),
            resource=_resource(),
        )
        db.commit()

    with session_factory() as db:
        accepted = repo.accept_fulfillment(
            db,
            capacity_reservation_id="cr-1",
            market="vms",
            fulfillment_request=envelope("vm.fulfillment_request", 1, {"image": "ubuntu"}),
        )
        db.commit()
        assert accepted.fulfillment_id is not None
        assert accepted.state == SettlementRecordState.dispatch_pending.value


def test_accept_fulfillment_retry_with_equivalent_request_returns_existing(session_factory, repo):
    with session_factory() as db:
        repo.schedule(
            db,
            capacity_reservation_id="cr-1",
            market="vms",
            scheduling_requirements=_requirement(),
            resource=_resource(),
        )
        db.commit()

    with session_factory() as db:
        first = repo.accept_fulfillment(
            db,
            capacity_reservation_id="cr-1",
            market="vms",
            fulfillment_request=envelope("vm.fulfillment_request", 1, {"image": "ubuntu"}),
        )
        db.commit()
        first_fulfillment_id = first.fulfillment_id

    with session_factory() as db:
        retried = repo.accept_fulfillment(
            db,
            capacity_reservation_id="cr-1",
            market="vms",
            fulfillment_request=envelope("vm.fulfillment_request", 1, {"image": "ubuntu"}),
        )
        db.commit()
        assert retried.fulfillment_id == first_fulfillment_id


def test_accept_fulfillment_retry_with_different_request_conflicts(session_factory, repo):
    with session_factory() as db:
        repo.schedule(
            db,
            capacity_reservation_id="cr-1",
            market="vms",
            scheduling_requirements=_requirement(),
            resource=_resource(),
        )
        db.commit()

    with session_factory() as db:
        repo.accept_fulfillment(
            db,
            capacity_reservation_id="cr-1",
            market="vms",
            fulfillment_request=envelope("vm.fulfillment_request", 1, {"image": "ubuntu"}),
        )
        db.commit()

    with session_factory() as db:
        with pytest.raises(FulfillmentConflictError):
            repo.accept_fulfillment(
                db,
                capacity_reservation_id="cr-1",
                market="vms",
                fulfillment_request=envelope("vm.fulfillment_request", 1, {"image": "debian"}),
            )


# ----------------------------------------------------------------------
# transition()
# ----------------------------------------------------------------------


def test_transition_applies_field_updates(session_factory, repo):
    with session_factory() as db:
        repo.schedule(
            db,
            capacity_reservation_id="cr-1",
            market="vms",
            scheduling_requirements=_requirement(),
            resource=_resource(),
        )
        repo.accept_fulfillment(
            db,
            capacity_reservation_id="cr-1",
            market="vms",
            fulfillment_request=envelope("vm.fulfillment_request", 1, {}),
        )
        db.commit()

    with session_factory() as db:
        updated = repo.transition(
            db,
            "cr-1",
            SettlementRecordState.dispatching.value,
            provider_metadata={"job_id": "abc"},
        )
        db.commit()
        assert updated.state == SettlementRecordState.dispatching.value
        assert updated.provider_metadata == {"job_id": "abc"}


def test_transition_retry_to_same_state_is_a_noop(session_factory, repo):
    with session_factory() as db:
        repo.schedule(
            db,
            capacity_reservation_id="cr-1",
            market="vms",
            scheduling_requirements=_requirement(),
            resource=_resource(),
        )
        db.commit()

    with session_factory() as db:
        result = repo.transition(db, "cr-1", SettlementRecordState.assigned.value)
        db.commit()
        assert result.state == SettlementRecordState.assigned.value


def test_transition_rejects_illegal_edge(session_factory, repo):
    with session_factory() as db:
        repo.schedule(
            db,
            capacity_reservation_id="cr-1",
            market="vms",
            scheduling_requirements=_requirement(),
            resource=_resource(),
        )
        db.commit()

    with session_factory() as db:
        with pytest.raises(Exception):
            repo.transition(db, "cr-1", SettlementRecordState.active.value)


def test_transition_unknown_reservation_raises(session_factory, repo):
    with session_factory() as db:
        with pytest.raises(SettlementEntityNotFoundError):
            repo.transition(db, "does-not-exist", SettlementRecordState.dispatch_pending.value)


# ----------------------------------------------------------------------
# Provisioned resources
# ----------------------------------------------------------------------


def test_add_provisioned_resource_requires_accepted_fulfillment(session_factory, repo):
    with session_factory() as db:
        repo.schedule(
            db,
            capacity_reservation_id="cr-1",
            market="vms",
            scheduling_requirements=_requirement(),
            resource=_resource(),
        )
        db.commit()

    with session_factory() as db:
        with pytest.raises(SettlementEntityNotFoundError):
            repo.add_provisioned_resource(db, capacity_reservation_id="cr-1")


def test_add_and_list_provisioned_resources(session_factory, repo):
    with session_factory() as db:
        repo.schedule(
            db,
            capacity_reservation_id="cr-1",
            market="vms",
            scheduling_requirements=_requirement(),
            resource=_resource(),
        )
        record = repo.accept_fulfillment(
            db,
            capacity_reservation_id="cr-1",
            market="vms",
            fulfillment_request=envelope("vm.fulfillment_request", 1, {}),
        )
        db.commit()
        fulfillment_id = record.fulfillment_id

    with session_factory() as db:
        repo.add_provisioned_resource(
            db, capacity_reservation_id="cr-1", domain_resource_ref="vm-123"
        )
        db.commit()

    with session_factory() as db:
        resources = repo.list_provisioned_resources(db, "cr-1")
        assert len(resources) == 1
        assert resources[0].fulfillment_id == fulfillment_id
        assert resources[0].domain_resource_ref == "vm-123"


# ----------------------------------------------------------------------
# Recovery claims
# ----------------------------------------------------------------------


def test_claim_pending_claims_matching_unclaimed_rows(session_factory, repo):
    with session_factory() as db:
        repo.schedule(
            db,
            capacity_reservation_id="cr-1",
            market="vms",
            scheduling_requirements=_requirement(),
            resource=_resource(),
        )
        repo.accept_fulfillment(
            db,
            capacity_reservation_id="cr-1",
            market="vms",
            fulfillment_request=envelope("vm.fulfillment_request", 1, {}),
        )
        db.commit()

    with session_factory() as db:
        claimed = repo.claim_pending(
            db,
            states=[SettlementRecordState.dispatch_pending.value],
            limit=10,
            lease_seconds=60,
            worker_id="worker-1",
        )
        db.commit()
        assert len(claimed) == 1
        assert claimed[0].claimed_by == "worker-1"
        assert claimed[0].attempt_count == 1


def test_claim_pending_skips_rows_with_a_live_claim(session_factory, repo):
    with session_factory() as db:
        repo.schedule(
            db,
            capacity_reservation_id="cr-1",
            market="vms",
            scheduling_requirements=_requirement(),
            resource=_resource(),
        )
        repo.accept_fulfillment(
            db,
            capacity_reservation_id="cr-1",
            market="vms",
            fulfillment_request=envelope("vm.fulfillment_request", 1, {}),
        )
        db.commit()

    with session_factory() as db:
        repo.claim_pending(
            db,
            states=[SettlementRecordState.dispatch_pending.value],
            limit=10,
            lease_seconds=3600,
            worker_id="worker-1",
        )
        db.commit()

    with session_factory() as db:
        claimed_again = repo.claim_pending(
            db,
            states=[SettlementRecordState.dispatch_pending.value],
            limit=10,
            lease_seconds=3600,
            worker_id="worker-2",
        )
        db.commit()
        assert claimed_again == []


def test_claim_pending_reclaims_rows_with_an_expired_claim(session_factory, repo):
    with session_factory() as db:
        repo.schedule(
            db,
            capacity_reservation_id="cr-1",
            market="vms",
            scheduling_requirements=_requirement(),
            resource=_resource(),
        )
        repo.accept_fulfillment(
            db,
            capacity_reservation_id="cr-1",
            market="vms",
            fulfillment_request=envelope("vm.fulfillment_request", 1, {}),
        )
        db.commit()

    long_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    with session_factory() as db:
        repo.claim_pending(
            db,
            states=[SettlementRecordState.dispatch_pending.value],
            limit=10,
            lease_seconds=1,
            worker_id="worker-1",
            now=long_ago,
        )
        db.commit()

    with session_factory() as db:
        claimed_again = repo.claim_pending(
            db,
            states=[SettlementRecordState.dispatch_pending.value],
            limit=10,
            lease_seconds=60,
            worker_id="worker-2",
        )
        db.commit()
        assert len(claimed_again) == 1
        assert claimed_again[0].claimed_by == "worker-2"
        assert claimed_again[0].attempt_count == 2
