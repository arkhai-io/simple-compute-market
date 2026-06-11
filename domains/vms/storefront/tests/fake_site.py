"""In-memory site authority for storefront tests.

``FakeSite`` mirrors the provisioning service's ``/api/v1/capacity``
surface behind an ``httpx.MockTransport`` (the real wire shapes are
pinned by that service's own integration tests). ``site_capacity``
patches ``build_capacity_client`` so every storefront code path — admin
endpoints, failure policy, claims truncation, negotiation holds,
fulfillment — runs against the fake ledger.
"""

from __future__ import annotations

import contextlib
import itertools
import json
from typing import Any, Iterator
from unittest.mock import patch

import httpx


class FakeSite:
    """Dict-backed single-site capacity ledger."""

    def __init__(self) -> None:
        self.resources: dict[str, dict] = {}
        self.allocations: dict[str, dict] = {}
        self.events: list[dict] = []
        self._versions = itertools.count(1)
        self._ids = itertools.count(1)
        self.seen_admin_keys: list[str | None] = []

    def add_resource(
        self,
        resource_id: str,
        total_units: int,
        *,
        attributes: dict | None = None,
    ) -> None:
        self.resources[resource_id] = {
            "resource_id": resource_id,
            "total_units": int(total_units),
            "attributes": dict(attributes or {}),
            "enabled": True,
        }

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _emit(self, kind: str, resource_id: str | None) -> None:
        self.events.append({
            "version": next(self._versions),
            "kind": kind,
            "resource_id": resource_id,
            "occurred_at": "2026-01-01T00:00:00Z",
        })

    def _available(self, rid: str) -> int:
        held = sum(
            a["units"] for a in self.allocations.values()
            if a["resource_id"] == rid
            and a["state"] in ("reserved", "provisioning", "leased", "releasing")
        )
        return self.resources[rid]["total_units"] - held

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.seen_admin_keys.append(request.headers.get("X-Admin-Key"))
        path = request.url.path
        body = json.loads(request.content) if request.content else {}

        if request.method == "PUT" and path.startswith("/api/v1/capacity/resources/"):
            rid = path.rsplit("/", 1)[1]
            self.resources[rid] = {
                "resource_id": rid,
                "total_units": body["total_units"],
                "attributes": body.get("attributes") or {},
                "enabled": body.get("enabled", True),
            }
            self._emit("released", rid)
            return httpx.Response(200, json=self.resources[rid])

        if path == "/api/v1/capacity/snapshot":
            return httpx.Response(200, json={"resources": [
                {
                    "resource_id": rid,
                    "resource_type": "compute.gpu",
                    "unit": "count",
                    "value": row["total_units"],
                    "available_units": self._available(rid),
                    "state": (
                        "available" if self._available(rid) > 0 else "leased"
                    ),
                    "attributes": row["attributes"],
                    "enabled": True,
                }
                for rid, row in self.resources.items() if row["enabled"]
            ]})

        if path == "/api/v1/capacity/probe":
            return httpx.Response(200, json={"match": self._match(body["claim"])})

        if path == "/api/v1/capacity/reservations":
            match = self._match(body["claim"])
            if match is None:
                return httpx.Response(200, json={"allocation": None})
            allocation_id = f"alloc-{next(self._ids)}"
            self.allocations[allocation_id] = {
                "allocation_id": allocation_id,
                "resource_id": match["resource_id"],
                "units": match["allocated_gpu_count"],
                "state": "reserved",
                "deal_ref": body.get("deal_ref") or {},
            }
            self._emit("reserved", match["resource_id"])
            return httpx.Response(200, json={"allocation": {
                **match,
                "allocation_id": allocation_id,
                "hold_expires_at": None,
            }})

        if path.endswith("/commit"):
            allocation_id = path.split("/")[-2]
            allocation = self.allocations.get(allocation_id)
            if allocation is None:
                return httpx.Response(404, json={"detail": "not found"})
            allocation["state"] = "leased"
            allocation["lease_end_utc"] = body["lease_end_utc"]
            self._emit("committed", allocation["resource_id"])
            return httpx.Response(200, json={"allocation": allocation})

        if path == "/api/v1/capacity/releases":
            allocation = None
            if body.get("allocation_id"):
                allocation = self.allocations.get(body["allocation_id"])
            else:
                escrow = (body.get("deal_ref") or {}).get("escrow_uid")
                allocation = next(
                    (a for a in self.allocations.values()
                     if a["deal_ref"].get("escrow_uid") == escrow
                     and a["state"] != "released"),
                    None,
                )
            if allocation is None or allocation["state"] == "released":
                return httpx.Response(200, json={"allocation": None})
            allocation["state"] = "released"
            allocation["failure_reason"] = body.get("failure_reason")
            allocation["failure_message"] = body.get("failure_message")
            self._emit("released", allocation["resource_id"])
            return httpx.Response(200, json={"allocation": {
                **allocation,
                "allocated_gpu_count": allocation["units"],
            }})

        if path.endswith("/truncate-lease"):
            allocation_id = path.split("/")[-2]
            allocation = self.allocations.get(allocation_id)
            if allocation is None:
                return httpx.Response(200, json={"allocation": None})
            allocation["lease_end_utc"] = body["lease_end_utc"]
            self._emit("lease_truncated", allocation["resource_id"])
            return httpx.Response(200, json={"allocation": allocation})

        if path == "/api/v1/capacity/allocations":
            escrow = request.url.params.get("escrow_uid")
            state = request.url.params.get("state")
            rows = [
                a for a in self.allocations.values()
                if (escrow is None or a["deal_ref"].get("escrow_uid") == escrow)
                and (state is None or a["state"] == state)
            ]
            return httpx.Response(200, json={
                "allocations": rows, "total": len(rows),
            })

        if path == "/api/v1/capacity/events":
            after = int(request.url.params.get("after", 0))
            limit = int(request.url.params.get("limit", 500))
            page = [e for e in self.events if e["version"] > after][:limit]
            latest = self.events[-1]["version"] if self.events else 0
            return httpx.Response(200, json={
                "events": page, "latest_version": latest,
            })

        return httpx.Response(404, json={"detail": f"unhandled {path}"})

    def _match(self, claim: dict) -> dict | None:
        claim = claim or {}
        requested = int(claim.get("gpu_count") or 1)
        for rid, row in self.resources.items():
            if not row["enabled"]:
                continue
            attrs = row["attributes"]
            top_level = {"resource_id": rid, "pool_id": rid}
            mismatched = any(
                attrs.get(k, top_level.get(k)) != v
                for k, v in claim.items() if k != "gpu_count"
            )
            if mismatched:
                continue
            available = self._available(rid)
            if available < requested:
                continue
            return {
                "resource_id": rid,
                "pool_id": None,
                "member_id": None,
                "vm_host": attrs.get("vm_host"),
                "allocated_gpu_count": requested,
                "available_gpu_count": available,
                "attributes": attrs,
            }
        return None


