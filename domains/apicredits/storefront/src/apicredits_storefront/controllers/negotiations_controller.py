"""Negotiations controller — the administrator's reads and controls of threads.

Every route here is the administrator's, verified under the operation and
resource the canonical storefront client signs for it, which every storefront
verifies too: a thread carries its buyer's principal and the agreed terms, and
the administrator acts on it only as the administrator, so the round it drives
is recorded as its own.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi_utils.cbv import cbv
from market_identity import Identity
from market_storefront_kit import DealControlRouteError, NegotiationControlRouteService

import apicredits_storefront.container as _container
from apicredits_storefront.middleware.admin_auth import (
    authenticate_admin,
    negotiation_list_resource,
)
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
        await authenticate_admin(
            request,
            operation="admin_list_negotiations",
            resource=negotiation_list_resource(request, listing_id),
        )
        if (buyer_scheme is None) != (buyer_identifier is None):
            raise HTTPException(
                status_code=422,
                detail="buyer_scheme and buyer_identifier must be supplied together",
            )
        try:
            buyer_principal = (
                Identity(scheme=buyer_scheme, identifier=buyer_identifier)
                if buyer_scheme is not None and buyer_identifier is not None
                else None
            )
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="invalid buyer principal") from exc
        try:
            threads = await self._svc.list_for_order(
                listing_id=listing_id,
                terminal_state=terminal_state or None,
                buyer_principal=buyer_principal,
                limit=limit,
                offset=offset,
            )
        except NegotiationServiceError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc))
        return NegotiationListResponse(
            listing_id=listing_id,
            negotiations=threads,
            count=len(threads),
            limit=limit,
            offset=offset,
        )

    @router.get(
        "/{listing_id}/negotiations/{neg_id}",
        response_model=NegotiationDetailResponse,
        summary="Get negotiation detail (admin)",
    )
    async def get_negotiation(
        self,
        listing_id: str,
        neg_id: str,
        request: Request,
    ) -> NegotiationDetailResponse:
        await authenticate_admin(
            request,
            operation="admin_get_negotiation",
            resource=f"{listing_id}/negotiations/{neg_id}",
        )
        try:
            detail = await self._svc.get_detail(listing_id=listing_id, neg_id=neg_id)
        except NegotiationServiceError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc))
        return NegotiationDetailResponse(**detail)

    @router.post(
        "/{listing_id}/negotiations/{neg_id}/advance",
        response_model=AdvanceResponse,
        summary="Drive one negotiation round (admin)",
    )
    async def advance_negotiation(
        self,
        listing_id: str,
        neg_id: str,
        body: AdvanceRequest,
        request: Request,
    ) -> AdvanceResponse:
        actor_principal = await authenticate_admin(
            request,
            operation="admin_advance_negotiation",
            resource=f"{listing_id}/{neg_id}",
        )
        try:
            result = await self._svc.advance(
                listing_id=listing_id,
                neg_id=neg_id,
                action=body.action,
                proposal=body.proposal,
                reason=body.reason,
                actor_principal=actor_principal,
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
    )
    async def force_accept_negotiation(
        self,
        listing_id: str,
        neg_id: str,
        body: ForceAcceptRequest,
        request: Request,
    ) -> ForceAcceptResponse:
        actor_principal = await authenticate_admin(
            request,
            operation="admin_force_accept_negotiation",
            resource=f"{listing_id}/{neg_id}",
        )
        runtime = _container.resolved_negotiation_runtime
        if runtime is None:
            raise HTTPException(
                status_code=503, detail="storefront negotiation is unavailable"
            )
        controls = NegotiationControlRouteService(
            runtime=runtime,
            repository=_container.resolved_sqlite_client,
            seller_principal=lambda: _container.resolved_marketplace_signer.identity,
        )
        try:
            return await controls.force_accept(
                listing_id, neg_id, body, actor_principal=actor_principal
            )
        except DealControlRouteError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
