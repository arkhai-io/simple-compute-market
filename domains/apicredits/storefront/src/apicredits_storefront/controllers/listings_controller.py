"""Listings: public reads, the administrator's pause and resume, the seller's publish and close."""

from __future__ import annotations

from arkhai_api_selling.publish_route import (
    PUBLISH_FROM_QUOTA_OPERATION,
    PUBLISH_FROM_QUOTA_PATH,
    PublishFromQuotaResponse,
)
from core_storefront.models.listing_models import (
    CloseListingResponse,
    ListingListResponse,
    ListingResponse,
    PauseListingResponse,
)
from fastapi import APIRouter, Depends, Query
from fastapi_utils.cbv import cbv

import apicredits_storefront.container as _container
from apicredits_storefront.container import PublishFromQuotaRequest
from apicredits_storefront.controllers.binding import serve

router = APIRouter(prefix="/api/v1", tags=["listings"])


@cbv(router)
class ListingsController:
    @router.get("/listings", response_model=ListingListResponse, summary="List local listings")
    async def list_listings(
        self,
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
        status: str | None = Query(default=None),
        paused: bool | None = Query(default=None),
    ) -> ListingListResponse:
        return await serve(
            _container.LISTING_ROUTES.list(limit=limit, offset=offset, status=status, paused=paused)
        )

    @router.get("/listings/{listing_id}", response_model=ListingResponse, summary="Get a single listing")
    async def get_listing(self, listing_id: str) -> ListingResponse:
        return await serve(_container.LISTING_ROUTES.get(listing_id))

    @router.post(
        "/listings/{listing_id}/pause",
        response_model=PauseListingResponse,
        summary="Pause a listing (admin)",
        dependencies=[Depends(_container.AUTH.require_admin_principal)],
    )
    async def pause_listing(self, listing_id: str) -> PauseListingResponse:
        return await serve(_container.LISTING_ROUTES.pause(listing_id))

    @router.post(
        "/listings/{listing_id}/resume",
        response_model=PauseListingResponse,
        summary="Resume a listing and publish to registry (admin)",
        dependencies=[Depends(_container.AUTH.require_admin_principal)],
    )
    async def resume_listing(self, listing_id: str) -> PauseListingResponse:
        return await serve(_container.LISTING_ROUTES.resume(listing_id))

    @router.post(
        PUBLISH_FROM_QUOTA_PATH.removeprefix(router.prefix),
        response_model=PublishFromQuotaResponse,
        summary="Create + publish a listing backed by a quota resource (seller auth)",
        dependencies=[Depends(_container.AUTH.seller_dependency(PUBLISH_FROM_QUOTA_OPERATION))],
    )
    async def publish_from_quota(self, body: PublishFromQuotaRequest) -> PublishFromQuotaResponse:
        return await serve(_container.LISTING_ROUTES.publish_from_quota(body))

    @router.post(
        "/listings/{listing_id}/close",
        response_model=CloseListingResponse,
        summary="Close a listing (seller auth)",
        dependencies=[Depends(_container.AUTH.seller_dependency("close_listing"))],
    )
    async def close_listing(self, listing_id: str) -> CloseListingResponse:
        return await serve(_container.LISTING_ROUTES.close(listing_id))
