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
Listing-level:
``status``  — filter by listing status (e.g. ``open``, ``accepted``, ``closed``).
              Omit to return all statuses.
``paused``  — ``true`` / ``false`` / omit for all.
``limit``   — max rows (default 50, max 200).
``offset``  — pagination offset (default 0).

Spec filters (mirror the registry-service ``GET /listings`` filter shape):
Equality —
``region``, ``gpu_model``, ``sla``, ``cpu_type``, ``host_disk_type``,
``motherboard``, ``gpu_interconnect``, ``virtualization_type``, ``static_ip``,
``datacenter_grade``.
Numeric ``_min`` (offer must satisfy >=) —
``gpu_count_min``, ``vcpu_count_min``, ``ram_gb_min``, ``disk_gb_min``,
``host_cpu_cores_min``, ``host_ram_gb_min``, ``host_disk_gb_min``,
``total_gpu_count_min``, ``nic_speed_gbps_min``,
``internet_download_mbps_min``, ``internet_upload_mbps_min``,
``open_ports_count_min``.
"""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from market_storefront.utils.listing_filters import matches_listing_filters


_BOOL_FILTER_FIELDS = ("static_ip", "datacenter_grade")
_FLOAT_FILTER_FIELDS = ("sla",)
_STR_FILTER_FIELDS = (
    "region", "gpu_model", "cpu_type", "host_disk_type", "motherboard",
    "gpu_interconnect", "virtualization_type",
)
_INT_MIN_FILTER_FIELDS = (
    "gpu_count_min", "vcpu_count_min", "ram_gb_min", "disk_gb_min",
    "host_cpu_cores_min", "host_ram_gb_min", "host_disk_gb_min",
    "total_gpu_count_min", "nic_speed_gbps_min",
    "internet_download_mbps_min", "internet_upload_mbps_min",
    "open_ports_count_min",
)


def _parse_bool_param(raw: str | None) -> bool | None:
    if raw is None:
        return None
    lowered = raw.lower()
    if lowered in ("true", "1", "yes"):
        return True
    if lowered in ("false", "0", "no"):
        return False
    return None


def _build_spec_filter_kwargs(query_params) -> dict:
    """Pull spec filters out of query_params and coerce types."""
    kwargs: dict = {}
    for field in _STR_FILTER_FIELDS:
        v = query_params.get(field)
        if v:
            kwargs[field] = v
    for field in _BOOL_FILTER_FIELDS:
        parsed = _parse_bool_param(query_params.get(field))
        if parsed is not None:
            kwargs[field] = parsed
    for field in _FLOAT_FILTER_FIELDS:
        v = query_params.get(field)
        if v:
            try:
                kwargs[field] = float(v)
            except ValueError:
                pass
    for field in _INT_MIN_FILTER_FIELDS:
        v = query_params.get(field)
        if v:
            try:
                kwargs[field] = int(v)
            except ValueError:
                pass
    return kwargs


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
        """``GET /api/v1/listings``

        Listing-level filters (status, paused) are pushed down into the
        SQL query. Spec filters (gpu_model, gpu_count_min, ram_gb_min,
        cpu_type, etc.) are applied in-memory after the DB read since the
        offer/demand resources live as JSON blobs. The local listing book
        is small enough (operator-scoped) that this is fine.

        Pagination semantics: limit/offset apply to the *post-filter*
        result set so callers see consistent counts. The DB-level fetch
        pulls a wider window when spec filters are present.
        """
        status_filter = request.query_params.get("status") or None
        paused_raw = request.query_params.get("paused")
        paused_filter: bool | None = _parse_bool_param(paused_raw)
        limit, offset = self._parse_pagination(request)

        spec_kwargs = _build_spec_filter_kwargs(request.query_params)
        has_spec_filters = bool(spec_kwargs)

        if has_spec_filters:
            # Pull a generous window so post-filter pagination still reflects
            # the user's limit. 200 is the route-level cap; 1000 internal is
            # the wider read so spec filters don't truncate against limit.
            db_limit = 1000
            listings_all = await self._sqlite_client.list_listings(
                status=status_filter,
                paused=paused_filter,
                limit=db_limit,
                offset=0,
            )
            filtered = [r for r in listings_all if matches_listing_filters(r, **spec_kwargs)]
            total_after_filter = len(filtered)
            listings = filtered[offset : offset + limit]
        else:
            listings = await self._sqlite_client.list_listings(
                status=status_filter,
                paused=paused_filter,
                limit=limit,
                offset=offset,
            )
            total_after_filter = None

        body: dict = {
            "listings": listings,
            "count": len(listings),
            "limit": limit,
            "offset": offset,
        }
        if total_after_filter is not None:
            body["total_after_filter"] = total_after_filter
        return JSONResponse(body)

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
