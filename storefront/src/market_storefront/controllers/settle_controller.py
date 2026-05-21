"""Settle controller — post-negotiation escrow and provisioning status."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi_utils.cbv import cbv

import market_storefront.container as _container
from market_storefront.middleware import buyer_auth
from market_storefront.middleware.admin_auth import require_admin_key
from market_storefront.models.settle_models import (
    EvaluateSettleRequest,
    EvaluateSettleResponse,
    SettleRequest,
    SettleResponse,
    SettleStatusResponse,
    SettleWaitResponse,
    VerifyEscrowRequest,
    VerifyEscrowResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/settle", tags=["settle"])


@cbv(router)
class SettleController:
    def __init__(
        self,
        db=Depends(lambda: _container.resolved_sqlite_client),
        alkahest=Depends(lambda: _container.resolved_alkahest_client),
    ) -> None:
        self._db = db
        self._alkahest = alkahest

    @router.post(
        "/{escrow_uid}",
        response_model=SettleResponse,
        summary="Submit settlement / kick off provisioning",
        description="Buyer-facing. Requires EIP-191 signed `X-Signature` + `X-Timestamp` headers.",
    )
    async def settle_escrow(
        self,
        escrow_uid: str,
        body: SettleRequest,
        request: Request,
    ) -> Any:
        from market_storefront.utils.escrow_verification import (
            EscrowVerificationError,
        )
        from market_storefront.utils.settlement_jobs import (
            serialize_settlement_job,
            start_settlement_job,
        )

        buyer_auth._verify(request, "settle_escrow", escrow_uid, body.buyer_address)

        if self._alkahest is None:
            raise HTTPException(
                status_code=500,
                detail="Alkahest client not configured — AGENT_PRIV_KEY and CHAIN_RPC_URL must be set",
            )
        try:
            result = await start_settlement_job(
                escrow_uid=escrow_uid,
                negotiation_id=body.negotiation_id,
                ssh_public_key=body.ssh_public_key,
                sqlite_client=self._db,
                alkahest_client=self._alkahest,
            )
        except EscrowVerificationError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except Exception as exc:
            logger.error("[SETTLE] start_settlement_job failed: %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail=str(exc))

        serialized = serialize_settlement_job(result) if "created_at" in result else result
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
        buyer_address: str = Query(description="Buyer wallet address for EIP-191 verification"),
    ) -> SettleStatusResponse:
        from market_storefront.utils.settlement_jobs import serialize_settlement_job

        buyer_auth._verify(request, "settle_status", escrow_uid, buyer_address)

        job = await self._db.load_escrow(escrow_uid=escrow_uid)
        if not job:
            raise HTTPException(status_code=404, detail=f"No settlement job for escrow {escrow_uid}")
        return SettleStatusResponse(**serialize_settlement_job(job))


# ---------------------------------------------------------------------------
# Admin dry-run settle controller
# ---------------------------------------------------------------------------

admin_settle_router = APIRouter(prefix="/api/v1/admin/settle", tags=["admin-settle"])


@cbv(admin_settle_router)
class AdminSettleController:
    def __init__(
        self,
        db=Depends(lambda: _container.resolved_sqlite_client),
        _key=Depends(require_admin_key),
    ) -> None:
        from market_storefront.services.admin_settle_service import AdminSettleService
        self._db = db
        self._svc = AdminSettleService(
            sqlite_client=db,
            alkahest_client=_container.resolved_alkahest_client,
        )

    @admin_settle_router.post(
        "/{escrow_uid}/verify",
        response_model=VerifyEscrowResponse,
        summary="Verify an on-chain escrow matches expected terms (dry-run, no DB writes)",
    )
    async def verify_escrow(
        self, escrow_uid: str, body: VerifyEscrowRequest
    ) -> VerifyEscrowResponse:
        """Read the escrow from chain and confirm it matches caller-supplied terms.

        No DB writes. Returns valid=True/False. Used by e2e stage 07b.
        """
        try:
            result = await self._svc.verify_escrow_dry_run(
                escrow_uid=escrow_uid,
                listing_id=body.listing_id,
                seller_wallet=body.seller_wallet,
                agreed_price=body.agreed_price,
                agreed_duration_seconds=body.agreed_duration_seconds,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except Exception as exc:
            logger.error("[ADMIN SETTLE] verify_escrow failed: %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail=str(exc))
        return VerifyEscrowResponse(**result)

    @admin_settle_router.post(
        "/{escrow_uid}/evaluate",
        response_model=EvaluateSettleResponse,
        summary="Evaluate provisioning job spec for a settlement (dry-run, no writes)",
    )
    async def evaluate_settle(
        self, escrow_uid: str, body: EvaluateSettleRequest
    ) -> EvaluateSettleResponse:
        """Resolve a host from inventory and build the provisioning job spec.

        No chain reads, no DB writes. Used by e2e stage 08a.
        """
        try:
            result = await self._svc.evaluate_settle_dry_run(
                escrow_uid=escrow_uid,
                listing_id=body.listing_id,
                ssh_public_key=body.ssh_public_key,
                duration_seconds=body.duration_seconds,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except Exception as exc:
            logger.error("[ADMIN SETTLE] evaluate_settle failed: %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail=str(exc))
        return EvaluateSettleResponse(**result)

    @admin_settle_router.get(
        "/{escrow_uid}/wait",
        response_model=SettleWaitResponse,
        summary="Long-poll until settlement reaches a terminal state (admin)",
        description=(
            "Blocks server-side until the settlement job for *escrow_uid* reaches "
            "``ready`` or ``failed``, or until *timeout* seconds elapse. "
            "Polls the settlement job row every second internally — no client-side "
            "polling loop needed. Returns immediately if the job is already terminal. "
            "Intended for the e2e test suite's stage 09b gate."
        ),
    )
    async def wait_for_settlement(
        self,
        escrow_uid: str,
        timeout: float = Query(default=60.0, gt=0, le=120,
                               description="Maximum seconds to wait (server-enforced, max 120)"),
    ) -> SettleWaitResponse:
        """Server-side long-poll: block until settlement is terminal or timeout elapses.

        Mirrors the registry-agent wait pattern from
        GET /api/v1/system/wait-for-registry-agent.
        """
        _terminal = {"ready", "failed"}
        start = time.monotonic()
        deadline = start + timeout

        while True:
            job = await self._db.load_escrow(escrow_uid=escrow_uid)
            elapsed_ms = int((time.monotonic() - start) * 1000)
            status = (job or {}).get("status", "")
            job_id = (job or {}).get("provisioning_job_id")

            if status in _terminal:
                return SettleWaitResponse(
                    ready=True,
                    status=status,
                    provisioning_job_id=job_id,
                    elapsed_ms=elapsed_ms,
                )

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            await asyncio.sleep(min(1.0, remaining))

        elapsed_ms = int((time.monotonic() - start) * 1000)
        job = await self._db.load_escrow(escrow_uid=escrow_uid)
        status = (job or {}).get("status", "unknown")
        job_id = (job or {}).get("provisioning_job_id")
        return SettleWaitResponse(
            ready=False,
            status=status,
            provisioning_job_id=job_id,
            elapsed_ms=elapsed_ms,
        )
