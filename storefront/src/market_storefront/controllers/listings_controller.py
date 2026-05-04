"""Listings controller — full listing lifecycle API.

Consolidates the former ``ListingsController`` (read/pause/resume) and
``OrdersController`` (create/close/refund/claim/reclaim/arbitrate/discover)
into a single controller, since all operations act on the ``listings``
resource. ``orders_controller.py`` is tombstoned.

Route groups
------------
Read (unauthenticated):
  GET  /api/v1/listings
  GET  /api/v1/listings/{listing_id}

Admin pause/resume (admin key via AdminAuthMiddleware):
  POST /api/v1/listings/{listing_id}/pause
  POST /api/v1/listings/{listing_id}/resume

Listing lifecycle (seller-signed via SellerAuthDepends):
  POST /listings/create
  POST /listings/close
  POST /listings/refund
  POST /listings/claim
  POST /listings/reclaim
  POST /listings/arbitrate
  POST /listings/discover
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi_utils.cbv import cbv

import market_storefront.container as _container
from market_storefront.middleware.seller_auth import make_seller_auth_dep
from market_storefront.models.listing_models import (
    ArbitrateRequest,
    ClaimRequest,
    CloseListingRequest,
    CreateListingRequest,
    DiscoverRequest,
    ListingFilterParams,
    ReclaimRequest,
    RefundRequest,
    listing_filter_params,
)
from market_storefront.utils.listing_filters import matches_listing_filters

logger = logging.getLogger(__name__)

router = APIRouter(tags=["listings"])


@cbv(router)
class ListingsController:
    def __init__(
        self,
        db=Depends(lambda: _container.resolved_sqlite_client),
        listing_svc=Depends(lambda: _container.resolved_listing_service),
        pipeline_svc=Depends(lambda: _container.resolved_policy_pipeline_service),
    ) -> None:
        self._db = db
        self._listing_svc = listing_svc
        self._pipeline_svc = pipeline_svc

    # ------------------------------------------------------------------
    # GET /api/v1/listings
    # ------------------------------------------------------------------

    @router.get("/api/v1/listings", summary="List seller-local listings")
    async def list_listings(
        self,
        params: ListingFilterParams = Depends(listing_filter_params),
    ) -> dict[str, Any]:
        spec_kwargs = params.to_spec_kwargs()
        has_spec = bool(spec_kwargs)

        if has_spec:
            all_rows = await self._db.list_listings(
                status=params.status, paused=params.paused, limit=1000, offset=0
            )
            filtered = [r for r in all_rows if matches_listing_filters(r, **spec_kwargs)]
            total_after_filter = len(filtered)
            listings = filtered[params.offset: params.offset + params.limit]
            return {
                "listings": listings,
                "count": len(listings),
                "limit": params.limit,
                "offset": params.offset,
                "total_after_filter": total_after_filter,
            }

        listings = await self._db.list_listings(
            status=params.status, paused=params.paused,
            limit=params.limit, offset=params.offset,
        )
        return {
            "listings": listings,
            "count": len(listings),
            "limit": params.limit,
            "offset": params.offset,
        }

    # ------------------------------------------------------------------
    # GET /api/v1/listings/{listing_id}
    # ------------------------------------------------------------------

    @router.get("/api/v1/listings/{listing_id}", summary="Get a single listing")
    async def get_listing(self, listing_id: str) -> dict[str, Any]:
        row = await self._db.load_listing(listing_id=listing_id)
        if not row:
            raise HTTPException(status_code=404, detail=f"Listing {listing_id} not found")
        if "paused" not in row:
            row["paused"] = False
        return row

    # ------------------------------------------------------------------
    # POST /api/v1/listings/{listing_id}/pause  (admin key)
    # ------------------------------------------------------------------

    @router.post("/api/v1/listings/{listing_id}/pause", summary="Pause a listing (admin)")
    async def pause_listing(self, listing_id: str) -> dict[str, Any]:
        row = await self._db.load_listing(listing_id=listing_id)
        if not row:
            raise HTTPException(status_code=404, detail=f"Listing {listing_id} not found")
        await self._db.set_listing_paused(listing_id=listing_id, paused=True)
        return {"listing_id": listing_id, "paused": True, "registry_status": "",
                "message": "Listing paused. New negotiations will receive 503."}

    # ------------------------------------------------------------------
    # POST /api/v1/listings/{listing_id}/resume  (admin key)
    # ------------------------------------------------------------------

    @router.post("/api/v1/listings/{listing_id}/resume",
                 summary="Resume a listing and publish to registry (admin)")
    async def resume_listing(self, listing_id: str) -> dict[str, Any]:
        row = await self._db.load_listing(listing_id=listing_id)
        if not row:
            raise HTTPException(status_code=404, detail=f"Listing {listing_id} not found")
        await self._db.set_listing_paused(listing_id=listing_id, paused=False)
        from market_storefront.utils.action_executor import publish_order_to_registry
        publish_result = await publish_order_to_registry(row)
        registry_status = publish_result.get("status", "unknown")
        return {"listing_id": listing_id, "paused": False,
                "registry_status": registry_status,
                "message": f"Listing resumed and {registry_status} to registry."}

    # ------------------------------------------------------------------
    # POST /listings/create  (seller auth)
    # ------------------------------------------------------------------

    @router.post(
        "/listings/create",
        summary="Create a new listing via policy pipeline (seller auth)",
        dependencies=[Depends(make_seller_auth_dep("create_listing"))],
    )
    async def create_listing(self, body: CreateListingRequest) -> dict[str, Any]:
        try:
            return await self._listing_svc.create_listing(body.model_dump(), self._pipeline_svc)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            logger.error("[LISTINGS] create unexpected: %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail=str(exc))

    # ------------------------------------------------------------------
    # POST /listings/close  (seller auth)
    # ------------------------------------------------------------------

    @router.post(
        "/listings/close",
        summary="Close a listing (seller auth)",
        dependencies=[Depends(make_seller_auth_dep("close_listing"))],
    )
    async def close_listing(self, body: CloseListingRequest) -> dict[str, Any]:
        if not body.listing_id.strip():
            raise HTTPException(status_code=400, detail="listing_id must not be empty")
        try:
            return await self._listing_svc.close_listing(body.listing_id, self._pipeline_svc)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            logger.error("[LISTINGS] close unexpected: %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail=str(exc))

    # ------------------------------------------------------------------
    # POST /listings/refund  (seller auth)
    # ------------------------------------------------------------------

    @router.post(
        "/listings/refund",
        summary="Direct token refund to buyer (seller auth)",
        dependencies=[Depends(make_seller_auth_dep("refund_listing"))],
    )
    async def refund(self, body: RefundRequest) -> Any:
        status_code, result = await self._listing_svc.refund(body.model_dump())
        if status_code != 200:
            raise HTTPException(status_code=status_code, detail=result.get("error", "Refund failed"))
        return result

    # ------------------------------------------------------------------
    # POST /listings/claim  (seller auth)
    # ------------------------------------------------------------------

    @router.post(
        "/listings/claim",
        summary="Seller claims on-chain escrow (seller auth)",
        dependencies=[Depends(make_seller_auth_dep("claim_listing"))],
    )
    async def claim(self, body: ClaimRequest) -> Any:
        status_code, result = await self._listing_svc.claim(body.model_dump())
        if status_code != 200:
            raise HTTPException(status_code=status_code, detail=result.get("error", "Claim failed"))
        return result

    # ------------------------------------------------------------------
    # POST /listings/reclaim  (seller auth)
    # ------------------------------------------------------------------

    @router.post(
        "/listings/reclaim",
        summary="Buyer reclaims expired escrow (seller auth)",
        dependencies=[Depends(make_seller_auth_dep("reclaim_listing"))],
    )
    async def reclaim(self, body: ReclaimRequest) -> Any:
        status_code, result = await self._listing_svc.reclaim(body.model_dump())
        if status_code != 200:
            raise HTTPException(status_code=status_code, detail=result.get("error", "Reclaim failed"))
        return result

    # ------------------------------------------------------------------
    # POST /listings/arbitrate  (seller auth)
    # ------------------------------------------------------------------

    @router.post(
        "/listings/arbitrate",
        summary="Oracle arbitration (seller auth)",
        dependencies=[Depends(make_seller_auth_dep("arbitrate_listing"))],
    )
    async def arbitrate(self, body: ArbitrateRequest) -> Any:
        status_code, result = await self._listing_svc.arbitrate(body.model_dump())
        if status_code != 200:
            raise HTTPException(status_code=status_code, detail=result.get("error", "Arbitrate failed"))
        return result

    # ------------------------------------------------------------------
    # POST /listings/discover  (seller auth)
    # ------------------------------------------------------------------

    @router.post(
        "/listings/discover",
        summary="Discover matching counterparty listings (seller auth)",
        dependencies=[Depends(make_seller_auth_dep("discover_listings"))],
    )
    async def discover(self, body: DiscoverRequest) -> Any:
        try:
            status_code, result = await self._listing_svc.discover(body.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        if status_code != 200:
            raise HTTPException(status_code=status_code, detail=result.get("error", "Discover failed"))
        return result
