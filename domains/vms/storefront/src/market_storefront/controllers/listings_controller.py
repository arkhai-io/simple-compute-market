"""Listings controller — full listing lifecycle.

All routes use the /api/v1/ prefix consistently with the rest of the API.
listing_id is always a path parameter (never in the request body).

Route groups
------------
Public read (no auth):
  GET  /api/v1/listings
  GET  /api/v1/listings/{listing_id}

Admin pause/resume (X-Admin-Key):
  POST /api/v1/listings/{listing_id}/pause
  POST /api/v1/listings/{listing_id}/resume

Seller lifecycle (EIP-191 seller-signed):
  POST /api/v1/listings/create
  POST /api/v1/listings/{listing_id}/close
  POST /api/v1/listings/{listing_id}/refund
  POST /api/v1/listings/{listing_id}/claim
  POST /api/v1/listings/{listing_id}/reclaim
  POST /api/v1/listings/{listing_id}/arbitrate

Admin evaluation (X-Admin-Key, no side effects):
  POST /api/v1/admin/listings/{listing_id}/evaluate-negotiate
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi_utils.cbv import cbv

import market_storefront.container as _container
from market_storefront.middleware.admin_auth import require_admin_key
from market_storefront.middleware.seller_auth import make_seller_auth_dep
from market_storefront.models.listing_models import (
    ArbitrateRequest,
    ArbitrateResponse,
    ClaimRequest,
    ClaimResponse,
    CloseListingResponse,
    CreateListingRequest,
    CreateListingResponse,
    EvaluateNegotiateRequest,
    EvaluateNegotiateResponse,
    ListingListResponse,
    ListingResponse,
    PauseListingResponse,
    ReclaimRequest,
    ReclaimResponse,
    RefundRequest,
    RefundResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["listings"])
admin_router = APIRouter(prefix="/api/v1/admin/listings", tags=["admin-listings"])


# ---------------------------------------------------------------------------
# Public read endpoints
# ---------------------------------------------------------------------------

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
        summary="List local listings (resource enumeration, not discovery)",
        description=(
            "Enumerates the seller's own listing resources.  Discovery vocabulary "
            "(gpu_model, region, token, etc.) moved to registries with milestone "
            "(a1b) — query `/filter-spec` and `/listings` on a registry for that."
        ),
    )
    async def list_listings(
        self,
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
        status: str | None = Query(default=None),
        paused: bool | None = Query(default=None),
    ) -> ListingListResponse:
        listings = await self._db.list_listings(
            status=status, paused=paused, limit=limit, offset=offset,
        )
        return ListingListResponse(
            listings=listings, count=len(listings),
            limit=limit, offset=offset,
        )

    @router.get(
        "/listings/{listing_id}",
        response_model=ListingResponse,
        summary="Get a single listing",
    )
    async def get_listing(self, listing_id: str) -> ListingResponse:
        row = await self._db.load_listing(listing_id=listing_id)
        if not row:
            raise HTTPException(status_code=404, detail=f"Listing {listing_id} not found")
        if "paused" not in row:
            row["paused"] = False
        return ListingResponse(**row)

    @router.post(
        "/listings/{listing_id}/pause",
        response_model=PauseListingResponse,
        summary="Pause a listing (admin)",
        dependencies=[Depends(require_admin_key)],
    )
    async def pause_listing(self, listing_id: str) -> PauseListingResponse:
        row = await self._db.load_listing(listing_id=listing_id)
        if not row:
            raise HTTPException(status_code=404, detail=f"Listing {listing_id} not found")
        await self._db.set_listing_paused(listing_id=listing_id, paused=True)
        return PauseListingResponse(
            listing_id=listing_id, paused=True,
            message="Listing paused. New negotiations will receive 503.",
        )

    @router.post(
        "/listings/{listing_id}/resume",
        response_model=PauseListingResponse,
        summary="Resume a listing and publish to registry (admin)",
        dependencies=[Depends(require_admin_key)],
    )
    async def resume_listing(self, listing_id: str) -> PauseListingResponse:
        row = await self._db.load_listing(listing_id=listing_id)
        if not row:
            raise HTTPException(status_code=404, detail=f"Listing {listing_id} not found")
        await self._db.set_listing_paused(listing_id=listing_id, paused=False)
        from market_storefront.utils.action_executor import publish_order_to_registry
        publish_result = await publish_order_to_registry(row)
        registry_status = publish_result.get("status", "unknown")
        return PauseListingResponse(
            listing_id=listing_id, paused=False,
            registry_status=registry_status,
            message=f"Listing resumed and {registry_status} to registry.",
        )

    @router.post(
        "/listings/create",
        response_model=CreateListingResponse,
        summary="Create a new listing (seller auth)",
        dependencies=[Depends(make_seller_auth_dep("create_listing"))],
    )
    async def create_listing(self, body: CreateListingRequest) -> CreateListingResponse:
        try:
            result = await self._listing_svc.create_listing(body)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            logger.error("[LISTINGS] create unexpected: %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail=str(exc))
        return result

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
        return result

    @router.post(
        "/listings/{listing_id}/refund",
        response_model=RefundResponse,
        summary="Direct token refund to buyer (seller auth)",
        dependencies=[Depends(make_seller_auth_dep("refund_listing"))],
    )
    async def refund(self, listing_id: str, body: RefundRequest) -> RefundResponse:
        status_code, result = await self._listing_svc.refund(
            listing_id=listing_id, payload=body
        )
        if status_code != 200:
            raise HTTPException(status_code=status_code, detail=result.get("error", "Refund failed"))
        return RefundResponse(**result)

    @router.post(
        "/listings/{listing_id}/claim",
        response_model=ClaimResponse,
        summary="Seller claims on-chain escrow (seller auth)",
        dependencies=[Depends(make_seller_auth_dep("claim_listing"))],
    )
    async def claim(self, listing_id: str, body: ClaimRequest) -> ClaimResponse:
        status_code, result = await self._listing_svc.claim(
            listing_id=listing_id, payload=body
        )
        if status_code != 200:
            raise HTTPException(status_code=status_code, detail=result.get("error", "Claim failed"))
        return ClaimResponse(**result)

    @router.post(
        "/listings/{listing_id}/reclaim",
        response_model=ReclaimResponse,
        summary="Buyer reclaims expired escrow (seller auth)",
        dependencies=[Depends(make_seller_auth_dep("reclaim_listing"))],
    )
    async def reclaim(self, listing_id: str, body: ReclaimRequest) -> ReclaimResponse:
        status_code, result = await self._listing_svc.reclaim(
            listing_id=listing_id, payload=body
        )
        if status_code != 200:
            raise HTTPException(status_code=status_code, detail=result.get("error", "Reclaim failed"))
        return ReclaimResponse(**result)

    @router.post(
        "/listings/{listing_id}/arbitrate",
        response_model=ArbitrateResponse,
        summary="Oracle arbitration (seller auth)",
        dependencies=[Depends(make_seller_auth_dep("arbitrate_listing"))],
    )
    async def arbitrate(self, listing_id: str, body: ArbitrateRequest) -> ArbitrateResponse:
        status_code, result = await self._listing_svc.arbitrate(
            listing_id=listing_id, payload=body
        )
        if status_code != 200:
            raise HTTPException(status_code=status_code, detail=result.get("error", "Arbitrate failed"))
        return ArbitrateResponse(**result)


# ---------------------------------------------------------------------------
# Admin evaluation endpoints (no side effects)
# ---------------------------------------------------------------------------

@cbv(admin_router)
class AdminListingsController:
    def __init__(
        self,
        listing_svc=Depends(lambda: _container.resolved_listing_service),
        _key=Depends(require_admin_key),
    ) -> None:
        self._listing_svc = listing_svc

    @admin_router.post(
        "/{listing_id}/evaluate-negotiate",
        response_model=EvaluateNegotiateResponse,
        summary="What would the negotiation strategy decide for this buyer offer? (no side effects)",
    )
    async def evaluate_negotiate(
        self, listing_id: str, body: EvaluateNegotiateRequest
    ) -> EvaluateNegotiateResponse:
        """Dry-run the seller's round-0 negotiation decision without creating a thread.

        Delegates to ``ListingService.evaluate_negotiate``, which calls
        ``_compute_round_zero_decision`` — the same pure-compute function used
        by the real ``/negotiate/new`` flow. The result is identical to what
        round 0 of a real negotiation would produce for the given price.

        Returns HTTP 404 if the listing doesn't exist or has no usable strategy.
        """
        try:
            return await self._listing_svc.evaluate_negotiate(
                listing_id,
                body.proposal,
                requested_duration_seconds=body.requested_duration_seconds,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except Exception as exc:
            logger.error("[ADMIN] evaluate-negotiate: %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail=str(exc))
