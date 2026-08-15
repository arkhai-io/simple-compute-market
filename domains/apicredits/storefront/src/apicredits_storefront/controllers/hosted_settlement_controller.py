"""Signed hosted settlement and issuance-evidence routes for API credits."""

from __future__ import annotations

from typing import Any

from core_storefront.auth import AuthError, authenticate_request
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi_utils.cbv import cbv
from market_identity import Identity
from market_settlement_runtime import HostedSettlementRouteError, HostedSettlementStart

import apicredits_storefront.container as _container
from apicredits_storefront.controllers.issuance_evidence_controller import (
    make_issuance_evidence_router,
)
from apicredits_storefront.hosted_routes import build_api_credit_hosted_route_service
from apicredits_storefront.middleware import buyer_auth
from apicredits_storefront.middleware.response_auth import bind_response_auth
from apicredits_storefront.settlement_models import (
    ApiCreditsHostedSettlementResponse,
)

router = APIRouter(prefix="/api/v1", tags=["hosted-settlement"])


@cbv(router)
class HostedSettlementsController:
    def __init__(
        self,
        db: Any = Depends(lambda: _container.resolved_sqlite_client),
    ) -> None:
        self._db = db

    @staticmethod
    def _composition() -> Any:
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
                expected_principal=expected_principal,
                body=dict(body) if body is not None else None,
                allow_exact_retry=True,
            )

        return build_api_credit_hosted_route_service(
            composition=self._composition(),
            sqlite_client=self._db,
            authorize_request=authorize,
        )

    @staticmethod
    def _raise(exc: HostedSettlementRouteError) -> None:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    @router.post(
        "/settlements",
        response_model=ApiCreditsHostedSettlementResponse,
        summary="Start one accepted hosted API-credit obligation",
    )
    async def start(
        self,
        body: HostedSettlementStart,
        request: Request,
    ) -> ApiCreditsHostedSettlementResponse:
        try:
            projected = await self._service().start(request, body)
        except HostedSettlementRouteError as exc:
            self._raise(exc)
        return ApiCreditsHostedSettlementResponse.model_validate(projected)

    @router.get(
        "/settlements/{settlement_ref}",
        response_model=ApiCreditsHostedSettlementResponse,
        summary="Retrieve hosted funding, issuance, evidence, and collection status",
    )
    async def status(
        self,
        settlement_ref: str,
        request: Request,
    ) -> ApiCreditsHostedSettlementResponse:
        try:
            projected = await self._service().status(request, settlement_ref)
        except HostedSettlementRouteError as exc:
            self._raise(exc)
        return ApiCreditsHostedSettlementResponse.model_validate(projected)

    @router.post(
        "/settlements/{settlement_ref}/reclaim",
        response_model=ApiCreditsHostedSettlementResponse,
        summary="Reclaim an eligible unissued hosted API-credit obligation",
    )
    async def reclaim(
        self,
        settlement_ref: str,
        request: Request,
    ) -> ApiCreditsHostedSettlementResponse:
        try:
            projected = await self._service().reclaim(request, settlement_ref)
        except HostedSettlementRouteError as exc:
            self._raise(exc)
        return ApiCreditsHostedSettlementResponse.model_validate(projected)


async def _authenticate_evidence_resolver(request: Request) -> Identity:
    composition = _container.resolved_settlement_composition
    db = _container.resolved_sqlite_client
    if composition is None or db is None:
        raise HTTPException(status_code=503, detail="storefront is not initialized")
    stripe = composition.settlement_config.mechanism_config("stripe")
    trust = getattr(stripe, "authority", None)
    if trust is None:
        raise HTTPException(status_code=503, detail="hosted authority trust is unavailable")
    try:
        authenticated = await authenticate_request(
            headers=request.headers,
            method=request.method,
            operation="resolve_api_credit_issuance_evidence",
            resource=str(request.path_params.get("evidence_digest") or ""),
            expected_role="authority",
            replay_store=db,
            allowed_principals=trust.principals,
        )
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    bind_response_auth(
        request,
        authenticated,
        operation="resolve_api_credit_issuance_evidence",
        resource=str(request.path_params.get("evidence_digest") or ""),
    )
    return authenticated.principal


evidence_router = make_issuance_evidence_router(
    lambda: _container.resolved_issuance_evidence_service,
    _authenticate_evidence_resolver,
)
