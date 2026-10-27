"""In-memory site authority for storefront tests.

``FakeSite`` mirrors the provisioning service's ``/api/v1/capacity``
surface behind an ``httpx.MockTransport``. The real wire shapes are pinned
by that service's own integration tests. ``site_capacity`` injects the exact
``CapacityRuntime`` and the projection state over its aggregate used by
settle/fulfillment tests; ``capacity_runtime_over`` is available when a test
owns composition directly. ``FakeProjectionSite`` serves only the two
projection families, for a test that builds its own projection state with
``site_projection_state``.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import itertools
import json
import time
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import patch

import httpx
from core_storefront.aggregation import AggregateCapacityClient
from market_capacity_publication import SiteProjectionState
from market_identity import (
    EMPTY_BODY,
    ResponseEnvelope,
    TrustedIdentitySet,
    canonical_body_hash,
    create_signer,
    sign_response,
)
from market_site_client.client import (
    IDENTITY_IDENTIFIER_HEADER,
    IDENTITY_SCHEME_HEADER,
    REQUEST_ID_HEADER,
    ROLE_HEADER,
    SIGNATURE_HEADER,
    SIGNATURE_VERSION_HEADER,
    TIMESTAMP_HEADER,
    resolve_capacity_route,
)

import market_storefront.container as container


TEST_MARKETPLACE_SIGNER = create_signer("ed25519", b"\x41" * 32)
TEST_SITE_AUTHORITY_SIGNER = create_signer("ed25519", b"\x42" * 32)
TEST_SITE_AUTHORITIES = TrustedIdentitySet(
    identities=(TEST_SITE_AUTHORITY_SIGNER.identity,)
)
# Signs as an authority the storefront does not trust, for answers that must not
# verify. A development key; never used on a public network.
TEST_UNTRUSTED_SIGNER = create_signer("ed25519", b"\x43" * 32)


class FakeSite:
    """Dict-backed single-site capacity ledger."""

    def __init__(self, *, deliverable_modes: set[str] | frozenset[str] | None = None) -> None:
        self.deliverable_modes = frozenset(deliverable_modes or ())
        self.resources: dict[str, dict] = {}
        self.reservations: dict[str, dict] = {}
        self.events: list[dict] = []
        self._versions = itertools.count(1)
        self._ids = itertools.count(1)
        #: The live resource-pool projection the site serves. ``None`` projects
        #: each resource as its own one-member pool; a test sets a list to serve
        #: exactly that generation.
        self.pool_projection: list[dict] | None = None
        self.pool_projection_revision = 1
        #: The capacity-bucket projection the site serves. ``None`` serves none,
        #: so the storefront holds no bucket generation and derives fungible
        #: availability from the pool rows instead.
        self.capacity_buckets: list[dict] | None = None
        #: Off: every request fails to connect, as an unreachable site does.
        self.reachable = True
        #: Off: every answer is signed by an authority the storefront does not
        #: trust, so it arrives but does not verify.
        self.verifiable = True
        #: The authority that signs the site's answers; ``None`` signs as the
        #: trusted test authority, or the untrusted one while ``verifiable`` is
        #: off. A test rotating the site's key sets it.
        self.signer: Any = None
        #: ``(method, path)`` of every request that reached the site.
        self.requests: list[tuple[str, str]] = []
        #: Reservations fulfillment delivered against: the site's release
        #: guard refuses to free them, as the provisioning service's does.
        self.delivered: set[str] = set()

    def add_resource(
        self,
        resource_id: str,
        total_units: int,
        *,
        attributes: dict | None = None,
        capacity: dict | None = None,
    ) -> None:
        """Declare one resource. ``capacity`` declares every dimension; without
        it the resource declares its GPU count only."""
        self.resources[resource_id] = {
            "resource_id": resource_id,
            "total_units": int(total_units),
            "attributes": dict(attributes or {}),
            "capacity": dict(capacity) if capacity is not None else None,
            "enabled": True,
        }

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def emit(self, kind: str, resource_id: str | None = None) -> None:
        """Append one capacity event to the feed, as the site would on a change."""
        self._emit(kind, resource_id)

    def _emit(self, kind: str, resource_id: str | None) -> None:
        self.events.append(
            {
                "version": next(self._versions),
                "kind": kind,
                "resource_id": resource_id,
                "occurred_at": "2026-01-01T00:00:00Z",
            }
        )

    def _capacity(self, rid: str) -> dict[str, int]:
        row = self.resources[rid]
        return dict(row.get("capacity") or {"gpu_count": row["total_units"]})

    def available_dimensions(self, rid: str) -> dict[str, int]:
        """Every declared dimension less what live reservations hold, as the
        site ledger debits each requested dimension."""
        available = self._capacity(rid)
        for reservation in self.reservations.values():
            if reservation["resource_id"] != rid or reservation["state"] not in (
                "reserved", "provisioning", "leased", "releasing"
            ):
                continue
            held = reservation.get("dimensions") or {"gpu_count": reservation["units"]}
            for key, amount in held.items():
                available[key] = available.get(key, 0) - int(amount)
        return available

    def _available(self, rid: str) -> int:
        return self.available_dimensions(rid).get("gpu_count", 0)

    def served_pool_projection(self) -> list[dict]:
        if self.pool_projection is not None:
            return self.pool_projection
        return _pool_projection_rows(self)

    def _pool_projection_generation(self) -> dict[str, Any]:
        return _generation(
            self.served_pool_projection(), revision=self.pool_projection_revision
        )

    def _handle(self, request: httpx.Request) -> httpx.Response:
        if not self.reachable:
            raise httpx.ConnectError("fake site is unreachable", request=request)
        self.requests.append((request.method, request.url.path))
        response = self._dispatch(request)
        request_body = json.loads(request.content) if request.content else {}
        response_body = response.json() if response.content else EMPTY_BODY
        operation, resource = resolve_capacity_route(
            request.method,
            request.url.path,
            request_body,
        )
        signer = self.signer or (
            TEST_SITE_AUTHORITY_SIGNER if self.verifiable else TEST_UNTRUSTED_SIGNER
        )
        signed = sign_response(
            signer=signer,
            envelope=ResponseEnvelope(
                role="service",
                principal=signer.identity,
                method=request.method,
                operation=operation,
                resource=resource,
                request_id=request.headers[REQUEST_ID_HEADER],
                timestamp=int(time.time()),
                status=response.status_code,
                body_hash=canonical_body_hash(response_body),
            ),
        )
        headers = {
            SIGNATURE_VERSION_HEADER: signed.protocol,
            IDENTITY_SCHEME_HEADER: signed.principal.scheme.value,
            IDENTITY_IDENTIFIER_HEADER: signed.principal.identifier,
            ROLE_HEADER: signed.role,
            REQUEST_ID_HEADER: signed.request_id,
            TIMESTAMP_HEADER: str(signed.timestamp),
            SIGNATURE_HEADER: signed.proof.value,
        }
        if response_body is EMPTY_BODY:
            return httpx.Response(
                response.status_code,
                content=b"",
                headers=headers,
            )
        return httpx.Response(
            response.status_code,
            json=response_body,
            headers=headers,
        )

    def _dispatch(self, request: httpx.Request) -> httpx.Response:
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

        if request.method == "GET" and path == "/api/v1/capacity/site-resource-pools":
            return httpx.Response(
                200,
                json={
                    **self._pool_projection_generation(),
                    "resource_pools": self.served_pool_projection(),
                },
            )

        if (
            request.method == "GET"
            and path == "/api/v1/capacity/site-resource-pools/version"
        ):
            return httpx.Response(200, json=self._pool_projection_generation())

        if self.capacity_buckets is not None and request.method == "GET":
            if path == "/api/v1/capacity/site-capacity-buckets":
                return httpx.Response(
                    200,
                    json={
                        **_generation(self.capacity_buckets),
                        "capacity_buckets": self.capacity_buckets,
                    },
                )
            if path == "/api/v1/capacity/site-capacity-buckets/version":
                return httpx.Response(200, json=_generation(self.capacity_buckets))

        if path == "/api/v1/capacity/snapshot":
            return httpx.Response(
                200,
                json={
                    "resources": [
                        {
                            "resource_id": rid,
                            # Every declaration names its pool, and a row with
                            # none matches no claim; this fake places each
                            # resource in a pool of its own, as its matcher does.
                            "pool_id": rid,
                            "resource_type": "compute.gpu",
                            "unit": "count",
                            "value": row["total_units"],
                            "available_units": self._available(rid),
                            # Real kit/site's snapshot always includes a
                            # multidimensional "available" map (PRIMARY_DIMENSION
                            # is "gpu_count") -- without it, an injected exact
                            # ClaimMatcher (which always resolves both legacy and
                            # modern claims through this map, never
                            # available_units directly) sees every row as
                            # zero-capacity for ranking purposes, regardless of
                            # this fake's own separate reservation-matching logic.
                            "available": self.available_dimensions(rid),
                            "state": (
                                "available" if self._available(rid) > 0 else "leased"
                            ),
                            "attributes": row["attributes"],
                            "enabled": True,
                        }
                        for rid, row in self.resources.items()
                        if row["enabled"]
                    ]
                },
            )

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
                "dimensions": dict(match["dimensions"]),
                "state": "reserved",
                "deal_ref": body.get("deal_ref") or {},
            }
            self._emit("reserved", match["resource_id"])
            return httpx.Response(
                200,
                json={
                    "reservation": {
                        **match,
                        "capacity_reservation_id": capacity_reservation_id,
                        "hold_expires_at": None,
                    }
                },
            )

        if path.endswith("/commit"):
            capacity_reservation_id = path.split("/")[-2]
            reservation = self.reservations.get(capacity_reservation_id)
            if reservation is None:
                return httpx.Response(404, json={"detail": "not found"})
            escrow_uid = dict(body.get("deal_ref") or {}).get("escrow_uid")
            if escrow_uid and not reservation.get("escrow_uid"):
                reservation["escrow_uid"] = escrow_uid
            # A commit is write-once, as the site's: a repeat on a leased
            # reservation answers with the window the first one recorded.
            if reservation.get("state") == "leased":
                return httpx.Response(200, json={"reservation": reservation})
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
                    (
                        a
                        for a in self.reservations.values()
                        if a["deal_ref"].get("escrow_uid") == escrow
                        and a["state"] != "released"
                    ),
                    None,
                )
            if reservation is None or reservation["state"] == "released":
                return httpx.Response(200, json={"reservation": None})
            if reservation["capacity_reservation_id"] in self.delivered:
                return httpx.Response(200, json={"reservation": None})
            reservation["state"] = "released"
            reservation["failure_reason"] = body.get("failure_reason")
            reservation["failure_message"] = body.get("failure_message")
            self._emit("released", reservation["resource_id"])
            return httpx.Response(
                200,
                json={
                    "reservation": {
                        **reservation,
                        "allocated_gpu_count": reservation["units"],
                    }
                },
            )

        if path.endswith("/truncate-lease"):
            capacity_reservation_id = path.split("/")[-2]
            reservation = self.reservations.get(capacity_reservation_id)
            if reservation is None:
                return httpx.Response(200, json={"reservation": None})
            reservation["lease_end_utc"] = body["lease_end_utc"]
            self._emit("lease_truncated", reservation["resource_id"])
            return httpx.Response(200, json={"reservation": reservation})
        if (
            request.method == "GET"
            and path.startswith("/api/v1/capacity/reservations/")
        ):
            capacity_reservation_id = path.rsplit("/", 1)[1]
            reservation = self.reservations.get(capacity_reservation_id)
            if reservation is None:
                return httpx.Response(404, json={"detail": "not found"})
            return httpx.Response(200, json={"reservation": reservation})

        if request.method == "GET" and path == "/api/v1/capacity/reservations":
            escrow = request.url.params.get("escrow_uid")
            state = request.url.params.get("state")
            rows = [
                a
                for a in self.reservations.values()
                if (escrow is None or a["deal_ref"].get("escrow_uid") == escrow)
                and (state is None or a["state"] == state)
            ]
            return httpx.Response(
                200,
                json={
                    "reservations": rows,
                    "total": len(rows),
                },
            )

        if path == "/api/v1/capacity/events":
            after = int(request.url.params.get("after", 0))
            limit = int(request.url.params.get("limit", 500))
            page = [e for e in self.events if e["version"] > after][:limit]
            latest = self.events[-1]["version"] if self.events else 0
            return httpx.Response(
                200,
                json={
                    "events": page,
                    "latest_version": latest,
                },
            )

        return httpx.Response(404, json={"detail": f"unhandled {path}"})

    def _match(self, claim: dict) -> dict | None:
        claim = claim or {}
        offering_mode = claim.get("offering_mode")
        if (
            not isinstance(offering_mode, str)
            or offering_mode not in self.deliverable_modes
        ):
            return None
        # compute_capacity_claim_from_order now always routes gpu_count.
        # This fake only proves the GPU-count contract this test double
        # documents itself as covering but it must at least read the
        # quantity from the new location and skip "dimensions" in the
        # attribute-equality mismatch check the same way the real
        # ledger's _resource_matches skips it.
        dimensions = claim.get("dimensions") or {}
        requested = int(dimensions.get("gpu_count") or claim.get("gpu_count") or 1)
        requested_dimensions = {
            str(key): int(value) for key, value in dimensions.items()
        } or {"gpu_count": requested}
        # resource_type is a special top-level claim key (mirroring real
        # kit/site's _split_claim_requirement), not an arbitrary
        # attribute -- every resource this fake serves is "compute.gpu"
        # (see the hardcoded snapshot() response above), so it never
        # lives in a resource's own attributes dict the way
        # gpu_model/region do.
        required_resource_type = claim.get("resource_type")
        if (
            required_resource_type is not None
            and required_resource_type != "compute.gpu"
        ):
            return None
        for rid, row in self.resources.items():
            if not row["enabled"]:
                continue
            attrs = row["attributes"]
            top_level = {"resource_id": rid, "pool_id": rid}
            mismatched = any(
                attrs.get(k, top_level.get(k)) != v
                for k, v in claim.items()
                if k not in (
                    "gpu_count",
                    "dimensions",
                    "resource_type",
                    "offering_mode",
                )
            )
            if mismatched:
                continue
            available_dimensions = self.available_dimensions(rid)
            # Every requested dimension must fit; one the resource does not
            # declare has nothing available, as the ledger treats it.
            if any(
                available_dimensions.get(key, 0) < amount
                for key, amount in requested_dimensions.items()
            ):
                continue
            available = available_dimensions.get("gpu_count", 0)
            return {
                "resource_id": rid,
                "pool_id": None,
                "member_id": None,
                "host_id": attrs.get("host_id"),
                "allocated_gpu_count": requested,
                "available_gpu_count": available,
                "dimensions": requested_dimensions,
                "attributes": attrs,
            }
        return None


def aggregate_over(
    fake: FakeSite,
    *,
    site_name: str = "default",
    sqlite_client_factory: Any | None = None,
    site_projections: Any = None,
):
    """A real AggregateCapacityClient over the fake site's transport.

    With ``sqlite_client_factory``, the production listing-reconcile
    subscriber is attached — drive it with ``pump_events``. It reads the
    projection state ``site_projections`` provides, by default the one a test
    injected into the container.
    """
    from core_storefront.aggregation import AggregateCapacityClient
    from market_capacity_publication import (
        CapacityProjection,
        CapacityReconcileContext,
        capacity_availability,
    )
    from market_site_client import SiteCapacityClient

    from market_storefront.services.capacity_client import _capacity_reconciler

    remote = SiteCapacityClient(
        "http://fake-site:8081",
        signer=TEST_MARKETPLACE_SIGNER,
        expected_authorities=TEST_SITE_AUTHORITIES,
        transport=fake.transport(),
    )
    aggregate = AggregateCapacityClient({site_name: remote})
    if sqlite_client_factory is not None:
        reconcile = _capacity_reconciler(
            sqlite_client_factory,
            site_projections=site_projections or _injected_site_projections,
        )

        async def _on_delta(delta):
            rows = tuple(await aggregate.snapshot())
            await reconcile(
                CapacityReconcileContext(
                    projections=(CapacityProjection(site_name, rows),),
                    availability=await capacity_availability(aggregate),
                    delta=delta,
                )
            )

        aggregate.subscribe(_on_delta)
    return aggregate


def capacity_runtime_over(
    fake: FakeSite,
    *,
    site_name: str = "default",
    sqlite_client_factory: Any | None = None,
    site_projections: Any = None,
):
    """A kit-owned ``CapacityRuntime`` over the fake site's transport."""
    return capacity_runtime_over_sites(
        {site_name: fake},
        sqlite_client_factory=sqlite_client_factory,
        site_projections=site_projections,
    )


