"""Site-authority capacity ledger.

The authoritative resource ledger for this site
(docs/development/design-settlement-lifecycle-and-capacity.md, Part II):
unit-counted resources, allocation holds with their lease tail, and the
anonymous versioned capacity-event feed. Storefronts reach it through
the ``/api/v1/capacity`` HTTP surface, which mirrors the
``core_storefront.capacity.CapacityClient`` contract verb for verb.

Matching semantics deliberately mirror the storefront's embedded ledger
(``reserve_available_compute_vm``): a claim is an exact-match attribute
mapping plus a ``gpu_count`` unit request, checked first against the
resource's attributes JSON and then against its top-level fields, and a
resource is eligible only when its attributes name a ``vm_host``. The
remote client must behave byte-for-byte like the embedded adapter it
replaces — the move is a move, not a behavior change.

Mutations serialize on a process-level lock: the site authority is the
serialization point for reserves across storefronts, and that point is
exactly one process per site (SQLite is single-writer anyway). Every
mutation appends a ``CapacityEvent`` row in the same transaction, so the
feed is always consistent with a snapshot.
"""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional

from sqlalchemy.orm import Session, sessionmaker

from db.models import (
    HELD_ALLOCATION_STATES,
    AllocationState,
    CapacityEvent,
    SiteAllocation,
    SiteResource,
)

logger = logging.getLogger(__name__)


class CapacityConflictError(Exception):
    """Raised when a mutation references a row in an incompatible state."""


def _parse_utc(value: str | None) -> Optional[datetime]:
    """Tolerantly parse the ISO-ish timestamp strings the ledger stores.

    Accepts ``YYYY-MM-DD HH:MM[:SS]`` (the storefront's lease format) and
    full ISO-8601 with or without timezone; naive values are taken as UTC.
    """
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    for candidate in (text, text.replace(" ", "T", 1)):
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    return None


def _requested_units(claim: Mapping[str, Any] | None) -> int:
    raw = (claim or {}).get("gpu_count")
    if raw is None:
        return 1
    try:
        requested = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"gpu_count must be an integer, got {raw!r}") from exc
    if requested < 1:
        raise ValueError(f"gpu_count must be >= 1, got {requested}")
    return requested


def _resource_matches(
    resource: SiteResource, claim: Mapping[str, Any] | None
) -> bool:
    if not claim:
        return True
    attrs = resource.attributes or {}
    top_level = {
        "resource_id": resource.resource_id,
        # Pools are an aggregator (storefront) concept; the degenerate
        # single-resource pool is keyed by the resource_id, which is what
        # claims carry for un-pooled inventory.
        "pool_id": resource.resource_id,
        "resource_type": resource.resource_type,
        "resource_subtype": resource.resource_subtype,
        "value": resource.total_units,
        "gpu_count": resource.total_units,
    }
    for key, expected in claim.items():
        if key == "gpu_count":
            continue
        actual = attrs.get(key, top_level.get(key))
        if actual != expected:
            return False
    return True


