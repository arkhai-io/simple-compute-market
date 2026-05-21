"""System controller — health, liveness, policy diagnostics, and stage events."""
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
    PolicyEvaluateRequest,
    PolicyEvaluateResponse,
    PolicyStatusResponse,
    RegistryAgentReadyResponse,
    SeedPoliciesResponse,
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
        policy_svc=Depends(lambda: _container.resolved_policy_service),
    ) -> None:
        self._db = db
        self._svc = system_svc
        self._policy_svc = policy_svc

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
        "/api/v1/system/wait-for-registry-agent",
        response_model=RegistryAgentReadyResponse,
        summary="Long-poll until this agent is indexed in the registry (admin)",
        description=(
            "Blocks server-side until ``registry_auth_check()`` returns a "
            "definitive result — i.e. the registry has indexed this agent and "
            "the storefront can confirm ownership, or a terminal error occurred. "
            "Returns immediately on any result other than ``agent_not_found`` "
            "(which is the transient state while the registry's EventSync is "
            "still catching up). Times out after *timeout* seconds (max 120). "
            "Intended for the e2e test suite's stage 03c gate."
        ),
        dependencies=[Depends(require_admin_key)],
    )
    async def wait_for_registry_agent(
        self,
        timeout: Annotated[float, Query(gt=0, le=120)] = 90.0,
    ) -> RegistryAgentReadyResponse:
        return RegistryAgentReadyResponse(**(await self._svc.wait_for_registry_agent(timeout)))

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

    @router.post(
        "/api/v1/admin/policy/seed",
        response_model=SeedPoliciesResponse,
        summary="Discover callables and seed default policies",
        dependencies=[Depends(require_admin_key)],
    )
    async def policy_seed(self) -> SeedPoliciesResponse:
        try:
            result = await self._svc.seed_policies()
        except Exception as exc:
            logger.error("[POLICY SEED] %s", exc)
            raise HTTPException(status_code=500, detail=str(exc))
        return result  # SystemService.seed_policies returns SeedPoliciesResponse directly

    @router.get(
        "/api/v1/system/policy",
        response_model=PolicyStatusResponse,
        summary="Policy callable registry and seeded policies",
    )
    async def policy_status(self) -> PolicyStatusResponse:
        result = await self._svc.get_policy_status()
        return result  # SystemService.get_policy_status returns PolicyStatusResponse directly

    @router.post(
        "/api/v1/system/policy/evaluate",
        response_model=PolicyEvaluateResponse,
        summary="Dry-run an order_create event against the policy",
    )
    async def policy_evaluate(self, body: PolicyEvaluateRequest) -> PolicyEvaluateResponse:
        if body.event_type != "order_create":
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported event_type: {body.event_type!r}. Only 'order_create' is supported.",
            )
        if not body.offer or not body.accepted_escrows:
            raise HTTPException(
                status_code=400,
                detail="Request body must include 'offer' and 'accepted_escrows'.",
            )
        try:
            result = await self._policy_svc.evaluate_listing_create_policy_from_raw(
                offer_raw=body.offer,
                accepted_escrows=body.accepted_escrows,
                max_duration_seconds=body.max_duration_seconds,
                policy_components=body.policy_components,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            logger.warning("[POLICY EVAL] %s", exc)
            raise HTTPException(status_code=500, detail=str(exc))
        return PolicyEvaluateResponse(
            action=result.action, policy_used=result.policy_used,
            components=result.components, resolvable=result.resolvable,
            reason=result.reason,
        )