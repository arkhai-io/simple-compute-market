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
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .db import ProvisionedResource, SettlementRecord, SettlementRecordState
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


def _begin_sqlite_write_transaction(db: Session) -> None:
    """Reserve SQLite's single writer slot before reading mutable state.

    ``BEGIN IMMEDIATE`` is SQLite's database-level write reservation. It is
    intentionally used instead of claiming row-lock semantics that SQLite
    does not provide. The caller still owns commit or rollback.
    """

    connection = db.connection()
    if connection.dialect.name == "sqlite":
        connection.exec_driver_sql("BEGIN IMMEDIATE")


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
        provisioned = ProvisionedResource(
            capacity_reservation_id=capacity_reservation_id,
            fulfillment_id=record.fulfillment_id,
            domain_resource_ref=domain_resource_ref,
            status=status,
        )
        db.add(provisioned)
        db.flush()
        return provisioned

    # ------------------------------------------------------------------
    # Recovery claims
    # ------------------------------------------------------------------

    def select_pending_for_single_worker(
        self,
        db: Session,
        *,
        states: Sequence[str],
        limit: int,
        lease_seconds: int,
        worker_id: str,
        now: datetime | None = None,
    ) -> list[SettlementRecord]:
        """Lease pending rows for one SQLite recovery worker.

        This helper records the durable lease shape and supports a deployment
        with exactly one recovery worker. It is not a concurrent worker-claim
        protocol; Section 7's recovery workflow owns duplicate-dispatch
        prevention under the service's final execution model.
        """

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
            record.claim_expires_at = now + timedelta(seconds=lease_seconds)
            record.attempt_count = (record.attempt_count or 0) + 1
        db.flush()
        return candidates
