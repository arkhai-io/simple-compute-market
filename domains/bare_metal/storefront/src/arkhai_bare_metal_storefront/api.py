"""Schema-opaque HTTP routes owned by the bare-metal composition."""

from __future__ import annotations

import json
from typing import Annotated, Any

from core_storefront.auth import AuthError, authenticate_request
from core_storefront.models.listing_models import ListingListResponse, ListingResponse
from core_storefront.models.negotiation_models import (
    NegotiateContinueRequest,
    NegotiateContinueResponse,
    NegotiateNewRequest,
    NegotiateNewResponse,
    NegotiationDetailResponse,
    NegotiationListResponse,
)
from core_storefront.models.system_models import AdminPauseResponse
from fastapi import APIRouter, HTTPException, Query, Request

from market_identity import EMPTY_BODY, Identity

from .models import (
    BareMetalHealthResponse,
    BareMetalSettleRequest,
    BareMetalSettleResponse,
    BareMetalSettleStatusResponse,
)
from .negotiation_service import NegotiationRequestError
from .runtime import BareMetalStorefrontRuntime
from .settlement_service import SettlementRequestError
from .response_auth import bind_response_auth

router = APIRouter()


def _runtime(request: Request) -> BareMetalStorefrontRuntime:
    runtime = getattr(request.app.state, "runtime", None)
    if not isinstance(runtime, BareMetalStorefrontRuntime):
        raise HTTPException(status_code=503, detail="storefront runtime unavailable")
    return runtime


async def _principal(
    *,
    request: Request,
    runtime: BareMetalStorefrontRuntime,
    operation: str,
    resource: str,
    expected_role: str,
    expected_principal: Identity | None = None,
    allowed_principals: tuple[Identity, ...] | None = None,
    body: Any = EMPTY_BODY,
) -> Identity:
    try:
        authenticated = await authenticate_request(
            headers=request.headers,
            method=request.method,
            operation=operation,
            resource=resource,
            body=body,
            expected_role=expected_role,
            replay_store=runtime.db,
            expected_principal=expected_principal,
            allowed_principals=allowed_principals,
        )
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    bind_response_auth(
        request,
        authenticated,
        operation=operation,
        resource=resource,
    )
    if not authenticated.dispatch_allowed:
        raise HTTPException(status_code=409, detail="request was already dispatched")
    return authenticated.principal


async def _buyer(
    *,
    request: Request,
    runtime: BareMetalStorefrontRuntime,
    operation: str,
    resource: str,
    expected_principal: Identity,
    body: Any = EMPTY_BODY,
) -> Identity:
    return await _principal(
        request=request,
        runtime=runtime,
        operation=operation,
        resource=resource,
        body=body,
        expected_role="buyer",
        expected_principal=expected_principal,
    )


async def _admin(
    *,
    request: Request,
    runtime: BareMetalStorefrontRuntime,
    operation: str,
) -> Identity:
    return await _principal(
        request=request,
        runtime=runtime,
        operation=operation,
        resource=request.url.path,
        expected_role="admin",
        allowed_principals=runtime.admin_principals.identities,
    )


