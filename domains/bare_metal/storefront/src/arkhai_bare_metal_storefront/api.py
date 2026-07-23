"""Schema-opaque HTTP routes owned by the bare-metal composition."""

from __future__ import annotations

import json
from typing import Annotated, Any

from core_storefront.auth import (
    AuthError,
    verify_admin_key,
    verify_buyer_signature,
)
from core_storefront.models.listing_models import ListingListResponse, ListingResponse
from core_storefront.models.negotiation_models import (
    NegotiateContinueRequest,
    NegotiateContinueResponse,
    NegotiateNewRequest,
    NegotiateNewResponse,
    NegotiationDetailResponse,
    NegotiationListResponse,
)
from core_storefront.models.system_models import AdminPauseResponse, HealthResponse
from fastapi import APIRouter, Header, HTTPException, Query, Request

from .negotiation_service import NegotiationRequestError
from .runtime import BareMetalStorefrontRuntime

router = APIRouter()


def _runtime(request: Request) -> BareMetalStorefrontRuntime:
    runtime = getattr(request.app.state, "runtime", None)
    if not isinstance(runtime, BareMetalStorefrontRuntime):
        raise HTTPException(status_code=503, detail="storefront runtime unavailable")
    return runtime


def _admin(runtime: BareMetalStorefrontRuntime, supplied: str | None) -> None:
    try:
        verify_admin_key(configured=runtime.admin_key, supplied=supplied)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


def _listing_response(runtime: BareMetalStorefrontRuntime, row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("offer_resource")
    if isinstance(raw, str):
        raw = json.loads(raw)
    listing = runtime.domain.codecs.listing(raw)
    normalized = dict(row)
    normalized["offer_resource"] = listing.model_dump(mode="json", exclude_none=True)
    return normalized


@router.get("/api/v1/listings", response_model=ListingListResponse)
async def list_listings(
    request: Request,
    status: str | None = None,
    paused: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ListingListResponse:
    runtime = _runtime(request)
    rows = await runtime.db.list_listings(
        status=status,
        paused=paused,
        limit=limit,
        offset=offset,
    )
    listings = [_listing_response(runtime, row) for row in rows]
    return ListingListResponse(
        listings=listings,
        count=len(listings),
        limit=limit,
        offset=offset,
        total_after_filter=len(listings),
    )


@router.get("/api/v1/listings/{listing_id}", response_model=ListingResponse)
async def get_listing(listing_id: str, request: Request) -> ListingResponse:
    runtime = _runtime(request)
    row = await runtime.db.load_listing(listing_id=listing_id)
    if row is None:
        raise HTTPException(status_code=404, detail="listing not found")
    return ListingResponse.model_validate(_listing_response(runtime, row))


@router.post("/api/v1/negotiate/new", response_model=NegotiateNewResponse)
async def negotiate_new(
    body: NegotiateNewRequest,
    request: Request,
) -> NegotiateNewResponse:
    runtime = _runtime(request)
    try:
        identity = verify_buyer_signature(
            headers=request.headers,
            operation="negotiate_new",
            resource_id=body.listing_id,
            claimed_address=body.buyer_address,
        )
        return await runtime.negotiation_service().open(
            request=body,
            buyer_identity=identity.identifier,
        )
    except (AuthError, NegotiationRequestError) as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post(
    "/api/v1/negotiate/{negotiation_id}",
    response_model=NegotiateContinueResponse,
)
async def negotiate_continue(
    negotiation_id: str,
    body: NegotiateContinueRequest,
    request: Request,
) -> NegotiateContinueResponse:
    runtime = _runtime(request)
    try:
        identity = verify_buyer_signature(
            headers=request.headers,
            operation="negotiate_continue",
            resource_id=negotiation_id,
            claimed_address=body.buyer_address,
        )
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    thread = await runtime.db.load_negotiation_thread_row(
        negotiation_id=negotiation_id,
    )
    if thread is None:
        raise HTTPException(status_code=404, detail="negotiation not found")
    if thread.get("buyer") != identity.identifier:
        raise HTTPException(status_code=403, detail="negotiation buyer mismatch")
    if thread.get("terminal_state") is not None:
        raise HTTPException(status_code=409, detail="negotiation is terminal")
    raise HTTPException(
        status_code=409,
        detail="default bare-metal policy does not support additional rounds",
    )


@router.get(
    "/api/v1/listings/{listing_id}/negotiations",
    response_model=NegotiationListResponse,
)
async def list_negotiations(
    listing_id: str,
    request: Request,
    terminal_state: str | None = None,
    buyer_address: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> NegotiationListResponse:
    runtime = _runtime(request)
    if await runtime.db.load_listing(listing_id=listing_id) is None:
        raise HTTPException(status_code=404, detail="listing not found")
    rows = await runtime.db.list_negotiations_for_listing(
        listing_id=listing_id,
        terminal_state=terminal_state,
        buyer_address=buyer_address,
        limit=limit,
        offset=offset,
    )
    return NegotiationListResponse(
        listing_id=listing_id,
        negotiations=rows,
        count=len(rows),
        limit=limit,
        offset=offset,
    )


@router.get(
    "/api/v1/listings/{listing_id}/negotiations/{negotiation_id}",
    response_model=NegotiationDetailResponse,
)
async def get_negotiation(
    listing_id: str,
    negotiation_id: str,
    request: Request,
) -> NegotiationDetailResponse:
    detail = await _runtime(request).db.load_negotiation_detail(
        listing_id=listing_id,
        neg_id=negotiation_id,
    )
    if detail is None:
        raise HTTPException(status_code=404, detail="negotiation not found")
    return NegotiationDetailResponse.model_validate(detail)


@router.get("/health", response_model=HealthResponse)
@router.get("/api/v1/system/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    return HealthResponse.model_validate(await _runtime(request).health())


@router.get("/api/v1/system/status", response_model=HealthResponse)
async def system_status(
    request: Request,
    x_admin_key: Annotated[str | None, Header()] = None,
) -> HealthResponse:
    runtime = _runtime(request)
    _admin(runtime, x_admin_key)
    return HealthResponse.model_validate(await runtime.health())


@router.post("/api/v1/admin/pause", response_model=AdminPauseResponse)
async def pause(
    request: Request,
    x_admin_key: Annotated[str | None, Header()] = None,
) -> AdminPauseResponse:
    runtime = _runtime(request)
    _admin(runtime, x_admin_key)
    await runtime.db.set_global_paused(paused=True)
    return AdminPauseResponse(paused=True, message="storefront paused")


@router.post("/api/v1/admin/resume", response_model=AdminPauseResponse)
async def resume(
    request: Request,
    x_admin_key: Annotated[str | None, Header()] = None,
) -> AdminPauseResponse:
    runtime = _runtime(request)
    _admin(runtime, x_admin_key)
    await runtime.db.set_global_paused(paused=False)
    return AdminPauseResponse(paused=False, message="storefront resumed")
