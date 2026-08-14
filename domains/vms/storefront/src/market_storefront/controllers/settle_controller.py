"""Settle controller — post-negotiation escrow and provisioning status."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

from arkhai_vms import VmProvisionTerms
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
from market_settlement_runtime import SettlementObligationRecord

import market_storefront.container as _container
from market_storefront.middleware import buyer_auth
from market_storefront.middleware.admin_auth import require_admin_key
from market_storefront.models.hosted_settlement_models import (
    SettlementPublicResponse,
    SettlementStartRequest,
)
from market_storefront.models.settle_models import VmSettleRequest
from market_storefront.services.admin_settle_service import AdminSettleService
from market_storefront.settlement_composition import (
    ensure_hosted_fulfillment,
    hosted_settlement_projection,
    load_hosted_agreement,
    serialize_settlement_job,
    truncate_lease_for_terminal_settlement,
)
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
            provision = VmProvisionTerms.model_validate(thread.get("provision_terms"))
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
                detail="hosted obligations use /api/v1/settlements",
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

    async def _record(self, settlement_ref: str) -> SettlementObligationRecord:
        composition = self._composition()
        row = await composition.repository.load_settlement_obligation_by_mechanism_ref(
            settlement_ref
        )
        if row is None:
            raise HTTPException(status_code=404, detail="settlement not found")
        record = SettlementObligationRecord.model_validate(row)
        if record.obligation.get("mechanism") != "fiat.stripe.v1":
            raise HTTPException(status_code=404, detail="settlement not found")
        return record

    async def _authorize(
        self,
        request: Request,
        *,
        operation: str,
        resource_id: str,
        record: SettlementObligationRecord,
    ) -> None:
        agreement = await load_hosted_agreement(
            sqlite_client=self._db,
            negotiation_id=record.agreement_ref,
            obligation_ref=record.obligation_ref,
        )
        auth = await buyer_auth._verify(
            request,
            operation,
            resource_id,
            agreement.buyer_principal,
        )
        if auth.exact_retry and auth.recorded_outcome is None:
            raise HTTPException(status_code=409, detail="request retry is pending")
        return auth

    @settlements_router.post(
        "/settlements",
        response_model=SettlementPublicResponse,
        summary="Start one accepted hosted settlement obligation",
    )
    async def start(
        self,
        body: SettlementStartRequest,
        request: Request,
    ) -> SettlementPublicResponse:
        composition = self._composition()
        try:
            agreement = await load_hosted_agreement(
                sqlite_client=self._db,
                negotiation_id=body.negotiation_id,
                obligation_ref=body.obligation_ref,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if (
            body.payer_principal != agreement.buyer_principal
            or body.claimant_principal != composition.local_principal
        ):
            raise HTTPException(status_code=403, detail="settlement parties mismatch")
        auth = await buyer_auth._verify(
            request,
            "settlement_start",
            agreement.obligation_ref,
            agreement.buyer_principal,
            body.model_dump(mode="json"),
        )
        if auth.exact_retry:
            if auth.recorded_outcome is None:
                raise HTTPException(status_code=409, detail="request retry is pending")
            status_code, payload = auth.recorded_outcome
            if status_code >= 400:
                raise HTTPException(status_code=status_code, detail=payload)
            return SettlementPublicResponse.model_validate(payload)

        records = await composition.runtime.register_plan(
            agreement_ref=agreement.negotiation_id,
            obligations=[agreement.obligation],
        )
        record = records[0]
        worker_id = f"settlement-start:{uuid.uuid4().hex}"
        try:
            await composition.runtime.materialize(
                obligation_ref=record.obligation_ref,
                local_principal=agreement.buyer_principal,
                worker_id=worker_id,
            )
            row = await composition.repository.load_settlement_obligation(
                record.obligation_ref
            )
            assert row is not None
            record = SettlementObligationRecord.model_validate(row)
            if record.mechanism_status == "ready":
                record = await ensure_hosted_fulfillment(
                    composition=composition,
                    sqlite_client=self._db,
                    record=record,
                    worker_id=f"settlement-fulfill:{uuid.uuid4().hex}",
                )
            projected = await hosted_settlement_projection(
                composition=composition,
                record=record,
            )
        except Exception as exc:
            logger.warning(
                "[SETTLEMENTS] Hosted settlement start failed after durable reservation"
            )
            raise HTTPException(
                status_code=503,
                detail="hosted settlement authority is temporarily unavailable",
            ) from exc
        return SettlementPublicResponse(**projected)

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
        composition = self._composition()
        record = await self._record(settlement_ref)
        await self._authorize(
            request,
            operation="settlement_status",
            resource_id=settlement_ref,
            record=record,
        )
        try:
            await composition.runtime.reconcile_status(
                obligation_ref=record.obligation_ref,
                local_principal=record.payer_principal,
                worker_id=f"settlement-status:{uuid.uuid4().hex}",
            )
            row = await composition.repository.load_settlement_obligation(
                record.obligation_ref
            )
            assert row is not None
            record = SettlementObligationRecord.model_validate(row)
            if record.mechanism_status == "ready" and not record.fulfillment_ref:
                record = await ensure_hosted_fulfillment(
                    composition=composition,
                    sqlite_client=self._db,
                    record=record,
                    worker_id=f"settlement-fulfill:{uuid.uuid4().hex}",
                )
            projected = await hosted_settlement_projection(
                composition=composition,
                record=record,
            )
        except Exception as exc:
            logger.exception(
                "[SETTLEMENTS] Hosted settlement status reconciliation failed"
            )
            raise HTTPException(
                status_code=503,
                detail="hosted settlement status is temporarily unavailable",
            ) from exc
        return SettlementPublicResponse(**projected)

    @settlements_router.post(
        "/settlements/{settlement_ref}/reclaim",
        response_model=SettlementPublicResponse,
        summary="Reclaim one eligible expired hosted settlement",
    )
    async def reclaim(
        self,
        settlement_ref: str,
        request: Request,
    ) -> SettlementPublicResponse:
        composition = self._composition()
        record = await self._record(settlement_ref)
        await self._authorize(
            request,
            operation="settlement_reclaim",
            resource_id=settlement_ref,
            record=record,
        )
        try:
            outcome = await composition.runtime.reclaim(
                obligation_ref=record.obligation_ref,
                local_principal=record.payer_principal,
                worker_id=f"settlement-reclaim:{uuid.uuid4().hex}",
            )
            if outcome.status == "busy":
                raise HTTPException(
                    status_code=409,
                    detail="settlement fulfillment or collection already reserved",
                )
            if outcome.status == "succeeded":
                await truncate_lease_for_terminal_settlement(
                    escrow_uid=settlement_ref,
                    reason="hosted settlement reclaimed",
                    sqlite_client=self._db,
                )
            row = await composition.repository.load_settlement_obligation(
                record.obligation_ref
            )
            assert row is not None
            record = SettlementObligationRecord.model_validate(row)
            projected = await hosted_settlement_projection(
                composition=composition,
                record=record,
            )
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception as exc:
            logger.warning("[SETTLEMENTS] Hosted reclaim reconciliation failed")
            raise HTTPException(
                status_code=503,
                detail="hosted settlement reclaim is temporarily unavailable",
            ) from exc
        return SettlementPublicResponse(**projected)


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
            sqlite_client=db,
            alkahest_clients=_container.resolved_alkahest_clients,
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
                chain_name=body.chain_name,
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
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            logger.error(
                "[ADMIN SETTLE] evaluate_settle failed: %s", exc, exc_info=True
            )
            raise HTTPException(status_code=500, detail=str(exc)) from exc
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
        timeout: float = Query(
            default=60.0,
            gt=0,
            le=120,
            description="Maximum seconds to wait (server-enforced, max 120)",
        ),
    ) -> SettleWaitResponse:
        """Server-side long-poll: block until settlement is terminal or timeout elapses."""
        _terminal = {"ready", "failed"}
        start = time.monotonic()
        deadline = start + timeout

        while True:
            job = await self._db.load_escrow(escrow_uid=escrow_uid)
            elapsed_ms = int((time.monotonic() - start) * 1000)
            status = (job or {}).get("status", "")
            job_id = (job or {}).get("provisioning_job_id")
            fulfillment_id = (job or {}).get("fulfillment_id")

            if status in _terminal:
                return SettleWaitResponse(
                    ready=True,
                    status=status,
                    provisioning_job_id=job_id,
                    fulfillment_id=fulfillment_id,
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
        fulfillment_id = (job or {}).get("fulfillment_id")
        return SettleWaitResponse(
            ready=False,
            status=status,
            provisioning_job_id=job_id,
            fulfillment_id=fulfillment_id,
            elapsed_ms=elapsed_ms,
        )
