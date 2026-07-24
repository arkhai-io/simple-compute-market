"""Settlement/fulfillment aggregate repository.

Every method takes a caller-supplied ``Session`` and never commits: a caller
composing one transaction across this repository and another (for example,
``market_site``'s reservation ledger) owns the transaction boundary and
commits once, after every write it needs has been made against the same
session. This lets scheduling compose capacity rebinding and settlement
assignment in one transaction. See
``openspec/specs/fulfillment/spec.md#durable-settlement-persistence``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable, Sequence

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .db import ProvisionedResource, SchedulingCursor, SettlementRecord, SettlementRecordState
from .envelopes import VersionedEnvelope
from .ids import new_fulfillment_id
from .provider import FulfillmentConflictError
from .settlement_types import (
    SettlementEntityNotFoundError,
    SettlementRequestMismatchError,
    SettlementRequirement,
    SettlementResource,
)
from .transitions import validate_transition



_LIFECYCLE_UPDATE_FIELDS = frozenset(
    {
        "prepared_create_operation",
        "prepared_teardown_operation",
        "provider_metadata",
        "teardown_provider_metadata",
        "failure_reason",
        "failure_message",
    }
)


def begin_sqlite_write_transaction(db: Session) -> None:
    """Reserve SQLite's single writer slot before reading mutable state.

    ``BEGIN IMMEDIATE`` is SQLite's database-level write reservation. It is
    intentionally used instead of claiming row-lock semantics that SQLite
    does not provide. The caller still owns commit or rollback. Shared by
    every caller that needs this repository's SQLite concurrency contract
    (fulfillment acceptance here; ``PhysicalSettlementScheduler.schedule_resource``
    for scheduling and its round-robin cursor).
    """

    connection = db.connection()
    if connection.dialect.name == "sqlite":
        connection.exec_driver_sql("BEGIN IMMEDIATE")


# Retained as a private alias so this module's own call sites below don't
# need to change; new external callers should use the public name.
_begin_sqlite_write_transaction = begin_sqlite_write_transaction


def _scheduling_matches(
    record: SettlementRecord,
    *,
    market: str,
    serialized_requirements: dict,
    resource_id_constraint: str | None,
) -> bool:
    return (
        record.market == market
        and record.scheduling_requirements == serialized_requirements
        and (
            resource_id_constraint is None
            or resource_id_constraint == record.settlement_resource_id
        )
    )


def _serialize_requirement(requirement: SettlementRequirement) -> dict:
    return requirement.model_dump(mode="json")


def _serialize_envelope(envelope: VersionedEnvelope) -> dict:
    return envelope.model_dump(mode="json")


class SettlementRepository:
    """Caller-supplied-session repository over the settlement aggregate."""

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get(self, db: Session, capacity_reservation_id: str) -> SettlementRecord | None:
        return db.get(SettlementRecord, capacity_reservation_id)

    def get_by_fulfillment_id(self, db: Session, fulfillment_id: str) -> SettlementRecord | None:
        return (
            db.query(SettlementRecord)
            .filter(SettlementRecord.fulfillment_id == fulfillment_id)
            .one_or_none()
        )

    def list_provisioned_resources(
        self, db: Session, capacity_reservation_id: str
    ) -> list[ProvisionedResource]:
        return (
            db.query(ProvisionedResource)
            .filter(ProvisionedResource.capacity_reservation_id == capacity_reservation_id)
            .order_by(ProvisionedResource.created_at.asc())
            .all()
        )

    # ------------------------------------------------------------------
    # Scheduling: schedule_resource's idempotency boundary
    # ------------------------------------------------------------------

    def schedule(
        self,
        db: Session,
        *,
        capacity_reservation_id: str,
        market: str,
        scheduling_requirements: SettlementRequirement,
        resource: SettlementResource,
        resource_id_constraint: str | None = None,
    ) -> SettlementRecord:
        """Create the aggregate in ``assigned`` state, or return it on an
        equivalent retry.

        Scheduling equivalence compares ``market`` and
        ``scheduling_requirements`` against the stored values. A supplied
        ``resource_id_constraint`` is checked separately, for consistency
        against the row's ``settlement_resource_id`` -- it is not folded into
        the ``market``/``scheduling_requirements`` equality, because it is an
        optional pre-selection constraint on the request, not part of the
        requirement identity being scheduled.
        """

        existing = self.get(db, capacity_reservation_id)
        serialized_requirements = _serialize_requirement(scheduling_requirements)
        if existing is not None:
            if _scheduling_matches(
                existing,
                market=market,
                serialized_requirements=serialized_requirements,
                resource_id_constraint=resource_id_constraint,
            ):
                return existing
            raise SettlementRequestMismatchError(
                f"capacity_reservation_id={capacity_reservation_id!r} already has a "
                "settlement assignment with a different market, requirements, or "
                "resource constraint"
            )

        record = SettlementRecord(
            capacity_reservation_id=capacity_reservation_id,
            market=market,
            scheduling_requirements=serialized_requirements,
            resource_id_constraint=resource_id_constraint,
            settlement_resource_id=resource.settlement_resource_id,
            pool_id=resource.pool_id,
            provider=resource.provider,
            resource_attributes=dict(resource.attributes),
            state=SettlementRecordState.assigned.value,
        )
        try:
            with db.begin_nested():
                db.add(record)
                db.flush()
            return record
        except IntegrityError:
            # A concurrent creator may have won the primary-key race. Re-read
            # the durable row and apply the ordinary equivalence rule.
            existing = self.get(db, capacity_reservation_id)
            if existing is not None and _scheduling_matches(
                existing,
                market=market,
                serialized_requirements=serialized_requirements,
                resource_id_constraint=resource_id_constraint,
            ):
                return existing
            raise SettlementRequestMismatchError(
                f"capacity_reservation_id={capacity_reservation_id!r} was concurrently "
                "scheduled with a different market, requirements, or resource constraint"
            ) from None

    # ------------------------------------------------------------------
    # Fulfillment acceptance: begin_fulfillment's idempotency boundary
    # ------------------------------------------------------------------

    def accept_fulfillment(
        self,
        db: Session,
        *,
        capacity_reservation_id: str,
        market: str,
        fulfillment_request: VersionedEnvelope,
    ) -> SettlementRecord:
        """Accept a fulfillment request against an already-scheduled row.

        Fulfillment equivalence compares ``market`` and ``fulfillment_request``
        only -- there is no caller-supplied resource to compare, since
        ``begin_fulfillment`` loads the already-scheduled resource from this
        row rather than trusting one from the caller.
        """

        _begin_sqlite_write_transaction(db)
        statement = (
            select(SettlementRecord)
            .where(SettlementRecord.capacity_reservation_id == capacity_reservation_id)
            .with_for_update()
        )
        record = db.execute(statement).scalar_one_or_none()
        if record is None:
            raise SettlementEntityNotFoundError(
                f"no settlement assignment exists for capacity_reservation_id="
                f"{capacity_reservation_id!r}; schedule_resource must run first"
            )
        serialized_request = _serialize_envelope(fulfillment_request)
        if record.market != market:
            raise FulfillmentConflictError(
                f"capacity_reservation_id={capacity_reservation_id!r} was scheduled for "
                f"market={record.market!r}, not {market!r}"
            )
        if record.fulfillment_id is not None:
            if record.market == market and record.fulfillment_request == serialized_request:
                return record
            raise FulfillmentConflictError(
                f"capacity_reservation_id={capacity_reservation_id!r} already has a "
                "fulfillment with a different market or fulfillment request"
            )

        validate_transition(record.state, SettlementRecordState.dispatch_pending.value)
        record.fulfillment_id = new_fulfillment_id()
        record.fulfillment_request = serialized_request
        record.state = SettlementRecordState.dispatch_pending.value
        db.flush()
        return record

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    def transition(
        self,
        db: Session,
        capacity_reservation_id: str,
        target_state: str,
        **lifecycle_updates: object,
    ) -> SettlementRecord:
        """Move the row to ``target_state``, applying allowed lifecycle updates.

        A retry that finds the row already at ``target_state`` is a no-op
        return rather than a table lookup -- self-transitions are
        intentionally absent from the transition table (see
        ``transitions.validate_transition``).
        """

        unsupported = set(lifecycle_updates) - _LIFECYCLE_UPDATE_FIELDS
        if unsupported:
            raise ValueError(
                "transition lifecycle updates are not permitted for: "
                + ", ".join(sorted(unsupported))
            )

        record = self.get(db, capacity_reservation_id)
        if record is None:
            raise SettlementEntityNotFoundError(
                f"no settlement assignment exists for capacity_reservation_id="
                f"{capacity_reservation_id!r}"
            )
        if record.state != target_state:
            validate_transition(record.state, target_state)
            record.state = target_state
        for field, value in lifecycle_updates.items():
            setattr(record, field, value)
        db.flush()
        return record

    # ------------------------------------------------------------------
    # Provisioned resources
    # ------------------------------------------------------------------

    def add_provisioned_resource(
        self,
        db: Session,
        *,
        capacity_reservation_id: str,
        domain_resource_ref: str | None = None,
        status: str = "active",
    ) -> ProvisionedResource:
        record = self.get(db, capacity_reservation_id)
        if record is None or record.fulfillment_id is None:
            raise SettlementEntityNotFoundError(
                f"capacity_reservation_id={capacity_reservation_id!r} has no accepted "
                "fulfillment to attach a provisioned resource to"
            )
        existing = (
            db.query(ProvisionedResource)
            .filter(ProvisionedResource.capacity_reservation_id == capacity_reservation_id)
            .filter(ProvisionedResource.domain_resource_ref == domain_resource_ref)
            .one_or_none()
        )
        if existing is not None:
            return existing
        provisioned = ProvisionedResource(
            capacity_reservation_id=capacity_reservation_id,
            fulfillment_id=record.fulfillment_id,
            domain_resource_ref=domain_resource_ref,
            status=status,
        )
        try:
            with db.begin_nested():
                db.add(provisioned)
                db.flush()
            return provisioned
        except IntegrityError:
            # A concurrent caller won the unique-constraint race between our
            # existence check and our insert (task 6.3.4's backstop doing
            # its job). Re-read and return the winning row rather than
            # raising -- add_provisioned_resource stays idempotent under
            # genuine concurrency, not just under sequential retries.
            existing = (
                db.query(ProvisionedResource)
                .filter(
                    ProvisionedResource.capacity_reservation_id == capacity_reservation_id
                )
                .filter(ProvisionedResource.domain_resource_ref == domain_resource_ref)
                .one_or_none()
            )
            if existing is not None:
                return existing
            raise

    # ------------------------------------------------------------------
    # Scheduling fairness cursor
    # ------------------------------------------------------------------

    def get_cursor_in_session(self, db: Session, resource_kind: str) -> SchedulingCursor:
        """Return the durable round-robin cursor for ``resource_kind``.

        Creates a zero-value row on first use so callers never need a
        separate "no cursor yet" branch -- an absent cursor and a cursor
        that has never advanced are the same starting state.
        """

        cursor = db.get(SchedulingCursor, resource_kind)
        if cursor is None:
            cursor = SchedulingCursor(
                resource_kind=resource_kind, last_pool_id=None, last_resource_by_pool={}
            )
            db.add(cursor)
            db.flush()
        return cursor

    def save_cursor_in_session(
        self,
        db: Session,
        resource_kind: str,
        *,
        last_pool_id: str | None,
        last_resource_by_pool: dict,
    ) -> SchedulingCursor:
        """Persist an updated cursor value in the caller's open transaction.

        Callers write this alongside the settlement-record change it
        accompanies so a cursor advance is never observed independently of
        the assignment it produced.
        """

        cursor = self.get_cursor_in_session(db, resource_kind)
        cursor.last_pool_id = last_pool_id
        cursor.last_resource_by_pool = dict(last_resource_by_pool)
        db.flush()
        return cursor

    # ------------------------------------------------------------------
    # Abandonment hook
    # ------------------------------------------------------------------

    def abandon_if_assigned(self, db: Session, capacity_reservation_id: str) -> None:
        """Transition an ``assigned`` aggregate to ``abandoned``, or no-op.

        This is the concrete implementation ``market_site.CapacityLedgerService``
        invokes (through a ``Protocol`` it defines, referencing no
        fulfillment types) whenever it reclaims capacity that might belong
        to a reservation with a not-yet-dispatched settlement assignment --
        a lapsed TTL hold, a terminal release, or a negotiation-driven
        resize's supersede step. It is called unconditionally by those
        callers; whether there is anything to abandon is entirely this
        method's decision, not theirs.
        """

        record = self.get(db, capacity_reservation_id)
        if record is None or record.state != SettlementRecordState.assigned.value:
            return
        validate_transition(record.state, SettlementRecordState.abandoned.value)
        record.state = SettlementRecordState.abandoned.value
        db.flush()

    # ------------------------------------------------------------------
    # Recovery claims
    # ------------------------------------------------------------------

    def claim_pending(
        self,
        db: Session,
        *,
        states: Sequence[str],
        limit: int,
        lease_seconds: int | Callable[[int], float],
        worker_id: str,
        now: datetime | None = None,
    ) -> list[SettlementRecord]:
        """Claim pending rows for recovery in one short, self-contained transaction.

        Opens and commits its own
        ``BEGIN IMMEDIATE``-guarded transaction rather than depending on a
        caller-supplied open transaction, so the writer slot is released
        before any provider call happens. SQLite has no
        ``SELECT ... FOR UPDATE SKIP LOCKED``; under SQLite's single-writer
        contract it is unnecessary, since this transaction already
        serializes against any other concurrent claim attempt. This is
        concurrent-claim-safe defense-in-depth (overlapping asyncio tasks
        within one watchdog cycle, a brief overlap during pod replacement,
        or a second instance run for diagnosis) — not a distributed
        multi-replica protocol. See
        ``openspec/specs/fulfillment/spec.md#durable-settlement-persistence``.

        ``lease_seconds`` is either a flat lease length applied to every
        claimed row, or a callable receiving each row's own
        (already-incremented) ``attempt_count`` and returning that row's
        lease length — the mechanism ``FulfillmentConvergenceWatchdog``
        uses (via ``market_fulfillment.backoff.Backoff.delay_seconds``) to
        make a claimed-but-not-yet-due row's ``claim_expires_at`` reflect
        exponential backoff with jitter rather than a fixed lease.

        The caller must pass a session dedicated to this call; it is
        committed here and should not be reused for the subsequent
        provider call.
        """

        begin_sqlite_write_transaction(db)
        now = now or datetime.now(timezone.utc)
        candidates = (
            db.query(SettlementRecord)
            .filter(SettlementRecord.state.in_(list(states)))
            .filter(
                (SettlementRecord.claimed_by.is_(None))
                | (SettlementRecord.claim_expires_at <= now)
            )
            .order_by(SettlementRecord.created_at.asc())
            .limit(limit)
            .all()
        )
        for record in candidates:
            record.claimed_by = worker_id
            record.attempt_count = (record.attempt_count or 0) + 1
            lease = (
                lease_seconds(record.attempt_count)
                if callable(lease_seconds)
                else lease_seconds
            )
            record.claim_expires_at = now + timedelta(seconds=lease)
        db.commit()
        for record in candidates:
            db.refresh(record)
            db.expunge(record)
        return candidates

    def clear_claim(
        self,
        db: Session,
        capacity_reservation_id: str,
        *,
        worker_id: str,
    ) -> None:
        """Release a claim once a handler has finished acting on the row.

        A no-op if the row is no longer claimed by ``worker_id`` — e.g. a
        slow worker whose lease has since lapsed and been reclaimed by
        another worker must not clear that worker's claim out from under it.
        """

        record = self.get(db, capacity_reservation_id)
        if record is None or record.claimed_by != worker_id:
            return
        record.claimed_by = None
        record.claim_expires_at = None
        db.flush()

    def mark_provisioned_resources_torn_down(
        self,
        db: Session,
        capacity_reservation_id: str,
        *,
        status: str = "torn_down",
    ) -> None:
        """Update existing ``ProvisionedResource`` rows on confirmed teardown.

        Does not create new rows — teardown convergence updates what create
        convergence already persisted via ``add_provisioned_resource``;
        resource identity is not re-resolved at teardown time.
        """

        db.query(ProvisionedResource).filter(
            ProvisionedResource.capacity_reservation_id == capacity_reservation_id
        ).update({"status": status})
        db.flush()

    # ------------------------------------------------------------------
    # Recovery diagnostics
    # ------------------------------------------------------------------

    _RECOVERY_STATES = (
        SettlementRecordState.dispatch_pending,
        SettlementRecordState.dispatching,
        SettlementRecordState.teardown_dispatch_pending,
        SettlementRecordState.tearing_down,
    )

    def recovery_diagnostics(self, db: Session, *, now: datetime | None = None) -> dict:
        """Operator-facing snapshot of recovery health, one query per field.

        Reports, per non-terminal recovery-relevant state: total row count,
        currently-claimed count, and expired-but-unclaimed count (a
        transient query result surfaced for trend-watching, not itself an
        error condition -- a nonzero value briefly is expected between
        expiry and the next claim cycle). Also reports the oldest
        non-terminal row's age from ``created_at``, the max ``attempt_count``
        across non-terminal rows, and terminal `failed`/`teardown_failed`
        counts. Deliberately does not report a history of transient
        per-attempt provider-call failures -- the schema stores only the
        aggregate's current state and latest failure, not a durable event
        log; that remains out of scope for this method, covered instead by
        ``attempt_count`` and retry age.
        """

        now = now or datetime.now(timezone.utc)
        non_terminal_states = [s.value for s in self._RECOVERY_STATES]

        per_state: dict[str, dict[str, int]] = {}
        for state in self._RECOVERY_STATES:
            base_query = db.query(SettlementRecord).filter(
                SettlementRecord.state == state.value
            )
            total = base_query.count()
            claimed = base_query.filter(
                SettlementRecord.claimed_by.isnot(None),
                SettlementRecord.claim_expires_at > now,
            ).count()
            expired = base_query.filter(
                SettlementRecord.claimed_by.isnot(None),
                SettlementRecord.claim_expires_at <= now,
            ).count()
            per_state[state.value] = {
                "total": total,
                "claimed": claimed,
                "expired_unclaimed": expired,
            }

        non_terminal_query = db.query(SettlementRecord).filter(
            SettlementRecord.state.in_(non_terminal_states)
        )
        oldest = (
            non_terminal_query.order_by(SettlementRecord.created_at.asc())
            .first()
        )
        oldest_age_seconds = None
        if oldest is not None:
            oldest_created_at = oldest.created_at
            # SQLite round-trips DateTime columns as naive regardless of
            # what was written (the same characteristic claim_pending's
            # tests already account for) -- normalize both sides to naive
            # before subtracting rather than assuming either's awareness.
            comparison_now = now.replace(tzinfo=None) if now.tzinfo else now
            if oldest_created_at.tzinfo:
                oldest_created_at = oldest_created_at.replace(tzinfo=None)
            oldest_age_seconds = (comparison_now - oldest_created_at).total_seconds()
        max_attempt_count = db.query(
            SettlementRecord.attempt_count
        ).filter(SettlementRecord.state.in_(non_terminal_states)).order_by(
            SettlementRecord.attempt_count.desc()
        ).limit(1).scalar()

        return {
            "per_state": per_state,
            "oldest_non_terminal_row_age_seconds": oldest_age_seconds,
            "max_attempt_count": max_attempt_count or 0,
            "terminal_failed_count": db.query(SettlementRecord)
            .filter(SettlementRecord.state == SettlementRecordState.failed.value)
            .count(),
            "terminal_teardown_failed_count": db.query(SettlementRecord)
            .filter(SettlementRecord.state == SettlementRecordState.teardown_failed.value)
            .count(),
        }
