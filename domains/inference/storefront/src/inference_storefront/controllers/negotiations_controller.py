"""Negotiations: the administrator's reads and controls of negotiation threads.

Every route is verified under the operation and resource the canonical
storefront client signs for it, and a round the administrator drives is
recorded as the administrator's.
"""

from __future__ import annotations

from typing import Annotated

from arkhai_api_selling.auth import negotiation_list_resource
from core_storefront.models.negotiation_models import (
    AdvanceRequest,
    AdvanceResponse,
    ForceAcceptRequest,
    ForceAcceptResponse,
    NegotiationDetailResponse,
    NegotiationListResponse,
)
from fastapi import APIRouter, Query, Request
from fastapi_utils.cbv import cbv

import inference_storefront.container as _container
from inference_storefront.controllers.binding import serve

router = APIRouter(prefix="/api/v1/listings", tags=["negotiations"])


@cbv(router)
class NegotiationsController:
    @router.get(
        "/{listing_id}/negotiations",
        response_model=NegotiationListResponse,
        summary="List negotiations for a listing (admin)",
    )
    async def list_negotiations(
        self,
        listing_id: str,
        request: Request,
        terminal_state: Annotated[str | None, Query()] = None,
        buyer_scheme: Annotated[str | None, Query()] = None,
        buyer_identifier: Annotated[str | None, Query()] = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> NegotiationListResponse:
        await _container.AUTH.authenticate_admin(
            request,
            operation="admin_list_negotiations",
            resource=negotiation_list_resource(request, listing_id),
        )
        return await serve(
            _container.NEGOTIATION_ROUTES.list(
                listing_id,
                terminal_state=terminal_state,
                buyer_scheme=buyer_scheme,
                buyer_identifier=buyer_identifier,
                limit=limit,
                offset=offset,
            )
        )

    @router.get(
        "/{listing_id}/negotiations/{neg_id}",
        response_model=NegotiationDetailResponse,
        summary="Get negotiation detail (admin)",
    )
    async def get_negotiation(
        self, listing_id: str, neg_id: str, request: Request
    ) -> NegotiationDetailResponse:
        await _container.AUTH.authenticate_admin(
            request,
            operation="admin_get_negotiation",
            resource=f"{listing_id}/negotiations/{neg_id}",
        )
        return await serve(_container.NEGOTIATION_ROUTES.get(listing_id, neg_id))

    @router.post(
        "/{listing_id}/negotiations/{neg_id}/advance",
        response_model=AdvanceResponse,
        summary="Drive one negotiation round (admin)",
    )
    async def advance_negotiation(
        self, listing_id: str, neg_id: str, body: AdvanceRequest, request: Request
    ) -> AdvanceResponse:
        actor_principal = await _container.AUTH.authenticate_admin(
            request,
            operation="admin_advance_negotiation",
            resource=f"{listing_id}/{neg_id}",
        )
        return await serve(
            _container.NEGOTIATION_ROUTES.advance(
                listing_id, neg_id, body, actor_principal=actor_principal
            )
        )

    @router.post(
        "/{listing_id}/negotiations/{neg_id}/force-accept",
        response_model=ForceAcceptResponse,
        summary="Force-accept a negotiation (admin)",
    )
    async def force_accept_negotiation(
        self,
        listing_id: str, neg_id: str, body: ForceAcceptRequest, request: Request
    ) -> ForceAcceptResponse:
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
