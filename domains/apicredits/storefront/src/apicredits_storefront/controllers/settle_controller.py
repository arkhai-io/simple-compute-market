"""Settle an API-credit deal and deliver its issued credentials.

Alkahest submissions are escrow-verified by the servicing coordinator.
Arkhai payments submissions are keyed by negotiation ID and issue credits
only after the exact accepted Agreement has a matching signed receipt; the
payment settlement service owns that flow and seller refunds.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Mapping
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
from market_arkhai_payments import ARKHAI_PAYMENTS_MECHANISM
from market_core.schemas import Agreement
from market_identity import Identity

import apicredits_storefront.container as _container
from apicredits_storefront.domain_runtime import (
    serialize_api_credit_settlement,
    serialize_api_credit_settlement_start,
)
from apicredits_storefront.middleware import buyer_auth
from apicredits_storefront.middleware.admin_auth import require_admin_principal
from apicredits_storefront.middleware.seller_auth import make_seller_auth_dep
from apicredits_storefront.services.payment_settlement_service import (
    PaymentSettlementError,
)
from apicredits_storefront.settlement_models import ApiCreditsSettleRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/settle", tags=["settle"])
settlements_router = APIRouter(prefix="/api/v1", tags=["settlements"])


@cbv(router)
class SettleController:
    def __init__(
        self,
        db=Depends(lambda: _container.resolved_sqlite_client),
        settlement_coordinator=Depends(
            lambda: _container.resolved_settlement_coordinator
        ),
    ) -> None:
        self._db = db
        self._settlement_coordinator = settlement_coordinator

    @router.post(
        "/{escrow_uid}",
        response_model=SettleResponse,
        summary="Submit settlement / kick off token issuance",
        description="Buyer-facing. Requires marketplace request-signature version 2 headers.",
    )
    async def settle_escrow(
        self,
        escrow_uid: str,
        body: ApiCreditsSettleRequest,
        request: Request,
    ) -> Any:
        from market_alkahest.escrow_verification import EscrowVerificationError

        signer = _container.resolved_marketplace_signer
        if signer is None:
            raise HTTPException(status_code=503, detail="storefront is not initialized")
        await buyer_auth._verify(
            request,
            "settle_escrow",
            escrow_uid,
            expected_principal=body.buyer_principal,
            body=body,
        )
        thread = await self._db.load_negotiation_thread_row(
            negotiation_id=body.negotiation_id
        )
        mechanism = body.settlement_mechanism or "alkahest.v1"
        if thread is not None:
            raw_agreement = thread.get("agreement_bytes")
            if isinstance(raw_agreement, memoryview):
                raw_agreement = raw_agreement.tobytes()
            try:
                agreement = Agreement.model_validate(json.loads(raw_agreement))
            except (TypeError, ValueError):
                agreement = None
            if agreement is not None and agreement.settlement is not None:
                mechanism = agreement.settlement.mechanism
        if (
            body.settlement_mechanism is not None
            and body.settlement_mechanism != mechanism
        ):
            raise HTTPException(
                status_code=400,
                detail="settlement mechanism conflicts with accepted Agreement",
            )
        if mechanism == ARKHAI_PAYMENTS_MECHANISM:
            if escrow_uid != body.negotiation_id:
                raise HTTPException(
                    status_code=400,
                    detail="payments settlement is keyed by negotiation ID",
                )
            composition = _container.resolved_settlement_composition
            service = composition.payment_service(self._db) if composition else None
            if service is None:
                raise HTTPException(status_code=503, detail="Arkhai payments is not enabled")
            try:
                result = await service.settle(
                    body.negotiation_id,
                    buyer_principal=body.buyer_principal,
                    seller_principal=signer.identity,
                )
            except PaymentSettlementError as exc:
                raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
            return JSONResponse(content=result.payload, status_code=result.status_code)
        if mechanism != "alkahest.v1":
            raise HTTPException(
                status_code=400, detail="unsupported settlement mechanism"
            )

        alkahest = _container.get_alkahest_client(body.chain_name)
        if not body.chain_name:
            raise HTTPException(
                status_code=422, detail="chain_name is required for Alkahest"
            )
        if alkahest is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"chain {body.chain_name!r} not configured on this "
                    f"storefront — available chains: "
                    f"{sorted(_container.configured_chain_names())}"
                ),
            )
        try:
            result = await self._settlement_coordinator.start(
                escrow_uid=escrow_uid,
                negotiation_id=body.negotiation_id,
                mechanism_client=alkahest,
                chain_name=body.chain_name,
                request=body,
            )
        except EscrowVerificationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            logger.error(
                "[SETTLE] settlement coordinator failed: %s",
                exc,
                exc_info=True,
            )
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        serialized = (
            serialize_api_credit_settlement(result)
            if "created_at" in result
            else serialize_api_credit_settlement_start(result)
        )
        serialized["buyer_principal"] = body.buyer_principal.model_dump(mode="json")
        serialized["seller_principal"] = signer.identity.model_dump(mode="json")
        status_code = 200 if result.get("status") in ("ready", "failed") else 202
        return JSONResponse(content=serialized, status_code=status_code)

    @router.get(
        "/{escrow_uid}/status",
        response_model=SettleStatusResponse,
        summary="Poll settlement status",
        description="Buyer-facing. Requires marketplace request-signature version 2 headers.",
    )
    async def settle_status(
        self,
        escrow_uid: str,
        request: Request,
    ) -> SettleStatusResponse:
        job = await self._db.load_escrow(escrow_uid=escrow_uid)
        if not job:
            raise HTTPException(
                status_code=404,
                detail=f"No settlement job for settlement {escrow_uid}",
            )
        negotiation_id = str(job["negotiation_id"])
        thread = await self._db.load_negotiation_thread_row(
            negotiation_id=negotiation_id
        )
        if not thread:
            raise HTTPException(
                status_code=409, detail="settlement negotiation is missing"
            )
        buyer_principal = Identity.model_validate(thread.get("buyer_principal"))
        await buyer_auth._verify(
            request,
            "settle_status",
            escrow_uid,
            expected_principal=buyer_principal,
        )
        signer = _container.resolved_marketplace_signer
        if signer is None:
            raise HTTPException(status_code=503, detail="storefront is not initialized")
        agreement = None
        stored_bytes = thread.get("agreement_bytes")
        if isinstance(stored_bytes, memoryview):
            stored_bytes = stored_bytes.tobytes()
        if stored_bytes:
            try:
                agreement = Agreement.model_validate(json.loads(stored_bytes))
            except (TypeError, ValueError):
                agreement = None
        if (
            agreement is not None
            and agreement.settlement is not None
            and agreement.settlement.mechanism == ARKHAI_PAYMENTS_MECHANISM
            and job.get("status") not in ("ready", "failed", "refunded")
        ):
            composition = _container.resolved_settlement_composition
            service = composition.payment_service(self._db) if composition else None
            if service is not None:
                try:
                    await service.settle(
                        negotiation_id,
                        buyer_principal=buyer_principal,
                        seller_principal=signer.identity,
                    )
                except PaymentSettlementError as exc:
                    if exc.status_code < 500:
                        raise HTTPException(
                            status_code=exc.status_code, detail=exc.detail
                        ) from exc
                    logger.warning(
                        "Payment settlement retry for %s is pending: %s",
                        negotiation_id,
                        exc.detail,
                    )
            job = await self._db.load_escrow(escrow_uid=escrow_uid) or job
        serialized = serialize_api_credit_settlement(job)
        if (
            agreement is not None
            and agreement.settlement is not None
            and agreement.settlement.mechanism == ARKHAI_PAYMENTS_MECHANISM
        ):
            settlement_data = thread.get("settlement_data")
            if isinstance(settlement_data, Mapping):
                serialized["settlement_ref"] = settlement_data.get("transaction_id")
        serialized["buyer_principal"] = buyer_principal.model_dump(mode="json")
        serialized["seller_principal"] = signer.identity.model_dump(mode="json")
        return SettleStatusResponse(**serialized)


admin_settle_router = APIRouter(prefix="/api/v1/admin/settle", tags=["admin-settle"])


@cbv(admin_settle_router)
class AdminSettleController:
    def __init__(
        self,
        db=Depends(lambda: _container.resolved_sqlite_client),
        _key=Depends(require_admin_principal),
    ) -> None:
        self._db = db

    @admin_settle_router.get(
        "/{escrow_uid}/wait",
        response_model=SettleWaitResponse,
        summary="Long-poll until settlement reaches a terminal state (admin)",
    )
    async def wait_for_settlement(
        self,
        escrow_uid: str,
        timeout: float = Query(
            default=60.0,
            gt=0,
            le=120,
            description="Maximum seconds to wait (server-enforced, max 120)",
        ),
    ) -> SettleWaitResponse:
        _terminal = {"ready", "failed"}
        start = time.monotonic()
        deadline = start + timeout

        while True:
            job = await self._db.load_escrow(escrow_uid=escrow_uid)
            elapsed_ms = int((time.monotonic() - start) * 1000)
            status = (job or {}).get("status", "")

            if status in _terminal:
                return SettleWaitResponse(
                    ready=True,
                    status=status,
                    elapsed_ms=elapsed_ms,
                )

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            await asyncio.sleep(min(1.0, remaining))

        elapsed_ms = int((time.monotonic() - start) * 1000)
        job = await self._db.load_escrow(escrow_uid=escrow_uid)
        return SettleWaitResponse(
            ready=False,
            status=(job or {}).get("status", "unknown"),
            elapsed_ms=elapsed_ms,
        )


@settlements_router.post(
    "/settlements/{negotiation_id}/refund",
    response_model=RefundSettlementResponse,
    summary="Refund an accepted payment deal",
    description=(
        "Seller-facing. Requires the storefront's own seller v2 signature. Reverses "
        "the deal's still-held payment and records it refunded so issuance cannot "
        "start; credits already issued are left in place."
    ),
    dependencies=[
        Depends(make_seller_auth_dep("refund_settlement", resource_param="negotiation_id"))
    ],
)
async def refund_settlement(negotiation_id: str) -> Any:
    composition = _container.resolved_settlement_composition
    db = _container.resolved_sqlite_client
    service = composition.payment_service(db) if composition else None
    if service is None:
        raise HTTPException(status_code=503, detail="Arkhai payments is not enabled")
    try:
        result = await service.refund(negotiation_id)
    except PaymentSettlementError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return JSONResponse(content=result.payload, status_code=result.status_code)