def _listing_response(
    runtime: BareMetalStorefrontRuntime, row: dict[str, Any]
) -> dict[str, Any]:
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
        identity = await _buyer(
            request=request,
            runtime=runtime,
            operation="negotiate_new",
            resource=body.listing_id,
            body=body.model_dump(mode="json", exclude_none=True),
            expected_principal=body.buyer_principal,
        )
        return await runtime.negotiation_service().open(
            request=body,
            buyer_principal=identity,
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
    identity = await _buyer(
        request=request,
        runtime=runtime,
        operation="negotiate_continue",
        resource=negotiation_id,
        body=body.model_dump(mode="json", exclude_none=True),
        expected_principal=body.buyer_principal,
    )
    thread = await runtime.db.load_negotiation_thread_row(
        negotiation_id=negotiation_id,
    )
    if thread is None:
        raise HTTPException(status_code=404, detail="negotiation not found")
    if Identity.model_validate(thread.get("buyer_principal")) != identity:
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
    buyer_scheme: str | None = None,
    buyer_identifier: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> NegotiationListResponse:
    runtime = _runtime(request)
    if (buyer_scheme is None) != (buyer_identifier is None):
        raise HTTPException(
            status_code=422,
            detail="buyer_scheme and buyer_identifier must be supplied together",
        )
    try:
        buyer_principal = (
            Identity(scheme=buyer_scheme, identifier=buyer_identifier)
            if buyer_scheme is not None and buyer_identifier is not None
            else None
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="invalid buyer principal") from exc
    if await runtime.db.load_listing(listing_id=listing_id) is None:
        raise HTTPException(status_code=404, detail="listing not found")
    rows = await runtime.db.list_negotiations_for_listing(
        listing_id=listing_id,
        terminal_state=terminal_state,
        buyer_principal=buyer_principal,
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


@router.post(
    "/api/v1/settle/{escrow_uid}",
    response_model=BareMetalSettleResponse,
)
async def settle(
    escrow_uid: str,
    body: BareMetalSettleRequest,
    request: Request,
) -> BareMetalSettleResponse:
    runtime = _runtime(request)
    try:
        identity = await _buyer(
            request=request,
            runtime=runtime,
            operation="settle_escrow",
            resource=escrow_uid,
            body=body.model_dump(mode="json", exclude_none=True),
            expected_principal=body.buyer_principal,
        )
        return await runtime.settlement_service().verify(
            escrow_uid=escrow_uid,
            request=body,
            buyer_principal=identity,
        )
    except (AuthError, SettlementRequestError) as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get(
    "/api/v1/settle/{escrow_uid}/status",
    response_model=BareMetalSettleStatusResponse,
)
async def settle_status(
    escrow_uid: str,
    request: Request,
) -> BareMetalSettleStatusResponse:
    runtime = _runtime(request)
    try:
        escrow = await runtime.db.load_escrow(escrow_uid=escrow_uid)
        if escrow is None:
            raise SettlementRequestError("escrow not found", status_code=404)
        thread = await runtime.db.load_negotiation_thread_row(
            negotiation_id=str(escrow["negotiation_id"]),
        )
        if thread is None:
            raise SettlementRequestError("negotiation not found", status_code=404)
        identity = await _buyer(
            request=request,
            runtime=runtime,
            operation="settle_status",
            expected_principal=Identity.model_validate(thread["buyer_principal"]),
            resource=escrow_uid,
        )
        return await runtime.settlement_service().status(
            escrow_uid=escrow_uid,
            buyer_principal=identity,
        )
    except (AuthError, SettlementRequestError) as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/health", response_model=BareMetalHealthResponse)
@router.get("/api/v1/system/health", response_model=BareMetalHealthResponse)
async def health(request: Request) -> BareMetalHealthResponse:
    return BareMetalHealthResponse.model_validate(await _runtime(request).health())


@router.get("/api/v1/system/status", response_model=BareMetalHealthResponse)
async def system_status(request: Request) -> BareMetalHealthResponse:
    runtime = _runtime(request)
    await _admin(request=request, runtime=runtime, operation="system_status")
    return BareMetalHealthResponse.model_validate(await runtime.health())


@router.post("/api/v1/admin/pause", response_model=AdminPauseResponse)
async def pause(request: Request) -> AdminPauseResponse:
    runtime = _runtime(request)
    await _admin(request=request, runtime=runtime, operation="pause")
    await runtime.db.set_global_paused(paused=True)
    return AdminPauseResponse(paused=True, message="storefront paused")


@router.post("/api/v1/admin/resume", response_model=AdminPauseResponse)
async def resume(request: Request) -> AdminPauseResponse:
    runtime = _runtime(request)
    await _admin(request=request, runtime=runtime, operation="resume")
    await runtime.db.set_global_paused(paused=False)
    return AdminPauseResponse(paused=False, message="storefront resumed")
