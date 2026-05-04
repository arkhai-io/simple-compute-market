"""Negotiations controller — admin read/control API for negotiation threads."""
from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi_utils.cbv import cbv

import market_storefront.container as _container
from market_storefront.models.negotiation_models import AdvanceRequest, ForceAcceptRequest
from market_storefront.services.negotiation_service import NegotiationServiceError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/listings", tags=["negotiations"])


@cbv(router)
class NegotiationsController:
    def __init__(
        self,
        neg_svc=Depends(lambda: _container.resolved_negotiation_service),
    ) -> None:
        self._svc = neg_svc

    @router.get("/{listing_id}/negotiations", summary="List negotiations for a listing")
    async def list_negotiations(
        self,
        listing_id: str,
        terminal_state: Annotated[str | None, Query()] = None,
        buyer_address: Annotated[str | None, Query()] = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> dict[str, Any]:
        try:
            threads = await self._svc.list_for_order(
                listing_id=listing_id,
                terminal_state=terminal_state or None,
                buyer_address=buyer_address or None,
                limit=limit,
                offset=offset,
            )
        except NegotiationServiceError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc))
        return {
            "listing_id": listing_id,
            "negotiations": threads,
            "count": len(threads),
            "limit": limit,
            "offset": offset,
        }

    @router.get("/{listing_id}/negotiations/{neg_id}", summary="Get negotiation detail")
    async def get_negotiation(self, listing_id: str, neg_id: str) -> dict[str, Any]:
        try:
            return await self._svc.get_detail(listing_id=listing_id, neg_id=neg_id)
        except NegotiationServiceError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc))

    @router.post(
        "/{listing_id}/negotiations/{neg_id}/advance",
        summary="Admin: drive one negotiation round",
    )
    async def advance_negotiation(
        self, listing_id: str, neg_id: str, body: AdvanceRequest
    ) -> dict[str, Any]:
        try:
            return await self._svc.advance(
                listing_id=listing_id, neg_id=neg_id,
                action=body.action, price=body.price, reason=body.reason,
            )
        except NegotiationServiceError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc))
        except Exception as exc:
            logger.error("[NEGOTIATIONS] advance: %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail=str(exc))

    @router.post(
        "/{listing_id}/negotiations/{neg_id}/force-accept",
        summary="Admin: force-accept a negotiation",
    )
    async def force_accept_negotiation(
        self, listing_id: str, neg_id: str, body: ForceAcceptRequest
    ) -> dict[str, Any]:
        try:
            return await self._svc.force_accept(
                listing_id=listing_id, neg_id=neg_id, price=body.price
            )
        except NegotiationServiceError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc))
        except Exception as exc:
            logger.error("[NEGOTIATIONS] force-accept: %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail=str(exc))
