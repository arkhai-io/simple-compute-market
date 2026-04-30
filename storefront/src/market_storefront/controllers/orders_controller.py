"""Orders controller — seller-local order read API and pause controls.

All read endpoints (``GET``) are unauthenticated — the storefront's order
book is operator-facing data that does not need to be hidden.

Write endpoints (``POST .../pause``, ``POST .../resume``) require the
``X-Admin-Key`` header enforced by ``AdminAuthMiddleware``.

Endpoints
---------
``GET  /api/v1/orders``                  List local orders (filterable).
``GET  /api/v1/orders/{order_id}``       Single order detail.
``POST /api/v1/orders/{order_id}/pause`` Take order off market (block new
                                         negotiations against it).
``POST /api/v1/orders/{order_id}/resume`` Put order back on market.
                                          If the order was created with
                                          ``paused=true`` and has never been
                                          published, this also triggers the
                                          registry publish.

Query parameters for ``GET /api/v1/orders``
-------------------------------------------
``status``  — filter by order status (e.g. ``open``, ``accepted``, ``closed``).
              Omit to return all statuses.
``paused``  — ``true`` / ``false`` / omit for all.
``limit``   — max rows (default 50, max 200).
``offset``  — pagination offset (default 0).
"""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route


class OrdersController:
    def __init__(self, *, sqlite_client) -> None:
        self._sqlite_client = sqlite_client

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _parse_pagination(self, request: Request) -> tuple[int, int]:
        try:
            limit = min(int(request.query_params.get("limit", 50)), 200)
        except (ValueError, TypeError):
            limit = 50
        try:
            offset = max(int(request.query_params.get("offset", 0)), 0)
        except (ValueError, TypeError):
            offset = 0
        return limit, offset

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    async def list_orders(self, request: Request) -> JSONResponse:
        """``GET /api/v1/orders``"""
        status_filter = request.query_params.get("status") or None
        paused_raw = request.query_params.get("paused")
        paused_filter: bool | None = None
        if paused_raw is not None:
            paused_filter = paused_raw.lower() in ("true", "1", "yes")
        limit, offset = self._parse_pagination(request)

        orders = await self._sqlite_client.list_listings(
            status=status_filter,
            paused=paused_filter,
            limit=limit,
            offset=offset,
        )
        return JSONResponse({
            "orders": orders,
            "count": len(orders),
            "limit": limit,
            "offset": offset,
        })

    async def get_order(self, request: Request) -> JSONResponse:
        """``GET /api/v1/orders/{order_id}``"""
        order_id = request.path_params["order_id"]
        order = await self._sqlite_client.load_listing(listing_id=order_id)
        if not order:
            return JSONResponse(
                {"error": "Not found", "order_id": order_id},
                status_code=404,
            )
        # Attach paused flag if present (older rows default to False)
        if "paused" not in order:
            order["paused"] = False
        return JSONResponse(order)

    async def pause_order(self, request: Request) -> JSONResponse:
        """``POST /api/v1/orders/{order_id}/pause``

        Marks the order as paused. New ``/negotiate/new`` calls against
        this order will receive 503 while it is paused.
        """
        order_id = request.path_params["order_id"]
        order = await self._sqlite_client.load_listing(listing_id=order_id)
        if not order:
            return JSONResponse(
                {"error": "Not found", "order_id": order_id},
                status_code=404,
            )
        await self._sqlite_client.set_listing_paused(listing_id=order_id, paused=True)
        return JSONResponse({
            "order_id": order_id,
            "paused": True,
            "message": "Order paused. New negotiations against this order will receive 503.",
        })

    async def resume_order(self, request: Request) -> JSONResponse:
        """``POST /api/v1/orders/{order_id}/resume``

        Clears the paused flag then publishes the order to the registry.
        Safe to call when the order was never published (paused at creation)
        or when it was previously published and temporarily paused.
        """
        order_id = request.path_params["order_id"]
        order = await self._sqlite_client.load_listing(listing_id=order_id)
        if not order:
            return JSONResponse(
                {"error": "Not found", "order_id": order_id},
                status_code=404,
            )
        await self._sqlite_client.set_listing_paused(listing_id=order_id, paused=False)

        # Publish to registry — idempotent if already published; required if
        # this is the first resume after a paused-at-creation order.
        from market_storefront.utils.action_executor import publish_order_to_registry
        publish_result = await publish_order_to_registry(order)
        registry_status = publish_result.get("status", "unknown")

        return JSONResponse({
            "order_id": order_id,
            "paused": False,
            "registry_status": registry_status,
            "message": f"Order resumed and {registry_status} to registry.",
        })

    # ------------------------------------------------------------------
    # Route factory
    # ------------------------------------------------------------------

    def routes(self) -> list[Route]:
        return [
            Route("/api/v1/orders", self.list_orders, methods=["GET"]),
            Route("/api/v1/orders/{order_id}", self.get_order, methods=["GET"]),
            Route("/api/v1/orders/{order_id}/pause", self.pause_order, methods=["POST"]),
            Route("/api/v1/orders/{order_id}/resume", self.resume_order, methods=["POST"]),
        ]