def aggregate_over(
    fake: FakeSite,
    *,
    site_name: str = "default",
    sqlite_client_factory: Any | None = None,
):
    """A real AggregateCapacityClient over the fake site's transport.

    With ``sqlite_client_factory``, the production listing-reconcile
    subscriber is attached — drive it with ``pump_events``.
    """
    from core_storefront.aggregation import AggregateCapacityClient

    from market_storefront.services.capacity_client import (
        RemoteCapacityClient,
        _make_listing_reconcile_subscriber,
    )

    remote = RemoteCapacityClient(
        "http://fake-site:8081", "test-key", transport=fake.transport(),
    )
    aggregate = AggregateCapacityClient({site_name: remote})
    if sqlite_client_factory is not None:
        aggregate.subscribe(
            _make_listing_reconcile_subscriber(sqlite_client_factory, aggregate),
        )
    return aggregate


@contextlib.contextmanager
def site_capacity(
    fake: FakeSite,
    *,
    site_name: str = "default",
    sqlite_client_factory: Any | None = None,
) -> Iterator[Any]:
    """Route every build_capacity_client() call at the fake ledger."""
    aggregate = aggregate_over(
        fake, site_name=site_name, sqlite_client_factory=sqlite_client_factory,
    )
    patches = [patch(
        "market_storefront.services.capacity_client.build_capacity_client",
        return_value=aggregate,
    )]
    # fulfillment_service binds the name at import time.
    patches.append(patch(
        "market_storefront.services.fulfillment_service.build_capacity_client",
        return_value=aggregate,
    ))
    with contextlib.ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        yield aggregate


async def pump_events(
    aggregate: Any, fake: FakeSite, *, site_name: str = "default", after: int = 0,
) -> int:
    """Deliver the fake site's events to aggregate subscribers (the
    production poller's job). Returns the last delivered version."""
    from core_storefront.capacity import CapacityDelta

    last = after
    for event in fake.events:
        if event["version"] <= after:
            continue
        await aggregate.emit_site_delta(site_name, CapacityDelta(
            kind=event["kind"],
            version=event["version"],
            resource_id=event.get("resource_id"),
        ))
        last = event["version"]
    return last
