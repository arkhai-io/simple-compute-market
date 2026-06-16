"""Remote site-authority capacity client + event-feed poller.

``RemoteCapacityClient`` speaks one site authority's
``/api/v1/capacity`` HTTP surface (the shared ledger router from
``core_site``); ``site_events_poller`` tails that authority's versioned
capacity-event feed into the local bus. Both are domain-neutral: the
storefront composition root supplies settings resolution, aggregation,
and the listing-reconcile reaction (``full_reconcile``) — see the VM
storefront's ``services/capacity_client.py`` for the composed shape.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Mapping

import httpx

from core_storefront.capacity import (
    CapacityDelta,
    CapacityEventBus,
    CapacitySubscriber,
)

logger = logging.getLogger(__name__)


class RemoteCapacityClient:
    """``CapacityClient`` over the site authority's HTTP capacity API.

    Verbs map one-to-one onto ``/api/v1/capacity/*`` (the payload shapes
    are the wire contract). Mutations do NOT emit into the local bus:
    the event-feed poller is the single source of deltas, so reactions
    fire identically whether this storefront or another one moved
    capacity.
    """

    def __init__(
        self,
        base_url: str,
        admin_key: str = "",
        *,
        bus: CapacityEventBus | None = None,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._admin_key = admin_key
        self._bus = bus or CapacityEventBus()
        self._timeout = timeout
        self._transport = transport  # test seam (httpx.MockTransport / ASGI)

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
            return await http.post(
                f"{self._base_url}{path}", json=body, headers=self._headers(),
            )

    async def snapshot(self) -> list[dict[str, Any]]:
        data = await self._get("/api/v1/capacity/snapshot")
        return list(data.get("resources") or [])

    async def probe(
        self, *, claim: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        resp = await self._post(
            "/api/v1/capacity/probe", {"claim": dict(claim or {})},
        )
        resp.raise_for_status()
        return resp.json().get("match")

    async def reserve(
        self,
        *,
        claim: Mapping[str, Any] | None = None,
        deal_ref: Mapping[str, Any] | None = None,
        ttl_seconds: float | None = None,
    ) -> dict[str, Any] | None:
        body: dict[str, Any] = {
            "claim": dict(claim or {}),
            "deal_ref": dict(deal_ref or {}),
        }
        if ttl_seconds is not None:
            body["ttl_seconds"] = float(ttl_seconds)
        resp = await self._post("/api/v1/capacity/reservations", body)
        resp.raise_for_status()
        return resp.json().get("allocation")

    async def commit(
        self,
        *,
        resource_id: str,
        allocation_id: str | None = None,
        lease_end_utc: str | None = None,
        idempotency_ref: str | None = None,
    ) -> None:
        if not allocation_id:
            raise ValueError(
                "remote capacity commit requires the allocation_id the "
                "reserve returned (the site ledger has no aggregate path)",
            )
        resp = await self._post(
            f"/api/v1/capacity/allocations/{allocation_id}/commit",
            {
                "resource_id": resource_id,
                # None = open-ended commit (no lease tail) — prepaid
                # domains never schedule expiry.
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
        allocation_id: str | None = None,
        deal_ref: Mapping[str, Any] | None = None,
        failure_reason: str | None = None,
        failure_message: str | None = None,
    ) -> dict[str, Any] | None:
        body: dict[str, Any] = {
            "allocation_id": allocation_id,
            "deal_ref": dict(deal_ref or {}),
        }
        if failure_reason is not None:
            body["failure_reason"] = failure_reason
        if failure_message is not None:
            body["failure_message"] = failure_message
        resp = await self._post("/api/v1/capacity/releases", body)
        resp.raise_for_status()
        return resp.json().get("allocation")

    async def truncate_lease(
        self,
        *,
        allocation_id: str,
        lease_end_utc: str,
    ) -> dict[str, Any] | None:
        resp = await self._post(
            f"/api/v1/capacity/allocations/{allocation_id}/truncate-lease",
            {"lease_end_utc": str(lease_end_utc)},
        )
        resp.raise_for_status()
        return resp.json().get("allocation")

    def subscribe(self, subscriber: CapacitySubscriber) -> Callable[[], None]:
        return self._bus.subscribe(subscriber)

    # Beyond the protocol: the feed the poller tails and the registry
    # mirror used by inventory seeding.

    async def list_allocations(
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
        data = await self._get("/api/v1/capacity/allocations", params=params)
        return list(data.get("allocations") or [])

    async def events_after(
        self, after_version: int, *, limit: int = 500,
    ) -> tuple[list[dict[str, Any]], int]:
        data = await self._get(
            "/api/v1/capacity/events",
            params={"after": int(after_version), "limit": int(limit)},
        )
        return list(data.get("events") or []), int(data.get("latest_version") or 0)

    async def register_resource(
        self,
        resource_id: str,
        *,
        total_units: int,
        resource_subtype: str | None = None,
        attributes: Mapping[str, Any] | None = None,
        enabled: bool = True,
    ) -> dict[str, Any]:
        async with self._http() as http:
            resp = await http.put(
                f"{self._base_url}/api/v1/capacity/resources/{resource_id}",
                json={
                    "total_units": int(total_units),
                    "resource_subtype": resource_subtype,
                    "attributes": dict(attributes or {}),
                    "enabled": enabled,
                },
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()

    async def emit_local(self, delta: CapacityDelta) -> None:
        """Feed a delta from the poller into local subscribers."""
        await self._bus.emit(delta)


async def site_events_poller(
    aggregate: Any,
    site_name: str,
    client: RemoteCapacityClient,
    interval: float,
    *,
    full_reconcile: Callable[[], Awaitable[None]],
) -> None:
    """Tail one site authority's capacity-event feed into the local bus.

    Positions at the feed head, runs ``full_reconcile`` once to converge
    with anything missed while down, then polls for new versions and
    emits each as a site-tagged ``CapacityDelta`` on the aggregate bus.
    A feed head that moves backwards (ledger reset) re-runs the full
    reconcile instead of replaying. ``full_reconcile`` is the domain's
    listing-reconciliation reaction — core never interprets listings.
    """
    last_applied: int | None = None
    logger.info(
        "[CAPACITY] Event poller started for site %r at %s (interval=%ss)",
        site_name, client.base_url, interval,
    )
    while True:
        try:
            if last_applied is None:
                _, last_applied = await client.events_after(0, limit=1)
                await full_reconcile()
            events, latest = await client.events_after(last_applied)
            if latest < last_applied:
                logger.warning(
                    "[CAPACITY] Site %r feed head moved backwards (%d -> %d) "
                    "— ledger reset? Resyncing from snapshot.",
                    site_name, last_applied, latest,
                )
                last_applied = latest
                await full_reconcile()
                events = []
            for event in events:
                await aggregate.emit_site_delta(site_name, CapacityDelta(
                    kind=str(event.get("kind") or ""),
                    version=int(event.get("version") or 0),
                    resource_id=(
                        str(event["resource_id"])
                        if event.get("resource_id") else None
                    ),
                ))
                last_applied = int(event.get("version") or last_applied)
            if events and latest > last_applied:
                continue  # truncated page — keep draining before sleeping
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "[CAPACITY] Site %r poller cycle failed: %s", site_name, exc,
            )
        await asyncio.sleep(interval)
