"""Site-authority capacity API router.

All endpoints are under ``/capacity`` (mount with ``prefix="/api/v1"``)
and mirror the ``core_storefront.capacity.CapacityClient`` contract verb
for verb, plus the resource registry and the versioned event feed (pull
model with snapshot resync).

Authentication is the mounting service's concern: capacity is the same
trust domain as job submission — a caller that may create workloads may
also reserve the capacity they run on — so the host service's existing
admin middleware covers this router when mounted on the same app.

Router registration::

    app.include_router(
        make_capacity_router(lambda: resolved_ledger), prefix="/api/v1",
    )
"""

from __future__ import annotations

import logging
from typing import Callable

from fastapi import APIRouter, Depends, HTTPException, Query

from .http_models import (
    AllocationListResponse,
    AllocationResponse,
    CapacityEventsResponse,
    CommitRequest,
    MatchResponse,
    ProbeRequest,
    ReleaseRequest,
    ReserveRequest,
    ResourceListResponse,
    ResourceRegisterRequest,
    SnapshotResponse,
    TruncateLeaseRequest,
)
from .ledger import CapacityConflictError, CapacityLedgerService

logger = logging.getLogger(__name__)


def make_capacity_router(
    get_ledger: Callable[[], CapacityLedgerService],
) -> APIRouter:
    """Build the ``/capacity`` router over a ledger provider.

    ``get_ledger`` is called per request (FastAPI dependency), so the
    mounting service may resolve the ledger from its own container.
    """
    router = APIRouter(prefix="/capacity", tags=["capacity"])

    # ------------------------------------------------------------------
    # Resource registry
    # ------------------------------------------------------------------

    @router.put(
        "/resources/{resource_id}",
        summary="Register or update a ledger resource",
    )
    def register_resource(
        resource_id: str,
        body: ResourceRegisterRequest,
        ledger: CapacityLedgerService = Depends(get_ledger),
    ) -> dict:
        """Upsert a resource row in the site ledger.

        Called by the storefront when inventory is registered (remote
        capacity mode) or by operators/seeding directly.
        """
        resource = ledger.register_resource(
            resource_id=resource_id,
            total_units=body.total_units,
            resource_type=body.resource_type,
            resource_subtype=body.resource_subtype,
            attributes=body.attributes,
            enabled=body.enabled,
        )
        logger.info(
            "[CAPACITY] Registered resource %s (units=%d enabled=%s)",
            resource_id, body.total_units, body.enabled,
        )
        return resource

    @router.get(
        "/resources",
        response_model=ResourceListResponse,
        summary="List ledger resources with availability",
    )
    def list_resources(
        ledger: CapacityLedgerService = Depends(get_ledger),
    ) -> ResourceListResponse:
        resources = ledger.list_resources()
        return ResourceListResponse(resources=resources, total=len(resources))

    # ------------------------------------------------------------------
    # CapacityClient verbs
    # ------------------------------------------------------------------

    @router.get(
        "/snapshot",
        response_model=SnapshotResponse,
        summary="Advisory availability snapshot",
    )
    def snapshot(
        ledger: CapacityLedgerService = Depends(get_ledger),
    ) -> SnapshotResponse:
        """Negotiation-time policy input; consumes nothing."""
        return SnapshotResponse(resources=ledger.snapshot())

    @router.post(
        "/probe",
        response_model=MatchResponse,
        summary="Dry-run claim match",
    )
    def probe(
        body: ProbeRequest,
        ledger: CapacityLedgerService = Depends(get_ledger),
    ) -> MatchResponse:
        try:
            return MatchResponse(match=ledger.probe(
                claim=body.claim,
                lease_start_utc=body.lease_start_utc,
                lease_duration_seconds=body.lease_duration_seconds,
            ))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    @router.post(
        "/reservations",
        response_model=AllocationResponse,
        summary="Atomically check-and-reserve capacity",
    )
    def reserve(
        body: ReserveRequest,
        ledger: CapacityLedgerService = Depends(get_ledger),
    ) -> AllocationResponse:
        """Reserve capacity matching the claim.

        Returns ``allocation: null`` (not an error status) when nothing
        matches — "no capacity" is a routine answer the aggregator routes
        around, not an exceptional condition.
        """
        try:
            allocation = ledger.reserve(
                claim=body.claim,
                deal_ref=body.deal_ref,
                ttl_seconds=body.ttl_seconds,
                lease_start_utc=body.lease_start_utc,
                lease_duration_seconds=body.lease_duration_seconds,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        return AllocationResponse(allocation=allocation)

    @router.post(
        "/allocations/{allocation_id}/commit",
        response_model=AllocationResponse,
        summary="Confirm a reservation into an active lease",
    )
    def commit(
        allocation_id: str,
        body: CommitRequest,
        ledger: CapacityLedgerService = Depends(get_ledger),
    ) -> AllocationResponse:
        try:
            allocation = ledger.commit(
                resource_id=body.resource_id,
                allocation_id=allocation_id,
                lease_start_utc=body.lease_start_utc,
                lease_end_utc=body.lease_end_utc,
                idempotency_ref=body.idempotency_ref,
            )
        except CapacityConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        if allocation is None:
            raise HTTPException(
                status_code=404,
                detail=f"allocation {allocation_id!r} not found",
            )
        return AllocationResponse(allocation=allocation)

    @router.post(
        "/releases",
        response_model=AllocationResponse,
        summary="Return held capacity to the pool",
    )
    def release(
        body: ReleaseRequest,
        ledger: CapacityLedgerService = Depends(get_ledger),
    ) -> AllocationResponse:
        """Release by allocation_id or by deal ref (escrow_uid).

        Idempotent: releasing an already-released or unknown allocation
        returns ``allocation: null``.
        """
        return AllocationResponse(allocation=ledger.release(
            allocation_id=body.allocation_id,
            deal_ref=body.deal_ref,
            failure_reason=body.failure_reason,
            failure_message=body.failure_message,
        ))

    @router.post(
        "/allocations/{allocation_id}/truncate-lease",
        response_model=AllocationResponse,
        summary="End a lease early",
    )
    def truncate_lease(
        allocation_id: str,
        body: TruncateLeaseRequest,
        ledger: CapacityLedgerService = Depends(get_ledger),
    ) -> AllocationResponse:
        """Shorten an active lease (settlement decided the deal is over).

        The ledger's watchdog picks the new expiry up through the normal
        lease-end path; returns ``allocation: null`` when the allocation
        is unknown or no longer held.
        """
        return AllocationResponse(allocation=ledger.truncate_lease(
            allocation_id=allocation_id,
            lease_end_utc=body.lease_end_utc,
        ))

    # ------------------------------------------------------------------
    # Allocation reads (deal-side bookkeeping and operators)
    # ------------------------------------------------------------------

    @router.get(
        "/allocations",
        response_model=AllocationListResponse,
        summary="List ledger allocations",
    )
    def list_allocations(
        state: str | None = Query(default=None),
        escrow_uid: str | None = Query(default=None),
        ledger: CapacityLedgerService = Depends(get_ledger),
    ) -> AllocationListResponse:
        allocations = ledger.list_allocations(state=state)
        if escrow_uid is not None:
            allocations = [
                a for a in allocations if a.get("escrow_uid") == escrow_uid
            ]
        return AllocationListResponse(
            allocations=allocations, total=len(allocations),
        )

    @router.get(
        "/allocations/{allocation_id}",
        response_model=AllocationResponse,
        summary="Get a ledger allocation",
    )
    def get_allocation(
        allocation_id: str,
        ledger: CapacityLedgerService = Depends(get_ledger),
    ) -> AllocationResponse:
        allocation = ledger.get_allocation(allocation_id)
        if allocation is None:
            raise HTTPException(
                status_code=404,
                detail=f"allocation {allocation_id!r} not found",
            )
        return AllocationResponse(allocation=allocation)

    # ------------------------------------------------------------------
    # Event feed
    # ------------------------------------------------------------------

    @router.get(
        "/events",
        response_model=CapacityEventsResponse,
        summary="Versioned capacity-change feed",
    )
    def events(
        after: int = Query(default=0, ge=0, description="Last applied version."),
        limit: int = Query(default=500, ge=1, le=5000),
        ledger: CapacityLedgerService = Depends(get_ledger),
    ) -> CapacityEventsResponse:
        """Anonymous availability deltas newer than ``after``.

        Events carry *that* availability changed and where — never whose
        deal caused it.
        """
        events, latest = ledger.events_after(after, limit=limit)
        return CapacityEventsResponse(events=events, latest_version=latest)

    return router
