"""Tests for SettlementRepository: the two independent equivalence scopes,
conflicting-retry rejection, provisioned-resource attachment, and single-worker recovery leases.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from market_fulfillment.db import Base, SettlementRecordState
from market_fulfillment.envelopes import envelope
from market_fulfillment.provider import FulfillmentConflictError
from market_fulfillment.settlement_repository import SettlementRepository
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


def test_accept_fulfillment_rejects_first_request_for_different_market(session_factory, repo):
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
        with pytest.raises(FulfillmentConflictError):
            repo.accept_fulfillment(
                db,
                capacity_reservation_id="cr-1",
                market="bare-metal",
                fulfillment_request=envelope("host.fulfillment_request", 1, {}),
            )
        db.rollback()

    with session_factory() as db:
        record = repo.get(db, "cr-1")
        assert record.market == "vms"
        assert record.fulfillment_id is None
        assert record.fulfillment_request is None


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

    with session_factory() as db:
        claimed_again = repo.claim_pending(
            db,
            states=[SettlementRecordState.dispatch_pending.value],
            limit=10,
            lease_seconds=3600,
            worker_id="worker-2",
        )
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

    with session_factory() as db:
        claimed_again = repo.claim_pending(
            db,
            states=[SettlementRecordState.dispatch_pending.value],
            limit=10,
            lease_seconds=60,
            worker_id="worker-2",
        )
        assert len(claimed_again) == 1
        assert claimed_again[0].claimed_by == "worker-2"
        # A reclaim is still a new attempt against this row.
        assert claimed_again[0].attempt_count == 2


def test_claim_pending_accepts_a_backoff_callable_for_lease_seconds(session_factory, repo):
    """The mechanism FulfillmentConvergenceWatchdog actually uses: lease
    length grows with each row's own post-increment attempt_count rather
    than being fixed."""

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

    seen_attempt_counts: list[int] = []

    def lease_for_attempt(attempt_count: int) -> float:
        seen_attempt_counts.append(attempt_count)
        return 10.0 * attempt_count

    fixed_now = datetime.now(timezone.utc)
    with session_factory() as db:
        claimed = repo.claim_pending(
            db,
            states=[SettlementRecordState.dispatch_pending.value],
            limit=10,
            lease_seconds=lease_for_attempt,
            worker_id="worker-1",
            now=fixed_now,
        )
        assert seen_attempt_counts == [1]
        # claim_pending's db.refresh() round-trips this value through
        # SQLite, which returns a naive datetime regardless of what was
        # written -- compare the wall-clock value, not tzinfo.
        expected = (fixed_now + timedelta(seconds=10.0)).replace(tzinfo=None)
        assert claimed[0].claim_expires_at == expected


def test_clear_claim_releases_a_claim_owned_by_the_caller(session_factory, repo):
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

    with session_factory() as db:
        repo.clear_claim(db, "cr-1", worker_id="worker-1")
        db.commit()

    with session_factory() as db:
        record = repo.get(db, "cr-1")
        assert record.claimed_by is None
        assert record.claim_expires_at is None


def test_clear_claim_is_a_noop_when_the_claim_was_reclaimed_by_another_worker(
    session_factory, repo
):
    """A slow worker's stale clear_claim must not release a lease another
    worker has since legitimately reclaimed."""

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

    with session_factory() as db:
        repo.claim_pending(
            db,
            states=[SettlementRecordState.dispatch_pending.value],
            limit=10,
            lease_seconds=3600,
            worker_id="worker-2",
        )

    with session_factory() as db:
        repo.clear_claim(db, "cr-1", worker_id="worker-1")
        db.commit()

    with session_factory() as db:
        record = repo.get(db, "cr-1")
        assert record.claimed_by == "worker-2"
        assert record.claim_expires_at is not None


def test_mark_provisioned_resources_torn_down_updates_status(session_factory, repo):
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
        repo.add_provisioned_resource(
            db, capacity_reservation_id="cr-1", domain_resource_ref="vm-1"
        )
        db.commit()

    with session_factory() as db:
        repo.mark_provisioned_resources_torn_down(db, "cr-1")
        db.commit()

    with session_factory() as db:
        resources = repo.list_provisioned_resources(db, "cr-1")
        assert len(resources) == 1
        assert resources[0].status == "torn_down"
        # No new row -- the existing one was updated, not resolved again.


def test_recovery_diagnostics_reports_per_state_counts_and_ages(session_factory, repo):
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
        repo.schedule(
            db,
            capacity_reservation_id="cr-2",
            market="vms",
            scheduling_requirements=_requirement(),
            resource=_resource(),
        )
        repo.accept_fulfillment(
            db,
            capacity_reservation_id="cr-2",
            market="vms",
            fulfillment_request=envelope("vm.fulfillment_request", 1, {}),
        )
        db.commit()

    long_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    with session_factory() as db:
        # cr-1: claimed and still within its lease.
        repo.claim_pending(
            db,
            states=[SettlementRecordState.dispatch_pending.value],
            limit=1,
            lease_seconds=3600,
            worker_id="worker-a",
        )

    with session_factory() as db:
        # cr-2: claimed, but the lease has already lapsed.
        repo.claim_pending(
            db,
            states=[SettlementRecordState.dispatch_pending.value],
            limit=1,
            lease_seconds=1,
            worker_id="worker-b",
            now=long_ago,
        )

    with session_factory() as db:
        diagnostics = repo.recovery_diagnostics(db)
        state = diagnostics.per_state[SettlementRecordState.dispatch_pending.value]
        assert state.total == 2
        assert state.actively_claimed == 1
        assert state.expired_claims == 1
        assert state.max_attempt_count == 1
        assert state.oldest_row_age_seconds is not None
        assert state.oldest_row_age_seconds > 0
        empty_state = diagnostics.per_state[SettlementRecordState.tearing_down.value]
        assert empty_state.total == 0
        assert empty_state.oldest_row_age_seconds is None
        assert empty_state.max_attempt_count == 0
        assert diagnostics.failed_count == 0
        assert diagnostics.teardown_failed_count == 0


def test_recovery_diagnostics_counts_terminal_failures(session_factory, repo):
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
        repo.transition(
            db,
            "cr-1",
            SettlementRecordState.dispatching.value,
            provider_metadata={"job": "1"},
        )
        repo.transition(
            db,
            "cr-1",
            SettlementRecordState.failed.value,
            failure_reason="provider_reported_failure",
        )
        db.commit()

    with session_factory() as db:
        diagnostics = repo.recovery_diagnostics(db)
        assert diagnostics.failed_count == 1
        assert diagnostics.teardown_failed_count == 0
        assert (
            diagnostics.per_state[SettlementRecordState.dispatch_pending.value].total
            == 0
        )


def test_concurrent_add_provisioned_resource_produces_exactly_one_row(tmp_path):
    """Task 6.7: the (capacity_reservation_id, domain_resource_ref) unique
    constraint (6.3.4) is a genuine backstop, not just app-level dedup --
    two real threads racing add_provisioned_resource for the same
    reservation/ref must still produce exactly one row."""

    database = tmp_path / "add_provisioned_resource.db"
    engine = create_engine(
        f"sqlite:///{database}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    repo = SettlementRepository()

    with factory() as db:
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

    def add() -> None:
        with factory() as thread_db:
            repo.add_provisioned_resource(
                thread_db,
                capacity_reservation_id="cr-1",
                domain_resource_ref="vm-42",
            )
            thread_db.commit()

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(add) for _ in range(4)]
        for future in futures:
            future.result(timeout=10)

    with factory() as db:
        resources = repo.list_provisioned_resources(db, "cr-1")
        assert len(resources) == 1
        assert resources[0].domain_resource_ref == "vm-42"


def test_concurrent_claim_pending_never_returns_the_same_row_to_two_workers(tmp_path):
    """Task 6.3.2: two real threads, independent sessions, file-backed
    SQLite (same technique as test_scheduler.py's independent-session
    proof), racing claim_pending against the same eligible rows."""

    database = tmp_path / "claim_pending.db"
    engine = create_engine(
        f"sqlite:///{database}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    repo = SettlementRepository()

    row_count = 20
    for i in range(row_count):
        cr_id = f"cr-{i}"
        with factory() as db:
            repo.schedule(
                db,
                capacity_reservation_id=cr_id,
                market="vms",
                scheduling_requirements=_requirement(),
                resource=_resource(),
            )
            repo.accept_fulfillment(
                db,
                capacity_reservation_id=cr_id,
                market="vms",
                fulfillment_request=envelope("vm.fulfillment_request", 1, {}),
            )
            db.commit()

    def claim(worker_id: str) -> list[str]:
        with factory() as thread_db:
            claimed = repo.claim_pending(
                thread_db,
                states=[SettlementRecordState.dispatch_pending.value],
                limit=row_count,
                lease_seconds=60,
                worker_id=worker_id,
            )
            return [record.capacity_reservation_id for record in claimed]

    with ThreadPoolExecutor(max_workers=2) as pool:
        future_a = pool.submit(claim, "worker-a")
        future_b = pool.submit(claim, "worker-b")
        claimed_a = future_a.result(timeout=10)
        claimed_b = future_b.result(timeout=10)

    assert set(claimed_a).isdisjoint(claimed_b)
    assert len(set(claimed_a) | set(claimed_b)) == row_count


def test_transition_allows_shared_lifecycle_fields(session_factory, repo):
    with session_factory() as db:
        repo.schedule(
            db, capacity_reservation_id="cr-allowed", market="vms",
            scheduling_requirements=_requirement(), resource=_resource(),
        )
        repo.accept_fulfillment(
            db, capacity_reservation_id="cr-allowed", market="vms",
            fulfillment_request=envelope("vm.fulfillment_request", 1, {}),
        )
        db.commit()

    updates = {
        "prepared_create_operation": {"kind": "create", "schema_version": 1, "payload": {}},
        "prepared_teardown_operation": {"kind": "teardown", "schema_version": 1, "payload": {}},
        "provider_metadata": {"job_id": "job-1"},
        "teardown_provider_metadata": {"job_id": "job-2"},
        "failure_reason": "provider_error",
        "failure_message": "failed",
    }
    with session_factory() as db:
        record = repo.transition(
            db, "cr-allowed", SettlementRecordState.dispatching.value, **updates
        )
        db.commit()
        for field, value in updates.items():
            assert getattr(record, field) == value


@pytest.mark.parametrize(
    "field,value",
    [
        ("market", "bare-metal"),
        ("fulfillment_request", {}),
        ("state", SettlementRecordState.active.value),
        ("claimed_by", "worker-2"),
        ("updated_at", None),
        ("provider_metdata", {}),
    ],
)
def test_transition_rejects_non_lifecycle_fields_before_state_mutation(
    session_factory, repo, field, value
):
    with session_factory() as db:
        repo.schedule(
            db, capacity_reservation_id="cr-forbidden", market="vms",
            scheduling_requirements=_requirement(), resource=_resource(),
        )
        repo.accept_fulfillment(
            db, capacity_reservation_id="cr-forbidden", market="vms",
            fulfillment_request=envelope("vm.fulfillment_request", 1, {}),
        )
        db.commit()

    with session_factory() as db:
        record = repo.get(db, "cr-forbidden")
        original_state = record.state
        with pytest.raises(ValueError):
            repo.transition(
                db, "cr-forbidden", SettlementRecordState.dispatching.value,
                **{field: value},
            )
        assert record.state == original_state


def test_canonical_models_normalize_explicit_defaults_and_nested_payload(session_factory, repo):
    implicit = SettlementRequirement(resource_kind="compute.gpu", dimensions={"gpu_count": 1})
    explicit = SettlementRequirement(
        resource_kind="compute.gpu", dimensions={"gpu_count": 1}, attributes={}
    )
    nested = envelope(
        "vm.fulfillment_request", 1,
        {"network": {"ports": [22, 443], "metadata": {"role": "worker"}}},
    )
    with session_factory() as db:
        repo.schedule(
            db, capacity_reservation_id="cr-canonical", market="vms",
            scheduling_requirements=implicit, resource=_resource(),
        )
        db.commit()
    with session_factory() as db:
        assert repo.schedule(
            db, capacity_reservation_id="cr-canonical", market="vms",
            scheduling_requirements=explicit, resource=_resource(),
        ).scheduling_requirements == explicit.model_dump(mode="json")
        db.commit()
    with session_factory() as db:
        repo.accept_fulfillment(
            db, capacity_reservation_id="cr-canonical", market="vms",
            fulfillment_request=nested,
        )
        db.commit()
    with session_factory() as db:
        record = repo.get(db, "cr-canonical")
        assert record.fulfillment_request == nested.model_dump(mode="json")


def test_concurrent_sqlite_acceptance_returns_one_fulfillment_identity(tmp_path, repo):
    database = tmp_path / "fulfillment.db"
    engine = create_engine(
        f"sqlite:///{database}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        repo.schedule(
            db, capacity_reservation_id="cr-race", market="vms",
            scheduling_requirements=_requirement(), resource=_resource(),
        )
        db.commit()

    barrier = Barrier(2)

    def accept() -> str:
        with factory() as db:
            barrier.wait()
            record = repo.accept_fulfillment(
                db, capacity_reservation_id="cr-race", market="vms",
                fulfillment_request=envelope("vm.fulfillment_request", 1, {"image": "ubuntu"}),
            )
            db.commit()
            assert record.fulfillment_id is not None
            return record.fulfillment_id

    with ThreadPoolExecutor(max_workers=2) as pool:
        identities = list(pool.map(lambda _: accept(), range(2)))

    assert len(set(identities)) == 1
    with factory() as db:
        assert repo.get(db, "cr-race").fulfillment_id == identities[0]


# ----------------------------------------------------------------------
# capacity-reclamation abandonment hook
# ----------------------------------------------------------------------

def test_abandon_if_assigned_transitions_only_assigned_rows(session_factory, repo):
    with session_factory() as db:
        repo.schedule(db, capacity_reservation_id="cr-abandon", market="vms",
                      scheduling_requirements=_requirement(), resource=_resource())
        db.commit()
    with session_factory() as db:
        repo.abandon_if_assigned(db, "missing")
        repo.abandon_if_assigned(db, "cr-abandon")
        assert repo.get(db, "cr-abandon").state == SettlementRecordState.abandoned.value
        repo.abandon_if_assigned(db, "cr-abandon")
        db.commit()
    with session_factory() as db:
        assert repo.get(db, "cr-abandon").state == SettlementRecordState.abandoned.value


def test_abandon_if_assigned_obeys_caller_rollback(session_factory, repo):
    with session_factory() as db:
        repo.schedule(db, capacity_reservation_id="cr-rollback", market="vms",
                      scheduling_requirements=_requirement(), resource=_resource())
        db.commit()
    with session_factory() as db:
        repo.abandon_if_assigned(db, "cr-rollback")
        assert repo.get(db, "cr-rollback").state == SettlementRecordState.abandoned.value
        db.rollback()
    with session_factory() as db:
        assert repo.get(db, "cr-rollback").state == SettlementRecordState.assigned.value


def test_abandon_if_assigned_preserves_post_assignment_state(session_factory, repo):
    with session_factory() as db:
        repo.schedule(db, capacity_reservation_id="cr-dispatch", market="vms",
                      scheduling_requirements=_requirement(), resource=_resource())
        record = repo.get(db, "cr-dispatch")
        record.state = SettlementRecordState.dispatch_pending.value
        db.commit()
    with session_factory() as db:
        repo.abandon_if_assigned(db, "cr-dispatch")
        assert repo.get(db, "cr-dispatch").state == SettlementRecordState.dispatch_pending.value
