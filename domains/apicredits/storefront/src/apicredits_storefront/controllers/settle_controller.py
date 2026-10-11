"""Authenticated API-credit settlement dispatch and private result projection.

Each route resolves the seller stage declared for the accepted Agreement's
mechanism and returns that stage's response; mechanism behavior lives in the
stage entries.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from core_storefront.models.settle_models import (
    RefundSettlementResponse,
    SettleResponse,
    SettleStatusResponse,
    SettleWaitResponse,
)
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi_utils.cbv import cbv
from market_alkahest.escrow_verification import EscrowVerificationError
from market_identity import Identity
from market_settlement_runtime import SettlementAdminRouteService
from storefront_client.settlement_routes import REFUND, SETTLE, SETTLE_STATUS

import apicredits_storefront.container as container
from apicredits_storefront.middleware import buyer_auth
from apicredits_storefront.middleware.admin_auth import authenticate_admin
from apicredits_storefront.middleware.seller_auth import make_seller_auth_dep
from apicredits_storefront.settlement_composition import SELLER_STAGES
from apicredits_storefront.settlement_models import ApiCreditsSettleRequest
from apicredits_storefront.settlement_stages import SettlementRefusal, accepted_agreement

logger = logging.getLogger(__name__)
_settlement_locks: dict[str, asyncio.Lock] = {}
router = APIRouter(prefix="/api/v1/settle", tags=["settle"])
settlements_router = APIRouter(prefix="/api/v1", tags=["settlements"])


def _accepted_stage(thread: Any) -> tuple[Any, Any]:
    try:
        agreement, _raw = accepted_agreement(thread or {})
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(409, "accepted Agreement is unavailable or invalid") from exc
    stage = SELLER_STAGES.get(agreement.settlement.mechanism)
    if stage is None:
        raise HTTPException(400, "unsupported accepted settlement mechanism")
    return agreement, stage


@cbv(router)
class SettleController:
    def __init__(
        self, db=Depends(lambda: container.resolved_sqlite_client),
        settlement_coordinator=Depends(lambda: container.resolved_settlement_coordinator),
    ) -> None:
        self._db = db
        self._settlement_coordinator = settlement_coordinator

    async def _context(self, negotiation_id: str, reference: str, body: Any) -> tuple[Any, dict[str, Any]]:
        composition = container.resolved_settlement_composition
        signer = container.resolved_marketplace_signer
        if composition is None or signer is None:
            raise HTTPException(503, "settlement composition is not initialized")
        thread = await self._db.load_negotiation_thread_row(negotiation_id=negotiation_id)
        agreement, stage = _accepted_stage(thread)
        if Identity.model_validate(agreement.buyer) != body.buyer_principal or Identity.model_validate(agreement.seller) != signer.identity:
            raise HTTPException(403, "settlement parties differ from accepted Agreement")
        if body.settlement_mechanism is not None and body.settlement_mechanism != agreement.settlement.mechanism:
            raise HTTPException(400, "settlement mechanism conflicts with accepted Agreement")
        return stage, {
            "db": self._db, "composition": composition, "coordinator": self._settlement_coordinator,
            "reference": reference, "body": body, "signer": signer, "thread": thread,
        }

    @router.post(
        "/{escrow_uid}",
        response_model=SettleResponse,
        summary="Submit settlement / kick off credit issuance",
        description="Buyer-facing. Requires marketplace request-signature version 2 headers.",
    )
    async def settle_escrow(self, escrow_uid: str, body: ApiCreditsSettleRequest, request: Request) -> Any:
        await buyer_auth._verify(
            request, SETTLE.operation, escrow_uid, expected_principal=body.buyer_principal, body=body,
        )
        stage, context = await self._context(body.negotiation_id, escrow_uid, body)
        lock = _settlement_locks.setdefault(body.negotiation_id, asyncio.Lock())
        try:
            async with lock:
                result = await stage.settle(**context)
        except SettlementRefusal as exc:
            raise HTTPException(exc.status_code, exc.detail) from exc
        except (ValueError, EscrowVerificationError) as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:
            logger.exception("Settlement is unavailable for %s", body.negotiation_id)
            raise HTTPException(502, "settlement authority is unavailable") from exc
        return JSONResponse(result.payload, status_code=result.status_code)

    @router.get(
        "/{escrow_uid}/status",
        response_model=SettleStatusResponse,
        summary="Poll settlement status",
        description="Buyer-facing. Requires marketplace request-signature version 2 headers.",
    )
    async def settle_status(self, escrow_uid: str, request: Request) -> SettleStatusResponse:
        # Payment settlement is keyed by negotiation ID and may have no issuance
        # progress yet; other references resolve through their progress row.
        row = await self._db.load_issuance_progress(reference=escrow_uid)
        negotiation_id = str(row["negotiation_id"]) if row is not None else escrow_uid
        thread = await self._db.load_negotiation_thread_row(negotiation_id=negotiation_id)
        if thread is None:
            raise HTTPException(404, "settlement progress is unavailable")
        buyer = Identity.model_validate(thread["buyer_principal"])
        await buyer_auth._verify(request, SETTLE_STATUS.operation, escrow_uid, expected_principal=buyer)
        body = ApiCreditsSettleRequest(negotiation_id=negotiation_id, buyer_principal=buyer)
        stage, context = await self._context(negotiation_id, escrow_uid, body)
        lock = _settlement_locks.setdefault(negotiation_id, asyncio.Lock())
        try:
            async with lock:
                result = await stage.status(**context)
        except SettlementRefusal as exc:
            raise HTTPException(exc.status_code, exc.detail) from exc
        if result is None:
            raise HTTPException(404, "settlement progress is unavailable")
        return SettleStatusResponse(**result.payload)


admin_settle_router = APIRouter(prefix="/api/v1/admin/settle", tags=["admin-settle"])


@cbv(admin_settle_router)
class AdminSettleController:
    def __init__(self, db=Depends(lambda: container.resolved_sqlite_client)) -> None:
        self._db = db

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
        # The canonical client signs the timeout exactly as it sends it, so the
        # wait it authorizes cannot be lengthened by rewriting the query.
        raw_timeout = request.query_params.get("timeout")
        if raw_timeout is None:
            raise HTTPException(
                status_code=400, detail="admin settlement wait requires explicit timeout"
            )
        await authenticate_admin(
            request,
            operation="admin_settle_wait",
            resource=f"{escrow_uid}?timeout={raw_timeout}",
        )

        async def settle_status(uid: str):
            return await self._db.load_issuance_progress(reference=uid)

        waited = await SettlementAdminRouteService(
            settle_status=settle_status,
            is_terminal=lambda status: status.get("status") in {"ready", "failed"},
        ).wait(escrow_uid, timeout=timeout)
        return SettleWaitResponse(
            ready=waited["ready"],
            status=waited["status"],
            elapsed_ms=waited["elapsed_ms"],
        )


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
        Depends(make_seller_auth_dep(REFUND.operation, resource_param="negotiation_id"))
    ],
)
async def refund_settlement(negotiation_id: str) -> Any:
    composition = container.resolved_settlement_composition
    db = container.resolved_sqlite_client
    if composition is None or db is None:
        raise HTTPException(503, "settlement composition is not initialized")
    thread = await db.load_negotiation_thread_row(negotiation_id=negotiation_id)
    if not thread or thread.get("terminal_state") != "success":
        raise HTTPException(404, "accepted negotiation not found")
    _agreement, stage = _accepted_stage(thread)
    # Deliberately not serialized behind an in-flight settle: refund intent and
    # delivery start are ordered by their durable transitions, and a refund must
    # be able to land while issuance is under way.
    try:
        result = await stage.refund(db=db, composition=composition, negotiation_id=negotiation_id)
    except SettlementRefusal as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
    return JSONResponse(content=result.payload, status_code=result.status_code)
