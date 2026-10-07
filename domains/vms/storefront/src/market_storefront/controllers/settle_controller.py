"""Settle controller — post-negotiation escrow and provisioning status."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from arkhai_vms import normalize_vm_provision_terms
from core_storefront.models.settle_models import (
    EvaluateSettleRequest,
    EvaluateSettleResponse,
    RefundSettlementResponse,
    SettleResponse,
    SettleStatusResponse,
    SettleWaitResponse,
    VerifyEscrowRequest,
    VerifyEscrowResponse,
)
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi_utils.cbv import cbv
from market_arkhai_payments import ARKHAI_PAYMENTS_MECHANISM
from market_identity import Identity

import market_storefront.container as _container
from market_storefront.middleware import buyer_auth
from market_storefront.middleware.admin_auth import require_admin_key
from market_storefront.models.settle_models import (
    VmPaymentsSettleRequest,
    VmSettleRequest,
)
from market_storefront.payment_settlement import PaymentSettlementError
from market_storefront.services.admin_settle_service import AdminSettleService
from market_storefront.settlement_composition import serialize_settlement_job
from market_storefront.utils.escrow_verification import EscrowVerificationError

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
        if selected.get("mechanism") == ARKHAI_PAYMENTS_MECHANISM:
            if not isinstance(body, VmPaymentsSettleRequest) or escrow_uid != body.negotiation_id:
                raise HTTPException(status_code=400, detail="Arkhai settlement uses negotiation ID only")
            composition = _container.resolved_settlement_composition
            coordinator = getattr(composition, "payments_coordinator", None)
            if coordinator is None:
                raise HTTPException(status_code=503, detail="Arkhai settlement is unavailable")
            if auth.exact_retry and auth.recorded_outcome is None:
                raise HTTPException(status_code=409, detail="request retry is pending")
            try:
                result = await coordinator.start(body.negotiation_id, thread)
            except PaymentSettlementError as exc:
                raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
            payload = serialize_settlement_job(result.payload) if "created_at" in result.payload else dict(result.payload)
            payload["buyer_principal"] = Identity.model_validate(thread["buyer_principal"]).model_dump(mode="json")
            payload["seller_principal"] = composition.local_principal.model_dump(mode="json")
            return JSONResponse(content=payload, status_code=result.status_code)
        if not isinstance(body, VmSettleRequest):
            raise HTTPException(status_code=400, detail="Alkahest settlement requires EVM inputs")
        if auth.exact_retry:
            if auth.recorded_outcome is None:
                raise HTTPException(status_code=409, detail="request retry is pending")
            status_code, payload = auth.recorded_outcome
            return JSONResponse(content=payload, status_code=status_code)

        persisted_negotiation_id = str(
            thread.get("negotiation_id") or body.negotiation_id
        )
        existing = await self._db.load_escrow(escrow_uid=escrow_uid)
        if (
            existing is not None
            and existing.get("negotiation_id") != persisted_negotiation_id
        ):
            raise HTTPException(
                status_code=403,
                detail="escrow does not match persisted negotiation binding",
            )
        try:
            persisted_buyer = Identity.model_validate(thread.get("buyer_principal"))
            provision = normalize_vm_provision_terms(thread.get("provision_terms"))
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=409,
                detail="accepted negotiation terms are invalid",
            ) from exc
        accepted_ssh_public_key = provision.ssh_public_key
        if not accepted_ssh_public_key.strip():
            raise HTTPException(
                status_code=409,
                detail="accepted provision terms have no SSH public key",
            )
        if body.ssh_public_key != accepted_ssh_public_key:
            raise HTTPException(
                status_code=403,
                detail="SSH public key does not match accepted provision terms",
            )

        proposal = thread.get("buyer_escrow_proposal")
        if not isinstance(proposal, dict):
            raise HTTPException(
                status_code=409,
                detail="accepted negotiation has no settlement selection",
            )
        selection = proposal.get("settlement_selection")
        mechanism = (
            selection.get("mechanism") if isinstance(selection, dict) else "alkahest.v1"
        )
        if mechanism != "alkahest.v1":
            raise HTTPException(
                status_code=400,
                detail="this route accepts only alkahest.v1",
            )
        accepted_chain = proposal.get("chain_name")
        if not isinstance(accepted_chain, str) or not accepted_chain:
            raise HTTPException(
                status_code=409,
                detail="accepted settlement terms have no chain",
            )
        if body.chain_name != accepted_chain:
            raise HTTPException(
                status_code=403,
                detail="settlement chain does not match accepted terms",
            )

        composition = _container.resolved_settlement_composition
        if composition is None:
            raise HTTPException(
                status_code=503, detail="settlement runtime is unavailable"
            )
        mechanism_client = composition.mechanism_clients.get(mechanism)
        if mechanism_client is None:
            raise HTTPException(
                status_code=400,
                detail=f"settlement mechanism {mechanism!r} is not configured",
            )
        if accepted_chain not in _container.configured_chain_names():
            raise HTTPException(
                status_code=400,
                detail=(
                    f"chain {accepted_chain!r} not configured on this storefront — "
                    f"available chains: {sorted(_container.configured_chain_names())}"
                ),
            )
        try:
            result = await composition.coordinator.start(
                escrow_uid=escrow_uid,
                negotiation_id=persisted_negotiation_id,
                mechanism_client=mechanism_client,
                chain_name=accepted_chain,
                request=None,
            )
        except EscrowVerificationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            logger.error("[SETTLE] settlement start failed: %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

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
        job = await self._db.load_escrow(escrow_uid=escrow_uid)
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
            job = await self._db.load_escrow(escrow_uid=escrow_uid) or {}
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

@settlements_router.post(
    "/settlements/{negotiation_id}/refund",
    response_model=RefundSettlementResponse,
    summary="Refund an accepted payment deal",
    description=(
        "Seller-facing. Requires the storefront's own seller v2 signature. Reverses "
        "the deal's still-held payment and records it refunded so delivery cannot "
        "start; anything already delivered is left in place."
    ),
)
async def refund_settlement(negotiation_id: str) -> Any:
    db = _container.resolved_sqlite_client
    thread = await db.load_negotiation_thread_row(negotiation_id=negotiation_id)
    if not isinstance(thread, dict) or thread.get("terminal_state") != "success":
        raise HTTPException(status_code=404, detail="accepted negotiation not found")
    agreement_raw = thread.get("agreement_bytes")
    agreement = json.loads(agreement_raw) if isinstance(agreement_raw, bytes) else {}
    if (agreement.get("settlement") or {}).get("mechanism") != ARKHAI_PAYMENTS_MECHANISM:
        raise HTTPException(
            status_code=409, detail="this settlement mechanism refunds through its own path"
        )
    coordinator = getattr(_container.resolved_settlement_composition, "payments_coordinator", None)
    if coordinator is None:
        raise HTTPException(status_code=503, detail="Arkhai settlement is unavailable")
    try:
        result = await coordinator.refund(negotiation_id, thread)
    except PaymentSettlementError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return JSONResponse(content=result.payload, status_code=result.status_code)
