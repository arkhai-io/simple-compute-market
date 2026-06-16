"""Negotiations controller — admin introspection of negotiation threads."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi_utils.cbv import cbv

import apitokens_storefront.container as _container
from apitokens_storefront.middleware.admin_auth import require_admin_key
from core_storefront.models.negotiation_models import (
    AdvanceRequest,
    AdvanceResponse,
    ForceAcceptRequest,
    ForceAcceptResponse,
    NegotiationDetailResponse,
    NegotiationListResponse,
)
from core_storefront.services.negotiation_service import NegotiationServiceError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/listings", tags=["negotiations"])


@cbv(router)
class NegotiationsController:
    def __init__(
        self,
        neg_svc=Depends(lambda: _container.resolved_negotiation_service),
    ) -> None:
        self._svc = neg_svc

    @router.get("/{listing_id}/negotiations",
                response_model=NegotiationListResponse,
                summary="List negotiations for a listing")
    async def list_negotiations(
        self,
        listing_id: str,
        terminal_state: Annotated[str | None, Query()] = None,
        buyer_address: Annotated[str | None, Query()] = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> NegotiationListResponse:
        try:
            threads = await self._svc.list_for_order(
                listing_id=listing_id,
                terminal_state=terminal_state or None,
                buyer_address=buyer_address or None,
                limit=limit, offset=offset,
            )
        except NegotiationServiceError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc))
        return NegotiationListResponse(
            listing_id=listing_id, negotiations=threads,
            count=len(threads), limit=limit, offset=offset,
        )

    @router.get("/{listing_id}/negotiations/{neg_id}",
                response_model=NegotiationDetailResponse,
                summary="Get negotiation detail")
    async def get_negotiation(
        self, listing_id: str, neg_id: str,
    ) -> NegotiationDetailResponse:
        try:
            detail = await self._svc.get_detail(listing_id=listing_id, neg_id=neg_id)
        except NegotiationServiceError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc))
        return NegotiationDetailResponse(**detail)

    @router.post(
        "/{listing_id}/negotiations/{neg_id}/advance",
        response_model=AdvanceResponse,
        summary="Drive one negotiation round (admin)",
        dependencies=[Depends(require_admin_key)],
    )
    async def advance_negotiation(
        self, listing_id: str, neg_id: str, body: AdvanceRequest,
    ) -> AdvanceResponse:
        try:
            result = await self._svc.advance(
                listing_id=listing_id, neg_id=neg_id,
                action=body.action, proposal=body.proposal, reason=body.reason,
            )
        except NegotiationServiceError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc))
        except Exception as exc:
            logger.error("[NEGOTIATIONS] advance: %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail=str(exc))
        return AdvanceResponse(**result)

    @router.post(
        "/{listing_id}/negotiations/{neg_id}/force-accept",
        response_model=ForceAcceptResponse,
        summary="Force-accept a negotiation (admin)",
        dependencies=[Depends(require_admin_key)],
    )
    async def force_accept_negotiation(
        self, listing_id: str, neg_id: str, body: ForceAcceptRequest,
    ) -> ForceAcceptResponse:
        try:
            result = await self._svc.force_accept(
                listing_id=listing_id, neg_id=neg_id, amount=body.amount,
            )
        except NegotiationServiceError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc))
        except Exception as exc:
            logger.error("[NEGOTIATIONS] force-accept: %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail=str(exc))
        return ForceAcceptResponse(**result)
