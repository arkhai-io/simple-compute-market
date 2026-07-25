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

from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .db import ProvisionedResource, SchedulingCursor, SettlementRecord, SettlementRecordState
from .envelopes import VersionedEnvelope
from .ids import new_fulfillment_id
from .provider import FulfillmentConflictError
from .recovery_diagnostics import RecoveryDiagnostics, RecoveryStateDiagnostics
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
        provisioned_resource_id: str,
        status: str = "active",
    ) -> ProvisionedResource:
        """Persist or return one output under its stable fulfillment identity."""

        record = self.get(db, capacity_reservation_id)
        if record is None or record.fulfillment_id is None:
            raise SettlementEntityNotFoundError(
                f"capacity_reservation_id={capacity_reservation_id!r} has no accepted "
                "fulfillment to attach a provisioned resource to"
            )
        existing = db.get(ProvisionedResource, provisioned_resource_id)
        if existing is not None:
            if existing.capacity_reservation_id != capacity_reservation_id:
                raise FulfillmentConflictError(
                    f"provisioned_resource_id={provisioned_resource_id!r} belongs to "
                    "another fulfillment"
                )
            return existing
        provisioned = ProvisionedResource(
            provisioned_resource_id=provisioned_resource_id,
            capacity_reservation_id=capacity_reservation_id,
            fulfillment_id=record.fulfillment_id,
            status=status,
        )
        try:
            with db.begin_nested():
                db.add(provisioned)
                db.flush()
            return provisioned
        except IntegrityError:
            existing = db.get(ProvisionedResource, provisioned_resource_id)
            if existing is not None and existing.capacity_reservation_id == capacity_reservation_id:
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

    def recovery_diagnostics(
        self, db: Session, *, now: datetime | None = None
    ) -> RecoveryDiagnostics:
        """Return one typed snapshot of recovery health.

        Recovery age and attempt metrics are calculated independently for
        each non-terminal lifecycle state. The query also distinguishes
        active leases from expired claims eligible for reclamation.
        """

        now = now or datetime.now(timezone.utc)
        state_values = [state.value for state in self._RECOVERY_STATES]

        active_claim = case(
            (
                SettlementRecord.claimed_by.isnot(None)
                & (SettlementRecord.claim_expires_at > now),
                1,
            ),
            else_=0,
        )
        expired_claim = case(
            (
                SettlementRecord.claimed_by.isnot(None)
                & (SettlementRecord.claim_expires_at <= now),
                1,
            ),
            else_=0,
        )
        rows = (
            db.query(
                SettlementRecord.state,
                func.count(SettlementRecord.capacity_reservation_id),
                func.sum(active_claim),
                func.sum(expired_claim),
                func.min(SettlementRecord.created_at),
                func.max(SettlementRecord.attempt_count),
            )
            .filter(SettlementRecord.state.in_(state_values))
            .group_by(SettlementRecord.state)
            .all()
        )

        per_state = {
            state.value: RecoveryStateDiagnostics(
                total=0,
                actively_claimed=0,
                expired_claims=0,
                oldest_row_age_seconds=None,
                max_attempt_count=0,
            )
            for state in self._RECOVERY_STATES
        }
        for state, total, actively_claimed, expired_claims, oldest, max_attempts in rows:
            per_state[state] = RecoveryStateDiagnostics(
                total=int(total or 0),
                actively_claimed=int(actively_claimed or 0),
                expired_claims=int(expired_claims or 0),
                oldest_row_age_seconds=self._row_age_seconds(now, oldest),
                max_attempt_count=int(max_attempts or 0),
            )

        failure_counts = dict(
            db.query(SettlementRecord.state, func.count(SettlementRecord.capacity_reservation_id))
            .filter(
                SettlementRecord.state.in_(
                    (
                        SettlementRecordState.failed.value,
                        SettlementRecordState.teardown_failed.value,
                    )
                )
            )
            .group_by(SettlementRecord.state)
            .all()
        )
        return RecoveryDiagnostics(
            per_state=per_state,
            failed_count=int(failure_counts.get(SettlementRecordState.failed.value, 0)),
            teardown_failed_count=int(
                failure_counts.get(SettlementRecordState.teardown_failed.value, 0)
            ),
        )

    @staticmethod
    def _row_age_seconds(now: datetime, created_at: datetime | None) -> float | None:
        if created_at is None:
            return None
        comparison_now = now.replace(tzinfo=None) if now.tzinfo else now
        comparison_created_at = (
            created_at.replace(tzinfo=None) if created_at.tzinfo else created_at
        )
        return (comparison_now - comparison_created_at).total_seconds()

