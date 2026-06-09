"""System controller — health, liveness, and stage events."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from fastapi_utils.cbv import cbv

import market_storefront.container as _container
from market_storefront.middleware.admin_auth import require_admin_key
from market_storefront.models.system_models import (
    HealthResponse,
    StageEventResponse,
)
from market_storefront.server import is_globally_paused

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

    @router.get("/health", response_model=HealthResponse, summary="Kubernetes liveness probe")
    async def health_bare(self) -> HealthResponse:
        return HealthResponse(**(await self._svc.get_health()))

    @router.get("/api/v1/system/health", response_model=HealthResponse,
                summary="Versioned health alias")
    async def health_versioned(self) -> HealthResponse:
        return HealthResponse(**(await self._svc.get_health()))

    @router.get("/api/v1/system/status", response_model=HealthResponse,
                summary="Full diagnostic status (includes registry + pause state)")
    async def system_status(self) -> HealthResponse:
        body = await self._svc.get_health(include_registry=True)
        body["paused"] = is_globally_paused()
        return HealthResponse(**body)

    @router.get(
        "/api/v1/system/events",
        summary="Stage event log",
        dependencies=[Depends(require_admin_key)],
    )
    async def stream_events(
        self,
        request: Request,
        since_id: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        stream: Annotated[bool, Query()] = False,
        stage: Annotated[str | None, Query()] = None,
        listing_id: Annotated[str | None, Query()] = None,
        negotiation_id: Annotated[str | None, Query()] = None,
    ):
        last_event_id_hdr = request.headers.get("last-event-id")
        if last_event_id_hdr:
            try:
                since_id = int(last_event_id_hdr)
            except (ValueError, TypeError):
                pass

        if not stream:
            rows = await self._db.list_stage_events(
                after_id=since_id, limit=limit,
                stage=stage, listing_id=listing_id, negotiation_id=negotiation_id,
            )
            return StageEventResponse(events=rows, count=len(rows))

        async def _generate():
            cursor = since_id
            while True:
                rows = await self._db.list_stage_events(
                    after_id=cursor, limit=50,
                    stage=stage, listing_id=listing_id, negotiation_id=negotiation_id,
                )
                for row in rows:
                    cursor = row["id"]
                    yield f"id: {cursor}\ndata: {json.dumps(row, default=str)}\n\n"
                if not rows:
                    await asyncio.sleep(0.2)

        return StreamingResponse(_generate(), media_type="text/event-stream")

