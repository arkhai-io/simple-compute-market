"""Settle controller — post-negotiation escrow and provisioning status."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from core_storefront.models.settle_models import (
    EvaluateSettleRequest,
    EvaluateSettleResponse,
    SettleResponse,
    SettleStatusResponse,
    SettleWaitResponse,
    VerifyEscrowRequest,
    VerifyEscrowResponse,
)
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi_utils.cbv import cbv
from market_identity import Identity

import market_storefront.container as _container
from market_storefront.middleware import buyer_auth
from market_storefront.middleware.admin_auth import require_admin_key
from market_storefront.models.settle_models import (
    VmPaymentsSettleRequest,
    VmSettleRequest,
)
from market_storefront.services.admin_settle_service import AdminSettleService
from market_storefront.settlement_composition import serialize_settlement_job

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/settle", tags=["settle"])
settlements_router = APIRouter(prefix="/api/v1", tags=["settlements"])


@cbv(router)
class SettleController:
    def __init__(
        self,
        db: Any = Depends(lambda: _container.resolved_sqlite_client),  # noqa: B008
    ) -> None:
        self._db = db

    @router.post(
        "/{escrow_uid}",
        response_model=SettleResponse,
        summary="Submit settlement / kick off provisioning",
        description="Buyer-facing. Requires marketplace v2 request authentication.",
    )
    async def settle_escrow(
        self,
        escrow_uid: str,
        body: VmSettleRequest | VmPaymentsSettleRequest,
        request: Request,
    ) -> Any:
        thread = await self._db.load_negotiation_thread_row(
            negotiation_id=body.negotiation_id
        )
        if not isinstance(thread, dict) or thread.get("terminal_state") != "success":
            raise HTTPException(
                status_code=404, detail="accepted negotiation not found"
            )
        auth = await buyer_auth.settle_escrow_auth(
            escrow_uid,
            body,
            request,
            negotiation_thread=thread,
        )
        agreement_raw = thread.get("agreement_bytes")
        agreement = json.loads(agreement_raw) if isinstance(agreement_raw, bytes) else {}
        selected = agreement.get("settlement") or {}
        composition = _container.resolved_settlement_composition
        if composition is None:
            raise HTTPException(status_code=503, detail="settlement runtime is unavailable")
        try:
            stage = composition.seller_stages[selected.get("mechanism")]
        except KeyError as exc:
            raise HTTPException(status_code=400, detail="accepted settlement mechanism is unsupported") from exc
        started = await stage.start(
            reference=escrow_uid, body=body, thread=thread, auth=auth,
            composition=composition, db=self._db, configured_chains=_container,
        )
        if isinstance(started, JSONResponse):
            return started
        result, persisted_buyer = started
        serialized = (
            serialize_settlement_job(result)
            if "created_at" in result
            else {
                "escrow_uid": result.get("escrow_uid"),
                "negotiation_id": result.get("negotiation_id"),
                "status": result.get("status"),
            }
        )
        serialized["buyer_principal"] = persisted_buyer.model_dump(mode="json")
        serialized["seller_principal"] = composition.local_principal.model_dump(
            mode="json"
        )
        status_code = 200 if result.get("status") in ("ready", "failed") else 202
        return JSONResponse(content=serialized, status_code=status_code)

    @router.get(
        "/{escrow_uid}/status",
        response_model=SettleStatusResponse,
        summary="Poll settlement status",
        description="Buyer-facing. Requires marketplace v2 request authentication.",
    )
    async def settle_status(
        self,
        escrow_uid: str,
        request: Request,
    ) -> SettleStatusResponse:
        job = await self._db.load_vm_settlement_job(reference=escrow_uid)
        if not job:
            raise HTTPException(
                status_code=404, detail=f"No settlement job for escrow {escrow_uid}"
            )
        thread = await self._db.load_negotiation_thread_row(
            negotiation_id=job.get("negotiation_id")
        )
        buyer_principal = Identity.model_validate((thread or {}).get("buyer_principal"))
        auth = await buyer_auth._verify(
            request,
            "settle_status",
            escrow_uid,
            buyer_principal,
        )
        if auth.exact_retry and auth.recorded_outcome is not None:
            status_code, payload = auth.recorded_outcome
            if status_code >= 400:
                raise HTTPException(status_code=status_code, detail=payload)
            return SettleStatusResponse.model_validate(payload)

        serialized = serialize_settlement_job(job)
        serialized["buyer_principal"] = buyer_principal.model_dump(mode="json")
        serialized["seller_principal"] = (
            _container.resolved_marketplace_signer.identity.model_dump(mode="json")
        )
        return SettleStatusResponse(**serialized)


# ---------------------------------------------------------------------------
# Admin dry-run settle controller
# ---------------------------------------------------------------------------

admin_settle_router = APIRouter(prefix="/api/v1/admin/settle", tags=["admin-settle"])


@cbv(admin_settle_router)
class AdminSettleController:
    def __init__(
        self,
        db: Any = Depends(lambda: _container.resolved_sqlite_client),  # noqa: B008
        _key: Any = Depends(require_admin_key),  # noqa: B008
    ) -> None:
        self._db = db
        self._svc = AdminSettleService(
            sqlite_client=db, alkahest_clients=_container.resolved_alkahest_clients
        )

    @admin_settle_router.post(
        "/{escrow_uid}/verify",
        response_model=VerifyEscrowResponse,
        summary="Verify an on-chain escrow matches expected terms (dry-run, no DB writes)",
    )
    async def verify_escrow(
        self, escrow_uid: str, body: VerifyEscrowRequest
    ) -> VerifyEscrowResponse:
        """Read the escrow from chain and confirm caller-supplied terms without writes."""
        try:
            result = await self._svc.verify_escrow_dry_run(
                escrow_uid=escrow_uid, listing_id=body.listing_id,
                seller_wallet=body.seller_wallet, agreed_price=body.agreed_price,
                agreed_duration_seconds=body.agreed_duration_seconds, chain_name=body.chain_name,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            logger.error("[ADMIN SETTLE] verify_escrow failed: %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return VerifyEscrowResponse(**result)

    @admin_settle_router.post(
        "/{escrow_uid}/evaluate",
        response_model=EvaluateSettleResponse,
        summary="Evaluate provisioning job spec for a settlement (dry-run, no writes)",
    )
    async def evaluate_settle(
        self, escrow_uid: str, body: EvaluateSettleRequest
    ) -> EvaluateSettleResponse:
        """Resolve inventory and build a job spec without chain reads or database writes."""
        try:
            result = await self._svc.evaluate_settle_dry_run(
                escrow_uid=escrow_uid, listing_id=body.listing_id,
                ssh_public_key=body.ssh_public_key, duration_seconds=body.duration_seconds,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            logger.error("[ADMIN SETTLE] evaluate_settle failed: %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return EvaluateSettleResponse(**result)

    @admin_settle_router.get(
        "/{escrow_uid}/wait",
        response_model=SettleWaitResponse,
        summary="Long-poll until settlement reaches a terminal state (admin)",
    )
    async def wait_for_settlement(
        self,
        escrow_uid: str,
        timeout: float = Query(default=60.0, gt=0, le=120),
    ) -> SettleWaitResponse:
        """Block until settlement is terminal or the bounded timeout elapses."""
        start = time.monotonic()
        deadline = start + timeout
        while True:
            job = await self._db.load_vm_settlement_job(reference=escrow_uid) or {}
            status = job.get("status", "unknown")
            elapsed_ms = int((time.monotonic() - start) * 1000)
            remaining = deadline - time.monotonic()
            if status in {"ready", "failed"} or remaining <= 0:
                return SettleWaitResponse(
                    ready=status in {"ready", "failed"}, status=status,
                    provisioning_job_id=job.get("provisioning_job_id"),
                    fulfillment_id=job.get("fulfillment_id"), elapsed_ms=elapsed_ms,
                )
            await asyncio.sleep(min(1.0, remaining))
