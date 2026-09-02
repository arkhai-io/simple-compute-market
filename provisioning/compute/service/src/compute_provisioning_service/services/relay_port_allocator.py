"""Allocation and reclamation of remote ports on a relay.

A remote port binds a listening socket on the relay itself, so the port
namespace belongs to the relay rather than to a host or a pool. Two hosts
dialing one relay are not independent: if one holds ``R:6100`` the other cannot
also hold it. The relay would refuse the second registration, and the refusal
arrives asynchronously in a tunnel client's log rather than as a failed
allocation — the coordination failure that taking the relay's dashboard out of
this path set out to remove.

Allocation happens before the job is dispatched. Allocating afterwards would
mean a crash between the two leaves a port bound on the relay that no record
claims. The cost of allocating first is that a lease outlives any path that
fails before a teardown would run, which is why release is attached to every
terminal outcome and why reconciliation exists beneath it.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from compute_provisioning_service.db.models import Relay, RelayPortLease

logger = logging.getLogger(__name__)


class RelayWindowExhaustedError(RuntimeError):
    """Every port in a relay's configured window is currently leased."""


@dataclass(frozen=True)
class PortLease:
    id: str
    relay_id: str
    remote_port: int


class RelayPortAllocator:
    def __init__(self, session_factory: Any) -> None:
        self._session_factory = session_factory

    def allocate(
        self,
        *,
        relay_id: str,
        owner_kind: str,
        owner_id: str,
        host_name: str | None = None,
        pool_id: str | None = None,
    ) -> PortLease:
        """Lease the lowest free port in the relay's window.

        Lowest-free rather than next-after-last so that a released port is
        reused promptly: the window is finite, and a strategy that always moves
        forward turns a slow leak into an outage sooner.

        The unique constraint is the arbiter, not the read that precedes it.
        Two allocations racing on one relay both see the same free port; the
        second commit fails and retries against a set that now excludes it,
        which is correct without a lock held across the whole window scan.
        """
        with self._session_factory() as db:
            relay = db.get(Relay, relay_id)
            if relay is None:
                raise RelayWindowExhaustedError(
                    f"relay '{relay_id}' does not exist, so no port can be leased on it"
                )
            window = range(
                relay.vm_port_range_start,
                relay.vm_port_range_start + relay.vm_port_range_count,
            )
            # Bounded by the window size: a full window fails after trying every
            # port once rather than spinning.
            for _ in range(relay.vm_port_range_count):
                port = self._lowest_free(db, relay_id, window)
                lease = self._claim(
                    db,
                    relay_id=relay_id,
                    port=port,
                    owner_kind=owner_kind,
                    owner_id=owner_id,
                    host_name=host_name,
                    pool_id=pool_id,
                )
                try:
                    db.commit()
                except IntegrityError:
                    db.rollback()
                    continue
                return PortLease(id=lease.id, relay_id=relay_id, remote_port=port)
            raise self._exhausted(relay)

    @staticmethod
    def _claim(
        db: Session,
        *,
        relay_id: str,
        port: int,
        owner_kind: str,
        owner_id: str,
        host_name: str | None,
        pool_id: str | None,
    ) -> RelayPortLease:
        """Take the row for this port, reusing a released one if it exists.

        Uniqueness is ``(relay_id, remote_port)`` unconditionally, so a
        released lease still occupies its port in the index. Reclaiming the row
        rather than inserting a second one is what lets a released port be
        reissued while that constraint stays exactly as strict as it reads.

        The alternative — a partial index excluding released rows — would keep
        per-lease history, at the cost of a constraint whose meaning depends on
        a column and which the lease tests could no longer state simply. The
        table is then bounded by relays multiplied by window size rather than
        growing with VM churn, which is the better trade for a record whose
        purpose is answering "what is bound on this relay right now".
        """
        existing = (
            db.query(RelayPortLease)
            .filter(
                RelayPortLease.relay_id == relay_id,
                RelayPortLease.remote_port == port,
            )
            .one_or_none()
        )
        if existing is not None:
            existing.owner_kind = owner_kind
            existing.owner_id = owner_id
            existing.host_name = host_name
            existing.pool_id = pool_id
            existing.released_at = None
            existing.created_at = datetime.now(timezone.utc).replace(tzinfo=None)
            return existing
        lease = RelayPortLease(
            id=str(uuid.uuid4()),
            relay_id=relay_id,
            remote_port=port,
            host_name=host_name,
            pool_id=pool_id,
            owner_kind=owner_kind,
            owner_id=owner_id,
        )
        db.add(lease)
        return lease

    def release(self, *, owner_kind: str, owner_id: str) -> int:
        """Release every lease held by one owner. Returns how many were released.

        Idempotent, and safe to call on a path that may already have released:
        every terminal outcome of a VM's life calls this, and a set of code
        paths is never provably exhaustive, so the ones that overlap must not
        fail each other.
        """
        with self._session_factory() as db, db.begin():
            held = (
                db.query(RelayPortLease)
                .filter(
                    RelayPortLease.owner_kind == owner_kind,
                    RelayPortLease.owner_id == owner_id,
                    RelayPortLease.released_at.is_(None),
                )
                .all()
            )
            now = datetime.now(timezone.utc)
            for lease in held:
                lease.released_at = now
            return len(held)

    def reconcile(
        self,
        *,
        is_owner_terminal: Any,
        grace: timedelta = timedelta(hours=1),
    ) -> int:
        """Release leases whose owner has been terminal beyond a grace period.

        Release is attached to every terminal outcome, and that is still not
        sufficient on its own: a set of code paths is never provably
        exhaustive, and the one that is missed is the one nobody thought of.
        This converts an unenumerated leak into a bounded one.

        ``is_owner_terminal`` is supplied by the caller rather than queried
        here, because what makes a job or a fulfillment terminal belongs to
        those subsystems and not to port accounting.
        """
        cutoff = datetime.now(timezone.utc) - grace
        released = 0
        with self._session_factory() as db, db.begin():
            candidates: Iterable[RelayPortLease] = (
                db.query(RelayPortLease)
                .filter(
                    RelayPortLease.released_at.is_(None),
                    RelayPortLease.created_at < cutoff.replace(tzinfo=None),
                )
                .all()
            )
            now = datetime.now(timezone.utc)
            for lease in candidates:
                if not is_owner_terminal(lease.owner_kind, lease.owner_id):
                    continue
                lease.released_at = now
                released += 1
                logger.warning(
                    "Reconciliation released relay port %s:%d held by %s %s — "
                    "a release path was missed",
                    lease.relay_id,
                    lease.remote_port,
                    lease.owner_kind,
                    lease.owner_id,
                )
        return released

    def held_ports(self, relay_id: str) -> list[int]:
        with self._session_factory() as db:
            return sorted(
                row.remote_port
                for row in db.query(RelayPortLease)
                .filter(
                    RelayPortLease.relay_id == relay_id,
                    RelayPortLease.released_at.is_(None),
                )
                .all()
            )

    @staticmethod
    def _lowest_free(db: Session, relay_id: str, window: range) -> int:
        held = {
            row.remote_port
            for row in db.query(RelayPortLease)
            .filter(
                RelayPortLease.relay_id == relay_id,
                RelayPortLease.released_at.is_(None),
            )
            .all()
        }
        for port in window:
            if port not in held:
                return port
        raise RelayWindowExhaustedError(
            f"relay '{relay_id}' has no free port in {window.start}-{window.stop - 1}"
        )

    @staticmethod
    def _exhausted(relay: Relay) -> RelayWindowExhaustedError:
        last = relay.vm_port_range_start + relay.vm_port_range_count - 1
        return RelayWindowExhaustedError(
            f"relay '{relay.id}' ({relay.relay_addr}:{relay.relay_port}) has no free "
            f"port in its configured window {relay.vm_port_range_start}-{last}"
        )

    @staticmethod
    def count_held(db: Session, relay_id: str) -> int:
        return (
            db.query(func.count(RelayPortLease.id))
            .filter(
                RelayPortLease.relay_id == relay_id,
                RelayPortLease.released_at.is_(None),
            )
            .scalar()
            or 0
        )
