"""CRUD service for the vm_leases table.

LeaseService owns all direct DB access for leases. The LeaseWatchdog and
the system controller's check-leases endpoint both call this service; neither
touches the DB directly.

Lifecycle transitions:
  pending  → active    advance_pending()      — lease_start_utc has passed / is None
  active   → releasing begin_releasing()      — lease_end_utc passed, check job submitted
  releasing→ released  mark_released()        — check confirmed VM gone; storefront patched
  releasing→ forced    mark_forced()          — grace period elapsed; storefront patched anyway
  *        → cancelled mark_cancelled()       — explicit pre-expiry cancellation

All mutation methods use the pattern: fetch-within-session, mutate, commit,
expunge, re-fetch for return — matching HostService exactly.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session, sessionmaker

from db.models import LeaseStatus, VmLease
from models.lease_model import LeaseCreate, LeaseUpdate

logger = logging.getLogger(__name__)


class LeaseNotFoundError(Exception):
    """Raised when a requested lease does not exist in the DB."""


class LeaseConflictError(Exception):
    """Raised when a lease with the given escrow_uid already exists."""


class LeaseService:
    """CRUD operations and lifecycle helpers for the ``vm_leases`` table."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def list_leases(
        self,
        status: Optional[str] = None,
        vm_host: Optional[str] = None,
        escrow_uid: Optional[str] = None,
    ) -> list[VmLease]:
        """Return leases from the DB, optionally filtered."""
        with self._session_factory() as db:
            q = db.query(VmLease)
            if status is not None:
                q = q.filter(VmLease.status == status)
            if vm_host is not None:
                q = q.filter(VmLease.vm_host == vm_host)
            if escrow_uid is not None:
                q = q.filter(VmLease.escrow_uid == escrow_uid)
            leases = q.order_by(VmLease.created_at.desc()).all()
            for lease in leases:
                db.expunge(lease)
            return leases

    def get_lease(self, lease_id: str) -> VmLease:
        """Return the lease row for *lease_id*.

        Raises:
            LeaseNotFoundError: If no lease with this id exists.
        """
        with self._session_factory() as db:
            lease = db.query(VmLease).filter(VmLease.id == lease_id).one_or_none()
            if lease is None:
                raise LeaseNotFoundError(f"Lease '{lease_id}' not found")
            db.expunge(lease)
            return lease

    def get_lease_by_escrow(self, escrow_uid: str) -> Optional[VmLease]:
        """Return the lease for *escrow_uid*, or None if not found."""
        with self._session_factory() as db:
            lease = (
                db.query(VmLease)
                .filter(VmLease.escrow_uid == escrow_uid)
                .one_or_none()
            )
            if lease is not None:
                db.expunge(lease)
            return lease

    def list_pending_to_activate(self, now: datetime) -> list[VmLease]:
        """Return leases that should transition pending → active.

        These are leases with status='pending' whose lease_start_utc has passed
        (or is None). Processed by the watchdog before the expiry check so
        newly-active leases are caught in the same cycle.
        """
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        with self._session_factory() as db:
            leases = (
                db.query(VmLease)
                .filter(
                    VmLease.status == LeaseStatus.pending.value,
                    (VmLease.lease_start_utc == None) |  # noqa: E711
                    (VmLease.lease_start_utc <= now),
                )
                .all()
            )
            for lease in leases:
                db.expunge(lease)
            return leases

    def list_due(self, now: datetime) -> list[VmLease]:
        """Return active leases whose lease_end_utc has passed.

        The watchdog calls this after advance_pending() to find leases
        that need cleanup. Only 'active' status — pending leases are handled
        separately by list_pending_to_activate().
        """
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        with self._session_factory() as db:
            leases = (
                db.query(VmLease)
                .filter(
                    VmLease.lease_end_utc <= now,
                    VmLease.status == LeaseStatus.active.value,
                )
                .order_by(VmLease.lease_end_utc.asc())
                .all()
            )
            for lease in leases:
                db.expunge(lease)
            return leases

    def list_releasing(self) -> list[VmLease]:
        """Return leases in 'releasing' status (check job in progress).

        The watchdog processes these to poll job completion and patch the
        storefront when the check job succeeds.
        """
        with self._session_factory() as db:
            leases = (
                db.query(VmLease)
                .filter(VmLease.status == LeaseStatus.releasing.value)
                .all()
            )
            for lease in leases:
                db.expunge(lease)
            return leases

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def create(self, data: LeaseCreate) -> VmLease:
        """Insert a new lease row.

        The initial status is 'active' when lease_start_utc is None or in the
        past, and 'pending' when lease_start_utc is in the future.

        Raises:
            LeaseConflictError: If a lease with the given escrow_uid already exists.
        """
        existing = self.get_lease_by_escrow(data.escrow_uid)
        if existing is not None:
            raise LeaseConflictError(
                f"Lease for escrow_uid '{data.escrow_uid}' already exists "
                f"(id={existing.id})"
            )

        now = datetime.now(timezone.utc)
        if data.lease_start_utc is None or data.lease_start_utc <= now:
            initial_status = LeaseStatus.active.value
        else:
            initial_status = LeaseStatus.pending.value

        lease = VmLease(
            resource_id=data.resource_id,
            escrow_uid=data.escrow_uid,
            vm_host=data.vm_host,
            vm_target=data.vm_target,
            lease_start_utc=data.lease_start_utc,
            lease_end_utc=data.lease_end_utc,
            status=initial_status,
            create_job_id=data.create_job_id,
        )
        with self._session_factory() as db:
            db.add(lease)
            db.commit()
            lease_id = lease.id

        logger.info(
            "[LEASE] Created lease %s for resource=%s escrow=%s status=%s",
            lease_id, data.resource_id, data.escrow_uid, initial_status,
        )
        return self.get_lease(lease_id)

    def update(self, lease_id: str, data: LeaseUpdate) -> VmLease:
        """Apply a partial update to a lease row.

        Only non-None fields in *data* are written.
        """
        with self._session_factory() as db:
            lease = self._require(db, lease_id)
            if data.status is not None:
                lease.status = data.status
            if data.check_job_id is not None:
                lease.check_job_id = data.check_job_id
            if data.lease_end_utc is not None:
                lease.lease_end_utc = data.lease_end_utc
            db.commit()
        return self.get_lease(lease_id)

    def advance_pending(self, lease_id: str) -> VmLease:
        """Transition a 'pending' lease to 'active'.

        No-op (returns current state) if the lease is already active.
        """
        with self._session_factory() as db:
            lease = self._require(db, lease_id)
            if lease.status == LeaseStatus.pending.value:
                lease.status = LeaseStatus.active.value
                db.commit()
                logger.info("[LEASE] %s: pending → active", lease_id)
        return self.get_lease(lease_id)

    def begin_releasing(self, lease_id: str, check_job_id: str) -> VmLease:
        """Transition an 'active' lease to 'releasing' and record the check job.

        Called by the watchdog when lease_end_utc has passed and a check
        Ansible job has been submitted to confirm VM cleanup.
        """
        with self._session_factory() as db:
            lease = self._require(db, lease_id)
            lease.status = LeaseStatus.releasing.value
            lease.check_job_id = check_job_id
            db.commit()
        logger.info(
            "[LEASE] %s: active → releasing (check_job=%s)", lease_id, check_job_id
        )
        return self.get_lease(lease_id)

    def mark_released(self, lease_id: str) -> VmLease:
        """Transition a lease to 'released' after storefront resource has been patched."""
        with self._session_factory() as db:
            lease = self._require(db, lease_id)
            lease.status = LeaseStatus.released.value
            db.commit()
        logger.info("[LEASE] %s: → released", lease_id)
        return self.get_lease(lease_id)

    def mark_forced(self, lease_id: str) -> VmLease:
        """Transition a lease to 'forced' after grace period elapsed."""
        with self._session_factory() as db:
            lease = self._require(db, lease_id)
            lease.status = LeaseStatus.forced.value
            db.commit()
        logger.warning("[LEASE] %s: → forced (grace period elapsed)", lease_id)
        return self.get_lease(lease_id)

    def mark_cancelled(self, lease_id: str) -> VmLease:
        """Transition a lease to 'cancelled' before it expires."""
        with self._session_factory() as db:
            lease = self._require(db, lease_id)
            lease.status = LeaseStatus.cancelled.value
            db.commit()
        logger.info("[LEASE] %s: → cancelled", lease_id)
        return self.get_lease(lease_id)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _require(self, db: Session, lease_id: str) -> VmLease:
        lease = db.query(VmLease).filter(VmLease.id == lease_id).one_or_none()
        if lease is None:
            raise LeaseNotFoundError(f"Lease '{lease_id}' not found")
        return lease
