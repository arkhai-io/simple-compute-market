"""Keys API: issuance (market-facing), consume/verify (middleware-facing),
and the admin/guard surface.

Router-factory style (like ``core_site.router``): endpoints resolve the
service per request through ``get_service`` so the composition root owns
construction order.
"""

from __future__ import annotations

import logging
from typing import Callable

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from models.keys_model import (
    AdjustRequest,
    ConsumeBatchRequest,
    ConsumeBatchResponse,
    ConsumeRequest,
    GrantListResponse,
    IssuanceRequest,
    IssuanceResponse,
    KeyListResponse,
    UsageListResponse,
    VerifyRequest,
)
from services.keys_service import (
    INSUFFICIENT_CREDITS,
    KEY_NOT_FOUND,
    KEY_NOT_OWNED,
    KEY_REVOKED,
    QUOTA_EXHAUSTED,
    IssuanceError,
    KeysService,
)

logger = logging.getLogger(__name__)

#: HTTP status per machine-readable refusal reason. The reason rides the
#: body either way — clients dispatch on it, not the status.
_ISSUANCE_STATUS = {
    KEY_NOT_FOUND: 404,
    KEY_NOT_OWNED: 403,
    KEY_REVOKED: 409,
    QUOTA_EXHAUSTED: 409,
}


def make_keys_router(get_service: Callable[[], KeysService]) -> APIRouter:
    router = APIRouter(tags=["keys"])

    # ------------------------------------------------------------------
    # Market-facing: issuance
    # ------------------------------------------------------------------

    @router.post(
        "/issuance",
        response_model=IssuanceResponse,
        summary="Fulfill a deal: quota commit + key + credit grant",
    )
    def issue(
        body: IssuanceRequest,
        service: KeysService = Depends(get_service),
    ) -> IssuanceResponse:
        """Idempotent on ``escrow_uid`` — safe under storefront retry."""
        try:
            result = service.issue(
                escrow_uid=body.escrow_uid,
                quantity=body.quantity,
                key_mode=body.key.mode,
                key_id=body.key.key_id,
                buyer_scheme=body.buyer.scheme if body.buyer else None,
                buyer_id=body.buyer.id if body.buyer else None,
                owner_scheme=body.owner.scheme if body.owner else None,
                owner_id=body.owner.id if body.owner else None,
                allocation_id=body.allocation_id,
                resource_id=body.resource_id,
            )
        except IssuanceError as exc:
            logger.info(
                "[ISSUANCE] refused escrow=%s: %s (%s)",
                body.escrow_uid, exc.reason, exc.message,
            )
            return JSONResponse(
                status_code=_ISSUANCE_STATUS.get(exc.reason, 409),
                content={"error": exc.reason, "detail": exc.message},
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        logger.info(
            "[ISSUANCE] escrow=%s key=%s quantity=%d already_issued=%s",
            body.escrow_uid, result["key_id"], body.quantity,
            result["already_issued"],
        )
        return IssuanceResponse(**result)

    # ------------------------------------------------------------------
    # Middleware-facing: consume / verify
    # ------------------------------------------------------------------

    @router.post(
        "/keys/{key_id}/consume",
        summary="Decrement credits (402 when exhausted)",
    )
    def consume(
        key_id: str,
        body: ConsumeRequest,
        service: KeysService = Depends(get_service),
    ):
        try:
            outcome = service.consume(
                key_id=key_id,
                amount=body.amount,
                idempotency_key=body.idempotency_key,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        if outcome.get("ok"):
            return outcome
        reason = outcome.get("reason")
        status = {
            KEY_NOT_FOUND: 404,
            KEY_REVOKED: 403,
            INSUFFICIENT_CREDITS: 402,
        }.get(reason, 402)
        return JSONResponse(
            status_code=status,
            content={"error": reason, "balance": outcome.get("balance", 0)},
        )

    @router.post(
        "/keys/consume-batch",
        response_model=ConsumeBatchResponse,
        summary="Apply a middleware flush of consume items",
    )
    def consume_batch(
        body: ConsumeBatchRequest,
        service: KeysService = Depends(get_service),
    ) -> ConsumeBatchResponse:
        """Items are independent; per-item outcomes return in order with
        a 200 overall (a failed item is not an HTTP failure)."""
        results = service.consume_batch([item.model_dump() for item in body.items])
        return ConsumeBatchResponse(results=results)

    @router.post(
        "/keys/{key_id}/verify",
        summary="Verify a presented bearer secret",
    )
    def verify(
        key_id: str,
        body: VerifyRequest,
        service: KeysService = Depends(get_service),
    ) -> dict:
        """POST (not GET) so the secret rides the body, never a URL."""
        return service.verify(key_id=key_id, secret=body.secret)

    # ------------------------------------------------------------------
    # Admin + the seller guards' key→owner lookup
    # ------------------------------------------------------------------

    @router.get(
        "/keys",
        response_model=KeyListResponse,
        summary="List keys (no secrets)",
    )
    def list_keys(
        status: str | None = Query(default=None),
        owner_id: str | None = Query(default=None),
        service: KeysService = Depends(get_service),
    ) -> KeyListResponse:
        keys = service.list_keys(status=status, owner_id=owner_id)
        return KeyListResponse(keys=keys, total=len(keys))

    @router.get(
        "/keys/{key_id}",
        summary="Key detail — status, ownership claim, balance",
    )
    def get_key(
        key_id: str,
        service: KeysService = Depends(get_service),
    ) -> dict:
        """The negotiation guards' key→owner lookup rides this endpoint."""
        key = service.get_key(key_id)
        if key is None:
            raise HTTPException(status_code=404, detail=f"key {key_id!r} not found")
        return key

    @router.post(
        "/keys/{key_id}/revoke",
        summary="Revoke a key (idempotent)",
    )
    def revoke(
        key_id: str,
        service: KeysService = Depends(get_service),
    ) -> dict:
        key = service.revoke(key_id)
        if key is None:
            raise HTTPException(status_code=404, detail=f"key {key_id!r} not found")
        return key

    @router.post(
        "/keys/{key_id}/adjust",
        summary="Operator credit adjustment (recorded as a grant)",
    )
    def adjust(
        key_id: str,
        body: AdjustRequest,
        service: KeysService = Depends(get_service),
    ) -> dict:
        try:
            key = service.adjust(
                key_id=key_id, delta=body.delta, reason=body.reason,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        if key is None:
            raise HTTPException(status_code=404, detail=f"key {key_id!r} not found")
        return key

    @router.get(
        "/keys/{key_id}/grants",
        response_model=GrantListResponse,
        summary="Credit grants for a key",
    )
    def list_grants(
        key_id: str,
        service: KeysService = Depends(get_service),
    ) -> GrantListResponse:
        grants = service.list_grants(key_id)
        return GrantListResponse(grants=grants, total=len(grants))

    @router.get(
        "/keys/{key_id}/usage",
        response_model=UsageListResponse,
        summary="Consumption log for a key (paged by event id)",
    )
    def list_usage(
        key_id: str,
        after_id: int = Query(default=0, ge=0),
        limit: int = Query(default=500, ge=1, le=5000),
        service: KeysService = Depends(get_service),
    ) -> UsageListResponse:
        events = service.list_usage(key_id, after_id=after_id, limit=limit)
        return UsageListResponse(events=events, total=len(events))

    return router
