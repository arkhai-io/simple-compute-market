"""In-memory site authority for storefront tests.

``FakeSite`` mirrors the provisioning service's ``/api/v1/capacity``
surface behind an ``httpx.MockTransport``. The real wire shapes are pinned
by that service's own integration tests. ``site_capacity`` injects the exact
``CapacityRuntime`` and pool projection used by settle/fulfillment tests;
``capacity_runtime_over`` is available when a test owns composition directly.
"""

from __future__ import annotations

import contextlib
import itertools
import json
import time
from collections.abc import Iterator
from typing import Any
from unittest.mock import patch

import httpx
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


TEST_MARKETPLACE_SIGNER = create_signer("ed25519", b"\x41" * 32)
TEST_SITE_AUTHORITY_SIGNER = create_signer("ed25519", b"\x42" * 32)
TEST_SITE_AUTHORITIES = TrustedIdentitySet(
    identities=(TEST_SITE_AUTHORITY_SIGNER.identity,)
)


class FakeSite:
    """Dict-backed single-site capacity ledger."""

    def __init__(self, *, deliverable_modes: set[str] | frozenset[str] | None = None) -> None:
        self.deliverable_modes = frozenset(deliverable_modes or ())
        self.resources: dict[str, dict] = {}
        self.reservations: dict[str, dict] = {}
        self.events: list[dict] = []
        self._versions = itertools.count(1)
        self._ids = itertools.count(1)

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
        self.events.append(
            {
                "version": next(self._versions),
                "kind": kind,
                "resource_id": resource_id,
                "occurred_at": "2026-01-01T00:00:00Z",
            }
        )

    def _available(self, rid: str) -> int:
        held = sum(
            a["units"]
            for a in self.reservations.values()
            if a["resource_id"] == rid
            and a["state"] in ("reserved", "provisioning", "leased", "releasing")
        )
        return self.resources[rid]["total_units"] - held

    def _handle(self, request: httpx.Request) -> httpx.Response:
        response = self._dispatch(request)
        request_body = json.loads(request.content) if request.content else {}
        response_body = response.json() if response.content else EMPTY_BODY
        operation, resource = resolve_capacity_route(
            request.method,
            request.url.path,
            request_body,
        )
        signed = sign_response(
            signer=TEST_SITE_AUTHORITY_SIGNER,
            envelope=ResponseEnvelope(
                role="service",
                principal=TEST_SITE_AUTHORITY_SIGNER.identity,
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

        if path == "/api/v1/capacity/snapshot":
            return httpx.Response(
                200,
                json={
                    "resources": [
                        {
                            "resource_id": rid,
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
                            "available": {"gpu_count": self._available(rid)},
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
        executor_kind = claim.get("executor_kind")
        if (
            not isinstance(executor_kind, str)
            or executor_kind not in self.deliverable_modes
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
                    "executor_kind",
                )
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
        reconcile = _capacity_reconciler(sqlite_client_factory)

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
):
    """A kit-owned ``CapacityRuntime`` over the fake site's transport."""
    from core_storefront.aggregation import fill_first
    from market_capacity_publication import CapacityRuntime, CapacitySite
    from market_site_client import SiteCapacityClient

    from market_storefront.services.capacity_client import _capacity_reconciler

    if sqlite_client_factory is None:
        async def reconcile(_context):
            return None
    else:
        reconcile = _capacity_reconciler(sqlite_client_factory)

    return CapacityRuntime(
        sites=(
            CapacitySite(
                site_name,
                "http://fake-site:8081",
                TEST_SITE_AUTHORITIES,
            ),
        ),
        signer=TEST_MARKETPLACE_SIGNER,
        placement=fill_first,
        reconcile=reconcile,
        site_client_factory=lambda _site, _signer: SiteCapacityClient(
            "http://fake-site:8081",
            signer=TEST_MARKETPLACE_SIGNER,
            expected_authorities=TEST_SITE_AUTHORITIES,
            transport=fake.transport(),
        ),
    )


def _pool_projection_rows(fake: FakeSite) -> list[dict[str, Any]]:
    """Project each fake resource as its exact one-member VM pool."""
    return [
        {
            "resource_pool_id": resource_id,
            "pool_metadata": {
                "policy_tags": {
                    "deliverable_modes": sorted(fake.deliverable_modes),
                },
            },
            "resources": [
                {
                    "physical_resource_id": resource_id,
                    "capacity": {"gpu_count": row["total_units"]},
                    "available": {"gpu_count": fake._available(resource_id)},
                    "attributes": dict(row["attributes"]),
                    "enabled": bool(row["enabled"]),
                },
            ],
        }
        for resource_id, row in fake.resources.items()
    ]


def _pool_projection_caches(fake: FakeSite, *, site_name: str):
    """Loaded pool metadata for the fake authority's exact VM capabilities."""
    from core_storefront.site_projections import (
        ProjectionCache,
        ProjectionIdentity,
        ProjectionState,
    )
    from market_storefront.services.site_projection_cache import SiteProjectionCaches

    resource_pools = ProjectionCache(client=None)
    resource_pools._value = _pool_projection_rows(fake)
    resource_pools._state = ProjectionState.loaded
    resource_pools._identity = ProjectionIdentity(
        revision=1,
        digest=f"fake:{site_name}:{','.join(sorted(fake.resources))}",
    )
    return SiteProjectionCaches(
        resource_pools=resource_pools,
        capacity_buckets=ProjectionCache(client=None),
    )


@contextlib.contextmanager
def site_capacity(
    fake: FakeSite,
    *,
    site_name: str = "default",
    sqlite_client_factory: Any | None = None,
    project_pool_modes: bool = False,
) -> Iterator[Any]:
    """Inject one explicit fake-backed capacity runtime and optional pools."""
    from market_storefront.services import site_projection_cache
    import market_storefront.container as container

    runtime = capacity_runtime_over(
        fake,
        site_name=site_name,
        sqlite_client_factory=sqlite_client_factory,
    )
    aggregate = runtime.client()
    patches = [
        patch(
            "market_storefront.services.capacity_client.build_capacity_runtime",
            return_value=runtime,
        ),
        patch(
            "market_storefront.services.capacity_client.build_capacity_client",
            return_value=aggregate,
        ),
        # fulfillment_service binds both factory names at import time.
        patch(
            "market_storefront.services.fulfillment_service.build_capacity_runtime",
            return_value=runtime,
        ),
        patch(
            "market_storefront.services.fulfillment_service.build_capacity_client",
            return_value=aggregate,
        ),
        patch.object(container, "resolved_capacity_runtime", runtime),
    ]
    if project_pool_modes:
        patches.append(
            patch.dict(
                site_projection_cache._caches,
                {site_name: _pool_projection_caches(fake, site_name=site_name)},
                clear=True,
            )
        )
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
    from market_storefront.services.site_projection_cache import projection_caches

    caches = projection_caches().get(site_name)
    if caches is not None and str(
        getattr(
            getattr(caches.resource_pools, "_identity", None),
            "digest",
            "",
        )
    ).startswith(f"fake:{site_name}:"):
        # The real projection poller refreshes this view before capacity
        # deltas are reconciled. Mirror that ordering with the fake's
        # post-reservation availability so only genuinely oversized slices close.
        caches.resource_pools._value = _pool_projection_rows(fake)

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
