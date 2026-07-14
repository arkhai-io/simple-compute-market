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
            "Buyer-facing. Requires EIP-191 signed `X-Signature` + "
            "`X-Timestamp` headers; the timestamp is the heartbeat's "
            "claimed send time and must be strictly newer than the "
            "deal's last recorded heartbeat."
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

        buyer_auth.deal_heartbeat_auth(escrow_uid, body, request)

        escrow = await self._db.load_escrow(escrow_uid=escrow_uid)
        if escrow is None:
            raise HTTPException(status_code=404, detail=f"Unknown deal {escrow_uid}")

        # Bind the heartbeat to the deal's buyer when the negotiation
        # recorded one — a valid signature from the wrong wallet is not
        # evidence for this deal.
        thread = await self._db.load_negotiation_thread_row(
            negotiation_id=escrow.get("negotiation_id"),
        )
        recorded_buyer = (thread or {}).get("buyer") or ""
        if (
            recorded_buyer.startswith("0x")
            and recorded_buyer.lower() != body.buyer_address.lower()
        ):
            raise HTTPException(
                status_code=403,
                detail="signer is not this deal's buyer",
            )

        try:
            payload = validate_vm_heartbeat_payload(body.payload)
        except VmHeartbeatError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        # The signed X-Timestamp is the claimed send time (already
        # skew-checked by signature verification; heartbeats re-check
        # against their own window and enforce monotonicity).
        try:
            sent_at = float(request.headers.get("X-Timestamp", ""))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Missing X-Timestamp") from exc

        try:
            record = await record_heartbeat(
                self._db,
                deal_ref=escrow_uid,
                signer=body.buyer_address,
                sent_at_unix=sent_at,
                payload=payload,
            )
        except HeartbeatError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

        count = await self._db.count_heartbeats(escrow_uid)
        stage_event(
            "service", "heartbeat_recorded",
            deal_ref=escrow_uid,
            signer=body.buyer_address,
            count=count,
            status=payload.get("status"),
        )
        cadence = float(getattr(settings, "heartbeat_interval_seconds", 60))
        return DealHeartbeatResponse(
            deal_ref=escrow_uid,
            sent_at_unix=record["sent_at_unix"],
            heartbeat_count=count,
            next_expected_by_unix=record["sent_at_unix"] + cadence,
        )
