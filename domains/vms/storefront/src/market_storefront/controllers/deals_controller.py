"""Deal-servicing endpoints: buyer heartbeats for active deals.

POST /api/v1/deals/{escrow_uid}/heartbeat — buyer-signed liveness
attestation. Auth is the standard signed-request verification
(``deal_heartbeat:<escrow_uid>:<X-Timestamp>``); the timestamp doubles
as the heartbeat's claimed send time, and ``core_storefront.heartbeats``
enforces per-deal monotonicity on it, so a replayed request is rejected
as soon as any newer heartbeat lands. Payload vocabulary is the VM
domain's (``vms.heartbeat.v1``).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi_utils.cbv import cbv

import market_storefront.container as _container
from market_storefront.middleware import buyer_auth
from core_storefront.heartbeats import HeartbeatError, record_heartbeat
from core_storefront.models.deal_models import (
    DealHeartbeatRequest,
    DealHeartbeatResponse,
)
from core_storefront.stage_log import stage_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/deals", tags=["deals"])


@cbv(router)
class DealsController:
    def __init__(
        self,
        db=Depends(lambda: _container.resolved_sqlite_client),
    ) -> None:
        self._db = db

    @router.post(
        "/{escrow_uid}/heartbeat",
        response_model=DealHeartbeatResponse,
        summary="Record a buyer liveness heartbeat for an active deal",
        description=(
            "Buyer-facing. Requires marketplace v2 request authentication; "
            "the authenticated timestamp is the heartbeat's claimed send time "
            "and must be strictly newer than the deal's last recorded heartbeat."
        ),
    )
    async def deal_heartbeat(
        self,
        escrow_uid: str,
        body: DealHeartbeatRequest,
        request: Request,
    ) -> DealHeartbeatResponse:
        from domains.vms.settlement.heartbeats import (
            VmHeartbeatError,
            validate_vm_heartbeat_payload,
        )
        from market_storefront.utils.config import settings

        auth = await buyer_auth.deal_heartbeat_auth(escrow_uid, body, request)
        if auth.exact_retry:
            if auth.recorded_outcome is None:
                raise HTTPException(status_code=409, detail="request retry is pending")
            status_code, response = auth.recorded_outcome
            if status_code >= 400:
                raise HTTPException(status_code=status_code, detail=response)
            return DealHeartbeatResponse.model_validate(response)


        escrow = await self._db.load_escrow(escrow_uid=escrow_uid)
        negotiation_id = (escrow or {}).get("negotiation_id")
        if negotiation_id is None:
            composition = _container.resolved_settlement_composition
            record = (
                await composition.repository.load_settlement_obligation_by_mechanism_ref(
                    escrow_uid
                )
                if composition is not None
                else None
            )
            negotiation_id = (record or {}).get("agreement_ref")
        if not negotiation_id:
            raise HTTPException(status_code=404, detail=f"Unknown deal {escrow_uid}")
        thread = await self._db.load_negotiation_thread_row(
            negotiation_id=negotiation_id,
        )
        if (thread or {}).get("buyer_principal") != body.buyer_principal.model_dump(
            mode="json"
        ):
            raise HTTPException(status_code=403, detail="wrong deal buyer principal")
        if (thread or {}).get("seller_principal") != body.seller_principal.model_dump(
            mode="json"
        ):
            raise HTTPException(status_code=403, detail="wrong deal seller principal")

        try:
            payload = validate_vm_heartbeat_payload(body.payload)
        except VmHeartbeatError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        try:
            sent_at = float(request.headers.get("X-Market-Timestamp", ""))
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail="Missing X-Market-Timestamp",
            ) from exc

        try:
            record = await record_heartbeat(
                self._db,
                deal_ref=escrow_uid,
                buyer_principal=body.buyer_principal,
                seller_principal=body.seller_principal,
                sent_at_unix=sent_at,
                payload=payload,
            )
        except HeartbeatError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

        count = await self._db.count_heartbeats(escrow_uid)
        stage_event(
            "service",
            "heartbeat_recorded",
            deal_ref=escrow_uid,
            principal=body.buyer_principal.model_dump(mode="json"),
            count=count,
            status=payload.get("status"),
        )
        cadence = float(getattr(settings, "heartbeat_interval_seconds", 60))
        return DealHeartbeatResponse(
            deal_ref=escrow_uid,
            buyer_principal=body.buyer_principal,
            seller_principal=body.seller_principal,
            sent_at_unix=record["sent_at_unix"],
            heartbeat_count=count,
            next_expected_by_unix=record["sent_at_unix"] + cadence,
        )
