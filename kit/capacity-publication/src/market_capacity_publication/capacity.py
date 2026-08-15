"""Strict multi-site capacity source and projection orchestration.

The runtime owns transport aggregation, projection, delta delivery, and effect
routing.  Domain composition supplies configured sites, a signer, an explicit
placement policy, and schema-specific reconciliation hooks.  It never supplies
or infers a domain claim schema.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from core_storefront.aggregation import AggregateCapacityClient, PlacementPolicy
from core_storefront.capacity import CapacityDelta
from core_storefront.capacity_remote import site_events_poller
from market_site_client import SiteCapacityClient


class CapacityConfigurationError(ValueError):
    """Capacity composition is incomplete or ambiguous."""


class CapacityBindingError(ValueError):
    """A capacity effect does not match its durable authority binding."""


@dataclass(frozen=True, slots=True)
class CapacitySite:
    """One trusted site-authority endpoint from local composition."""

    site_id: str
    url: str
    expected_authorities: Any

    def __post_init__(self) -> None:
        site_id = self.site_id.strip()
        url = self.url.strip().rstrip("/")
        if not site_id:
            raise CapacityConfigurationError("capacity site_id must be non-empty")
        if not url:
            raise CapacityConfigurationError(
                f"capacity site {site_id!r} requires an authority URL"
            )
        object.__setattr__(self, "site_id", site_id)
        object.__setattr__(self, "url", url)


@dataclass(frozen=True, slots=True)
class CapacityBinding:
    """Exact publication/effect authority selected by domain composition.

    ``source_id`` is domain-owned and opaque to this kit (pool ID, quota
    resource ID, Physical Resource ID, or another stable candidate identity).
    ``offering_mode`` is the exact pool-declared mode advertised by the
    candidate and later passed to reservation/fulfillment policy.
    """

    site_id: str
    offering_mode: str
    source_id: str

    def __post_init__(self) -> None:
        for field_name in ("site_id", "offering_mode", "source_id"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise CapacityBindingError(f"{field_name} must be non-empty")
            object.__setattr__(self, field_name, value.strip())


@dataclass(frozen=True, slots=True)
class CapacityProjection:
    """A schema-opaque capacity snapshot with explicit site authority."""

    site_id: str
    rows: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True, slots=True)
class CapacityReconcileContext:
    """Domain-neutral inputs to a candidate reconciliation pass."""

    projections: tuple[CapacityProjection, ...]
    availability: Mapping[tuple[str, str], int]
    delta: CapacityDelta | None


class CapacityReconciler(Protocol):
    async def __call__(self, context: CapacityReconcileContext) -> None: ...


SiteClientFactory = Callable[[CapacitySite, Any], Any]


def _default_site_client(site: CapacitySite, signer: Any) -> SiteCapacityClient:
    return SiteCapacityClient(
        site.url,
        signer=signer,
        expected_authorities=site.expected_authorities,
    )

def remote_site_clients(client: Any) -> dict[str, Any]:
    """Return explicitly named aggregate members; never invent a default site."""
    if not isinstance(client, AggregateCapacityClient):
        return {}
    return {site_id: client.site(site_id) for site_id in client.site_names}

async def capacity_availability(client: Any) -> dict[tuple[str, str], int]:
    """Project exact site/resource availability from a named aggregate."""
    configured = set(remote_site_clients(client))
    view: dict[tuple[str, str], int] = {}
    for row in await client.snapshot():
        site_id = row.get("site")
        resource_id = row.get("resource_id")
        available = row.get("available_units")
        if (
            not isinstance(site_id, str)
            or site_id not in configured
            or not isinstance(resource_id, str)
            or not resource_id.strip()
            or available is None
        ):
            continue
        view[(site_id, resource_id)] = max(int(available), 0)
    return view


class CapacityRuntime:
    """One composed source for projection, reconciliation, and bound effects."""

    def __init__(
        self,
        *,
        sites: Sequence[CapacitySite],
        signer: Any,
        placement: PlacementPolicy,
        reconcile: CapacityReconciler,
        site_client_factory: SiteClientFactory = _default_site_client,
    ) -> None:
        if signer is None:
            raise CapacityConfigurationError("capacity signer is required")
        if placement is None:
            raise CapacityConfigurationError("capacity placement policy is required")
        by_id: dict[str, CapacitySite] = {}
        for site in sites:
            if site.site_id in by_id:
                raise CapacityConfigurationError(
                    f"duplicate capacity site_id {site.site_id!r}"
                )
            by_id[site.site_id] = site
        if not by_id:
            raise CapacityConfigurationError("at least one capacity site is required")
        self._sites = by_id
        self._signer = signer
        self._placement = placement
        self._reconcile_hook = reconcile
        self._site_client_factory = site_client_factory
        self._client: AggregateCapacityClient | None = None

    @property
    def site_ids(self) -> tuple[str, ...]:
        return tuple(self._sites)

    def client(self) -> AggregateCapacityClient:
        """Return the composition-scoped aggregate, constructing it once."""
        if self._client is None:
            self._client = AggregateCapacityClient(
                {
                    site_id: self._site_client_factory(site, self._signer)
                    for site_id, site in self._sites.items()
                },
                placement=self._placement,
            )
            self._client.subscribe(self._on_delta)
        return self._client

    def site_client(self, site_id: str) -> Any:
        """Return exactly the configured site; unknown sites fail closed."""
        if site_id not in self._sites:
            raise CapacityBindingError(f"unknown capacity site_id {site_id!r}")
        return self.client().site(site_id)

    def require_binding(self, binding: CapacityBinding) -> CapacityBinding:
        if binding.site_id not in self._sites:
            raise CapacityBindingError(
                f"capacity binding references unconfigured site {binding.site_id!r}"
            )
        return binding

    async def projections(self) -> tuple[CapacityProjection, ...]:
        """Fetch each site separately so no row can choose its own authority."""
        async def _site_projection(site_id: str) -> CapacityProjection:
            rows = await self.site_client(site_id).snapshot()
            return CapacityProjection(
                site_id=site_id,
                rows=tuple(dict(row) for row in rows),
            )

        return tuple(
            await asyncio.gather(*(_site_projection(site_id) for site_id in self.site_ids))
        )

    async def availability(self) -> dict[tuple[str, str], int]:
        """Project exact ``(site_id, resource_id)`` availability keys only."""
        view: dict[tuple[str, str], int] = {}
        for projection in await self.projections():
            for row in projection.rows:
                resource_id = row.get("resource_id")
                available = row.get("available_units")
                if not isinstance(resource_id, str) or not resource_id.strip():
                    continue
                if available is None:
                    continue
                view[(projection.site_id, resource_id)] = max(int(available), 0)
        return view

    async def reserve(
        self,
        binding: CapacityBinding,
        *,
        claim: Mapping[str, Any],
        deal_ref: Mapping[str, Any] | None = None,
        ttl_seconds: float | None = None,
        lease_start_utc: str | None = None,
        lease_duration_seconds: int | None = None,
    ) -> dict[str, Any] | None:
        """Reserve only at the candidate's recorded authority."""
        binding = self.require_binding(binding)
        reserved = await self.client().reserve(
            claim=claim,
            deal_ref=deal_ref,
            ttl_seconds=ttl_seconds,
            lease_start_utc=lease_start_utc,
            lease_duration_seconds=lease_duration_seconds,
            site=binding.site_id,
        )
        if reserved is not None and reserved.get("site") != binding.site_id:
            raise CapacityBindingError("capacity authority returned a mismatched site")
        return reserved

    async def commit(
        self,
        binding: CapacityBinding,
        *,
        resource_id: str | None,
        capacity_reservation_id: str,
        lease_start_utc: str | None = None,
        lease_end_utc: str | None = None,
        idempotency_ref: str | None = None,
    ) -> None:
        """Commit directly at the recorded site, including after restart."""
        binding = self.require_binding(binding)
        await self.site_client(binding.site_id).commit(
            resource_id=resource_id,
            capacity_reservation_id=capacity_reservation_id,
            lease_start_utc=lease_start_utc,
            lease_end_utc=lease_end_utc,
            idempotency_ref=idempotency_ref,
        )

    async def release(
        self,
        binding: CapacityBinding,
        *,
        capacity_reservation_id: str,
        deal_ref: Mapping[str, Any] | None = None,
        failure_reason: str | None = None,
    ) -> dict[str, Any] | None:
        """Release directly at the recorded site, without discovery fan-out."""
        binding = self.require_binding(binding)
        released = await self.site_client(binding.site_id).release(
            capacity_reservation_id=capacity_reservation_id,
            deal_ref=deal_ref,
            failure_reason=failure_reason,
        )
        if released is None:
            return None
        out = dict(released)
        out["site"] = binding.site_id
        return out

    async def reconcile_now(self) -> None:
        await self._run_reconcile(None)

    async def _on_delta(self, delta: CapacityDelta) -> None:
        await self._run_reconcile(delta)

    async def _run_reconcile(self, delta: CapacityDelta | None) -> None:
        projections = await self.projections()
        availability: dict[tuple[str, str], int] = {}
        for projection in projections:
            for row in projection.rows:
                resource_id = row.get("resource_id")
                available = row.get("available_units")
                if isinstance(resource_id, str) and resource_id.strip() and available is not None:
                    availability[(projection.site_id, resource_id)] = max(
                        int(available), 0
                    )
        await self._reconcile_hook(
            CapacityReconcileContext(
                projections=projections,
                availability=availability,
                delta=delta,
            )
        )

    async def poll_events(self, *, interval_seconds: float) -> None:
        """Tail every configured authority and reconcile at feed boundaries."""
        if interval_seconds <= 0:
            raise CapacityConfigurationError("poll interval must be positive")
        aggregate = self.client()
        await asyncio.gather(
            *(
                site_events_poller(
                    aggregate,
                    site_id,
                    self.site_client(site_id),
                    interval_seconds,
                    full_reconcile=self.reconcile_now,
                )
                for site_id in self.site_ids
            )
        )
