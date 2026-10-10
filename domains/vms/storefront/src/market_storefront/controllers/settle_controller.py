"""Settle controller — post-negotiation escrow and provisioning status."""

from __future__ import annotations

import json
import logging
from typing import Any

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
from market_identity import Identity
from market_settlement_runtime import (
    SettlementAdminRouteError,
    SettlementAdminRouteService,
)
from storefront_client.settlement_routes import SETTLE_STATUS

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
            SETTLE_STATUS.operation,
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
        checks = AdminSettleService(
            sqlite_client=db,
            alkahest_clients=_container.resolved_alkahest_clients,
        )

        async def verify(escrow_uid: str, request):
            try:
                return await checks.verify_escrow_dry_run(
                    escrow_uid=escrow_uid, **dict(request)
                )
            except ValueError as exc:
                raise LookupError(str(exc)) from exc

        async def preview(escrow_uid: str, request):
            try:
                return await checks.evaluate_settle_dry_run(
                    escrow_uid=escrow_uid, **dict(request)
                )
            except ValueError as exc:
                raise LookupError(str(exc)) from exc

        async def settle_status(escrow_uid: str):
            return await db.load_vm_settlement_job(reference=escrow_uid)

        self._routes = SettlementAdminRouteService(
            verify=verify,
            preview_fulfillment=preview,
            settle_status=settle_status,
            is_terminal=lambda status: status.get("status") in {"ready", "failed"},
        )

    async def _routed(self, call):
        try:
            return await call
        except SettlementAdminRouteError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    @admin_settle_router.post(
        "/{escrow_uid}/verify",
        response_model=VerifyEscrowResponse,
        summary="Verify an on-chain escrow matches expected terms (dry-run, no DB writes)",
    )
    async def verify_escrow(
        self, escrow_uid: str, body: VerifyEscrowRequest
    ) -> VerifyEscrowResponse:
        """Read the escrow from chain and confirm it matches caller-supplied terms.

        No DB writes. Returns valid=True/False.
        """
        result = await self._routed(
            self._routes.verify(escrow_uid, body.model_dump(mode="python"))
        )
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

        No chain reads, no DB writes.
        """
        result = await self._routed(
            self._routes.evaluate(escrow_uid, body.model_dump(mode="python"))
        )
        return EvaluateSettleResponse(**result)

    @admin_settle_router.get(
        "/{escrow_uid}/wait",
        response_model=SettleWaitResponse,
        summary="Long-poll until settlement reaches a terminal state (admin)",
        description=(
            "Blocks server-side until the settlement job for *escrow_uid* reaches "
            "``ready`` or ``failed``, or until *timeout* seconds elapse. "
            "Returns immediately if the job is already terminal."
        ),
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
        """Server-side long-poll: block until settlement is terminal or timeout elapses."""
        waited = await self._routes.wait(escrow_uid, timeout=timeout)
        return SettleWaitResponse(
            ready=waited["ready"],
            status=waited["status"],
            provisioning_job_id=waited.get("provisioning_job_id"),
            fulfillment_id=waited.get("fulfillment_id"),
            elapsed_ms=waited["elapsed_ms"],
        )


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
    composition = _container.resolved_settlement_composition
    if composition is None:
        raise HTTPException(status_code=503, detail="settlement runtime is unavailable")
    stage = composition.seller_stages.get((agreement.get("settlement") or {}).get("mechanism"))
    refund = getattr(stage, "refund", None)
    if refund is None:
        # A mechanism whose seller entry has no refund operation refunds
        # through its own path (an Alkahest deal through its listing refund).
        raise HTTPException(
            status_code=409, detail="this settlement mechanism refunds through its own path"
        )
    status_code, payload = await refund(
        negotiation_id=negotiation_id, thread=thread, composition=composition
    )
    RefundSettlementResponse.model_validate(payload)
    return JSONResponse(content=payload, status_code=status_code)
