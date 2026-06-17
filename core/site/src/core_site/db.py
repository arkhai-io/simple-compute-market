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

from sqlalchemy import JSON, Boolean, Column, DateTime, Integer, String, Text
from sqlalchemy.orm import declarative_base
from sqlalchemy.sql import func

Base = declarative_base()


class AllocationState(str, enum.Enum):
    """Lifecycle states for a site-ledger allocation.

    The allocation row is the merged ledger entry the capacity design doc
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
HELD_ALLOCATION_STATES = (
    AllocationState.reserved.value,
    AllocationState.provisioning.value,
    AllocationState.leased.value,
    AllocationState.releasing.value,
    AllocationState.release_failed.value,
    AllocationState.unmanaged.value,
)


class SiteResource(Base):
    """A unit-counted resource in the site authority's ledger.

    Resource-domain only: the attributes JSON speaks the site's vocabulary
    (vm_host, gpu_model, region, …) and never market schema (pricing,
    accepted escrows stay on the storefront side of the boundary).
    """

    __tablename__ = "site_resources"

    resource_id = Column(String, primary_key=True)
    resource_type = Column(String, nullable=False, default="compute.gpu")
    resource_subtype = Column(String, nullable=True)  # e.g. "h200"
    total_units = Column(Integer, nullable=False, default=0)
    attributes = Column(JSON, nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SiteAllocation(Base):
    """A capacity hold and its lease tail, as one ledger row.

    Merges the storefront's ``compute_allocations`` shape with the lease
    fields previously duplicated into ``vm_leases``: when the watchdog
    releases an expired lease it updates *this* row locally and emits
    events, instead of PATCHing the storefront's resource table.

    deal_ref is the opaque mapping the storefront passed at reserve time
    (listing_id, escrow_uid, owner callback) — the ledger never interprets
    it beyond routing deal-scoped events back to the owning storefront.
    Timestamps are ISO-8601 TEXT, matching the storefront ledger they
    replace; the allocation count per site is small enough to compare in
    Python.
    """

    __tablename__ = "site_allocations"

    allocation_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    resource_id = Column(String, nullable=False, index=True)
    units = Column(Integer, nullable=False, default=1)
    state = Column(
        String, nullable=False, default=AllocationState.reserved.value, index=True
    )
    deal_ref = Column(JSON, nullable=True)
    escrow_uid = Column(String, nullable=True, index=True)  # lifted from deal_ref
    hold_expires_at = Column(String, nullable=True)  # TTL soft hold (two-phase reserve)
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
    kind = Column(String, nullable=False)  # "reserved"|"committed"|"released"|"lease_truncated"
    resource_id = Column(String, nullable=True, index=True)
    occurred_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
