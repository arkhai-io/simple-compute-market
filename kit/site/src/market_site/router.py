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
from typing import Any, Callable, Iterable, Mapping

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from .http_models import (
    ReservationListResponse,
    ReservationResponse,
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
    ProjectionIdentityResponse,
    ResourcePoolProjectionResponse,
    CapacityBucketProjectionResponse,
)
from .ledger import CapacityConflictError, CapacityLedgerService
from .projections import SiteProjectionService

logger = logging.getLogger(__name__)


def _storefront_principal(request: Request) -> str:
    return str(
        getattr(request.state, "storefront_principal", "local-development"),
    )


def _public_reservation(
    reservation: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if reservation is None:
        return None
    public = dict(reservation)
    public.pop("owner_principal", None)
    return public


def _require_owned_reservation(
    ledger: CapacityLedgerService,
    capacity_reservation_id: str,
    principal: str,
) -> None:
    if ledger.reservation_owner_principal(capacity_reservation_id) != principal:
        raise HTTPException(
            status_code=404,
            detail=f"reservation {capacity_reservation_id!r} not found",
        )


def make_capacity_router(
    get_ledger: Callable[[], CapacityLedgerService],
    *,
    get_resource_inventory: Callable[[], Iterable[Mapping[str, Any]]] | None = None,
) -> APIRouter:
    """Build the ``/capacity`` router over a ledger provider.

    ``get_ledger`` is called per request (FastAPI dependency), so the
    mounting service may resolve the ledger from its own container.
    """
    router = APIRouter(prefix="/capacity", tags=["capacity"])
    projection_services: dict[int, SiteProjectionService] = {}

    def projections(ledger: CapacityLedgerService) -> SiteProjectionService:
        return projection_services.setdefault(
            id(ledger),
            SiteProjectionService(ledger, resource_inventory=get_resource_inventory),
        )

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

        Compatibility endpoint for domains that register logical capacity
        directly. Physical inventory projections are derived from the
        mounting provisioning service's authoritative inventory provider.
        """
        resource = ledger.register_resource(
            resource_id=resource_id,
            total_units=body.total_units,
            resource_type=body.resource_type,
            resource_subtype=body.resource_subtype,
            pool_id=body.pool_id,
            attributes=body.attributes,
            capacity=body.capacity,
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

    @router.get("/site-resource-pools/version", response_model=ProjectionIdentityResponse)
    def resource_pool_projection_version(
        ledger: CapacityLedgerService = Depends(get_ledger),
    ) -> ProjectionIdentityResponse:
        identity, _ = projections(ledger).resource_pools()
        return ProjectionIdentityResponse(revision=identity.revision, digest=identity.digest)

    @router.get("/site-resource-pools", response_model=ResourcePoolProjectionResponse)
    def resource_pool_projection(
        ledger: CapacityLedgerService = Depends(get_ledger),
    ) -> ResourcePoolProjectionResponse:
        identity, rows = projections(ledger).resource_pools()
        return ResourcePoolProjectionResponse(
            revision=identity.revision, digest=identity.digest, resource_pools=rows
        )

    @router.get("/site-capacity-buckets/version", response_model=ProjectionIdentityResponse)
    def capacity_bucket_projection_version(
        ledger: CapacityLedgerService = Depends(get_ledger),
    ) -> ProjectionIdentityResponse:
        identity, _ = projections(ledger).capacity_buckets()
        return ProjectionIdentityResponse(revision=identity.revision, digest=identity.digest)

    @router.get("/site-capacity-buckets", response_model=CapacityBucketProjectionResponse)
    def capacity_bucket_projection(
        ledger: CapacityLedgerService = Depends(get_ledger),
    ) -> CapacityBucketProjectionResponse:
        identity, rows = projections(ledger).capacity_buckets()
        return CapacityBucketProjectionResponse(
            revision=identity.revision, digest=identity.digest, capacity_buckets=rows
        )

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
        response_model=ReservationResponse,
        summary="Atomically check-and-reserve capacity",
    )
    def reserve(
        body: ReserveRequest,
        request: Request,
        ledger: CapacityLedgerService = Depends(get_ledger),
    ) -> ReservationResponse:
        """Reserve capacity matching the claim.

        Returns ``reservation: null`` (not an error status) when nothing
        matches — "no capacity" is a routine answer the aggregator routes
        around, not an exceptional condition.
        """
        try:
            reservation = ledger.reserve(
                claim=body.claim,
                deal_ref=body.deal_ref,
                ttl_seconds=body.ttl_seconds,
                lease_start_utc=body.lease_start_utc,
                lease_duration_seconds=body.lease_duration_seconds,
                owner_principal=_storefront_principal(request),
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        if reservation is not None:
            reservation = {
                key: value for key, value in reservation.items()
                if key not in {"resource_id", "capacity_bucket_id", "backing_resource_id"}
            }
        return ReservationResponse(reservation=reservation)

    @router.post(
        "/reservations/{capacity_reservation_id}/commit",
        response_model=ReservationResponse,
        summary="Confirm a reservation into an active lease",
    )
    def commit(
        capacity_reservation_id: str,
        body: CommitRequest,
        request: Request,
        ledger: CapacityLedgerService = Depends(get_ledger),
    ) -> ReservationResponse:
        _require_owned_reservation(
            ledger,
            capacity_reservation_id,
            _storefront_principal(request),
        )
        try:
            reservation = ledger.commit(
                resource_id=body.resource_id,
                capacity_reservation_id=capacity_reservation_id,
                lease_start_utc=body.lease_start_utc,
                lease_end_utc=body.lease_end_utc,
                idempotency_ref=body.idempotency_ref,
            )
        except CapacityConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        if reservation is None:
            raise HTTPException(
                status_code=404,
                detail=f"reservation {capacity_reservation_id!r} not found",
            )
        return ReservationResponse(reservation=_public_reservation(reservation))

    @router.post(
        "/releases",
        response_model=ReservationResponse,
        summary="Return held capacity to the pool",
    )
    def release(
        body: ReleaseRequest,
        request: Request,
        ledger: CapacityLedgerService = Depends(get_ledger),
    ) -> ReservationResponse:
        """Release by capacity_reservation_id or by deal ref (escrow_uid).

        Idempotent: releasing an already-released or unknown reservation
        returns ``reservation: null``. A known identifier owned by another
        principal remains indistinguishable from an unknown identifier.
        """
        principal = _storefront_principal(request)
        return ReservationResponse(reservation=_public_reservation(ledger.release(
            capacity_reservation_id=body.capacity_reservation_id,
            deal_ref=body.deal_ref,
            failure_reason=body.failure_reason,
            failure_message=body.failure_message,
            owner_principal=principal,
        )))

    @router.post(
        "/reservations/{capacity_reservation_id}/truncate-lease",
        response_model=ReservationResponse,
        summary="End a lease early",
    )
    def truncate_lease(
        capacity_reservation_id: str,
        body: TruncateLeaseRequest,
        request: Request,
        ledger: CapacityLedgerService = Depends(get_ledger),
    ) -> ReservationResponse:
        """Shorten an active lease (settlement decided the deal is over).

        The injected compute lease watchdog observes the new expiry through the
        normal lease-end path. Returns ``reservation: null`` when the reservation
        is unknown or no longer held.
        """
        _require_owned_reservation(
            ledger,
            capacity_reservation_id,
            _storefront_principal(request),
        )
        return ReservationResponse(reservation=_public_reservation(
            ledger.truncate_lease(
                capacity_reservation_id=capacity_reservation_id,
                lease_end_utc=body.lease_end_utc,
            ),
        ))

    # ------------------------------------------------------------------
    # Reservation reads (deal-side bookkeeping and operators)
    # ------------------------------------------------------------------

    @router.get(
        "/reservations",
        response_model=ReservationListResponse,
        summary="List ledger reservations",
    )
    def list_reservations(
        request: Request,
        state: str | None = Query(default=None),
        escrow_uid: str | None = Query(default=None),
        ledger: CapacityLedgerService = Depends(get_ledger),
    ) -> ReservationListResponse:
        reservations = ledger.list_reservations(
            state=state,
            owner_principal=_storefront_principal(request),
        )
        if escrow_uid is not None:
            reservations = [
                a for a in reservations if a.get("escrow_uid") == escrow_uid
            ]
        return ReservationListResponse(
            reservations=[
                public
                for reservation in reservations
                if (public := _public_reservation(reservation)) is not None
            ],
            total=len(reservations),
        )

    @router.get(
        "/reservations/{capacity_reservation_id}",
        response_model=ReservationResponse,
        summary="Get a ledger reservation",
    )
    def get_reservation(
        capacity_reservation_id: str,
        request: Request,
        ledger: CapacityLedgerService = Depends(get_ledger),
    ) -> ReservationResponse:
        reservation = ledger.get_reservation(
            capacity_reservation_id,
            owner_principal=_storefront_principal(request),
        )
        if reservation is None:
            raise HTTPException(
                status_code=404,
                detail=f"reservation {capacity_reservation_id!r} not found",
            )
        return ReservationResponse(reservation=_public_reservation(reservation))

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
