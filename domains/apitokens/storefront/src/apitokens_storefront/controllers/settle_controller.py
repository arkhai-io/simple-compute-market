"""Settle controller — post-negotiation escrow and issuance status.

Same wire shape as the VM storefront: the buyer settles with
``POST /settle/{escrow_uid}`` (the api_tokens domain ignores the VM
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

import apitokens_storefront.container as _container
from apitokens_storefront.middleware import buyer_auth
from apitokens_storefront.middleware.admin_auth import require_admin_key
from core_storefront.models.settle_models import (
    SettleRequest,
    SettleResponse,
    SettleStatusResponse,
    SettleWaitResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/settle", tags=["settle"])


@cbv(router)
class SettleController:
    def __init__(
        self,
        db=Depends(lambda: _container.resolved_sqlite_client),
    ) -> None:
        self._db = db

    @router.post(
        "/{escrow_uid}",
        response_model=SettleResponse,
        summary="Submit settlement / kick off token issuance",
        description="Buyer-facing. Requires EIP-191 signed `X-Signature` + `X-Timestamp` headers.",
    )
    async def settle_escrow(
        self,
        escrow_uid: str,
        body: SettleRequest,
        request: Request,
    ) -> Any:
        from core_storefront.escrow_verification import EscrowVerificationError

        from apitokens_storefront.utils.settlement_jobs import (
            serialize_settlement_job,
            start_settlement_job,
        )

        buyer_auth._verify(request, "settle_escrow", escrow_uid, body.buyer_address)

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
            result = await start_settlement_job(
                escrow_uid=escrow_uid,
                negotiation_id=body.negotiation_id,
                sqlite_client=self._db,
                alkahest_client=alkahest,
                chain_name=body.chain_name,
            )
        except EscrowVerificationError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except Exception as exc:
            logger.error(
                "[SETTLE] start_settlement_job failed: %s", exc, exc_info=True,
            )
            raise HTTPException(status_code=500, detail=str(exc))

        serialized = (
            serialize_settlement_job(result) if "created_at" in result else result
        )
        status_code = 200 if result.get("status") in ("ready", "failed") else 202
        return JSONResponse(content=serialized, status_code=status_code)

    @router.get(
        "/{escrow_uid}/status",
        response_model=SettleStatusResponse,
        summary="Poll settlement status",
        description="Buyer-facing. Requires EIP-191 signed `X-Signature` + `X-Timestamp` headers.",
    )
    async def settle_status(
        self,
        escrow_uid: str,
        request: Request,
        buyer_address: str = Query(
            description="Buyer wallet address for EIP-191 verification",
        ),
    ) -> SettleStatusResponse:
        from apitokens_storefront.utils.settlement_jobs import (
            serialize_settlement_job,
        )

        buyer_auth._verify(request, "settle_status", escrow_uid, buyer_address)

        job = await self._db.load_escrow(escrow_uid=escrow_uid)
        if not job:
            raise HTTPException(
                status_code=404,
                detail=f"No settlement job for escrow {escrow_uid}",
            )
        return SettleStatusResponse(**serialize_settlement_job(job))


admin_settle_router = APIRouter(prefix="/api/v1/admin/settle", tags=["admin-settle"])


@cbv(admin_settle_router)
class AdminSettleController:
    def __init__(
        self,
        db=Depends(lambda: _container.resolved_sqlite_client),
        _key=Depends(require_admin_key),
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
            default=60.0, gt=0, le=120,
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