def _injected_site_projections():
    return container.resolved_site_projections


def capacity_runtime_over_sites(
    fakes: dict[str, FakeSite],
    *,
    sqlite_client_factory: Any | None = None,
    site_projections: Any = None,
):
    """A kit-owned ``CapacityRuntime`` over several fake sites, one per name.

    Sites are configured in the mapping's order, so its first is the home site.
    With ``sqlite_client_factory`` its reconciler runs, reading the projection
    state ``site_projections`` provides, by default the one a test injected
    into the container.
    """
    from core_storefront.aggregation import fill_first
    from market_capacity_publication import CapacityRuntime, CapacitySite
    from market_site_client import SiteCapacityClient

    from market_storefront.services.capacity_client import _capacity_reconciler

    if sqlite_client_factory is None:
        async def reconcile(_context):
            return None
    else:
        reconcile = _capacity_reconciler(
            sqlite_client_factory,
            site_projections=site_projections or _injected_site_projections,
        )

    return CapacityRuntime(
        sites=tuple(
            CapacitySite(name, "http://fake-site:8081", TEST_SITE_AUTHORITIES)
            for name in fakes
        ),
        signer=TEST_MARKETPLACE_SIGNER,
        placement=fill_first,
        reconcile=reconcile,
        site_client_factory=lambda site, _signer: SiteCapacityClient(
            "http://fake-site:8081",
            signer=TEST_MARKETPLACE_SIGNER,
            expected_authorities=TEST_SITE_AUTHORITIES,
            transport=fakes[site.site_id].transport(),
        ),
    )


