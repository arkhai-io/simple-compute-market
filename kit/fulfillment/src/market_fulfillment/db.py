"""Shared SQLAlchemy mappings for the durable settlement/fulfillment aggregate.

One row exists per ``capacity_reservation_id`` for the entire physical
settlement lifecycle of that reservation: ``schedule_resource`` creates it,
``begin_fulfillment`` accepts it, and provider dispatch/teardown converge it
in place. There is deliberately no separate scheduler-owned assignment table
alongside a distinct fulfillment record -- one row answers "does this
reservation have a settlement, and what state is it in" with one lookup and
keeps both callers' idempotency checks on the same primary key. See
``openspec/specs/fulfillment/spec.md``.

The mounting service owns the ordered migration that creates these tables on
its engine. Shared mappings define the schema, but application startup does not
create it implicitly.
"""

from __future__ import annotations

import enum

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base
from sqlalchemy.sql import func

from .ids import new_provisioned_resource_id

Base = declarative_base()


class SettlementRecordState(str, enum.Enum):
    """Lifecycle states for one settlement/fulfillment aggregate row.

    ``assigned`` may persist for a real, potentially long window: a
    reservation can be scheduled well before a deal finalizes and
    fulfillment begins. It is not mutable while assigned -- a repeat
    ``schedule_resource`` call for the same row is an ordinary
    idempotent-retry-or-conflict check, never an in-place update of the
    assigned resource or requirements. A genuinely changed shape supersedes
    the reservation under a new ``capacity_reservation_id`` instead of
    mutating this one.

    ``failed``, ``torn_down``, and ``abandoned`` are terminal. Any changed
    shape after a terminal state is a new reservation's first
    ``schedule_resource`` call, not a transition out of this row.
    ``teardown_failed`` is not terminal: recovery may retry teardown.
    """

    assigned = "assigned"
    dispatch_pending = "dispatch_pending"
    dispatching = "dispatching"
    active = "active"
    failed = "failed"
    teardown_dispatch_pending = "teardown_dispatch_pending"
    tearing_down = "tearing_down"
    torn_down = "torn_down"
    teardown_failed = "teardown_failed"
    abandoned = "abandoned"


class SettlementRecord(Base):
    """The durable settlement/fulfillment aggregate for one capacity reservation.

    ``scheduling_requirements`` and ``fulfillment_request`` are two distinct,
    independently immutable-once-written request shapes with two distinct
    equivalence checks: the former governs ``schedule_resource`` retries, the
    latter governs ``begin_fulfillment`` retries. They are not the same field
    because ``begin_fulfillment`` loads its resource from this row rather
    than accepting one from the caller, so its retry has nothing to do with
    scheduling eligibility.

    ``prepared_create_operation``/``prepared_teardown_operation`` hold a
    ``VersionedEnvelope``-shaped payload each, frozen before the transaction
    that marks the corresponding dispatch-pending state commits, so a
    recovery retry dispatches from what was accepted rather than a live
    re-read of pool/provider configuration.

    There is no persisted result object: a caller-facing fulfillment result
    is a read-time projection over this row's state/failure fields and its
    ``ProvisionedResource`` children, not a value stored here.
    """

    __tablename__ = "settlement_records"

    capacity_reservation_id = Column(String, primary_key=True)
    fulfillment_id = Column(String, nullable=True, unique=True, index=True)
    owner_principal = Column(
        String,
        nullable=False,
        default="legacy-admin",
        index=True,
    )

    market = Column(String, nullable=False)
    scheduling_requirements = Column(JSON, nullable=False)
    resource_id_constraint = Column(String, nullable=True)

    settlement_resource_id = Column(String, nullable=False, index=True)
    pool_id = Column(String, nullable=False)
    provider = Column(String, nullable=False)
    resource_attributes = Column(JSON, nullable=True)

    fulfillment_request = Column(JSON, nullable=True)

    prepared_create_operation = Column(JSON, nullable=True)
    prepared_teardown_operation = Column(JSON, nullable=True)
    provider_metadata = Column(JSON, nullable=False, default=dict)
    teardown_provider_metadata = Column(JSON, nullable=True)

    state = Column(String, nullable=False, default=SettlementRecordState.assigned.value)
    failure_reason = Column(String, nullable=True)
    failure_message = Column(Text, nullable=True)
    credential_generation = Column(
        Integer, nullable=False, default=0, server_default="0"
    )

    # Multi-replica recovery-claim boundary. One aggregate has at most one
    # pending provider operation at a time, so these live on the row itself
    # rather than in a separate claims table.
    claimed_by = Column(String, nullable=True)
    claim_expires_at = Column(DateTime(timezone=True), nullable=True)
    attempt_count = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "capacity_reservation_id",
            "fulfillment_id",
            name="uq_settlement_reservation_fulfillment",
        ),
    )


class SchedulingCursor(Base):
    """Durable round-robin fairness state for one ``resource_kind``.

    A buyer negotiates for one ``resource_kind`` per reservation (a VM, a
    bare-metal instance, a pod), never across kinds within one reservation,
    so fairness is isolated per ``resource_kind`` rather than tracked
    globally or at a finer grain. ``schedule_resource``'s single-writer
    transaction (see ``openspec/specs/fulfillment/spec.md``) reads and
    rewrites this row in the same commit as the settlement-record write it
    accompanies, so cursor advancement and assignment are never observed
    out of sync with each other.
    """

    __tablename__ = "scheduling_cursors"

    resource_kind = Column(String, primary_key=True)
    last_pool_id = Column(String, nullable=True)
    last_resource_by_pool = Column(JSON, nullable=False, default=dict)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ProvisionedResource(Base):
    """One provider-created output of an accepted fulfillment.

    A fulfillment may produce zero or more of these, each with a globally
    unique ``provisioned_resource_id``. ``fulfillment_id`` is denormalized
    from the owning ``SettlementRecord`` because whole-fulfillment status and
    teardown are addressed by ``fulfillment_id``, not by the reservation
    identifier; ``capacity_reservation_id`` remains the foreign key because
    it is the row's primary key and is populated before ``fulfillment_id``
    exists.
    """

    __tablename__ = "provisioned_resources"

    provisioned_resource_id = Column(String, primary_key=True, default=new_provisioned_resource_id)
    capacity_reservation_id = Column(String, nullable=False, index=True)
    fulfillment_id = Column(String, nullable=False, index=True)
    domain_resource_ref = Column(String, nullable=True)
    status = Column(String, nullable=False, default="active")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["capacity_reservation_id", "fulfillment_id"],
            [
                "settlement_records.capacity_reservation_id",
                "settlement_records.fulfillment_id",
            ],
            ondelete="CASCADE",
            name="fk_provisioned_resource_settlement_identity",
        ),
        UniqueConstraint(
            "capacity_reservation_id",
            "domain_resource_ref",
            name="uq_provisioned_resource_domain_ref",
        ),
    )
