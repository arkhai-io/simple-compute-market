"""Listings controller — seller-local listing read API and pause controls.

All read endpoints (``GET``) are unauthenticated — the storefront's listing
book is operator-facing data that does not need to be hidden.

Write endpoints (``POST .../pause``, ``POST .../resume``) require the
``X-Admin-Key`` header enforced by ``AdminAuthMiddleware``.

Endpoints
---------
``GET  /api/v1/listings``                       List local listings (filterable).
``GET  /api/v1/listings/{listing_id}``          Single listing detail.
``POST /api/v1/listings/{listing_id}/pause``    Take listing off market (block new
                                                negotiations against it).
``POST /api/v1/listings/{listing_id}/resume``   Put listing back on market.

Query parameters for ``GET /api/v1/listings``
---------------------------------------------
``status``  — filter by listing status (e.g. ``open``, ``accepted``, ``closed``).
              Omit to return all statuses.
``paused``  — ``true`` / ``false`` / omit for all.
``limit``   — max rows (default 50, max 200).
``offset``  — pagination offset (default 0).
"""

from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route


def _row_to_wire(row: dict[str, Any]) -> dict[str, Any]:
    """Translate a SQLite listing row (DB column ``order_id``) into the
    wire shape (key ``listing_id``).

    The DB-level rename is deferred to a later slice; this layer keeps
    the public JSON contract on the listings vocabulary while the
    storage stays on the legacy column names.
    """
    out = dict(row)
    if "order_id" in out and "listing_id" not in out:
        out["listing_id"] = out.pop("order_id")
    return out


class ListingsController:
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

    async def list_listings(self, request: Request) -> JSONResponse:
        """``GET /api/v1/listings``"""
        status_filter = request.query_params.get("status") or None
        paused_raw = request.query_params.get("paused")
        paused_filter: bool | None = None
        if paused_raw is not None:
            paused_filter = paused_raw.lower() in ("true", "1", "yes")
        limit, offset = self._parse_pagination(request)

        rows = await self._sqlite_client.list_orders(
            status=status_filter,
            paused=paused_filter,
            limit=limit,
            offset=offset,
        )
        listings = [_row_to_wire(r) for r in rows]
        return JSONResponse({
            "listings": listings,
            "count": len(listings),
            "limit": limit,
            "offset": offset,
        })

    async def get_listing(self, request: Request) -> JSONResponse:
        """``GET /api/v1/listings/{listing_id}``"""
        listing_id = request.path_params["listing_id"]
        row = await self._sqlite_client.load_order(order_id=listing_id)
        if not row:
            return JSONResponse(
                {"error": "Not found", "listing_id": listing_id},
                status_code=404,
            )
        # Attach paused flag if present (older rows default to False)
        if "paused" not in row:
            row["paused"] = False
        return JSONResponse(_row_to_wire(row))

    async def pause_listing(self, request: Request) -> JSONResponse:
        """``POST /api/v1/listings/{listing_id}/pause``

        Marks the listing as paused. New ``/negotiate/new`` calls against
        this listing will receive 503 while it is paused.
        """
        listing_id = request.path_params["listing_id"]
        row = await self._sqlite_client.load_order(order_id=listing_id)
        if not row:
            return JSONResponse(
                {"error": "Not found", "listing_id": listing_id},
                status_code=404,
            )
        await self._sqlite_client.set_order_paused(order_id=listing_id, paused=True)
        return JSONResponse({
            "listing_id": listing_id,
            "paused": True,
            "message": "Listing paused. New negotiations against this listing will receive 503.",
        })

    async def resume_listing(self, request: Request) -> JSONResponse:
        """``POST /api/v1/listings/{listing_id}/resume``"""
        listing_id = request.path_params["listing_id"]
        row = await self._sqlite_client.load_order(order_id=listing_id)
        if not row:
            return JSONResponse(
                {"error": "Not found", "listing_id": listing_id},
                status_code=404,
            )
        await self._sqlite_client.set_order_paused(order_id=listing_id, paused=False)
        return JSONResponse({
            "listing_id": listing_id,
            "paused": False,
            "message": "Listing resumed.",
        })

    # ------------------------------------------------------------------
    # Route factory
    # ------------------------------------------------------------------

    def routes(self) -> list[Route]:
        return [
            Route("/api/v1/listings", self.list_listings, methods=["GET"]),
            Route("/api/v1/listings/{listing_id}", self.get_listing, methods=["GET"]),
            Route("/api/v1/listings/{listing_id}/pause", self.pause_listing, methods=["POST"]),
            Route("/api/v1/listings/{listing_id}/resume", self.resume_listing, methods=["POST"]),
        ]
