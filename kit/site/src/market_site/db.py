"""Site-authority ledger tables.

Extracted from the VM provisioning service as the shared site-authority
scaffold (docs/development/ARCHITECTURE.md, "Capacity and the Site
Authority"): any service hosting a site ledger mounts these tables on
its own engine. The mounting service is responsible for
``Base.metadata.create_all`` (or equivalent migrations) on its engine.
"""

from __future__ import annotations

import enum
import uuid

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import declarative_base
from sqlalchemy.sql import func

Base = declarative_base()


class ReservationState(str, enum.Enum):
    """Lifecycle states for a capacity reservation.

    The reservation row is the merged ledger entry the capacity design doc
    calls for: the storefront's hold (``reserved → provisioning → leased``)
    and the lease's temporal tail (``releasing → released``) are one row,
    so release happens in a local transaction with no cross-service sync.

    reserved     — capacity held for a deal; not yet provisioning. May carry
                   a TTL (``hold_expires_at``) for two-phase reserve.
    provisioning — executor is building the workload.
    provisioning_failed  — provisioning failed before a usable lease existed.
    leased       — committed into an active lease (``lease_end_utc`` set).
    releasing    — lease ended; teardown/vm_remove job in flight.
    released             — teardown succeeded and capacity returned to the pool.
    release_failed       — teardown failed/timed out; capacity remains held.
    unmanaged            — lifecycle oversight released; capacity remains held until admin repair.
    force_released       — admin asserted capacity is safe to resell without teardown proof.
    """

    reserved = "reserved"
    provisioning = "provisioning"
    provisioning_failed = "provisioning_failed"
    leased = "leased"
    releasing = "releasing"
    released = "released"
    release_failed = "release_failed"
    unmanaged = "unmanaged"
    force_released = "force_released"


# States that consume capacity. ``releasing`` still holds the units — the
# workload may not be torn down yet.
HELD_RESERVATION_STATES = (
    ReservationState.reserved.value,
    ReservationState.provisioning.value,
    ReservationState.leased.value,
    ReservationState.releasing.value,
    ReservationState.release_failed.value,
    ReservationState.unmanaged.value,
)



class CapacityBucket(Base):
    """Provisioning-private host-level capacity accounting boundary.

    A bucket carries the currently reservable multidimensional balance for one
    backing domain resource.  Its opaque identity and debit mappings never
    cross the storefront reservation contract.
    """

    __tablename__ = "capacity_buckets"
    __table_args__ = (
        UniqueConstraint("backing_resource_id", name="uq_capacity_buckets_backing_resource"),
    )

    capacity_bucket_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    backing_resource_id = Column(
        String, nullable=False, index=True,
    )
    pool_id = Column(String, nullable=True, index=True)
    resource_type = Column(String, nullable=False, default="compute.gpu")
    resource_subtype = Column(String, nullable=True)
    total_units = Column(Integer, nullable=False, default=0)
    capacity = Column(JSON, nullable=False, default=dict)
    attributes = Column(JSON, nullable=False, default=dict)
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class CapacityReservation(Base):
    """A capacity hold and its lease tail, as one ledger row.

    Merges the storefront's ``compute_allocations`` shape with the lease
    fields previously duplicated into ``vm_leases``: when the watchdog
    releases an expired lease it updates *this* row locally and emits
    events, instead of PATCHing the storefront's resource table.

    deal_ref is the opaque mapping the storefront passed at reserve time
    (listing_id, escrow_uid, owner callback) — the ledger never interprets
    it beyond routing deal-scoped events back to the owning storefront.
    Timestamps are ISO-8601 TEXT, matching the storefront ledger they
    replace; the reservation count per site is small enough to compare in
    Python.
    """

    __tablename__ = "capacity_reservations"

    capacity_reservation_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_principal = Column(
        String,
        nullable=False,
        default="legacy-admin",
        index=True,
    )
    # Null until scheduling persists a concrete assignment. The initial
    # capacity-accounting choice is private to CapacityReservationDebit.
    settlement_resource_id = Column(String, nullable=True, index=True)
    units = Column(Integer, nullable=False, default=1)
    # units mirrors dimensions["gpu_count"] for payload/caller compatibility.
    # May be null when the multidimensional map is absent, in which case dimensions is {"gpu_count": units}.
    dimensions = Column(JSON, nullable=True)
    state = Column(
        String, nullable=False, default=ReservationState.reserved.value, index=True
    )
    deal_ref = Column(JSON, nullable=True)
    escrow_uid = Column(String, nullable=True, index=True)  # lifted from deal_ref
    hold_expires_at = Column(String, nullable=True)  # TTL soft hold (two-phase reserve)
    executor_kind = Column(String, nullable=True)
    executor_target = Column(String, nullable=True)
    release_job_id = Column(String, nullable=True)
    executor_ref = Column(JSON, nullable=True)
    vm_host = Column(String, nullable=True)
    vm_target = Column(String, nullable=True)
    lease_start_utc = Column(String, nullable=True)
    lease_end_utc = Column(String, nullable=True)
    create_job_id = Column(String, nullable=True)
    vm_remove_job_id = Column(String, nullable=True)
    failure_reason = Column(String, nullable=True)
    failure_message = Column(Text, nullable=True)
    released_at = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class CapacityReservationDebit(Base):
    """Current provisioning-private debit backing one capacity reservation."""

    __tablename__ = "capacity_reservation_debits"
    __table_args__ = (
        UniqueConstraint(
            "capacity_reservation_id", name="uq_capacity_reservation_debits_reservation"
        ),
    )

    capacity_reservation_id = Column(
        String,
        ForeignKey("capacity_reservations.capacity_reservation_id", ondelete="CASCADE"),
        primary_key=True,
    )
    capacity_bucket_id = Column(
        String, ForeignKey("capacity_buckets.capacity_bucket_id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    dimensions = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class CapacityEvent(Base):
    """Anonymous, versioned capacity-change feed (pull model).

    One row per availability change; ``version`` is the table's
    monotonically increasing rowid, so subscribers detect gaps and resync
    from a snapshot. Rows carry *that* availability changed and where —
    never whose deal caused it (deal context is delivered point-to-point
    to the owning storefront, not broadcast).
    """

    __tablename__ = "capacity_events"

    version = Column(Integer, primary_key=True, autoincrement=True)
    kind = Column(String, nullable=False)  # "reserved"|"committed"|"released"|"lease_truncated"|"capacity_changed"
    resource_id = Column(String, nullable=True, index=True)
    # Signed per-dimension delta, e.g. {"gpu_count": -1, "vcpu": -4} for a
    # reserve, {"gpu_count": 1, "vcpu": 4} for a release.
    # Null for events that don't change held capacity (e.g. "committed",
    # "lease_truncated") or when no dimensional delta is recorded.
    dimensions = Column(JSON, nullable=True)
    occurred_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
