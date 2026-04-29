"""System controller — health and liveness endpoints.

Exposes:
  ``GET /health``          Kubernetes liveness/readiness probe.
  ``GET /api/v1/system/health``   Versioned alias, same handler.
  ``GET /api/v1/system/status``   Richer diagnostic (DB reachability, pause state).

``/health`` is kept at the root to match the Kubernetes probe convention
used by the provisioning and registry services.

Registration
------------
Mount via ``SystemController.routes()``::

    for route in SystemController.routes():
        app.routes.append(route)
"""

from __future__ import annotations

import sqlite3

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route


class SystemController:
    """Stateless handler class — all methods are ``@staticmethod`` or use
    module-level singletons injected at mount time."""

    def __init__(self, *, sqlite_client, globally_paused_fn) -> None:
        """
        Parameters
        ----------
        sqlite_client:
            The storefront's ``SQLiteClient`` instance (used for DB ping).
        globally_paused_fn:
            Zero-arg callable that returns ``bool`` — the current global pause
            state.  Passed as a callable so the controller always reads the
            live value rather than a snapshot taken at construction time.
        """
        self._sqlite_client = sqlite_client
        self._globally_paused_fn = globally_paused_fn

    async def _health_impl(self) -> JSONResponse:
        checks: dict[str, str] = {"api": "ok"}

        # DB ping — open a read connection and SELECT 1.
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
        """``GET /health`` — Kubernetes liveness probe."""
        return await self._health_impl()

    async def health_versioned(self, request: Request) -> JSONResponse:
        """``GET /api/v1/system/health`` — versioned alias."""
        return await self._health_impl()

    async def system_status(self, request: Request) -> JSONResponse:
        """``GET /api/v1/system/status`` — diagnostic snapshot.

        Returns the global pause flag alongside the health checks so callers
        can distinguish "healthy but paused" from "degraded".
        """
        health_response = await self._health_impl()
        import json
        body = json.loads(health_response.body)
        body["paused"] = self._globally_paused_fn()
        return JSONResponse(body, status_code=health_response.status_code)

    def routes(self) -> list[Route]:
        """Return all routes for this controller."""
        return [
            Route("/health", self.health_bare, methods=["GET"]),
            Route("/api/v1/system/health", self.health_versioned, methods=["GET"]),
            Route("/api/v1/system/status", self.system_status, methods=["GET"]),
        ]
