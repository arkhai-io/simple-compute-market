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

import json
import logging
import sqlite3
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
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

    async def _health_impl(self) -> JSONResponse:
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

        all_ok = all(v == "ok" for v in checks.values())
        return JSONResponse(
            {"status": "ok" if all_ok else "degraded", "checks": checks},
            status_code=200 if all_ok else 503,
        )

    async def health_bare(self, request: Request) -> JSONResponse:
        """GET /health — Kubernetes liveness probe."""
        return await self._health_impl()

    async def health_versioned(self, request: Request) -> JSONResponse:
        """GET /api/v1/system/health — versioned alias."""
        return await self._health_impl()

    async def system_status(self, request: Request) -> JSONResponse:
        """GET /api/v1/system/status — pause state + DB health."""
        health_response = await self._health_impl()
        body = json.loads(health_response.body)
        body["paused"] = self._globally_paused_fn()
        return JSONResponse(body, status_code=health_response.status_code)

    # ------------------------------------------------------------------
    # Policy seed  (admin key enforced by AdminAuthMiddleware)
    # ------------------------------------------------------------------

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
                duration_hours=body.get("duration_hours", 1),
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
            Route("/admin/policy/seed",              self.policy_seed,       methods=["POST"]),
            Route("/api/v1/system/policy",           self.policy_status,     methods=["GET"]),
            Route("/api/v1/system/policy/evaluate",  self.policy_evaluate,   methods=["POST"]),
        ]
