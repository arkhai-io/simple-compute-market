"""Site-authority capacity API.

All endpoints are under ``/api/v1/capacity`` and mirror the
``core_storefront.capacity.CapacityClient`` contract verb for verb, plus
the resource registry and the versioned event feed (pull model with
snapshot resync — see the design doc's event-model section).

Authentication rides the existing service-wide ``X-Admin-Key``
middleware: capacity is the same trust domain as job submission — a
caller that may create VMs may also reserve the capacity they run on.

Router registration (main.py)::

    app.include_router(CapacityController.make_router(), prefix="/api/v1")
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi_utils.cbv import cbv

import container as _container_module
from models.capacity_model import (
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
from services.capacity_ledger import CapacityConflictError, CapacityLedgerService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/capacity", tags=["capacity"])


@cbv(router)
class CapacityController:
    def __init__(
        self,
        ledger: CapacityLedgerService = Depends(
            lambda: _container_module.resolved_capacity_ledger_service
        ),
    ) -> None:
        self._ledger = ledger

    # ------------------------------------------------------------------
    # Resource registry
    # ------------------------------------------------------------------

    @router.put(
        "/resources/{resource_id}",
        summary="Register or update a ledger resource",
    )
    def register_resource(
        self, resource_id: str, body: ResourceRegisterRequest
    ) -> dict:
        """Upsert a resource row in the site ledger.

        Called by the storefront when inventory is registered (remote
        capacity mode) or by operators/seeding directly.
        """
        resource = self._ledger.register_resource(
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
    def list_resources(self) -> ResourceListResponse:
        resources = self._ledger.list_resources()
        return ResourceListResponse(resources=resources, total=len(resources))

    # ------------------------------------------------------------------
    # CapacityClient verbs
    # ------------------------------------------------------------------

    @router.get(
        "/snapshot",
        response_model=SnapshotResponse,
        summary="Advisory availability snapshot",
    )
    def snapshot(self) -> SnapshotResponse:
        """Negotiation-time policy input; consumes nothing."""
        return SnapshotResponse(resources=self._ledger.snapshot())

    @router.post(
        "/probe",
        response_model=MatchResponse,
        summary="Dry-run claim match",
    )
    def probe(self, body: ProbeRequest) -> MatchResponse:
        try:
            return MatchResponse(match=self._ledger.probe(claim=body.claim))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    @router.post(
        "/reservations",
        response_model=AllocationResponse,
        summary="Atomically check-and-reserve capacity",
    )
    def reserve(self, body: ReserveRequest) -> AllocationResponse:
        """Reserve capacity matching the claim.

        Returns ``allocation: null`` (not an error status) when nothing
        matches — "no capacity" is a routine answer the aggregator routes
        around, not an exceptional condition.
        """
        try:
            allocation = self._ledger.reserve(
                claim=body.claim,
                deal_ref=body.deal_ref,
                ttl_seconds=body.ttl_seconds,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        return AllocationResponse(allocation=allocation)

    @router.post(
        "/allocations/{allocation_id}/commit",
        response_model=AllocationResponse,
        summary="Confirm a reservation into an active lease",
    )
    def commit(self, allocation_id: str, body: CommitRequest) -> AllocationResponse:
        try:
            allocation = self._ledger.commit(
                resource_id=body.resource_id,
                allocation_id=allocation_id,
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
    def release(self, body: ReleaseRequest) -> AllocationResponse:
        """Release by allocation_id or by deal ref (escrow_uid).

        Idempotent: releasing an already-released or unknown allocation
        returns ``allocation: null``.
        """
        return AllocationResponse(allocation=self._ledger.release(
            allocation_id=body.allocation_id,
            deal_ref=body.deal_ref,
        ))

    @router.post(
        "/allocations/{allocation_id}/truncate-lease",
        response_model=AllocationResponse,
        summary="End a lease early",
    )
    def truncate_lease(
        self, allocation_id: str, body: TruncateLeaseRequest
    ) -> AllocationResponse:
        """Shorten an active lease (settlement decided the deal is over).

        The ledger's watchdog picks the new expiry up through the normal
        lease-end path; returns ``allocation: null`` when the allocation
        is unknown or no longer held.
        """
        return AllocationResponse(allocation=self._ledger.truncate_lease(
            allocation_id=allocation_id,
            lease_end_utc=body.lease_end_utc,
        ))

    # ------------------------------------------------------------------
    # Event feed
    # ------------------------------------------------------------------

    @router.get(
        "/events",
        response_model=CapacityEventsResponse,
        summary="Versioned capacity-change feed",
    )
    def events(
        self,
        after: int = Query(default=0, ge=0, description="Last applied version."),
        limit: int = Query(default=500, ge=1, le=5000),
    ) -> CapacityEventsResponse:
        """Anonymous availability deltas newer than ``after``.

        Events carry *that* availability changed and where — never whose
        deal caused it.
        """
        events, latest = self._ledger.events_after(after, limit=limit)
        return CapacityEventsResponse(events=events, latest_version=latest)

    @classmethod
    def make_router(cls) -> APIRouter:
        return router
