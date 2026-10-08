"""System controller — health, liveness, and stage events."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from fastapi_utils.cbv import cbv
from market_storefront_kit import DealControlRouteError, StageEventRouteService

import apicredits_storefront.container as _container
from apicredits_storefront.middleware.admin_auth import authenticate_admin
from core_storefront.models.system_models import (
    STAGE_EVENT_PAGE_CAP,
    HealthResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["system"])


@cbv(router)
class SystemController:
    def __init__(
        self,
        db=Depends(lambda: _container.resolved_sqlite_client),
        system_svc=Depends(lambda: _container.resolved_system_service),
    ) -> None:
        self._db = db
        self._svc = system_svc

    @router.get("/health", response_model=HealthResponse, summary="Liveness probe")
    async def health_bare(self) -> HealthResponse:
        return HealthResponse(**(await self._svc.get_health()))

    @router.get(
        "/api/v1/system/health",
        response_model=HealthResponse,
        summary="Versioned health alias",
    )
    async def health_versioned(self) -> HealthResponse:
        return HealthResponse(**(await self._svc.get_health()))

    @router.get(
        "/api/v1/system/status",
        response_model=HealthResponse,
        summary="Full diagnostic status",
    )
    async def system_status(self) -> HealthResponse:
        body = await self._svc.get_health(include_registry=True)
        body["paused"] = _container.trading_pause.paused
        return HealthResponse(**body)

    @router.get(
        "/api/v1/system/events",
        summary="Stage event log",
    )
    async def stream_events(
        self,
        request: Request,
        since_id: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=STAGE_EVENT_PAGE_CAP)] = 100,
        stream: Annotated[bool, Query()] = False,
        stage: Annotated[str | None, Query()] = None,
        listing_id: Annotated[str | None, Query()] = None,
        negotiation_id: Annotated[str | None, Query()] = None,
    ):
        try:
            resource = StageEventRouteService.signed_resource(
                request.query_params.multi_items()
            )
        except DealControlRouteError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
        await authenticate_admin(
            request, operation="admin_system_events", resource=resource
        )
        events = StageEventRouteService(self._db)
        since_id = events.resume_point(since_id, request.headers.get("last-event-id"))
        filters = {
            "stage": stage,
            "listing_id": listing_id,
            "negotiation_id": negotiation_id,
        }
        if not stream:
            return await events.page(since_id=since_id, limit=limit, **filters)
        return StreamingResponse(
            events.stream(since_id=since_id, **filters),
            media_type="text/event-stream",
        )
