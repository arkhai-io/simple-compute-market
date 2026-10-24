"""System: health, the administrator's status read, and the stage-event log."""

from __future__ import annotations

from typing import Annotated

from core_storefront.models.system_models import STAGE_EVENT_PAGE_CAP, HealthResponse
from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from fastapi_utils.cbv import cbv

import apicredits_storefront.container as _container
from apicredits_storefront.controllers.binding import serve

router = APIRouter(tags=["system"])


@cbv(router)
class SystemController:
    @router.get("/health", response_model=HealthResponse, summary="Liveness probe")
    async def health_bare(self) -> HealthResponse:
        return await serve(_container.SYSTEM_ROUTES.health())

    @router.get("/api/v1/system/health", response_model=HealthResponse, summary="Versioned health alias")
    async def health_versioned(self) -> HealthResponse:
        return await serve(_container.SYSTEM_ROUTES.health())

    @router.get("/api/v1/system/status", response_model=HealthResponse, summary="Full diagnostic status")
    async def system_status(self, request: Request) -> HealthResponse:
        # The administrator's read, signed as the other storefronts' is, so the
        # canonical client reads it.
        await _container.AUTH.authenticate_admin(
            request, operation="admin_system_status", resource="system/status"
        )
        return await serve(_container.SYSTEM_ROUTES.status())

    @router.get("/api/v1/system/events", summary="Stage event log")
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
        resource = await serve(
            _container.SYSTEM_ROUTES.events_resource(request.query_params.multi_items())
        )
        await _container.AUTH.authenticate_admin(
            request, operation="admin_system_events", resource=resource
        )
        events = await serve(
            _container.SYSTEM_ROUTES.events(
                since_id=since_id,
                last_event_id=request.headers.get("last-event-id"),
                limit=limit,
                stream=stream,
                stage=stage,
                listing_id=listing_id,
                negotiation_id=negotiation_id,
            )
        )
        if not stream:
            return events
        return StreamingResponse(events, media_type="text/event-stream")
