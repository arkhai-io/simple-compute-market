"""Schema-opaque HTTP routes owned by the bare-metal composition."""

from __future__ import annotations

import json
from typing import Annotated, Any

from core_storefront.auth import AuthError, verify_admin_key
from core_storefront.models.listing_models import ListingListResponse, ListingResponse
from core_storefront.models.system_models import AdminPauseResponse, HealthResponse
from fastapi import APIRouter, Header, HTTPException, Query, Request

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
