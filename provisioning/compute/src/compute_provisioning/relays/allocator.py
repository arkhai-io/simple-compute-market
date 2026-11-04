"""Allocation and reclamation of remote ports on a relay.

A remote port binds a listening socket on the relay itself, so the port
namespace belongs to the relay rather than to a host or a pool. Two hosts
dialing one relay are not independent: if one holds ``R:6100`` the other cannot
also hold it. The relay would refuse the second registration, and the refusal
arrives asynchronously in a tunnel client's log rather than as a failed
allocation.

Allocation happens before the job is dispatched. Allocating afterwards would
mean a crash between the two leaves a port bound on the relay that no record
claims. The cost of allocating first is that a lease outlives any path that
fails before a teardown would run, which is why the lease is returned with its
reservation's capacity, whatever path releases it, and why reconciliation
exists beneath that.

One allocator serves every domain: pools on one relay draw from its one window,
whatever their provider, so two allocators over that namespace would issue one
port twice.

Each lease records when the grants for it expire, and a released port is not
reissued until that expiry plus a reuse margin has passed. A relay admits a
proxy carrying an unexpired grant for its port, so a grant copied from a host
whose lease ended could otherwise register the port another host now holds.
The margin covers the relay's clock running behind the service's, since the
relay checks expiry on its own clock with no leeway.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from market_fulfillment.settlement_repository import begin_sqlite_write_transaction
from market_site.db import CapacityReservation
from market_site.ledger import parse_utc
from sqlalchemy import and_, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..release_effects import reservation_is_released
from .db import Relay, RelayPortLease

logger = logging.getLogger(__name__)

#: How long a lease's grants outlive its scheduled end, by default: the lease
#: watchdog's grace period (300 seconds by default) and a teardown job's
#: retries (three by default, backing off 60, 120, and 240 seconds) with their
#: runs, so a grant never expires while the teardown that revokes it is still
#: due. The service's ``relay_grant_expiry_grace_seconds`` sets it.
DEFAULT_GRANT_EXPIRY_GRACE = timedelta(hours=1)

#: How long a released port is held past its grant's expiry, by default. The
#: service's ``relay_port_reuse_margin_seconds`` sets it.
DEFAULT_PORT_REUSE_MARGIN = timedelta(seconds=300)


class RelayWindowExhaustedError(RuntimeError):
    """Every port in a relay's configured window is currently leased."""


@dataclass(frozen=True)
class PortLease:
    id: str
    relay_id: str
    remote_port: int


def grant_expiry(lease_ends_at: datetime, grace: timedelta) -> datetime:
    """When a lease's grants expire: its end plus the grace, rounded up.

    Rounded up to the whole second because a grant's ``exp`` is an integer
    number of seconds, and one stored value then serves both readers: the
    signer, which converts it exactly, and quarantine, which holds the port
    until it plus the reuse margin. Rounding down would expire a grant before
    the lease end plus the grace. Returned in UTC with no zone, as the lease
    table stores times; a naive ``lease_ends_at`` is taken as UTC.
    """
    end = lease_ends_at if lease_ends_at.tzinfo else lease_ends_at.replace(tzinfo=timezone.utc)
    expiry = end.astimezone(timezone.utc) + grace
    if expiry.microsecond:
        expiry = expiry.replace(microsecond=0) + timedelta(seconds=1)
    return expiry.replace(tzinfo=None)


