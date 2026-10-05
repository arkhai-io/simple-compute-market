"""Authenticated API-credit settlement dispatch and private result projection."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from core_storefront.models.settle_models import SettleResponse, SettleStatusResponse, SettleWaitResponse
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi_utils.cbv import cbv
from market_alkahest.escrow_verification import EscrowVerificationError
from market_identity import Identity

import apicredits_storefront.container as container
from apicredits_storefront.middleware import buyer_auth
from apicredits_storefront.middleware.admin_auth import require_admin_principal
from apicredits_storefront.settlement_composition import SELLER_STAGES
from apicredits_storefront.settlement_models import ApiCreditsSettleRequest
from apicredits_storefront.settlement_stages import accepted_agreement, project_progress

logger = logging.getLogger(__name__)
_settlement_locks: dict[str, asyncio.Lock] = {}
router = APIRouter(prefix="/api/v1/settle", tags=["settle"])


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
        try:
            agreement, _raw = accepted_agreement(thread or {})
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(409, "accepted Agreement is unavailable or invalid") from exc
        if Identity.model_validate(agreement.buyer) != body.buyer_principal or Identity.model_validate(agreement.seller) != signer.identity:
            raise HTTPException(403, "settlement parties differ from accepted Agreement")
        if body.settlement_mechanism is not None and body.settlement_mechanism != agreement.settlement.mechanism:
            raise HTTPException(400, "settlement mechanism conflicts with accepted Agreement")
        try:
            stage = SELLER_STAGES[agreement.settlement.mechanism]
        except KeyError as exc:
            raise HTTPException(400, "unsupported accepted settlement mechanism") from exc
        return stage, {
            "db": self._db, "composition": composition, "coordinator": self._settlement_coordinator,
            "reference": reference, "body": body, "signer": signer, "thread": thread,
        }

    async def _project(self, row: dict[str, Any], buyer: Identity) -> dict[str, Any]:
        result = await project_progress(self._db, row, owner=buyer)
        result["buyer_principal"] = buyer.model_dump(mode="json")
        result["seller_principal"] = container.resolved_marketplace_signer.identity.model_dump(mode="json")
        return result

    @router.post("/{escrow_uid}", response_model=SettleResponse)
    async def settle_escrow(self, escrow_uid: str, body: ApiCreditsSettleRequest, request: Request) -> Any:
        await buyer_auth._verify(request, "settle_escrow", escrow_uid, expected_principal=body.buyer_principal, body=body)
        stage, context = await self._context(body.negotiation_id, escrow_uid, body)
        lock = _settlement_locks.setdefault(body.negotiation_id, asyncio.Lock())
        try:
            async with lock:
                row = await stage.settle(**context)
        except (ValueError, EscrowVerificationError) as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:
            logger.exception("Settlement is unavailable for %s", body.negotiation_id)
            raise HTTPException(502, "settlement authority is unavailable") from exc
        if row is None:
            raise HTTPException(409, "settlement progress is unavailable")
        result = await self._project(row, body.buyer_principal)
        return JSONResponse(result, status_code=200 if row["status"] in {"ready", "failed"} else 202)

    @router.get("/{escrow_uid}/status", response_model=SettleStatusResponse)
    async def settle_status(self, escrow_uid: str, request: Request) -> SettleStatusResponse:
        row = await self._db.load_issuance_progress(reference=escrow_uid)
        if row is None:
            raise HTTPException(404, "settlement progress is unavailable")
        thread = await self._db.load_negotiation_thread_row(negotiation_id=row["negotiation_id"])
        if thread is None:
            raise HTTPException(409, "settlement negotiation is missing")
        buyer = Identity.model_validate(thread["buyer_principal"])
        await buyer_auth._verify(request, "settle_status", escrow_uid, expected_principal=buyer)
        body = ApiCreditsSettleRequest(negotiation_id=row["negotiation_id"], buyer_principal=buyer)
        stage, context = await self._context(row["negotiation_id"], escrow_uid, body)
        if row["status"] not in {"ready", "failed"}:
            lock = _settlement_locks.setdefault(row["negotiation_id"], asyncio.Lock())
            async with lock:
                try:
                    row = await stage.redrive(**context) or row
                except ValueError as exc:
                    raise HTTPException(409, str(exc)) from exc
                except Exception:
                    logger.exception("Settlement re-drive remains pending for %s", row["negotiation_id"])
        return SettleStatusResponse(**await self._project(row, buyer))


admin_settle_router = APIRouter(prefix="/api/v1/admin/settle", tags=["admin-settle"])


@cbv(admin_settle_router)
class AdminSettleController:
    def __init__(self, db=Depends(lambda: container.resolved_sqlite_client), _key=Depends(require_admin_principal)) -> None:
        self._db = db

    @admin_settle_router.get("/{escrow_uid}/wait", response_model=SettleWaitResponse)
    async def wait_for_settlement(self, escrow_uid: str, timeout: float = Query(default=60.0, gt=0, le=120)) -> SettleWaitResponse:
        start = time.monotonic()
        while True:
            row = await self._db.load_issuance_progress(reference=escrow_uid)
            status = (row or {}).get("status", "")
            elapsed_ms = int((time.monotonic() - start) * 1000)
            if status in {"ready", "failed"}:
                return SettleWaitResponse(ready=True, status=status, elapsed_ms=elapsed_ms)
            remaining = start + timeout - time.monotonic()
            if remaining <= 0:
                return SettleWaitResponse(ready=False, status=status or "unknown", elapsed_ms=elapsed_ms)
            await asyncio.sleep(min(1.0, remaining))
