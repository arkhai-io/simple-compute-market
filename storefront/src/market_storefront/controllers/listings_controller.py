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
  POST /api/v1/admin/listings/evaluate-create
  POST /api/v1/admin/listings/{listing_id}/evaluate-close
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi_utils.cbv import cbv

import market_storefront.container as _container
from market_storefront.middleware.admin_auth import require_admin_key
from market_storefront.middleware.seller_auth import make_seller_auth_dep
from market_storefront.models.listing_models import (
    AdminEvaluateCloseResponse,
    AdminEvaluateCreateResponse,
    ArbitrateRequest,
    ArbitrateResponse,
    ClaimRequest,
    ClaimResponse,
    CloseListingResponse,
    CreateListingRequest,
    CreateListingResponse,
    EvaluateNegotiateRequest,
    EvaluateNegotiateResponse,
    ListingFilterParams,
    ListingListResponse,
    ListingResponse,
    PauseListingResponse,
    ReclaimRequest,
    ReclaimResponse,
    RefundRequest,
    RefundResponse,
    listing_filter_params,
)
from market_storefront.utils.listing_filters import matches_listing_filters

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
        policy_svc=Depends(lambda: _container.resolved_policy_service),
    ) -> None:
        self._db = db
        self._listing_svc = listing_svc
        self._policy_svc = policy_svc

    @router.get("/listings", response_model=ListingListResponse, summary="List local listings")
    async def list_listings(
        self,
        params: ListingFilterParams = Depends(listing_filter_params),
    ) -> ListingListResponse:
        spec_kwargs = params.to_spec_kwargs()
        has_spec = bool(spec_kwargs)

        if has_spec:
            all_rows = await self._db.list_listings(
                status=params.status, paused=params.paused, limit=1000, offset=0
            )
            filtered = [r for r in all_rows if matches_listing_filters(r, **spec_kwargs)]
            total = len(filtered)
            listings = filtered[params.offset: params.offset + params.limit]
            return ListingListResponse(
                listings=listings, count=len(listings),
                limit=params.limit, offset=params.offset, total_after_filter=total,
            )

        listings = await self._db.list_listings(
            status=params.status, paused=params.paused,
            limit=params.limit, offset=params.offset,
        )
        return ListingListResponse(
            listings=listings, count=len(listings),
            limit=params.limit, offset=params.offset,
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
        summary="Create a new listing via policy pipeline (seller auth)",
        dependencies=[Depends(make_seller_auth_dep("create_listing"))],
    )
    async def create_listing(self, body: CreateListingRequest) -> CreateListingResponse:
        try:
            result = await self._listing_svc.create_listing(body, self._policy_svc)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            logger.error("[LISTINGS] create unexpected: %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail=str(exc))
        return CreateListingResponse(**result)

    @router.post(
        "/listings/{listing_id}/close",
        response_model=CloseListingResponse,
        summary="Close a listing (seller auth)",
        dependencies=[Depends(make_seller_auth_dep("close_listing"))],
    )
    async def close_listing(self, listing_id: str) -> CloseListingResponse:
        try:
            result = await self._listing_svc.close_listing(listing_id, self._policy_svc)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            logger.error("[LISTINGS] close unexpected: %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail=str(exc))
        return CloseListingResponse(**result)

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
        policy_svc=Depends(lambda: _container.resolved_policy_service),
        _key=Depends(require_admin_key),
    ) -> None:
        self._listing_svc = listing_svc
        self._policy_svc = policy_svc

    @admin_router.post(
        "/evaluate-create",
        response_model=AdminEvaluateCreateResponse,
        summary="What would the policy do for this create request? (no side effects)",
    )
    async def evaluate_create(self, body: CreateListingRequest) -> AdminEvaluateCreateResponse:
        """Consults the policy pipeline without writing to SQLite or the registry.

        Use this to validate that a CreateListingRequest would result in
        a listing being created before actually calling /listings/create.
        """
        try:
            result = await self._listing_svc.evaluate_create(body, self._policy_svc)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            logger.error("[ADMIN] evaluate-create: %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail=str(exc))
        return AdminEvaluateCreateResponse(**result)

    @admin_router.post(
        "/{listing_id}/evaluate-close",
        response_model=AdminEvaluateCloseResponse,
        summary="What would the policy do for a close event? (no side effects)",
    )
    async def evaluate_close(self, listing_id: str) -> AdminEvaluateCloseResponse:
        """Consults the policy pipeline for a close event without writing anything."""
        try:
            result = await self._listing_svc.evaluate_close(listing_id, self._policy_svc)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            logger.error("[ADMIN] evaluate-close: %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail=str(exc))
        return AdminEvaluateCloseResponse(**result)

    @admin_router.post(
        "/{listing_id}/evaluate-negotiate",
        response_model=EvaluateNegotiateResponse,
        summary="What would the negotiation strategy decide for this buyer offer? (no side effects)",
    )
    async def evaluate_negotiate(
        self, listing_id: str, body: EvaluateNegotiateRequest
    ) -> EvaluateNegotiateResponse:
        """Runs the configured negotiation strategy against a synthetic buyer offer.

        Loads the listing from SQLite, extracts the seller's floor price and
        direction, then calls ``strategy.decide()`` — identical to the logic
        in ``start_sync_negotiation`` — without creating a negotiation thread
        or writing anything to the database.

        Use this as the stage-05a dry-run before calling POST /api/v1/negotiate/new.
        A decision of 'exit' means the buyer's price is below the seller's
        acceptable range and the real call would immediately exit.
        """
        from market_storefront.models.domain_models import Listing
        from market_storefront.utils.action_executor import (
            _extract_initial_price_from_order,
            determine_strategy_from_order,
        )
        from market_storefront.utils.sync_negotiation import (
            _load_storefront_strategy,
            _direction_from_strategy_label,
        )
        from market_policy.negotiation_strategy import NegotiationRoundInput

        db = self._listing_svc._db
        try:
            row = await db.load_listing(listing_id=listing_id)
            if not row:
                raise ValueError(f"Listing {listing_id} not found")

            listing = Listing.model_validate(row)
            strategy_label = determine_strategy_from_order(listing)
            if not strategy_label:
                raise ValueError(
                    f"Listing {listing_id} has no usable strategy for negotiation"
                )
            our_price = _extract_initial_price_from_order(listing)
            direction = _direction_from_strategy_label(strategy_label)

            strategy_obj = _load_storefront_strategy()
            strategy_name = type(strategy_obj).__name__
            decision = strategy_obj.decide(NegotiationRoundInput(
                direction=direction,
                our_reference_price=our_price,
                their_proposed_price=body.their_proposed_price,
                history=[],
            ))
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except Exception as exc:
            logger.error("[ADMIN] evaluate-negotiate: %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail=str(exc))

        return EvaluateNegotiateResponse(
            listing_id=listing_id,
            our_reference_price=our_price,
            their_proposed_price=body.their_proposed_price,
            direction=direction,
            strategy=strategy_name,
            decision=decision.action,
            decision_price=decision.price,
            decision_reason=decision.reason,
            would_negotiate=(decision.action != "exit"),
        )
