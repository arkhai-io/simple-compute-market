"""Settle controller — post-negotiation escrow and issuance status.

Same wire shape as the VM storefront: the buyer settles with
``POST /settle/{escrow_uid}`` (the api_credits domain ignores the VM
``ssh_public_key`` field) and polls ``GET /settle/{escrow_uid}/status``;
the issued credentials ({key_id, secret?, base_url}) ride
``tenant_credentials``, delivered once.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi_utils.cbv import cbv

import apicredits_storefront.container as _container
from apicredits_storefront.middleware import buyer_auth
from apicredits_storefront.middleware.admin_auth import require_admin_principal
from apicredits_storefront.domain_runtime import (
    serialize_api_credit_settlement,
    serialize_api_credit_settlement_start,
)
from core_storefront.models.settle_models import (
    SettleResponse,
    SettleStatusResponse,
    SettleWaitResponse,
)
from apicredits_storefront.settlement_models import ApiCreditsSettleRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/settle", tags=["settle"])


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

        alkahest = _container.get_alkahest_client(body.chain_name)
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
            raise HTTPException(status_code=400, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except Exception as exc:
            logger.error(
                "[SETTLE] settlement coordinator failed: %s",
                exc,
                exc_info=True,
            )
            raise HTTPException(status_code=500, detail=str(exc))

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
                detail=f"No settlement job for escrow {escrow_uid}",
            )
        thread = await self._db.load_negotiation_thread_row(
            negotiation_id=str(job["negotiation_id"]),
        )
        if not thread:
            raise HTTPException(
                status_code=409, detail="settlement negotiation is missing"
            )
        from market_identity import Identity

        buyer_principal = Identity.model_validate(thread.get("buyer_principal"))
        await buyer_auth._verify(
            request,
            "settle_status",
            escrow_uid,
            expected_principal=buyer_principal,
        )
        serialized = serialize_api_credit_settlement(job)
        serialized["buyer_principal"] = buyer_principal.model_dump(mode="json")
        signer = _container.resolved_marketplace_signer
        if signer is None:
            raise HTTPException(status_code=503, detail="storefront is not initialized")
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
