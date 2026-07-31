"""Typed async client for a site authority's capacity-administration
surface: operator resource registration and update.

Deliberately separate from ``core_storefront.capacity_remote.RemoteCapacityClient``,
which speaks the buyer-facing read/reserve/commit surface only ("Mutations
do NOT emit into the local bus" — that client is never the write-path for
operator-owned inventory). This one exists for the opposite case: a
domain that owns and administers its own capacity resources directly
(today, only ``apicredits_storefront``'s startup-time quota seeding),
rather than reserving against inventory some other party advertises.
"""

from __future__ import annotations

from typing import Any

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
    ``RemoteCapacityClient`` does, so a composition root already holding
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
