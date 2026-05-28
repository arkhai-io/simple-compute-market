"""Unit tests for LeaseService.

Scope (per Architecture.md — Unit Tests jurisdiction):
  - create: initial status assignment based on lease_start_utc
  - create: duplicate escrow_uid raises LeaseConflictError
  - list_leases: status/vm_host/escrow_uid filters
  - list_due: returns only active leases with lease_end_utc < now
  - list_pending_to_activate: returns pending leases whose start has passed
  - lifecycle transitions: advance_pending, begin_releasing, mark_released,
    mark_forced, mark_cancelled
  - update: partial field writes

External boundary: SQLAlchemy with an in-memory SQLite DB.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from db.database import create_session_factory
from db.models import Base, LeaseStatus
from models.lease_model import LeaseCreate, LeaseUpdate
from services.lease_service import LeaseConflictError, LeaseNotFoundError, LeaseService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return engine


@pytest.fixture
def session_factory(db_engine):
    return create_session_factory(db_engine)


@pytest.fixture
def svc(session_factory):
    return LeaseService(session_factory=session_factory)


def _make_lease(
    resource_id: str = "compute-kvm1-001",
    escrow_uid: str = "escrow-abc",
    vm_host: str = "kvm1",
    vm_target: str = "tenant-a1b2",
    lease_start_utc=None,
    hours_from_now: int = 2,
    create_job_id: str | None = None,
) -> LeaseCreate:
    return LeaseCreate(
        resource_id=resource_id,
        escrow_uid=escrow_uid,
        vm_host=vm_host,
        vm_target=vm_target,
        lease_start_utc=lease_start_utc,
        lease_end_utc=datetime.now(timezone.utc) + timedelta(hours=hours_from_now),
        create_job_id=create_job_id,
    )


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------

class TestCreate:
    def test_creates_with_active_status_when_no_start(self, svc):
        """No lease_start_utc → immediate → status=active."""
        lease = svc.create(_make_lease(lease_start_utc=None))
        assert lease.status == LeaseStatus.active.value

    def test_creates_with_active_status_when_start_in_past(self, svc):
        """lease_start_utc in the past → already started → status=active."""
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        lease = svc.create(_make_lease(lease_start_utc=past))
        assert lease.status == LeaseStatus.active.value

    def test_creates_with_pending_status_when_start_in_future(self, svc):
        """lease_start_utc in the future → deferred → status=pending."""
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        lease = svc.create(_make_lease(lease_start_utc=future))
        assert lease.status == LeaseStatus.pending.value

    def test_stores_all_fields(self, svc):
        data = _make_lease(
            resource_id="compute-h200-001",
            escrow_uid="escrow-xyz",
            vm_host="h200-host",
            vm_target="tenant-z9y8",
            create_job_id="job-create-abc",
        )
        lease = svc.create(data)
        assert lease.resource_id == "compute-h200-001"
        assert lease.escrow_uid == "escrow-xyz"
        assert lease.vm_host == "h200-host"
        assert lease.vm_target == "tenant-z9y8"
        assert lease.create_job_id == "job-create-abc"
        assert lease.id is not None

    def test_duplicate_escrow_uid_raises_conflict(self, svc):
        svc.create(_make_lease(escrow_uid="esc-dup"))
        with pytest.raises(LeaseConflictError):
            svc.create(_make_lease(escrow_uid="esc-dup"))


# ---------------------------------------------------------------------------
# get / get_by_escrow
# ---------------------------------------------------------------------------

class TestGet:
    def test_get_returns_lease(self, svc):
        created = svc.create(_make_lease())
        fetched = svc.get_lease(created.id)
        assert fetched.id == created.id

    def test_get_raises_not_found(self, svc):
        with pytest.raises(LeaseNotFoundError):
            svc.get_lease("nonexistent-id")

    def test_get_by_escrow_returns_lease(self, svc):
        svc.create(_make_lease(escrow_uid="esc-find-me"))
        lease = svc.get_lease_by_escrow("esc-find-me")
        assert lease is not None
        assert lease.escrow_uid == "esc-find-me"

    def test_get_by_escrow_returns_none_when_missing(self, svc):
        assert svc.get_lease_by_escrow("nonexistent") is None


# ---------------------------------------------------------------------------
# list_leases
# ---------------------------------------------------------------------------

class TestListLeases:
    def test_empty_table_returns_empty(self, svc):
        assert svc.list_leases() == []

    def test_filters_by_status(self, svc):
        svc.create(_make_lease(escrow_uid="e1"))
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        svc.create(_make_lease(escrow_uid="e2", lease_start_utc=future))
        active = svc.list_leases(status=LeaseStatus.active.value)
        pending = svc.list_leases(status=LeaseStatus.pending.value)
        assert all(l.status == LeaseStatus.active.value for l in active)
        assert all(l.status == LeaseStatus.pending.value for l in pending)

    def test_filters_by_vm_host(self, svc):
        svc.create(_make_lease(escrow_uid="e1", vm_host="kvm1"))
        svc.create(_make_lease(escrow_uid="e2", vm_host="ww2"))
        result = svc.list_leases(vm_host="kvm1")
        assert len(result) == 1
        assert result[0].vm_host == "kvm1"

    def test_filters_by_escrow_uid(self, svc):
        svc.create(_make_lease(escrow_uid="target"))
        svc.create(_make_lease(escrow_uid="other"))
        result = svc.list_leases(escrow_uid="target")
        assert len(result) == 1
        assert result[0].escrow_uid == "target"


# ---------------------------------------------------------------------------
# list_due
# ---------------------------------------------------------------------------

class TestListDue:
    def test_returns_active_leases_past_end_time(self, svc):
        past = datetime.now(timezone.utc) - timedelta(seconds=1)
        data = LeaseCreate(
            resource_id="r1",
            escrow_uid="e-due",
            vm_host="kvm1",
            vm_target="t1",
            lease_end_utc=past,
        )
        svc.create(data)
        due = svc.list_due(datetime.now(timezone.utc))
        assert any(l.escrow_uid == "e-due" for l in due)

    def test_does_not_return_future_leases(self, svc):
        svc.create(_make_lease(escrow_uid="e-future", hours_from_now=2))
        due = svc.list_due(datetime.now(timezone.utc))
        assert not any(l.escrow_uid == "e-future" for l in due)

    def test_does_not_return_released_leases(self, svc):
        past = datetime.now(timezone.utc) - timedelta(seconds=1)
        lease = svc.create(LeaseCreate(
            resource_id="r2", escrow_uid="e-released",
            vm_host="kvm1", vm_target="t2", lease_end_utc=past,
        ))
        svc.mark_released(lease.id)
        due = svc.list_due(datetime.now(timezone.utc))
        assert not any(l.escrow_uid == "e-released" for l in due)

    def test_does_not_return_pending_leases(self, svc):
        """list_due only returns active leases — pending are handled separately."""
        past = datetime.now(timezone.utc) - timedelta(seconds=1)
        future_start = datetime.now(timezone.utc) + timedelta(hours=1)
        lease = svc.create(LeaseCreate(
            resource_id="r3", escrow_uid="e-pending-expired",
            vm_host="kvm1", vm_target="t3",
            lease_start_utc=future_start,
            lease_end_utc=past,
        ))
        assert lease.status == LeaseStatus.pending.value
        due = svc.list_due(datetime.now(timezone.utc))
        assert not any(l.escrow_uid == "e-pending-expired" for l in due)


# ---------------------------------------------------------------------------
# list_pending_to_activate
# ---------------------------------------------------------------------------

class TestListPendingToActivate:
    def test_returns_pending_with_null_start(self, svc):
        """Pending lease with no start time is immediately activatable."""
        future_start = datetime.now(timezone.utc) + timedelta(hours=1)
        lease = svc.create(_make_lease(lease_start_utc=future_start))
        assert lease.status == LeaseStatus.pending.value
        # Force to pending via update (normally only happens for future start)
        svc.update(lease.id, LeaseUpdate(status=LeaseStatus.pending.value))
        # Null start: patch the lease_start_utc to None via direct update
        # (create would set it to active if None; simulate a past-start pending)
        from db.models import VmLease
        from sqlalchemy.orm import Session
        with svc._session_factory() as db:
            row = db.query(VmLease).filter(VmLease.id == lease.id).one()
            row.lease_start_utc = None
            db.commit()
        result = svc.list_pending_to_activate(datetime.now(timezone.utc))
        assert any(l.id == lease.id for l in result)

    def test_returns_pending_with_past_start(self, svc):
        past_start = datetime.now(timezone.utc) - timedelta(minutes=5)
        future_end = datetime.now(timezone.utc) + timedelta(hours=2)
        # Use a future start at creation, then update to past start
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        lease = svc.create(LeaseCreate(
            resource_id="r1", escrow_uid="e-act",
            vm_host="kvm1", vm_target="t1",
            lease_start_utc=future,
            lease_end_utc=future_end,
        ))
        assert lease.status == LeaseStatus.pending.value
        # Move start to past
        from db.models import VmLease
        with svc._session_factory() as db:
            row = db.query(VmLease).filter(VmLease.id == lease.id).one()
            row.lease_start_utc = past_start
            db.commit()
        result = svc.list_pending_to_activate(datetime.now(timezone.utc))
        assert any(l.id == lease.id for l in result)

    def test_does_not_return_pending_with_future_start(self, svc):
        future = datetime.now(timezone.utc) + timedelta(hours=2)
        lease = svc.create(_make_lease(lease_start_utc=future))
        assert lease.status == LeaseStatus.pending.value
        result = svc.list_pending_to_activate(datetime.now(timezone.utc))
        assert not any(l.id == lease.id for l in result)

    def test_does_not_return_active_leases(self, svc):
        lease = svc.create(_make_lease())
        assert lease.status == LeaseStatus.active.value
        result = svc.list_pending_to_activate(datetime.now(timezone.utc))
        assert not any(l.id == lease.id for l in result)


# ---------------------------------------------------------------------------
# Lifecycle transitions
# ---------------------------------------------------------------------------

class TestLifecycleTransitions:
    def test_advance_pending_to_active(self, svc):
        future_start = datetime.now(timezone.utc) + timedelta(hours=1)
        lease = svc.create(_make_lease(lease_start_utc=future_start))
        assert lease.status == LeaseStatus.pending.value
        updated = svc.advance_pending(lease.id)
        assert updated.status == LeaseStatus.active.value

    def test_advance_pending_noop_when_already_active(self, svc):
        lease = svc.create(_make_lease())
        assert lease.status == LeaseStatus.active.value
        updated = svc.advance_pending(lease.id)
        assert updated.status == LeaseStatus.active.value

    def test_begin_releasing_transitions_and_stores_job_id(self, svc):
        lease = svc.create(_make_lease())
        updated = svc.begin_releasing(lease.id, check_job_id="job-check-123")
        assert updated.status == LeaseStatus.releasing.value
        assert updated.check_job_id == "job-check-123"

    def test_mark_released(self, svc):
        lease = svc.create(_make_lease())
        updated = svc.mark_released(lease.id)
        assert updated.status == LeaseStatus.released.value

    def test_mark_forced(self, svc):
        lease = svc.create(_make_lease())
        updated = svc.mark_forced(lease.id)
        assert updated.status == LeaseStatus.forced.value

    def test_mark_cancelled(self, svc):
        lease = svc.create(_make_lease())
        updated = svc.mark_cancelled(lease.id)
        assert updated.status == LeaseStatus.cancelled.value

    def test_transition_raises_not_found(self, svc):
        with pytest.raises(LeaseNotFoundError):
            svc.mark_released("no-such-id")


# ---------------------------------------------------------------------------
# list_releasing
# ---------------------------------------------------------------------------

class TestListReleasing:
    def test_returns_only_releasing_leases(self, svc):
        lease = svc.create(_make_lease(escrow_uid="e-releasing"))
        svc.begin_releasing(lease.id, check_job_id="j1")
        svc.create(_make_lease(escrow_uid="e-active"))  # should not appear

        result = svc.list_releasing()
        assert len(result) == 1
        assert result[0].escrow_uid == "e-releasing"
        assert result[0].status == LeaseStatus.releasing.value


# ---------------------------------------------------------------------------
# update (partial write)
# ---------------------------------------------------------------------------

class TestUpdate:
    def test_update_status(self, svc):
        lease = svc.create(_make_lease())
        updated = svc.update(lease.id, LeaseUpdate(status=LeaseStatus.cancelled.value))
        assert updated.status == LeaseStatus.cancelled.value

    def test_update_check_job_id(self, svc):
        lease = svc.create(_make_lease())
        updated = svc.update(lease.id, LeaseUpdate(check_job_id="job-xyz"))
        assert updated.check_job_id == "job-xyz"

    def test_update_ignores_none_fields(self, svc):
        lease = svc.create(_make_lease())
        original_status = lease.status
        updated = svc.update(lease.id, LeaseUpdate(check_job_id="j1"))
        assert updated.status == original_status

    def test_update_raises_not_found(self, svc):
        with pytest.raises(LeaseNotFoundError):
            svc.update("no-such-id", LeaseUpdate(status="cancelled"))