class CapacityLedgerService:
    """Authoritative capacity operations over the site ledger tables."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory
        self._write_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Resource registry
    # ------------------------------------------------------------------

    def register_resource(
        self,
        *,
        resource_id: str,
        total_units: int,
        resource_type: str = "compute.gpu",
        resource_subtype: str | None = None,
        attributes: Mapping[str, Any] | None = None,
        enabled: bool = True,
    ) -> dict[str, Any]:
        """Insert or update a ledger resource; emits a delta on change.

        An upsert that changes capacity (units, enablement) emits a
        "released" or "reserved"-equivalent availability change; we use
        "released" for grows/registrations and "reserved" for shrinks so
        subscribers reconcile in the right direction without a new kind.
        """
        with self._write_lock, self._session_factory() as db:
            row = db.get(SiteResource, resource_id)
            grew = True
            if row is None:
                row = SiteResource(
                    resource_id=resource_id,
                    resource_type=resource_type,
                    resource_subtype=resource_subtype,
                    total_units=int(total_units),
                    attributes=dict(attributes or {}),
                    enabled=enabled,
                )
                db.add(row)
            else:
                grew = (int(total_units), enabled) >= (int(row.total_units), bool(row.enabled))
                row.resource_type = resource_type
                row.resource_subtype = resource_subtype
                row.total_units = int(total_units)
                row.attributes = dict(attributes or {})
                row.enabled = enabled
            db.add(CapacityEvent(
                kind="released" if grew else "reserved",
                resource_id=resource_id,
            ))
            db.commit()
            return self._resource_payload(db, db.get(SiteResource, resource_id))

    def list_resources(self) -> list[dict[str, Any]]:
        with self._session_factory() as db:
            self._expire_stale_holds(db)
            rows = (
                db.query(SiteResource)
                .order_by(SiteResource.updated_at.asc())
                .all()
            )
            return [self._resource_payload(db, row) for row in rows]

    # ------------------------------------------------------------------
    # CapacityClient verbs
    # ------------------------------------------------------------------

    def snapshot(self) -> list[dict[str, Any]]:
        """Advisory availability view (enabled resources only)."""
        return [r for r in self.list_resources() if r.get("enabled")]

    def probe(self, *, claim: Mapping[str, Any] | None = None) -> dict[str, Any] | None:
        """Dry-run match for ``claim`` — consumes nothing."""
        requested = _requested_units(claim)
        with self._session_factory() as db:
            self._expire_stale_holds(db)
            match = self._find_candidate(db, claim, requested)
            if match is None:
                return None
            resource, available = match
            return self._match_payload(resource, available, requested)

    def reserve(
        self,
        *,
        claim: Mapping[str, Any] | None = None,
        deal_ref: Mapping[str, Any] | None = None,
        ttl_seconds: float | None = None,
    ) -> dict[str, Any] | None:
        """Atomically check-and-reserve capacity matching ``claim``."""
        requested = _requested_units(claim)
        deal = dict(deal_ref or {})
        with self._write_lock, self._session_factory() as db:
            self._expire_stale_holds(db)
            match = self._find_candidate(db, claim, requested)
            if match is None:
                return None
            resource, available = match
            hold_expires_at = None
            if ttl_seconds is not None:
                hold_expires_at = (
                    datetime.now(timezone.utc) + timedelta(seconds=float(ttl_seconds))
                ).isoformat()
            allocation = SiteAllocation(
                allocation_id=str(uuid.uuid4()),
                resource_id=resource.resource_id,
                units=requested,
                state=AllocationState.reserved.value,
                deal_ref=deal,
                escrow_uid=deal.get("escrow_uid"),
                hold_expires_at=hold_expires_at,
                vm_host=(resource.attributes or {}).get("vm_host"),
            )
            db.add(allocation)
            db.add(CapacityEvent(kind="reserved", resource_id=resource.resource_id))
            db.commit()
            payload = self._match_payload(resource, available - requested, requested)
            payload["allocation_id"] = allocation.allocation_id
            payload["hold_expires_at"] = hold_expires_at
            return payload

    def commit(
        self,
        *,
        resource_id: str,
        allocation_id: str | None = None,
        lease_end_utc: str,
        idempotency_ref: str | None = None,
    ) -> dict[str, Any] | None:
        """Confirm a reservation into an active lease.

        Idempotent: committing an already-leased allocation refreshes the
        lease end and clears any TTL hold.
        """
        with self._write_lock, self._session_factory() as db:
            allocation = self._find_allocation(
                db, allocation_id=allocation_id,
                resource_id=None if allocation_id else resource_id,
            )
            if allocation is None:
                return None
            if allocation.state not in HELD_ALLOCATION_STATES:
                raise CapacityConflictError(
                    f"allocation {allocation.allocation_id} is "
                    f"{allocation.state}; cannot commit"
                )
            allocation.state = AllocationState.leased.value
            allocation.lease_end_utc = str(lease_end_utc)
            allocation.hold_expires_at = None
            if not allocation.lease_start_utc:
                allocation.lease_start_utc = datetime.now(timezone.utc).isoformat()
            db.add(CapacityEvent(kind="committed", resource_id=allocation.resource_id))
            db.commit()
            return self._allocation_payload(allocation)

    def release(
        self,
        *,
        allocation_id: str | None = None,
        deal_ref: Mapping[str, Any] | None = None,
        state: str = AllocationState.released.value,
        failure_reason: str | None = None,
        failure_message: str | None = None,
    ) -> dict[str, Any] | None:
        """Return a held/leased allocation's capacity to the pool."""
        escrow_uid = dict(deal_ref or {}).get("escrow_uid")
        with self._write_lock, self._session_factory() as db:
            allocation = self._find_allocation(
                db, allocation_id=allocation_id,
                escrow_uid=None if allocation_id else escrow_uid,
            )
            if allocation is None or allocation.state not in HELD_ALLOCATION_STATES:
                return None
            allocation.state = state
            allocation.released_at = datetime.now(timezone.utc).isoformat()
            allocation.failure_reason = failure_reason
            allocation.failure_message = failure_message
            db.add(CapacityEvent(kind="released", resource_id=allocation.resource_id))
            db.commit()
            return self._allocation_payload(allocation)

    def truncate_lease(
        self,
        *,
        allocation_id: str,
        lease_end_utc: str,
    ) -> dict[str, Any] | None:
        """End a lease early; teardown stays with the ledger's watchdog."""
        with self._write_lock, self._session_factory() as db:
            allocation = self._find_allocation(db, allocation_id=allocation_id)
            if allocation is None or allocation.state not in HELD_ALLOCATION_STATES:
                return None
            allocation.state = AllocationState.leased.value
            allocation.lease_end_utc = str(lease_end_utc)
            db.add(CapacityEvent(
                kind="lease_truncated", resource_id=allocation.resource_id,
            ))
            db.commit()
            return self._allocation_payload(allocation)

    # ------------------------------------------------------------------
    # Lease tail (the merged vm_leases half of the allocation row)
    # ------------------------------------------------------------------

    def attach_lease(
        self,
        *,
        allocation_id: str | None = None,
        escrow_uid: str | None = None,
        vm_host: str | None = None,
        vm_target: str | None = None,
        lease_start_utc: str | None = None,
        lease_end_utc: str | None = None,
        create_job_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Record the lease tail on an existing held allocation.

        The ledger-mode replacement for registering a ``vm_leases`` row:
        the allocation and its lease are one record, so the watchdog
        tears down and releases in one local transaction. Emits no
        capacity event — availability already moved at commit time.
        Returns None when no held allocation matches (the caller falls
        back to the legacy lease table).
        """
        with self._write_lock, self._session_factory() as db:
            allocation = self._find_allocation(
                db, allocation_id=allocation_id,
                escrow_uid=None if allocation_id else escrow_uid,
            )
            if allocation is None or allocation.state not in HELD_ALLOCATION_STATES:
                return None
            if vm_host:
                allocation.vm_host = vm_host
            if vm_target:
                allocation.vm_target = vm_target
            if lease_start_utc:
                allocation.lease_start_utc = str(lease_start_utc)
            if lease_end_utc:
                allocation.lease_end_utc = str(lease_end_utc)
            if create_job_id:
                allocation.create_job_id = create_job_id
            if escrow_uid and not allocation.escrow_uid:
                allocation.escrow_uid = escrow_uid
            allocation.state = AllocationState.leased.value
            db.commit()
            return self._allocation_payload(allocation)

    def list_lease_due(self, now: datetime) -> list[dict[str, Any]]:
        """Leased allocations whose lease_end_utc has passed."""
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        due: list[dict[str, Any]] = []
        with self._session_factory() as db:
            rows = (
                db.query(SiteAllocation)
                .filter(
                    SiteAllocation.state == AllocationState.leased.value,
                    SiteAllocation.lease_end_utc.isnot(None),
                )
                .all()
            )
            for allocation in rows:
                lease_end = _parse_utc(allocation.lease_end_utc)
                if lease_end is not None and lease_end <= now:
                    due.append(self._allocation_payload(allocation))
        return due

    def begin_releasing(
        self, allocation_id: str, *, check_job_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Transition a leased allocation to releasing (teardown in flight).

        No capacity event: releasing still holds the units — the workload
        may not be torn down yet.
        """
        with self._write_lock, self._session_factory() as db:
            allocation = db.get(SiteAllocation, allocation_id)
            if allocation is None or allocation.state not in HELD_ALLOCATION_STATES:
                return None
            allocation.state = AllocationState.releasing.value
            allocation.check_job_id = check_job_id
            db.commit()
            return self._allocation_payload(allocation)

    # ------------------------------------------------------------------
    # Event feed
    # ------------------------------------------------------------------

    def events_after(
        self, after_version: int, *, limit: int = 500
    ) -> tuple[list[dict[str, Any]], int]:
        """Return (events newer than ``after_version``, latest version).

        The latest version is reported even when ``limit`` truncates the
        page, so pollers know to keep paging; a subscriber that finds a
        gap versus what it last applied resyncs from a snapshot.
        """
        with self._session_factory() as db:
            rows = (
                db.query(CapacityEvent)
                .filter(CapacityEvent.version > int(after_version))
                .order_by(CapacityEvent.version.asc())
                .limit(int(limit))
                .all()
            )
            latest = (
                db.query(CapacityEvent.version)
                .order_by(CapacityEvent.version.desc())
                .limit(1)
                .scalar()
            ) or 0
            events = [
                {
                    "version": row.version,
                    "kind": row.kind,
                    "resource_id": row.resource_id,
                    "occurred_at": (
                        row.occurred_at.isoformat() if row.occurred_at else None
                    ),
                }
                for row in rows
            ]
            return events, int(latest)

    # ------------------------------------------------------------------
    # Allocation queries (watchdog / deal-event plumbing)
    # ------------------------------------------------------------------

    def get_allocation(self, allocation_id: str) -> dict[str, Any] | None:
        with self._session_factory() as db:
            allocation = db.get(SiteAllocation, allocation_id)
            return self._allocation_payload(allocation) if allocation else None

    def get_allocation_by_escrow(self, escrow_uid: str) -> dict[str, Any] | None:
        with self._session_factory() as db:
            allocation = self._find_allocation(db, escrow_uid=escrow_uid)
            return self._allocation_payload(allocation) if allocation else None

    def list_allocations(
        self, *, state: str | None = None
    ) -> list[dict[str, Any]]:
        with self._session_factory() as db:
            q = db.query(SiteAllocation)
            if state is not None:
                q = q.filter(SiteAllocation.state == state)
            rows = q.order_by(SiteAllocation.created_at.asc()).all()
            return [self._allocation_payload(row) for row in rows]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _expire_stale_holds(self, db: Session) -> None:
        """Lapse TTL'd reservations whose hold expired without a commit.

        Runs lazily ahead of reads and reserves so expired holds never
        block capacity; each lapse emits a "released" event in the same
        transaction.
        """
        now = datetime.now(timezone.utc)
        stale = (
            db.query(SiteAllocation)
            .filter(
                SiteAllocation.state == AllocationState.reserved.value,
                SiteAllocation.hold_expires_at.isnot(None),
            )
            .all()
        )
        lapsed = False
        for allocation in stale:
            expires = _parse_utc(allocation.hold_expires_at)
            if expires is None or expires > now:
                continue
            allocation.state = AllocationState.released.value
            allocation.released_at = now.isoformat()
            allocation.failure_reason = "hold_expired"
            db.add(CapacityEvent(
                kind="released", resource_id=allocation.resource_id,
            ))
            lapsed = True
            logger.info(
                "[CAPACITY] TTL hold expired for allocation %s (resource=%s)",
                allocation.allocation_id, allocation.resource_id,
            )
        if lapsed:
            db.commit()

    def _held_units(self, db: Session, resource_id: str) -> int:
        rows = (
            db.query(SiteAllocation)
            .filter(
                SiteAllocation.resource_id == resource_id,
                SiteAllocation.state.in_(HELD_ALLOCATION_STATES),
            )
            .all()
        )
        return sum(int(row.units or 0) for row in rows)

    def _find_candidate(
        self,
        db: Session,
        claim: Mapping[str, Any] | None,
        requested: int,
    ) -> tuple[SiteResource, int] | None:
        rows = (
            db.query(SiteResource)
            .filter(SiteResource.enabled.is_(True))
            .order_by(SiteResource.updated_at.asc())
            .all()
        )
        for resource in rows:
            if not _resource_matches(resource, claim):
                continue
            vm_host = (resource.attributes or {}).get("vm_host")
            if not isinstance(vm_host, str) or not vm_host.strip():
                continue
            available = int(resource.total_units or 0) - self._held_units(
                db, resource.resource_id
            )
            if available < requested:
                continue
            return resource, available
        return None

    def _find_allocation(
        self,
        db: Session,
        *,
        allocation_id: str | None = None,
        escrow_uid: str | None = None,
        resource_id: str | None = None,
    ) -> SiteAllocation | None:
        if allocation_id:
            return db.get(SiteAllocation, allocation_id)
        q = db.query(SiteAllocation).filter(
            SiteAllocation.state.in_(HELD_ALLOCATION_STATES)
        )
        if escrow_uid:
            q = q.filter(SiteAllocation.escrow_uid == escrow_uid)
        elif resource_id:
            q = q.filter(SiteAllocation.resource_id == resource_id)
        else:
            return None
        return q.order_by(SiteAllocation.created_at.desc()).first()

    def _resource_payload(self, db: Session, row: SiteResource) -> dict[str, Any]:
        held = self._held_units(db, row.resource_id)
        total = int(row.total_units or 0)
        available = max(total - held, 0)
        if available >= total or held <= 0:
            state = "available"
        elif available > 0:
            state = "available"
        else:
            state = "leased"
        return {
            "resource_id": row.resource_id,
            "resource_type": row.resource_type,
            "resource_subtype": row.resource_subtype,
            "unit": "count",
            "value": total,
            "state": state,
            "available_units": available,
            "attributes": dict(row.attributes or {}),
            "enabled": bool(row.enabled),
        }

    @staticmethod
    def _match_payload(
        resource: SiteResource, available: int, requested: int
    ) -> dict[str, Any]:
        """Shape a probe/reserve result like the embedded adapter's.

        pool/member are storefront (aggregator) concepts the site does not
        know; they are present-and-None for payload compatibility.
        """
        attrs = dict(resource.attributes or {})
        return {
            "resource_id": resource.resource_id,
            "pool_id": None,
            "member_id": None,
            "vm_host": attrs.get("vm_host"),
            "resource_subtype": resource.resource_subtype,
            "unit": "count",
            "state": "available",
            "value": int(resource.total_units or 0),
            "allocated_gpu_count": requested,
            "available_gpu_count": available,
            "attributes": attrs,
        }

    @staticmethod
    def _allocation_payload(allocation: SiteAllocation) -> dict[str, Any]:
        return {
            "allocation_id": allocation.allocation_id,
            "resource_id": allocation.resource_id,
            "pool_id": None,
            "units": int(allocation.units or 0),
            "allocated_gpu_count": int(allocation.units or 0),
            "state": allocation.state,
            "deal_ref": dict(allocation.deal_ref or {}),
            "escrow_uid": allocation.escrow_uid,
            "hold_expires_at": allocation.hold_expires_at,
            "vm_host": allocation.vm_host,
            "vm_target": allocation.vm_target,
            "lease_start_utc": allocation.lease_start_utc,
            "lease_end_utc": allocation.lease_end_utc,
            "create_job_id": allocation.create_job_id,
            "check_job_id": allocation.check_job_id,
            "failure_reason": allocation.failure_reason,
            "released_at": allocation.released_at,
        }