def _pool_projection_rows(fake: FakeSite) -> list[dict[str, Any]]:
    """Project each fake resource as its exact one-member VM pool.

    A pool states the region its member declares, as an operator states it on
    both: a VM pool without a region is held rather than published.
    """
    return [
        {
            "pool_id": resource_id,
            "pool_metadata": {
                "policy_tags": {
                    "deliverable_modes": sorted(fake.deliverable_modes),
                    **(
                        {"region": row["attributes"]["region"]}
                        if row["attributes"].get("region")
                        else {}
                    ),
                },
            },
            "resources": [
                {
                    "physical_resource_id": resource_id, "resource_type": "compute.gpu",
                    "capacity": fake._capacity(resource_id),
                    "available": fake.available_dimensions(resource_id),
                    "attributes": dict(row["attributes"]),
                    "enabled": bool(row["enabled"]),
                },
            ],
        }
        for resource_id, row in fake.resources.items()
    ]


def buckets_from_pools(pools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The capacity-bucket family a site serves beside ``pools``: one bucket
    per enabled member, holding its current availability, as the site groups
    members whose capacity and criteria are identical. Per-member buckets give
    a fungible pool exactly the availability its pool rows do."""
    return [
        {
            "pool_id": pool.get("pool_id"),
            "resource_type": member.get("resource_type"),
            "resource_subtype": member.get("resource_subtype"),
            "available": dict(member.get("available") or {}),
            "grouping_attributes": dict(member.get("attributes") or {}),
            "capacity_group_key": f"{pool.get('pool_id')}:{member.get('physical_resource_id')}",
            "resource_count": 1,
        }
        for pool in pools
        for member in pool.get("resources") or []
        if member.get("enabled", True)
    ]


def _generation(rows: Any, *, revision: int = 1) -> dict[str, Any]:
    """A projection's identity: a digest of exactly the rows served, so a
    version poll refetches when, and only when, they changed."""
    digest = hashlib.sha256(json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()
    return {"revision": revision, "digest": digest}


class FakeProjectionSite:
    """One site's two projection families, as its site client serves them.

    A member of the fake aggregate a test builds a ``SiteProjectionState``
    over. Each family serves the rows a test sets, identified by a digest of
    them; ``None`` serves nothing, as a site that never answered. With
    ``derive_buckets`` and no bucket rows set, the capacity-bucket family is
    derived from the resource-pool rows as they stand (``buckets_from_pools``),
    as a site serves both families of one inventory. Rows are
    served as they stand when fetched, so a change reaches the state at its
    next poll or refresh and never otherwise. ``failing`` fails every call, as
    an unreachable site does. ``snapshots`` counts each family's fetches and
    ``calls`` names every call in order.
    """

    def __init__(
        self,
        resource_pools: list[dict[str, Any]] | None = None,
        capacity_buckets: list[dict[str, Any]] | None = None,
        *,
        derive_buckets: bool = False,
    ) -> None:
        self.rows: dict[str, list[dict[str, Any]] | None] = {
            "resource_pool": resource_pools,
            "capacity_bucket": capacity_buckets,
        }
        self.derive_buckets = derive_buckets
        self.failing = False
        self.snapshots = {"resource_pool": 0, "capacity_bucket": 0}
        self.calls: list[str] = []
        #: What the state installed for this site's topology-sensitive refusals.
        self.topology_error_handler: Any = None
        #: When set, the next version check answers as the rows stand and then
        #: parks until ``hold`` is set, having set ``holding``: an operation
        #: caught mid-poll.
        self.hold: asyncio.Event | None = None
        self.holding = asyncio.Event()

    @property
    def resource_pools(self) -> list[dict[str, Any]] | None:
        return self.rows["resource_pool"]

    @resource_pools.setter
    def resource_pools(self, rows: list[dict[str, Any]] | None) -> None:
        self.rows["resource_pool"] = rows

    @property
    def capacity_buckets(self) -> list[dict[str, Any]] | None:
        return self.rows["capacity_bucket"]

    @capacity_buckets.setter
    def capacity_buckets(self, rows: list[dict[str, Any]] | None) -> None:
        self.rows["capacity_bucket"] = rows

    def served(self, family: str) -> list[dict[str, Any]]:
        """The rows one family serves now; overridden to derive them live."""
        rows = self.rows[family]
        if family == "capacity_bucket" and rows is None and self.derive_buckets:
            return buckets_from_pools(self.served("resource_pool"))
        if self.failing or rows is None:
            raise ConnectionError(f"{family} projection unavailable")
        return rows

    async def _version(self, family: str) -> dict[str, Any]:
        self.calls.append(f"{family}.version")
        answer = _generation(self.served(family))
        if self.hold is not None and not self.hold.is_set():
            self.holding.set()
            await self.hold.wait()
        return answer

    async def _snapshot(self, family: str, key: str) -> dict[str, Any]:
        self.calls.append(f"{family}.snapshot")
        self.snapshots[family] += 1
        rows = self.served(family)
        return {**_generation(rows), key: rows}

    async def resource_pool_projection_version(self) -> dict[str, Any]:
        return await self._version("resource_pool")

    async def resource_pool_projection(self) -> dict[str, Any]:
        return await self._snapshot("resource_pool", "resource_pools")

    async def capacity_bucket_projection_version(self) -> dict[str, Any]:
        return await self._version("capacity_bucket")

    async def capacity_bucket_projection(self) -> dict[str, Any]:
        return await self._snapshot("capacity_bucket", "capacity_buckets")

    def set_topology_error_handler(self, handler: Any) -> None:
        self.topology_error_handler = handler


def site_projection_state(
    sites: Any,
    *,
    on_resource_pool_change: Any = None,
):
    """A ``SiteProjectionState`` over ``sites``, holding nothing until polled.

    ``sites`` is an aggregate capacity client -- a runtime's own, so a state
    over a ``FakeSite`` reads the projections that site serves -- or a mapping
    of site name to ``FakeProjectionSite``, which becomes the fake aggregate.
    """
    aggregate = (
        sites if isinstance(sites, AggregateCapacityClient) else AggregateCapacityClient(dict(sites))
    )
    return SiteProjectionState(
        aggregate,
        on_resource_pool_change=on_resource_pool_change or (lambda: None),
    )


async def loaded_site_projection_state(sites: Any, **kwargs: Any):
    """``site_projection_state`` after its first poll, as startup loads it."""
    state = site_projection_state(sites, **kwargs)
    await state.poll_once()
    return state


@contextlib.asynccontextmanager
async def site_capacity(
    fake: FakeSite,
    *,
    site_name: str = "default",
    sqlite_client_factory: Any | None = None,
    project_pool_modes: bool = False,
    on_resource_pool_change: Any = None,
) -> AsyncIterator[Any]:
    """Inject one explicit fake-backed capacity runtime and its projection state.

    The state is built over the runtime's own aggregate, as the composition
    root builds it, and injected through the container. With
    ``project_pool_modes`` it is loaded from what the fake site serves, as
    startup loads it; otherwise it holds nothing. ``on_resource_pool_change``
    is the publication wake the state raises.
    """
    # The runtime's reconciler reads the state built over its own aggregate,
    # bound once it exists.
    runtime = capacity_runtime_over(
        fake,
        site_name=site_name,
        sqlite_client_factory=sqlite_client_factory,
        site_projections=lambda: state,
    )
    aggregate = runtime.client()
    state = site_projection_state(aggregate, on_resource_pool_change=on_resource_pool_change)
    if project_pool_modes:
        await state.poll_once()
    patches = [
        patch(
            "market_storefront.services.capacity_client.build_capacity_runtime",
            return_value=runtime,
        ),
        patch(
            "market_storefront.services.capacity_client.build_capacity_client",
            return_value=aggregate,
        ),
        # fulfillment_service binds both factory names at import time, and
        # failure_actions binds the runtime factory.
        patch(
            "market_storefront.services.fulfillment_service.build_capacity_runtime",
            return_value=runtime,
        ),
        patch(
            "market_storefront.failure_actions.build_capacity_runtime",
            return_value=runtime,
        ),
        patch(
            "market_storefront.services.fulfillment_service.build_capacity_client",
            return_value=aggregate,
        ),
        patch.object(container, "resolved_capacity_runtime", runtime),
        patch.object(container, "resolved_site_projections", state),
    ]
    with contextlib.ExitStack() as stack:
        for capacity_patch in patches:
            stack.enter_context(capacity_patch)
        yield aggregate


async def pump_events(
    aggregate: Any,
    fake: FakeSite,
    *,
    site_name: str = "default",
    after: int = 0,
) -> int:
    """Deliver the fake site's events to aggregate subscribers (the
    production poller's job). Returns the last delivered version."""
    from core_storefront.capacity import CapacityDelta

    state = container.resolved_site_projections
    if state is not None:
        # The production poller refreshes the held projections before
        # capacity deltas are reconciled. Mirror that ordering, so only
        # genuinely oversized slices close.
        await state.poll_once()

    last = after
    for event in fake.events:
        if event["version"] <= after:
            continue
        await aggregate.emit_site_delta(
            site_name,
            CapacityDelta(
                kind=event["kind"],
                version=event["version"],
                resource_id=event.get("resource_id"),
            ),
        )
        last = event["version"]
    return last