class RelayPortAllocator:
    def __init__(
        self,
        session_factory: Any,
        *,
        grant_expiry_grace: timedelta = DEFAULT_GRANT_EXPIRY_GRACE,
        reuse_margin: timedelta = DEFAULT_PORT_REUSE_MARGIN,
    ) -> None:
        # A negative grace expires a grant before its lease ends, refusing the
        # tenant's proxy at its next reconnect within the paid term. A margin
        # that is not positive reissues a port while its previous grant may
        # still be admitted on a relay whose clock lags the service's, which
        # is the reuse the quarantine exists to prevent. Either defeats what
        # the setting configures, so the service refuses to start with it.
        if grant_expiry_grace < timedelta(0):
            raise ValueError(
                "relay_grant_expiry_grace_seconds must not be negative, got "
                f"{grant_expiry_grace.total_seconds():g}"
            )
        if reuse_margin <= timedelta(0):
            raise ValueError(
                "relay_port_reuse_margin_seconds must be positive, got "
                f"{reuse_margin.total_seconds():g}"
            )
        self._session_factory = session_factory
        self._grant_expiry_grace = grant_expiry_grace
        # Applied when a port is selected, never stored on a lease, so a raised
        # margin holds back ports already released as well as later ones.
        self._reuse_margin = reuse_margin

    def allocate(
        self,
        *,
        relay_id: str,
        owner_kind: str,
        owner_id: str,
        lease_ends_at: datetime,
        host_id: str | None = None,
        pool_id: str | None = None,
    ) -> PortLease:
        """Lease a port in a standalone transaction owned by the allocator."""
        with self._session_factory() as db:
            # Start the outer write transaction before using savepoints, and
            # serialize SQLite allocations before reading mutable lease state.
            begin_sqlite_write_transaction(db)
            lease = self.allocate_in_session(
                db,
                relay_id=relay_id,
                owner_kind=owner_kind,
                owner_id=owner_id,
                lease_ends_at=lease_ends_at,
                host_id=host_id,
                pool_id=pool_id,
            )
            db.commit()
            return lease

    def allocate_in_session(
        self,
        db: Session,
        *,
        relay_id: str,
        owner_kind: str,
        owner_id: str,
        lease_ends_at: datetime,
        host_id: str | None = None,
        pool_id: str | None = None,
    ) -> PortLease:
        """Lease the lowest free port in the relay's window.

        ``lease_ends_at`` is the owning reservation's scheduled lease end. The
        lease records its grants' expiry from it, in the caller's transaction.

        Lowest-free rather than next-after-last so that a released port is
        reused promptly: the window is finite, and a strategy that always moves
        forward turns a slow leak into an outage sooner. A port still in its
        quarantine is not free.

        The unique constraint is the arbiter, not the read that precedes it.
        Two allocations racing on one relay both see the same free port; the
        second flush fails and retries against a set that now excludes it.
        Savepoints contain a uniqueness conflict without rolling back the
        caller's other writes. The caller owns the outer write transaction and
        its commit; fulfillment acceptance reserves SQLite's writer slot before
        calling this method.
        """
        # Idempotent for one owner: retrying dispatch must not orphan a port.
        existing = (
            db.query(RelayPortLease)
            .filter(
                RelayPortLease.owner_kind == owner_kind,
                RelayPortLease.owner_id == owner_id,
                RelayPortLease.released_at.is_(None),
            )
            .one_or_none()
        )
        if existing is not None:
            return PortLease(
                id=existing.id,
                relay_id=existing.relay_id,
                remote_port=existing.remote_port,
            )
        relay = db.get(Relay, relay_id)
        if relay is None:
            raise RelayWindowExhaustedError(
                f"relay '{relay_id}' does not exist, so no port can be leased on it"
            )
        window = range(
            relay.vm_port_range_start,
            relay.vm_port_range_start + relay.vm_port_range_count,
        )
        expires_at = grant_expiry(lease_ends_at, self._grant_expiry_grace)
        # Bounded by the window size so a full window cannot spin forever.
        for _ in range(relay.vm_port_range_count):
            try:
                with db.begin_nested():
                    port = self._lowest_free(db, relay_id, window)
                    lease = self._claim(
                        db,
                        relay_id=relay_id,
                        port=port,
                        owner_kind=owner_kind,
                        owner_id=owner_id,
                        host_id=host_id,
                        pool_id=pool_id,
                        grant_expires_at=expires_at,
                    )
                    db.flush()
            except IntegrityError:
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
        host_id: str | None,
        pool_id: str | None,
        grant_expires_at: datetime,
    ) -> RelayPortLease:
        """Take the row for this port, reusing a released one if it exists.

        A reused row is a new tenancy: its owner, host, pool, grant expiry,
        and signing key are this one's, and nothing of the last tenancy's
        grants carries over.

        Uniqueness is ``(relay_id, remote_port)`` unconditionally, so a
        released lease still occupies its port in the index. Reclaiming the row
        rather than inserting a second one is what lets a released port be
        reissued while that constraint stays exactly as strict as it reads.

        The alternative — a partial index excluding released rows — would keep
        per-lease history, at the cost of a constraint whose meaning depends on
        a column and which the lease tests could no longer state simply. The
        table is then bounded by relays multiplied by window size rather than
        growing with delivery churn, which is the better trade for a record
        whose purpose is answering "what is bound on this relay right now".
        """
        existing = (
            db.query(RelayPortLease)
            .filter(
                RelayPortLease.relay_id == relay_id,
                RelayPortLease.remote_port == port,
            )
            .one_or_none()
        )
        if existing is not None and existing.released_at is not None:
            existing.owner_kind = owner_kind
            existing.owner_id = owner_id
            existing.host_id = host_id
            existing.pool_id = pool_id
            existing.released_at = None
            existing.created_at = datetime.now(timezone.utc).replace(tzinfo=None)
            existing.grant_expires_at = grant_expires_at
            existing.grant_key_id = None
            return existing
        lease = RelayPortLease(
            id=str(uuid.uuid4()),
            relay_id=relay_id,
            remote_port=port,
            host_id=host_id,
            pool_id=pool_id,
            owner_kind=owner_kind,
            owner_id=owner_id,
            # Set here rather than by the database's clock, so it is UTC as
            # every time a retired key's validity is compared against is.
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            grant_expires_at=grant_expires_at,
        )
        db.add(lease)
        return lease

    @staticmethod
    def release_in_session(db: Session, *, owner_kind: str, owner_id: str) -> int:
        """Release inside the caller's transaction, without committing.

        The release effect uses this so the port and the reservation's capacity
        are returned together. Releasing afterwards, in its own
        transaction, reintroduces on every crash exactly the leak that
        reconciliation exists to bound for paths nobody enumerated.
        """
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

    def find_active_lease(self, *, owner_kind: str, owner_id: str) -> PortLease | None:
        """The lease an owner currently holds, or None.

        Teardown reads this rather than pool configuration: the lease records
        where the port was bound, and a pool rebound since creation no longer
        describes it.
        """
        with self._session_factory() as db:
            row = (
                db.query(RelayPortLease)
                .filter(
                    RelayPortLease.owner_kind == owner_kind,
                    RelayPortLease.owner_id == owner_id,
                    RelayPortLease.released_at.is_(None),
                )
                .one_or_none()
            )
            if row is None:
                return None
            return PortLease(
                id=row.id, relay_id=row.relay_id, remote_port=row.remote_port
            )

    def release(self, *, owner_kind: str, owner_id: str) -> int:
        """Release every lease held by one owner. Returns how many were released.

        Idempotent, and safe to call on a path that may already have released:
        a set of code paths is never provably exhaustive, so the ones that
        overlap must not fail each other.
        """
        with self._session_factory() as db, db.begin():
            return self.release_in_session(
                db, owner_kind=owner_kind, owner_id=owner_id
            )

    def reconcile(
        self,
        *,
        is_owner_released: Any,
        grace: timedelta = timedelta(hours=1),
    ) -> int:
        """Release leases whose owner was released beyond a grace period.

        The release effect returns a port in the transaction that releases its
        reservation's capacity, and that is still not sufficient on its own:
        a set of code paths is never provably exhaustive, and the one that is
        missed is the one nobody thought of. This converts an unenumerated
        leak into a bounded one.

        ``is_owner_released`` is supplied by the caller rather than queried
        here, because when an owner is released belongs to the site's
        reservations and not to port accounting. It must answer exactly as the
        release effect decides, so this never returns a port that decision
        would hold.
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
                if not is_owner_released(lease.owner_kind, lease.owner_id):
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

    async def run_reconciliation(
        self,
        *,
        is_owner_released: Any,
        poll_interval_seconds: float,
        grace: timedelta,
    ) -> None:
        """Periodically release leases the release effect did not.

        A backstop, not the mechanism: a port is returned with its
        reservation's capacity, in the transaction that releases it. What this
        recovers is a lease whose reservation was released by some path that
        bypassed it — which is, by definition, a path nobody enumerated,
        which is why this exists at all rather than being reasoned away.

        Every release here is logged at warning level. A quiet sweep means the
        enumerated path is working; a noisy one names a path that needs
        finding.
        """
        while True:
            try:
                self.reconcile(is_owner_released=is_owner_released, grace=grace)
            except asyncio.CancelledError:
                raise
            except Exception:
                # A sweep failure must not end the loop: the next cycle is the
                # recovery, and a dead backstop is worse than a noisy one.
                logger.exception("Relay port reconciliation cycle failed")
            await asyncio.sleep(poll_interval_seconds)

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

    def _lowest_free(self, db: Session, relay_id: str, window: range) -> int:
        """The lowest port in the window neither held nor in quarantine.

        A released port is in quarantine until its last grant's expiry plus
        the reuse margin, read now rather than when it was released.
        """
        reusable_before = (
            datetime.now(timezone.utc).replace(tzinfo=None) - self._reuse_margin
        )
        held = {
            row.remote_port
            for row in db.query(RelayPortLease)
            .filter(
                RelayPortLease.relay_id == relay_id,
                or_(
                    RelayPortLease.released_at.is_(None),
                    and_(
                        RelayPortLease.grant_expires_at.is_not(None),
                        RelayPortLease.grant_expires_at > reusable_before,
                    ),
                ),
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
    def active_leases_for_relay(db: Session, relay_id: str) -> list[RelayPortLease]:
        """Leases still bound on a relay, for the rebinding rules to consult.

        A rebinding must be refused while any of these exist, because each one
        corresponds to a connection string a buyer already holds.
        """
        return (
            db.query(RelayPortLease)
            .filter(
                RelayPortLease.relay_id == relay_id,
                RelayPortLease.released_at.is_(None),
            )
            .all()
        )

    @staticmethod
    def active_leases_for_pool(db: Session, pool_id: str) -> list[RelayPortLease]:
        return (
            db.query(RelayPortLease)
            .filter(
                RelayPortLease.pool_id == pool_id,
                RelayPortLease.released_at.is_(None),
            )
            .all()
        )

    @staticmethod
    def active_leases_for_host(db: Session, host_id: str) -> list[RelayPortLease]:
        return (
            db.query(RelayPortLease)
            .filter(
                RelayPortLease.host_id == host_id,
                RelayPortLease.released_at.is_(None),
            )
            .all()
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


#: The owner kind a fulfillment's port lease records.
FULFILLMENT_OWNER_KIND = "fulfillment"


def release_reservation_ports(db: Session, capacity_reservation_id: str, state: str) -> None:
    """The relays' release effect: the reservation's port goes back to its relay.

    Runs in the site ledger's transaction that releases the reservation's
    capacity. A fulfillment's state alone never returns a port: a ``failed``
    create may have left a proxy registered, so the port is held, with the
    capacity, until an operator verifies the host and forces the release.
    """
    released = RelayPortAllocator.release_in_session(
        db, owner_kind=FULFILLMENT_OWNER_KIND, owner_id=capacity_reservation_id
    )
    if released:
        logger.info(
            "Released %d relay port lease(s) for %s with its capacity (%s)",
            released,
            capacity_reservation_id,
            state,
        )


def fulfillment_lease_owner_is_released(session_factory) -> Any:
    """The reconciliation predicate: whether a lease's reservation is released.

    The backstop beneath the release effect asks the same question the effect
    answers, so it never returns a port the release decision would hold. A
    lease whose owner is not a reservation's fulfillment is never reclaimed by
    it.
    """

    def is_owner_released(owner_kind: str, owner_id: str) -> bool:
        if owner_kind != FULFILLMENT_OWNER_KIND:
            return False
        with session_factory() as db:
            return reservation_is_released(db, owner_id)

    return is_owner_released


def reservation_lease_end(db: Session, capacity_reservation_id: str) -> datetime | None:
    """The scheduled lease end of a reservation, or None when it states none.

    A plan leasing a relay port for a fulfillment passes this to allocation,
    reading it in the acceptance session: the site ledger shares this database.
    """
    reservation = db.get(CapacityReservation, capacity_reservation_id)
    if reservation is None:
        return None
    return parse_utc(reservation.lease_end_utc)


__all__ = [
    "DEFAULT_GRANT_EXPIRY_GRACE",
    "DEFAULT_PORT_REUSE_MARGIN",
    "FULFILLMENT_OWNER_KIND",
    "PortLease",
    "RelayPortAllocator",
    "RelayWindowExhaustedError",
    "fulfillment_lease_owner_is_released",
    "grant_expiry",
    "release_reservation_ports",
    "reservation_lease_end",
]
