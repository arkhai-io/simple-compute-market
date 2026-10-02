"""System controller — health, liveness, and stage events."""

from __future__ import annotations

import logging
from typing import Annotated
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from fastapi_utils.cbv import cbv
from market_storefront_kit import StageEventRouteService

import apicredits_storefront.container as _container
from apicredits_storefront.middleware.admin_auth import authenticate_admin
from apicredits_storefront.server import is_globally_paused
from core_storefront.models.system_models import (
    STAGE_EVENT_PAGE_CAP,
    HealthResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["system"])


def _stage_events_resource(request: Request) -> str:
    """The resource the canonical storefront client signs for an events read.

    Every filter the client may send is bound, with its defaults made explicit,
    so a signed page cannot be replayed with a different filter.
    """
    query = request.query_params
    values = {
        "limit": query.get("limit", "100"),
        "since_id": query.get("since_id", "0"),
        "stream": query.get("stream", "false").lower(),
    }
    for name in ("listing_id", "negotiation_id", "stage"):
        value = query.get(name)
        if value is not None:
            values[name] = value
    return "system-events?" + urlencode(sorted(values.items()), quote_via=quote, safe="")


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
        body["paused"] = is_globally_paused()
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
        await authenticate_admin(
            request,
            operation="admin_system_events",
            resource=_stage_events_resource(request),
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
