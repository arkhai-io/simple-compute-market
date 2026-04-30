"""System controller — health, liveness, and policy diagnostic endpoints.

HTTP layer only.  Business logic lives in SystemService.

Endpoints
---------
  GET  /health                            Kubernetes liveness/readiness probe.
  GET  /api/v1/system/health              Versioned alias.
  GET  /api/v1/system/status              Pause state + DB health.
  POST /admin/policy/seed                 Discover callables + seed default policies.
  GET  /api/v1/system/policy              Callable registry + seeded policy diagnostic.
  POST /api/v1/system/policy/evaluate     Dry-run an order_create event.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from typing import Any, AsyncIterator

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from market_storefront.services.system_service import SystemService

logger = logging.getLogger(__name__)


class SystemController:
    def __init__(self, *, sqlite_client, globally_paused_fn, system_service: SystemService | None = None) -> None:
        self._sqlite_client = sqlite_client
        self._globally_paused_fn = globally_paused_fn
        # Injected for testing; defaults to a standard instance using the same sqlite_client.
        self._service = system_service or SystemService(sqlite_client=sqlite_client)

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def _health_impl(self, *, include_registry: bool = False) -> JSONResponse:
        checks: dict[str, str] = {"api": "ok"}
        try:
            conn = sqlite3.connect(self._sqlite_client.db_path, timeout=2)
            try:
                conn.execute("SELECT 1")
            finally:
                conn.close()
            checks["database"] = "ok"
        except Exception as exc:
            checks["database"] = f"error: {exc}"

        if include_registry:
            checks["registry"] = await self._registry_check()

        all_ok = all(v == "ok" for v in checks.values())
        return JSONResponse(
            {"status": "ok" if all_ok else "degraded", "checks": checks},
            status_code=200 if all_ok else 503,
        )

    async def _registry_check(self) -> str:
        """Probe the configured registry URL.  Returns 'ok' or an error string.

        Uses a 2-second timeout so the status endpoint stays fast.
        Only called from /api/v1/system/status — never from /health.
        """
        from market_storefront.utils.config import CONFIG
        url = (CONFIG.indexer_url or "").rstrip("/")
        if not url:
            return "unconfigured"
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"{url}/health")
            if resp.status_code < 500:
                return "ok"
            return f"http_{resp.status_code}"
        except httpx.ConnectError:
            return "unreachable"
        except httpx.TimeoutException:
            return "timeout"
        except Exception as exc:
            return f"error: {exc}"

    async def health_bare(self, request: Request) -> JSONResponse:
        """GET /health — Kubernetes liveness probe."""
        return await self._health_impl()

    async def health_versioned(self, request: Request) -> JSONResponse:
        """GET /api/v1/system/health — versioned alias."""
        return await self._health_impl()

    async def system_status(self, request: Request) -> JSONResponse:
        """GET /api/v1/system/status — pause state + DB health + registry connectivity."""
        health_response = await self._health_impl(include_registry=True)
        body = json.loads(health_response.body)
        body["paused"] = self._globally_paused_fn()
        return JSONResponse(body, status_code=health_response.status_code)

    # ------------------------------------------------------------------
    # Stage events stream  (admin key enforced by AdminAuthMiddleware)
    # ------------------------------------------------------------------

    async def stream_events(self, request: Request) -> StreamingResponse:
        """GET /api/v1/system/events — tail stage_events as SSE or query historically.

        Query parameters
        ----------------
        since_id : int, default 0
            Only return events with id > since_id.  Pass the last seen ``id``
            on each call to implement a cursor-based tail.
        limit : int, default 100 (max 500)
            Maximum rows for historical (non-streaming) queries.
        stream : bool, default false
            If ``true``, hold the connection open and push new events as they
            arrive (Server-Sent Events).  If ``false`` (default), return the
            matching events as a JSON array and close.
        stage : str, optional
            Filter by stage (e.g. ``discovery``, ``negotiation``).
        listing_id : str, optional
            Filter by listing_id.
        negotiation_id : str, optional
            Filter by negotiation_id.

        SSE event format
        ----------------
        Each event is emitted as::

            id: <row_id>
            data: <json_object>\\n\\n

        Callers should reconnect with ``Last-Event-ID`` header set to the last
        received id to resume without gaps.
        """
        try:
            since_id = int(request.query_params.get("since_id", 0))
        except (ValueError, TypeError):
            since_id = 0
        try:
            limit = min(int(request.query_params.get("limit", 100)), 500)
        except (ValueError, TypeError):
            limit = 100

        # SSE reconnect: Last-Event-ID header takes precedence over since_id param
        last_event_id_hdr = request.headers.get("last-event-id")
        if last_event_id_hdr:
            try:
                since_id = int(last_event_id_hdr)
            except (ValueError, TypeError):
                pass

        do_stream = request.query_params.get("stream", "false").lower() in ("1", "true", "yes")
        stage_filter = request.query_params.get("stage") or None
        listing_id_filter = request.query_params.get("listing_id") or None
        neg_id_filter = request.query_params.get("negotiation_id") or None

        if not do_stream:
            # Historical query — return JSON array and close.
            rows = await self._sqlite_client.list_stage_events(
                after_id=since_id,
                limit=limit,
                stage=stage_filter,
                listing_id=listing_id_filter,
                negotiation_id=neg_id_filter,
            )
            return JSONResponse({"events": rows, "count": len(rows)})

        # Live SSE stream.
        async def _generate():
            cursor = since_id
            while True:
                rows = await self._sqlite_client.list_stage_events(
                    after_id=cursor,
                    limit=50,
                    stage=stage_filter,
                    listing_id=listing_id_filter,
                    negotiation_id=neg_id_filter,
                )
                for row in rows:
                    cursor = row["id"]
                    data = json.dumps(row, default=str)
                    yield f"id: {cursor}\ndata: {data}\n\n"
                if not rows:
                    await asyncio.sleep(0.2)

        return StreamingResponse(_generate(), media_type="text/event-stream")


    async def policy_seed(self, request: Request) -> JSONResponse:
        """POST /admin/policy/seed — discover callables + seed default policies."""
        try:
            result = await self._service.seed_policies()
        except RuntimeError as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)
        except Exception as exc:
            logger.error("[POLICY SEED] Unexpected error: %s", exc)
            return JSONResponse({"error": "policy seeding failed", "detail": str(exc)}, status_code=500)

        return JSONResponse({
            "callable_registry_count": result.callable_registry_count,
            "callables": result.callables,
            "seeded_policies": result.seeded_policies,
            "import_errors": [{"module": e.module, "error": e.error} for e in result.import_errors],
        })

    # ------------------------------------------------------------------
    # Policy status  (read-only, no auth)
    # ------------------------------------------------------------------

    async def policy_status(self, request: Request) -> JSONResponse:
        """GET /api/v1/system/policy — callable registry + seeded policies."""
        result = await self._service.get_policy_status()
        return JSONResponse({
            "callable_count": result.callable_count,
            "callable_registry": result.callable_registry,
            "seeded_policies": [
                {
                    "policy_name": p.policy_name,
                    "trigger_type": p.trigger_type,
                    "components": p.components,
                    "components_resolvable": p.components_resolvable,
                }
                for p in result.seeded_policies
            ],
        })

    # ------------------------------------------------------------------
    # Policy evaluate  (read-only, no auth)
    # ------------------------------------------------------------------

    async def policy_evaluate(self, request: Request) -> JSONResponse:
        """POST /api/v1/system/policy/evaluate — dry-run an order_create event."""
        try:
            body: dict[str, Any] = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

        event_type = body.get("event_type", "order_create")
        if event_type != "order_create":
            return JSONResponse(
                {"error": f"Unsupported event_type: {event_type!r}. Only 'order_create' is supported."},
                status_code=400,
            )

        offer_raw = body.get("offer")
        demand_raw = body.get("demand")
        if not offer_raw or not demand_raw:
            return JSONResponse(
                {"error": "Request body must include 'offer' and 'demand' fields."},
                status_code=400,
            )

        try:
            result = await self._service.evaluate_order_create(
                offer_raw=offer_raw,
                demand_raw=demand_raw,
                max_duration_seconds=body.get("max_duration_seconds"),
            )
        except ValueError as exc:
            return JSONResponse({"error": "Invalid offer/demand resource", "detail": str(exc)}, status_code=400)
        except Exception as exc:
            logger.warning("[POLICY EVAL] Unexpected error: %s", exc)
            return JSONResponse({"error": "Policy evaluation error", "detail": str(exc)}, status_code=500)

        return JSONResponse({
            "action": result.action,
            "policy_used": result.policy_used,
            "components": result.components,
            "resolvable": result.resolvable,
            "reason": result.reason,
        })

    # ------------------------------------------------------------------
    # Route factory
    # ------------------------------------------------------------------

    def routes(self) -> list[Route]:
        return [
            Route("/health",                         self.health_bare,      methods=["GET"]),
            Route("/api/v1/system/health",           self.health_versioned,  methods=["GET"]),
            Route("/api/v1/system/status",           self.system_status,     methods=["GET"]),
            Route("/api/v1/system/events",           self.stream_events,     methods=["GET"]),
            Route("/admin/policy/seed",              self.policy_seed,       methods=["POST"]),
            Route("/api/v1/system/policy",           self.policy_status,     methods=["GET"]),
            Route("/api/v1/system/policy/evaluate",  self.policy_evaluate,   methods=["POST"]),
        ]
