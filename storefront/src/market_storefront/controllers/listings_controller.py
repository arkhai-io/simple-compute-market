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

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route


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

        listings = await self._sqlite_client.list_listings(
            status=status_filter,
            paused=paused_filter,
            limit=limit,
            offset=offset,
        )
        return JSONResponse({
            "listings": listings,
            "count": len(listings),
            "limit": limit,
            "offset": offset,
        })

    async def get_listing(self, request: Request) -> JSONResponse:
        """``GET /api/v1/listings/{listing_id}``"""
        listing_id = request.path_params["listing_id"]
        row = await self._sqlite_client.load_listing(listing_id=listing_id)
        if not row:
            return JSONResponse(
                {"error": "Not found", "listing_id": listing_id},
                status_code=404,
            )
        if "paused" not in row:
            row["paused"] = False
        return JSONResponse(row)

    async def pause_listing(self, request: Request) -> JSONResponse:
        """``POST /api/v1/listings/{listing_id}/pause``

        Marks the listing as paused. New ``/negotiate/new`` calls against
        this listing will receive 503 while it is paused.
        """
        listing_id = request.path_params["listing_id"]
        row = await self._sqlite_client.load_listing(listing_id=listing_id)
        if not row:
            return JSONResponse(
                {"error": "Not found", "listing_id": listing_id},
                status_code=404,
            )
        await self._sqlite_client.set_listing_paused(listing_id=listing_id, paused=True)
        return JSONResponse({
            "listing_id": listing_id,
            "paused": True,
            "message": "Listing paused. New negotiations against this listing will receive 503.",
        })

    async def resume_listing(self, request: Request) -> JSONResponse:
        """``POST /api/v1/listings/{listing_id}/resume``

        Clears the paused flag then publishes the listing to the registry.
        Safe to call when the listing was created with ``paused=true`` and
        has never been published, or when it was previously paused.
        """
        listing_id = request.path_params["listing_id"]
        row = await self._sqlite_client.load_listing(listing_id=listing_id)
        if not row:
            return JSONResponse(
                {"error": "Not found", "listing_id": listing_id},
                status_code=404,
            )
        await self._sqlite_client.set_listing_paused(listing_id=listing_id, paused=False)

        # Publish to registry — idempotent if already published; required if
        # this is the first resume after a paused-at-creation listing.
        from market_storefront.utils.action_executor import publish_order_to_registry
        publish_result = await publish_order_to_registry(row)
        registry_status = publish_result.get("status", "unknown")

        return JSONResponse({
            "listing_id": listing_id,
            "paused": False,
            "registry_status": registry_status,
            "message": f"Listing resumed and {registry_status} to registry.",
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
