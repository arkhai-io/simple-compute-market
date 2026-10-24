"""Buyer/seller negotiation authenticated by canonical marketplace principals."""

from __future__ import annotations

from core_storefront.models.negotiation_models import (
    NegotiateContinueRequest,
    NegotiateContinueResponse,
    NegotiateNewRequest,
    NegotiateNewResponse,
)
from fastapi import APIRouter, Request
from fastapi_utils.cbv import cbv

import apicredits_storefront.container as _container
from apicredits_storefront.controllers.binding import serve

router = APIRouter(prefix="/api/v1/negotiate", tags=["negotiate"])


@cbv(router)
class NegotiateController:
    @router.post(
        "/new",
        response_model=NegotiateNewResponse,
        summary="Start a new negotiation",
        description="Requires shared body-bound marketplace signature version 2 headers.",
    )
    async def negotiate_new(self, body: NegotiateNewRequest, request: Request) -> NegotiateNewResponse:
        auth = await _container.AUTH.verify_buyer(
            request,
            "negotiate_new",
            body.listing_id,
            expected_principal=body.buyer_principal,
            allow_exact_retry=True,
        )
        return await serve(_container.NEGOTIATE_ROUTES.new(body, auth))

    @router.post(
        "/{neg_id}",
        response_model=NegotiateContinueResponse,
        summary="Advance an existing negotiation",
        description="Requires shared body-bound marketplace signature version 2 headers.",
    )
    async def negotiate_continue(
        self,
        neg_id: str, body: NegotiateContinueRequest, request: Request
    ) -> NegotiateContinueResponse:
        auth = await _container.AUTH.verify_buyer(
            request,
            "negotiate_continue",
            neg_id,
            expected_principal=body.buyer_principal,
            allow_exact_retry=True,
        )
        return await serve(_container.NEGOTIATE_ROUTES.continue_negotiation(neg_id, body, auth))
