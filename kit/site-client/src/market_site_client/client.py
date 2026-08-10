"""Typed async clients for a site authority's capacity API: buyer-facing
read/reserve/commit (``SiteCapacityClient``) and operator resource
registration/update (``SiteCapacityAdminClient``).

The two are deliberately separate types and surfaces. Mutations on the
buyer-facing client do NOT emit into any local bus -- an event-feed
poller is the single source of deltas, so reactions fire identically
whether this consumer or another one moved capacity. Operator
registration goes through ``SiteCapacityAdminClient`` only (today, only
``apicredits_storefront``'s startup-time quota seeding); the buyer-facing
client is never the write-path for operator-owned inventory.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Mapping

import httpx

from market_site_client.models import ResourceRegistration


class SiteCapacityAdminClientError(Exception):
    """HTTP or protocol error from the site-authority capacity-admin API."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class SiteCapacityAdminClient:
    """Registers/updates capacity resources against one site authority's
    ``/api/v1/capacity/resources`` surface.

    Construction takes the same ``base_url``/``admin_key`` shape
    ``SiteCapacityClient`` does, so a composition root already holding
    those values doesn't need a second lookup path to use this client
    too.
    """

    def __init__(
        self,
        base_url: str,
        admin_key: str = "",
        *,
        timeout: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._admin_key = admin_key
        self._timeout = timeout
        self._transport = transport  # test seam (httpx.MockTransport / ASGI)

    def _headers(self) -> dict[str, str]:
        return {"X-Admin-Key": self._admin_key} if self._admin_key else {}

    async def register_resource(
        self,
        resource_id: str,
        *,
        total_units: int,
        resource_type: str = "compute.gpu",
        pool_id: str | None = None,
        resource_subtype: str | None = None,
        attributes: dict[str, Any] | None = None,
        capacity: dict[str, Any] | None = None,
        enabled: bool = True,
    ) -> dict[str, Any]:
        """Upsert a resource row in the site ledger.

        Raises :class:`SiteCapacityAdminClientError` on any non-2xx
        response or transport failure — never a raw ``httpx`` exception,
        so every caller sees the same error shape regardless of which
        capacity-admin operation failed.
        """
        body = ResourceRegistration(
            total_units=total_units,
            resource_type=resource_type,
            pool_id=pool_id,
            resource_subtype=resource_subtype,
            attributes=attributes or {},
            capacity=capacity,
            enabled=enabled,
        )
        url = f"{self._base_url}/api/v1/capacity/resources/{resource_id}"
        async with httpx.AsyncClient(
            timeout=self._timeout, transport=self._transport,
        ) as http:
            try:
                response = await http.put(
                    url,
                    json=body.model_dump(exclude_none=True),
                    headers=self._headers(),
                )
            except httpx.HTTPError as exc:
                raise SiteCapacityAdminClientError(
                    f"register_resource({resource_id!r}) failed to reach "
                    f"{self._base_url!r}: {exc}"
                ) from exc

        if response.status_code >= 400:
            raise SiteCapacityAdminClientError(
                f"register_resource({resource_id!r}) failed: "
                f"{response.status_code} {response.text}",
                status_code=response.status_code,
            )
        return response.json()



class SyncSiteCapacityAdminClient:
    """Synchronous twin of :class:`SiteCapacityAdminClient`.

    Same surface, same errors, same request. It exists because callers outside an
    event loop — operator scripts and the end-to-end scenarios, which drive every
    other service through synchronous typed clients — would otherwise have to wrap
    each call in ``asyncio.run``. A setup step that reaches the site authority by a
    different mechanism than production does is a step that can pass while
    production is broken.

    Keep the two in step: `docs/development/TESTING.md` expects signature parity
    where both a sync and an async client exist, and a divergence here would be
    invisible until a caller of one hit behaviour only the other had.
    """

    def __init__(
        self,
        base_url: str,
        admin_key: str = "",
        *,
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._admin_key = admin_key
        self._timeout = timeout
        self._transport = transport  # test seam (httpx.MockTransport / WSGI)

    def _headers(self) -> dict[str, str]:
        return {"X-Admin-Key": self._admin_key} if self._admin_key else {}

    def register_resource(
        self,
        resource_id: str,
        *,
        total_units: int,
        resource_type: str = "compute.gpu",
        pool_id: str | None = None,
        resource_subtype: str | None = None,
        attributes: dict[str, Any] | None = None,
        capacity: dict[str, Any] | None = None,
        enabled: bool = True,
    ) -> dict[str, Any]:
        """Upsert a resource row in the site ledger.

        Raises :class:`SiteCapacityAdminClientError` on any non-2xx response or
        transport failure — never a raw ``httpx`` exception, so every caller sees
        the same error shape regardless of which capacity-admin operation failed.
        """
        body = ResourceRegistration(
            total_units=total_units,
            resource_type=resource_type,
            pool_id=pool_id,
            resource_subtype=resource_subtype,
            attributes=attributes or {},
            capacity=capacity,
            enabled=enabled,
        )
        url = f"{self._base_url}/api/v1/capacity/resources/{resource_id}"
        with httpx.Client(
            timeout=self._timeout, transport=self._transport,
        ) as http:
            try:
                response = http.put(
                    url,
                    json=body.model_dump(exclude_none=True),
                    headers=self._headers(),
                )
            except httpx.HTTPError as exc:
                raise SiteCapacityAdminClientError(
                    f"register_resource({resource_id!r}) failed to reach "
                    f"{self._base_url!r}: {exc}"
                ) from exc

        if response.status_code >= 400:
            raise SiteCapacityAdminClientError(
                f"register_resource({resource_id!r}) failed: "
                f"{response.status_code} {response.text}",
                status_code=response.status_code,
            )
        return response.json()

class SiteCapacityClient:
    """``CapacityClient`` over the site authority's buyer-facing HTTP
    capacity API.

    Verbs map one-to-one onto ``/api/v1/capacity/*`` (the payload shapes
    are the wire contract). Deliberately separate from
    ``SiteCapacityAdminClient``, which speaks the operator resource-
    registration surface only -- this client is never the write-path
    for operator-owned inventory.
    """

    def __init__(
        self,
        base_url: str,
        admin_key: str = "",
        *,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._admin_key = admin_key
        self._timeout = timeout
        self._transport = transport  # test seam (httpx.MockTransport / ASGI)
        self._topology_error_handler: Callable[[], Awaitable[None]] | None = None

    @property
    def base_url(self) -> str:
        return self._base_url

    def _headers(self) -> dict[str, str]:
        return {"X-Admin-Key": self._admin_key} if self._admin_key else {}

    def _http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self._timeout, transport=self._transport)

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict:
        async with self._http() as http:
            resp = await http.get(
                f"{self._base_url}{path}", params=params, headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()

    async def _post(self, path: str, body: dict[str, Any]) -> httpx.Response:
        async with self._http() as http:
            response = await http.post(
                f"{self._base_url}{path}", json=body, headers=self._headers(),
            )
        if response.status_code in {404, 409, 422} and self._topology_error_handler is not None:
            await self._topology_error_handler()
        return response

    def set_topology_error_handler(
        self, handler: Callable[[], Awaitable[None]] | None
    ) -> None:
        """Install a bounded drift check invoked after topology-sensitive failures."""
        self._topology_error_handler = handler

    async def snapshot(self) -> list[dict[str, Any]]:
        data = await self._get("/api/v1/capacity/snapshot")
        return list(data.get("resources") or [])

    async def resource_pool_projection_version(self) -> dict[str, Any]:
        return await self._get("/api/v1/capacity/site-resource-pools/version")

    async def resource_pool_projection(self) -> dict[str, Any]:
        return await self._get("/api/v1/capacity/site-resource-pools")

    async def capacity_bucket_projection_version(self) -> dict[str, Any]:
        return await self._get("/api/v1/capacity/site-capacity-buckets/version")

    async def capacity_bucket_projection(self) -> dict[str, Any]:
        return await self._get("/api/v1/capacity/site-capacity-buckets")

    async def probe(
        self,
        *,
        claim: Mapping[str, Any] | None = None,
        lease_start_utc: str | None = None,
        lease_duration_seconds: int | None = None,
    ) -> dict[str, Any] | None:
        body: dict[str, Any] = {"claim": dict(claim or {})}
        if lease_start_utc is not None:
            body["lease_start_utc"] = str(lease_start_utc)
        if lease_duration_seconds is not None:
            body["lease_duration_seconds"] = int(lease_duration_seconds)
        resp = await self._post(
            "/api/v1/capacity/probe", body,
        )
        resp.raise_for_status()
        return resp.json().get("match")

    async def reserve(
        self,
        *,
        claim: Mapping[str, Any] | None = None,
        deal_ref: Mapping[str, Any] | None = None,
        ttl_seconds: float | None = None,
        lease_start_utc: str | None = None,
        lease_duration_seconds: int | None = None,
    ) -> dict[str, Any] | None:
        body: dict[str, Any] = {
            "claim": dict(claim or {}),
            "deal_ref": dict(deal_ref or {}),
        }
        if ttl_seconds is not None:
            body["ttl_seconds"] = float(ttl_seconds)
        if lease_start_utc is not None:
            body["lease_start_utc"] = str(lease_start_utc)
        if lease_duration_seconds is not None:
            body["lease_duration_seconds"] = int(lease_duration_seconds)
        resp = await self._post("/api/v1/capacity/reservations", body)
        resp.raise_for_status()
        return resp.json().get("reservation")

    async def commit(
        self,
        *,
        resource_id: str | None = None,
        capacity_reservation_id: str | None = None,
        lease_start_utc: str | None = None,
        lease_end_utc: str | None = None,
        idempotency_ref: str | None = None,
    ) -> None:
        # resource_id is not required by the wire contract (CommitRequest)
        # or the ledger method behind it -- capacity_reservation_id is what
        # identifies the reservation, and the site authority resolves the
        # backing resource internally. A caller working from the opaque
        # capacity-reservation boundary (reserve()'s response no longer
        # carries resource_id) has nothing to supply here; passing None is
        # correct, not a degraded call.
        if not capacity_reservation_id:
            raise ValueError(
                "remote capacity commit requires the capacity_reservation_id the "
                "reserve returned (the site ledger has no aggregate path)",
            )
        resp = await self._post(
            f"/api/v1/capacity/reservations/{capacity_reservation_id}/commit",
            {
                "resource_id": resource_id,
                "lease_start_utc": (
                    str(lease_start_utc) if lease_start_utc is not None else None
                ),
                "lease_end_utc": (
                    str(lease_end_utc) if lease_end_utc is not None else None
                ),
                "idempotency_ref": idempotency_ref,
            },
        )
        resp.raise_for_status()

    async def release(
        self,
        *,
        capacity_reservation_id: str | None = None,
        deal_ref: Mapping[str, Any] | None = None,
        failure_reason: str | None = None,
        failure_message: str | None = None,
    ) -> dict[str, Any] | None:
        body: dict[str, Any] = {
            "capacity_reservation_id": capacity_reservation_id,
            "deal_ref": dict(deal_ref or {}),
        }
        if failure_reason is not None:
            body["failure_reason"] = failure_reason
        if failure_message is not None:
            body["failure_message"] = failure_message
        resp = await self._post("/api/v1/capacity/releases", body)
        resp.raise_for_status()
        return resp.json().get("reservation")

    async def truncate_lease(
        self,
        *,
        capacity_reservation_id: str,
        lease_end_utc: str,
    ) -> dict[str, Any] | None:
        resp = await self._post(
            f"/api/v1/capacity/reservations/{capacity_reservation_id}/truncate-lease",
            {"lease_end_utc": str(lease_end_utc)},
        )
        resp.raise_for_status()
        return resp.json().get("reservation")

    async def list_reservations(
        self,
        *,
        state: str | None = None,
        escrow_uid: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if state is not None:
            params["state"] = state
        if escrow_uid is not None:
            params["escrow_uid"] = escrow_uid
        data = await self._get("/api/v1/capacity/reservations", params=params)
        return list(data.get("reservations") or [])

    async def events_after(
        self, after_version: int, *, limit: int = 500,
    ) -> tuple[list[dict[str, Any]], int]:
        data = await self._get(
            "/api/v1/capacity/events",
            params={"after": int(after_version), "limit": int(limit)},
        )
        return list(data.get("events") or []), int(data.get("latest_version") or 0)
