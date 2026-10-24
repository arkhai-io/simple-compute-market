"""Settlement: the buyer's settle and status, the administrator's wait, and the seller's refund."""

from __future__ import annotations

from typing import Any

from core_storefront.models.settle_models import (
    RefundSettlementResponse,
    SettleResponse,
    SettleStatusResponse,
    SettleWaitResponse,
)
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from fastapi_utils.cbv import cbv
from storefront_client.settlement_routes import REFUND, SETTLE, SETTLE_STATUS

import apicredits_storefront.container as _container
from apicredits_storefront.controllers.binding import serve
from apicredits_storefront.settlement_models import ApiCreditsSettleRequest

router = APIRouter(prefix="/api/v1/settle", tags=["settle"])
settlements_router = APIRouter(prefix="/api/v1", tags=["settlements"])
admin_settle_router = APIRouter(prefix="/api/v1/admin/settle", tags=["admin-settle"])


@cbv(router)
class SettleController:
    @router.post(
        "/{escrow_uid}",
        response_model=SettleResponse,
        summary="Submit settlement / kick off credit issuance",
        description="Buyer-facing. Requires marketplace request-signature version 2 headers.",
    )
    async def settle_escrow(
        self, escrow_uid: str, body: ApiCreditsSettleRequest, request: Request
    ) -> Any:
        await _container.AUTH.verify_buyer(
            request, SETTLE.operation, escrow_uid, expected_principal=body.buyer_principal
        )
        outcome = await serve(_container.SETTLE_ROUTES.settle(escrow_uid, body))
        return JSONResponse(outcome.payload, status_code=outcome.status_code)

    @router.get(
        "/{escrow_uid}/status",
        response_model=SettleStatusResponse,
        summary="Poll settlement status",
        description="Buyer-facing. Requires marketplace request-signature version 2 headers.",
    )
    async def settle_status(self, escrow_uid: str, request: Request) -> SettleStatusResponse:
        return await serve(
            _container.SETTLE_ROUTES.status(
                escrow_uid,
                verify_buyer=lambda buyer: _container.AUTH.verify_buyer(
                    request, SETTLE_STATUS.operation, escrow_uid, expected_principal=buyer
                ),
            )
        )


@cbv(admin_settle_router)
class AdminSettleController:
    @admin_settle_router.get(
        "/{escrow_uid}/wait",
        response_model=SettleWaitResponse,
        summary="Long-poll until settlement reaches a terminal state (admin)",
    )
    async def wait_for_settlement(
        self,
        escrow_uid: str,
        request: Request,
        timeout: float = Query(
            default=60.0,
            gt=0,
            le=120,
            description="Maximum seconds to wait (server-enforced, max 120)",
        ),
    ) -> SettleWaitResponse:
        resource = await serve(
            _container.SETTLE_ROUTES.wait_resource(escrow_uid, request.query_params.get("timeout"))
        )
        await _container.AUTH.authenticate_admin(
            request, operation="admin_settle_wait", resource=resource
        )
        return await serve(_container.SETTLE_ROUTES.wait(escrow_uid, timeout=timeout))


@settlements_router.post(
    "/settlements/{negotiation_id}/refund",
    response_model=RefundSettlementResponse,
    summary="Refund an accepted deal through its settlement mechanism",
    description=(
        "Seller-facing. Requires the storefront's own seller v2 signature. A "
        "mechanism with seller refunds reverses the deal's still-held payment and "
        "records it refunded so issuance cannot start; credits already issued are "
        "left in place. Other mechanisms refund through their own path (409)."
    ),
    dependencies=[
        Depends(
            _container.AUTH.seller_dependency(REFUND.operation, resource_param="negotiation_id")
        )
    ],
)
async def refund_settlement(negotiation_id: str) -> Any:
    outcome = await serve(_container.SETTLE_ROUTES.refund(negotiation_id))
    return JSONResponse(content=outcome.payload, status_code=outcome.status_code)
