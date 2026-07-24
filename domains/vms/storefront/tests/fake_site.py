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
        self.reservations: dict[str, dict] = {}
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
            a["units"] for a in self.reservations.values()
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
                "capacity": body.get("capacity"),
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

        if request.method == "POST" and path == "/api/v1/capacity/reservations":
            match = self._match(body["claim"])
            if match is None:
                return httpx.Response(200, json={"reservation": None})
            capacity_reservation_id = f"alloc-{next(self._ids)}"
            self.reservations[capacity_reservation_id] = {
                "capacity_reservation_id": capacity_reservation_id,
                "resource_id": match["resource_id"],
                "units": match["allocated_gpu_count"],
                "state": "reserved",
                "deal_ref": body.get("deal_ref") or {},
            }
            self._emit("reserved", match["resource_id"])
            return httpx.Response(200, json={"reservation": {
                **match,
                "capacity_reservation_id": capacity_reservation_id,
                "hold_expires_at": None,
            }})

        if path.endswith("/commit"):
            capacity_reservation_id = path.split("/")[-2]
            reservation = self.reservations.get(capacity_reservation_id)
            if reservation is None:
                return httpx.Response(404, json={"detail": "not found"})
            reservation["state"] = "leased"
            reservation["lease_start_utc"] = body.get("lease_start_utc")
            reservation["lease_end_utc"] = body.get("lease_end_utc")
            self._emit("committed", reservation["resource_id"])
            return httpx.Response(200, json={"reservation": reservation})

        if path == "/api/v1/capacity/releases":
            reservation = None
            if body.get("capacity_reservation_id"):
                reservation = self.reservations.get(body["capacity_reservation_id"])
            else:
                escrow = (body.get("deal_ref") or {}).get("escrow_uid")
                reservation = next(
                    (a for a in self.reservations.values()
                     if a["deal_ref"].get("escrow_uid") == escrow
                     and a["state"] != "released"),
                    None,
                )
            if reservation is None or reservation["state"] == "released":
                return httpx.Response(200, json={"reservation": None})
            reservation["state"] = "released"
            reservation["failure_reason"] = body.get("failure_reason")
            reservation["failure_message"] = body.get("failure_message")
            self._emit("released", reservation["resource_id"])
            return httpx.Response(200, json={"reservation": {
                **reservation,
                "allocated_gpu_count": reservation["units"],
            }})

        if path.endswith("/truncate-lease"):
            capacity_reservation_id = path.split("/")[-2]
            reservation = self.reservations.get(capacity_reservation_id)
            if reservation is None:
                return httpx.Response(200, json={"reservation": None})
            reservation["lease_end_utc"] = body["lease_end_utc"]
            self._emit("lease_truncated", reservation["resource_id"])
            return httpx.Response(200, json={"reservation": reservation})

        if request.method == "GET" and path == "/api/v1/capacity/reservations":
            escrow = request.url.params.get("escrow_uid")
            state = request.url.params.get("state")
            rows = [
                a for a in self.reservations.values()
                if (escrow is None or a["deal_ref"].get("escrow_uid") == escrow)
                and (state is None or a["state"] == state)
            ]
            return httpx.Response(200, json={
                "reservations": rows, "total": len(rows),
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
        # compute_capacity_claim_from_order now always routes gpu_count.
        # This fake only proves the GPU-count contract this test double
        # documents itself as covering but it must at least read the
        # quantity from the new location and skip "dimensions" in the
        # attribute-equality mismatch check the same way the real
        # ledger's _resource_matches skips it.
        dimensions = claim.get("dimensions") or {}
        requested = int(dimensions.get("gpu_count") or claim.get("gpu_count") or 1)
        for rid, row in self.resources.items():
            if not row["enabled"]:
                continue
            attrs = row["attributes"]
            top_level = {"resource_id": rid, "pool_id": rid}
            mismatched = any(
                attrs.get(k, top_level.get(k)) != v
                for k, v in claim.items() if k not in ("gpu_count", "dimensions")
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
