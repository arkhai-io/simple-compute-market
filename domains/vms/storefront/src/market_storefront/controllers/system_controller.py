"""System controller — health, liveness, and stage events."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from fastapi_utils.cbv import cbv

import market_storefront.container as _container
from market_storefront.middleware.admin_auth import require_admin_key
from core_storefront.models.system_models import (
    HealthResponse,
    StageEventResponse,
)
from market_storefront.lifecycle import (
    failed_loop_names,
    loop_states,
    starting_loop_names,
)
from market_storefront.server import are_loops_paused, is_globally_paused

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

    @router.get("/health", response_model=HealthResponse,
                summary="Kubernetes liveness probe")
    async def health_bare(self, response: Response) -> HealthResponse:
        return await self._liveness(response)

    @router.get("/api/v1/system/health", response_model=HealthResponse,
                summary="Versioned health alias")
    async def health_versioned(self, response: Response) -> HealthResponse:
        return await self._liveness(response)

    async def _liveness(self, response: Response) -> HealthResponse:
        """Whether this process is worth keeping.

        Fails only for a condition no further running can resolve. A timer loop
        that ended on its own is such a condition: nothing in this process
        restarts one, so replacing the process is the only recovery available and
        a failing liveness probe is how it is requested. A loop that has merely
        not started yet is not — that resolves on its own and belongs to
        readiness, which is why the two are separate routes.
        """
        body = await self._svc.get_health()
        failed = failed_loop_names()
        if failed:
            response.status_code = 503
            logger.error(
                "[HEALTH] liveness failing: timer loop(s) ended and will not "
                "restart: %s", ", ".join(failed),
            )
        return HealthResponse(**body)

    @router.get("/ready", response_model=HealthResponse,
                summary="Kubernetes readiness probe")
    async def ready_bare(self, response: Response) -> HealthResponse:
        return await self._readiness(response)

    @router.get("/api/v1/system/ready", response_model=HealthResponse,
                summary="Versioned readiness alias")
    async def ready_versioned(self, response: Response) -> HealthResponse:
        return await self._readiness(response)

    async def _readiness(self, response: Response) -> HealthResponse:
        """Whether this storefront can be relied on yet.

        A storefront answers its routes as soon as they are mounted, which is
        earlier than its timer loops begin cycling — so an unready storefront
        looks identical to a ready one on a liveness probe. Until every loop has
        reached its gate once, the background work a caller depends on is not
        running and the loops cannot observe a lifecycle pause either.

        A storefront held at its lifecycle pause is ready. The pause is
        operator-requested, the storefront still serves and still trades, and
        failing readiness on it would make an operator control indistinguishable
        from a fault.

        Deliberately does not probe the registry: a readiness probe runs on a
        short period and must not make an outbound call per cycle.
        """
        body = await self._svc.get_health()
        states = loop_states()
        failed = failed_loop_names()
        starting = starting_loop_names()
        if failed:
            response.status_code = 503
        elif not states:
            # No loop registered at all. Reported as starting rather than as a
            # fault because that is what it is during a lifespan that has not
            # finished, and readiness is exactly the signal that distinguishes
            # "not yet" from "serving".
            response.status_code = 503
            body["status"] = "starting"
        elif starting:
            # Distinct from "degraded": nothing is wrong, the storefront has not
            # finished starting. An operator reading a probe failure should be
            # able to tell "wait" from "investigate".
            response.status_code = 503
            body["status"] = "starting"
        body["loops"] = states
        return HealthResponse(**body)

    @router.get("/api/v1/system/status", response_model=HealthResponse,
                summary="Full diagnostic status (includes registry + pause state)")
    async def system_status(self) -> HealthResponse:
        body = await self._svc.get_health(include_registry=True)
        body["paused"] = is_globally_paused()
        body["loops_paused"] = are_loops_paused()
        # Per-loop state alongside the flag: "paused" says the flag is set, and
        # this says whether the background work actually stopped. The two can
        # disagree — a loop that exited on its own reports neither running nor
        # stopped — and collapsing them into one boolean would hide that.
        body["loops"] = loop_states()
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
            rows, truncated = await self._db.list_stage_events_page(
                after_id=since_id, limit=limit,
                stage=stage, listing_id=listing_id, negotiation_id=negotiation_id,
            )
            return StageEventResponse(
                events=rows, count=len(rows), truncated=truncated,
            )

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
