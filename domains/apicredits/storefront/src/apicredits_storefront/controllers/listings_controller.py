"""Listings controller — credit-listing lifecycle.

Public reads, admin pause/resume, and the seller-signed quota-backed
publish/close verbs. The VM domain's escrow verbs (refund / claim /
reclaim / arbitrate) don't ship here in v1 — the claims engine collects
automatically and there is no lease to refund against.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi_utils.cbv import cbv

from arkhai_api_selling.publish_route import (
    PUBLISH_FROM_QUOTA_OPERATION,
    PUBLISH_FROM_QUOTA_PATH,
    PublishFromQuotaResponse,
)

import apicredits_storefront.container as _container
from apicredits_storefront.container import PublishFromQuotaRequest
from apicredits_storefront.middleware.admin_auth import require_admin_principal
from apicredits_storefront.middleware.seller_auth import make_seller_auth_dep
from core_storefront.models.listing_models import (
    CloseListingResponse,
    ListingListResponse,
    ListingResponse,
    PauseListingResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["listings"])


@cbv(router)
class ListingsController:
    def __init__(
        self,
        db=Depends(lambda: _container.resolved_sqlite_client),
        listing_svc=Depends(lambda: _container.resolved_listing_service),
    ) -> None:
        self._db = db
        self._listing_svc = listing_svc

    @router.get(
        "/listings",
        response_model=ListingListResponse,
        summary="List local listings",
    )
    async def list_listings(
        self,
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
        status: str | None = Query(default=None),
        paused: bool | None = Query(default=None),
    ) -> ListingListResponse:
        listings = await self._db.list_listings(
            status=status,
            paused=paused,
            limit=limit,
            offset=offset,
        )
        return ListingListResponse(
            listings=listings,
            count=len(listings),
            limit=limit,
            offset=offset,
        )

    @router.get(
        "/listings/{listing_id}",
        response_model=ListingResponse,
        summary="Get a single listing",
    )
    async def get_listing(self, listing_id: str) -> ListingResponse:
        row = await self._db.load_listing(listing_id=listing_id)
        if not row:
            raise HTTPException(
                status_code=404,
                detail=f"Listing {listing_id} not found",
            )
        if "paused" not in row:
            row["paused"] = False
        return ListingResponse(**row)

    @router.post(
        "/listings/{listing_id}/pause",
        response_model=PauseListingResponse,
        summary="Pause a listing (admin)",
        dependencies=[Depends(require_admin_principal)],
    )
    async def pause_listing(self, listing_id: str) -> PauseListingResponse:
        row = await self._db.load_listing(listing_id=listing_id)
        if not row:
            raise HTTPException(
                status_code=404,
                detail=f"Listing {listing_id} not found",
            )
        await self._db.set_listing_paused(listing_id=listing_id, paused=True)
        return PauseListingResponse(
            listing_id=listing_id,
            paused=True,
            message="Listing paused. New negotiations will receive 503.",
        )

    @router.post(
        "/listings/{listing_id}/resume",
        response_model=PauseListingResponse,
        summary="Resume a listing and publish to registry (admin)",
        dependencies=[Depends(require_admin_principal)],
    )
    async def resume_listing(self, listing_id: str) -> PauseListingResponse:
        row = await self._db.load_listing(listing_id=listing_id)
        if not row:
            raise HTTPException(
                status_code=404,
                detail=f"Listing {listing_id} not found",
            )
        refusal = _container.QUOTA_PUBLICATION.refusal(row)
        if refusal is not None:
            raise HTTPException(status_code=409, detail=refusal)
        await self._db.set_listing_paused(listing_id=listing_id, paused=False)
        publish_result = await _container.QUOTA_PUBLICATION.publish(self._db, row)
        registry_status = publish_result.get("status", "unknown")
        return PauseListingResponse(
            listing_id=listing_id,
            paused=False,
            registry_status=registry_status,
            message=f"Listing resumed and {registry_status} to registry.",
        )

    @router.post(
        PUBLISH_FROM_QUOTA_PATH.removeprefix(router.prefix),
        response_model=PublishFromQuotaResponse,
        summary="Create + publish a listing backed by a quota resource (seller auth)",
        dependencies=[Depends(make_seller_auth_dep(PUBLISH_FROM_QUOTA_OPERATION))],
    )
    async def publish_from_quota(
        self,
        body: PublishFromQuotaRequest,
    ) -> PublishFromQuotaResponse:
        try:
            result = await self._listing_svc.publish_from_quota(
                resource_id=body.resource_id,
                accepted_escrows=body.accepted_escrows,
                settlement_clauses=body.settlement_clauses,
                paused=body.paused,
                **body.listing_request(),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            logger.error("[LISTINGS] publish unexpected: %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail=str(exc))
        return PublishFromQuotaResponse(**result)

    @router.post(
        "/listings/{listing_id}/close",
        response_model=CloseListingResponse,
        summary="Close a listing (seller auth)",
        dependencies=[Depends(make_seller_auth_dep("close_listing"))],
    )
    async def close_listing(self, listing_id: str) -> CloseListingResponse:
        try:
            result = await self._listing_svc.close_listing(listing_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            logger.error("[LISTINGS] close unexpected: %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail=str(exc))
        return CloseListingResponse(**result)
