"""Negotiations: the administrator's introspection of negotiation threads."""

from __future__ import annotations

from typing import Annotated

from core_storefront.models.negotiation_models import (
    AdvanceRequest,
    AdvanceResponse,
    ForceAcceptRequest,
    ForceAcceptResponse,
    NegotiationDetailResponse,
    NegotiationListResponse,
)
from fastapi import APIRouter, Depends, Query, Request
from fastapi_utils.cbv import cbv

import apicredits_storefront.container as _container
from apicredits_storefront.controllers.binding import serve

router = APIRouter(prefix="/api/v1/listings", tags=["negotiations"])


@cbv(router)
class NegotiationsController:
    @router.get(
        "/{listing_id}/negotiations",
        response_model=NegotiationListResponse,
        summary="List negotiations for a listing",
    )
    async def list_negotiations(
        self,
        listing_id: str,
        terminal_state: Annotated[str | None, Query()] = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> NegotiationListResponse:
        return await serve(
            _container.NEGOTIATION_ROUTES.list(
                listing_id, terminal_state=terminal_state, limit=limit, offset=offset
            )
        )

    @router.get(
        "/{listing_id}/negotiations/{neg_id}",
        response_model=NegotiationDetailResponse,
        summary="Get negotiation detail",
    )
    async def get_negotiation(self, listing_id: str, neg_id: str) -> NegotiationDetailResponse:
        return await serve(_container.NEGOTIATION_ROUTES.get(listing_id, neg_id))

    @router.post(
        "/{listing_id}/negotiations/{neg_id}/advance",
        response_model=AdvanceResponse,
        summary="Drive one negotiation round (admin)",
        dependencies=[Depends(_container.AUTH.require_admin_principal)],
    )
    async def advance_negotiation(self, listing_id: str, neg_id: str, body: AdvanceRequest) -> AdvanceResponse:
        return await serve(_container.NEGOTIATION_ROUTES.advance(listing_id, neg_id, body))

    @router.post(
        "/{listing_id}/negotiations/{neg_id}/force-accept",
        response_model=ForceAcceptResponse,
        summary="Force-accept a negotiation (admin)",
    )
    async def force_accept_negotiation(
        self,
        listing_id: str, neg_id: str, body: ForceAcceptRequest, request: Request
    ) -> ForceAcceptResponse:
        # The canonical storefront client's signed contract, which every
        # storefront binding this control verifies, not this route's own name.
        actor_principal = await _container.AUTH.authenticate_admin(
            request,
            operation="admin_force_accept_negotiation",
            resource=f"{listing_id}/{neg_id}",
        )
        return await serve(
            _container.NEGOTIATION_ROUTES.force_accept(
                listing_id, neg_id, body, actor_principal=actor_principal
            )
        )
