"""Admin controller — global pause/resume and status.

All endpoints require the ``X-Admin-Key`` header enforced by
``AdminAuthMiddleware``.  The middleware is registered in ``server.py``
before these routes, so by the time a request reaches here it has
already been authenticated.

Pause semantics
---------------
When ``_GLOBALLY_PAUSED`` is ``True``:

* ``POST /negotiate/new`` returns 503 with
  ``{"error": "paused", "hint": "use admin API to advance"}``.
* ``POST /negotiate/{neg_id}`` returns the same 503.
* Per-order ``paused`` flag operates independently — an order can be
  paused even when the storefront is globally running.

In-flight negotiations that were already mid-round when pause was set
are NOT interrupted; they complete normally.  The gate only fires on
new negotiation requests.

Endpoints
---------
``POST /admin/pause``   — set globally paused = True
``POST /admin/resume``  — set globally paused = False
``GET  /admin/status``  — returns pause state + live counts
"""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route


class AdminController:
    def __init__(self, *, sqlite_client, get_paused_fn, set_paused_fn) -> None:
        """
        Parameters
        ----------
        sqlite_client:
            Storefront SQLiteClient — used for live count queries.
        get_paused_fn:
            Zero-arg callable → bool.  Returns current global pause state.
        set_paused_fn:
            Single-arg callable(bool).  Sets the global pause flag.
        """
        self._sqlite_client = sqlite_client
        self._get_paused = get_paused_fn
        self._set_paused = set_paused_fn

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    async def pause(self, request: Request) -> JSONResponse:
        """``POST /admin/pause`` — halt new negotiations globally."""
        self._set_paused(True)
        return JSONResponse({"paused": True, "message": "Storefront paused. New negotiations will receive 503."})

    async def resume(self, request: Request) -> JSONResponse:
        """``POST /admin/resume`` — allow new negotiations again."""
        self._set_paused(False)
        return JSONResponse({"paused": False, "message": "Storefront resumed."})

    async def status(self, request: Request) -> JSONResponse:
        """``GET /admin/status`` — live operational snapshot.

        Returns:
            paused          — global pause flag
            active_negotiations — count of non-terminal negotiation threads
            open_orders     — count of orders with status='open' and paused=0
            paused_orders   — count of orders with paused=1
        """
        counts = await self._sqlite_client.get_admin_status_counts()
        return JSONResponse({
            "paused": self._get_paused(),
            **counts,
        })

    # ------------------------------------------------------------------
    # Route factory
    # ------------------------------------------------------------------

    def routes(self) -> list[Route]:
        return [
            Route("/admin/pause", self.pause, methods=["POST"]),
            Route("/admin/resume", self.resume, methods=["POST"]),
            Route("/admin/status", self.status, methods=["GET"]),
        ]
