"""Keys API bindings: issuance (market-facing), consume/verify (middleware-facing),
and the admin/guard surface.

Router-factory style (like ``market_site.router``): endpoints resolve the
route service per request through ``get_service`` so the composition root
owns construction order. Each binding maps its route to the authority's route
service and a refusal to its response, and holds no decision of its own.
"""

from __future__ import annotations

from typing import Callable

from arkhai_api_authority import AuthorityRouteService, RouteRefusal
from arkhai_api_contracts.models import (
    AdjustRequest,
    ConsumeBatchRequest,
    ConsumeBatchResponse,
    ConsumeRequest,
    GrantListResponse,
    KeyListResponse,
    UsageListResponse,
    VerifyRequest,
    issuance_request_model,
    issuance_response_model,
)
from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from apicredits_service.config import authority_config

IssuanceRequest = issuance_request_model(authority_config.label)
IssuanceResponse = issuance_response_model(authority_config.label)


def _refused(refusal: RouteRefusal) -> JSONResponse:
    return JSONResponse(status_code=refusal.status_code, content=refusal.body)


def make_keys_router(get_service: Callable[[], AuthorityRouteService]) -> APIRouter:
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
        service: AuthorityRouteService = Depends(get_service),
    ) -> IssuanceResponse:
        """Commit or replay one immutable fulfillment grant."""
        try:
            return IssuanceResponse(**service.issue(body))
        except RouteRefusal as refusal:
            return _refused(refusal)

    @router.get(
        "/issuance/{fulfillment_id}",
        response_model=IssuanceResponse,
        summary="Resolve a committed grant without bearer material",
    )
    def get_issuance(
        fulfillment_id: str,
        service: AuthorityRouteService = Depends(get_service),
    ) -> IssuanceResponse:
        try:
            return IssuanceResponse(**service.get_issuance(fulfillment_id))
        except RouteRefusal as refusal:
            return _refused(refusal)

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
        service: AuthorityRouteService = Depends(get_service),
    ):
        try:
            return service.consume(key_id, amount=body.amount, idempotency_key=body.idempotency_key)
        except RouteRefusal as refusal:
            return _refused(refusal)

    @router.post(
        "/keys/consume-batch",
        response_model=ConsumeBatchResponse,
        summary="Apply a middleware flush of consume items",
    )
    def consume_batch(
        body: ConsumeBatchRequest,
        service: AuthorityRouteService = Depends(get_service),
    ) -> ConsumeBatchResponse:
        """Items are independent; per-item outcomes return in order with
        a 200 overall (a failed item is not an HTTP failure)."""
        return ConsumeBatchResponse(
            **service.consume_batch([item.model_dump() for item in body.items])
        )

    @router.post(
        "/keys/{key_id}/verify",
        summary="Verify a presented bearer secret",
    )
    def verify(
        key_id: str,
        body: VerifyRequest,
        service: AuthorityRouteService = Depends(get_service),
    ) -> dict:
        """POST (not GET) so the secret rides the body, never a URL."""
        return service.verify(key_id, secret=body.secret)

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
        service: AuthorityRouteService = Depends(get_service),
    ) -> KeyListResponse:
        return KeyListResponse(**service.list_keys(status=status, owner_id=owner_id))

    @router.get(
        "/keys/{key_id}",
        summary="Key detail — status, ownership claim, balance",
    )
    def get_key(
        key_id: str,
        service: AuthorityRouteService = Depends(get_service),
    ) -> dict:
        """The negotiation guards' key→owner lookup rides this endpoint."""
        try:
            return service.get_key(key_id)
        except RouteRefusal as refusal:
            return _refused(refusal)

    @router.post(
        "/keys/{key_id}/revoke",
        summary="Revoke a key (idempotent)",
    )
    def revoke(
        key_id: str,
        service: AuthorityRouteService = Depends(get_service),
    ) -> dict:
        try:
            return service.revoke(key_id)
        except RouteRefusal as refusal:
            return _refused(refusal)

    @router.post(
        "/keys/{key_id}/adjust",
        summary="Operator credit adjustment (recorded as a grant)",
    )
    def adjust(
        key_id: str,
        body: AdjustRequest,
        service: AuthorityRouteService = Depends(get_service),
    ) -> dict:
        try:
            return service.adjust(key_id, delta=body.delta, reason=body.reason)
        except RouteRefusal as refusal:
            return _refused(refusal)

    @router.get(
        "/keys/{key_id}/grants",
        response_model=GrantListResponse,
        summary="Credit grants for a key",
    )
    def list_grants(
        key_id: str,
        service: AuthorityRouteService = Depends(get_service),
    ) -> GrantListResponse:
        return GrantListResponse(**service.list_grants(key_id))

    @router.get(
        "/keys/{key_id}/usage",
        response_model=UsageListResponse,
        summary="Consumption log for a key (paged by event id)",
    )
    def list_usage(
        key_id: str,
        after_id: int = Query(default=0, ge=0),
        limit: int = Query(default=500, ge=1, le=5000),
        service: AuthorityRouteService = Depends(get_service),
    ) -> UsageListResponse:
        return UsageListResponse(**service.list_usage(key_id, after_id=after_id, limit=limit))

    return router
