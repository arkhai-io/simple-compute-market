"""Settle controller — post-negotiation escrow and provisioning status."""
from __future__ import annotations

import logging
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

        job = await self._db.load_settlement_job(escrow_uid=escrow_uid)
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
        from market_storefront.utils.config import CONFIG
        from market_storefront.services.admin_settle_service import AdminSettleService
        self._svc = AdminSettleService(
            sqlite_client=db,
            config=CONFIG,
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
