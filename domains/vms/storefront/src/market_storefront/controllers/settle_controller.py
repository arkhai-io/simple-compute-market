"""Settle controller — post-negotiation escrow and provisioning status."""

from __future__ import annotations

import logging
from typing import Any

from arkhai_vms import normalize_vm_provision_terms
from core_storefront.models.settle_models import (
    EvaluateSettleRequest,
    EvaluateSettleResponse,
    SettleResponse,
    SettleStatusResponse,
    SettleWaitResponse,
    VerifyEscrowRequest,
    VerifyEscrowResponse,
)
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi_utils.cbv import cbv
from market_settlement_runtime import (
    SettlementAdminRouteError,
    SettlementAdminRouteService,
)
from market_identity import EMPTY_BODY, Identity
from market_settlement_runtime import (
    HostedSettlementRouteError,
    HostedSettlementStart,
)

import market_storefront.container as _container
from market_storefront.hosted_routes import build_vm_hosted_route_service
from market_storefront.middleware import buyer_auth
from market_storefront.middleware.admin_auth import require_admin_key
from market_storefront.models.hosted_settlement_models import SettlementPublicResponse
from market_storefront.models.settle_models import VmSettleRequest
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
        body: VmSettleRequest,
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
                detail="hosted obligations use /api/v1/settlements",
            )
        accepted_chain = proposal.get("chain_name")
        if not isinstance(accepted_chain, str) or not accepted_chain:
            raise HTTPException(
                status_code=409,
                detail="accepted settlement terms have no chain",
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


@cbv(settlements_router)
class SettlementsController:
    def __init__(
        self,
        db: Any = Depends(lambda: _container.resolved_sqlite_client),  # noqa: B008
    ) -> None:
        self._db = db

    @staticmethod
    def _composition():
        composition = _container.resolved_settlement_composition
        if composition is None or "fiat.stripe.v1" not in composition.mechanism_clients:
            raise HTTPException(
                status_code=503,
                detail="hosted settlement runtime is unavailable",
            )
        return composition

    def _service(self):
        async def authorize(
            request_context: Request,
            operation: str,
            resource_id: str,
            expected_principal: Identity,
            body: Any,
        ):
            return await buyer_auth._verify(
                request_context,
                operation,
                resource_id,
                expected_principal,
                dict(body) if body is not None else EMPTY_BODY,
            )

        return build_vm_hosted_route_service(
            composition=self._composition(),
            sqlite_client=self._db,
            authorize_request=authorize,
        )

    @staticmethod
    def _raise_route_error(exc: HostedSettlementRouteError) -> None:
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.detail,
        ) from exc

    @settlements_router.post(
        "/settlements",
        response_model=SettlementPublicResponse,
        summary="Start one accepted hosted settlement obligation",
    )
    async def start(
        self,
        body: HostedSettlementStart,
        request: Request,
    ) -> SettlementPublicResponse:
        try:
            projected = await self._service().start(request, body)
        except HostedSettlementRouteError as exc:
            self._raise_route_error(exc)
        return SettlementPublicResponse.model_validate(projected)

    @settlements_router.get(
        "/settlements/{settlement_ref}",
        response_model=SettlementPublicResponse,
        summary="Retrieve hosted funding and fulfillment status",
    )
    async def status(
        self,
        settlement_ref: str,
        request: Request,
    ) -> SettlementPublicResponse:
        try:
            projected = await self._service().status(request, settlement_ref)
        except HostedSettlementRouteError as exc:
            self._raise_route_error(exc)
        return SettlementPublicResponse.model_validate(projected)

    @settlements_router.post(
        "/settlements/{settlement_ref}/reclaim",
        response_model=SettlementPublicResponse,
        summary="Reclaim one eligible expired hosted settlement",
    )
    async def reclaim(
        self,
        settlement_ref: str,
        request: Request,
        mechanism_options: dict[str, Any] | None = Body(default=None),
    ) -> SettlementPublicResponse:
        """Reclaim one eligible expired hosted settlement.

        The body is the mechanism's own vocabulary for this one reclaim -- a
        push-funded profile needs somewhere to address the payer's return --
        so it is relayed opaquely rather than parsed into a model here.
        """
        try:
            projected = await self._service().reclaim(
                request, settlement_ref, mechanism_options
            )
        except HostedSettlementRouteError as exc:
            self._raise_route_error(exc)
        return SettlementPublicResponse.model_validate(projected)


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
            return await db.load_escrow(escrow_uid=escrow_uid)

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
