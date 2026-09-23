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
from typing import Any, ClassVar, Literal, Protocol

from core_storefront.aggregation import AggregateCapacityClient, PlacementPolicy
from core_storefront.capacity import CapacityDelta
from market_site_client import SiteCapacityClient

from .capacity_remote import (
    SiteEventCycle,
    SiteEventPreview,
    drain_site_events_once,
    preview_site_events,
    site_event_cursor,
    site_events_poller,
)


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
class _ListingIdentity:
    """A listing's common identity: origin site, offering mode, and source.

    ``site_id`` is the site the listing originates from, which every listing
    has. ``source_id`` is domain-owned and opaque to this kit (pool ID, quota
    resource ID, Physical Resource ID, or another stable candidate identity).
    ``offering_mode`` is the exact mode the listing advertises. Whether the
    origin site admits reservations is carried by the concrete class, never by
    a field a reader could leave unset.
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
class CapacityBinding(_ListingIdentity):
    """A listing whose origin site is an admission authority.

    Reservation, commit, release, scheduling, and dispatch accept only this
    class. ``UnbackedBinding`` is a sibling rather than a subclass, so an
    ``isinstance`` check against this class is exactly the backed-only check.
    """

    capacity_backing: ClassVar[Literal["backed"]] = "backed"


@dataclass(frozen=True, slots=True)
class UnbackedBinding(_ListingIdentity):
    """A listing with no admission authority behind it.

    It has an origin site and a source like any other listing, and nothing can
    be reserved against it. Dataclass equality compares classes, so it never
    equals a ``CapacityBinding`` over the same fields: a durable comparison
    catches a changed backing without a separate check.
    """

    capacity_backing: ClassVar[Literal["unbacked"]] = "unbacked"


PublicationBinding = CapacityBinding | UnbackedBinding

_BINDING_BY_BACKING: Mapping[str, type[CapacityBinding] | type[UnbackedBinding]] = {
    CapacityBinding.capacity_backing: CapacityBinding,
    UnbackedBinding.capacity_backing: UnbackedBinding,
}


def publication_binding(
    *,
    capacity_backing: str,
    site_id: str,
    offering_mode: str,
    source_id: str,
) -> PublicationBinding:
    """Load a binding from its durable backing value, refusing any other value.

    There is no default: a value this kit does not recognize is a durable-state
    error, not a listing to classify.
    """
    binding_type = _BINDING_BY_BACKING.get(capacity_backing)
    if binding_type is None:
        raise CapacityBindingError(
            f"unknown capacity_backing {capacity_backing!r}; expected one of "
            f"{sorted(_BINDING_BY_BACKING)}"
        )
    return binding_type(site_id, offering_mode, source_id)


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
        # Every capacity effect passes through here. An unbacked listing has no
        # admission authority, so a reservation against it would be a record
        # with nothing behind it; refuse before any site call.
        if not isinstance(binding, CapacityBinding):
            raise CapacityBindingError(
                "capacity operations require a capacity-backed listing binding"
            )
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
        failure_message: str | None = None,
    ) -> dict[str, Any] | None:
        """Release directly at the recorded site, without discovery fan-out."""
        binding = self.require_binding(binding)
        released = await self.site_client(binding.site_id).release(
            capacity_reservation_id=capacity_reservation_id,
            deal_ref=deal_ref,
            failure_reason=failure_reason,
            failure_message=failure_message,
        )
        if released is None:
            return None
        out = dict(released)
        out["site"] = binding.site_id
        return out

    async def truncate_lease(
        self,
        binding: CapacityBinding,
        *,
        capacity_reservation_id: str,
        lease_end_utc: str,
    ) -> dict[str, Any] | None:
        """Truncate only at the durable site binding."""
        binding = self.require_binding(binding)
        truncated = await self.site_client(binding.site_id).truncate_lease(
            capacity_reservation_id=capacity_reservation_id,
            lease_end_utc=lease_end_utc,
        )
        if truncated is None:
            return None
        out = dict(truncated)
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

    async def preview_events_once(self, site_id: str) -> SiteEventPreview:
        """Report what one site's next event cycle would do, changing nothing.

        The read half of stepping a held loop: a caller can see the pending
        events and the feed head before deciding to apply them, the same way
        the evaluate routes dry-run a negotiation or a settlement.
        """
        return await preview_site_events(
            self.site_client(site_id),
            site_event_cursor(site_id),
        )

    async def drain_events_once(self, site_id: str) -> SiteEventCycle:
        """Run exactly one event cycle for one site and report what it did.

        Addresses the same cursor the running poller holds, because a second
        position would replay or skip. Intended to be called while the loop is
        held: the pause guarantees a cycle either runs completely or never
        starts, so an advance has the feed to itself.
        """
        # `site_client` already fails closed on an unconfigured site, so
        # there is no second guard here saying the same thing differently.
        return await drain_site_events_once(
            self.client(),
            self.site_client(site_id),
            site_event_cursor(site_id),
            full_reconcile=self.reconcile_now,
        )

    async def poll_events(
        self,
        *,
        interval_seconds: float,
        paused: Callable[[str], Callable[[], bool]] | None = None,
    ) -> None:
        """Tail every configured authority and reconcile at feed boundaries.

        ``paused`` is a factory, not a predicate: it receives a site id and
        returns that site's gate. The pollers run concurrently and each holds
        its own feed position, so one site being held must not hold the others
        -- a single shared predicate could only stop all of them together.
        Supplying the gate per site keeps the naming with the caller, which is
        the only party that knows what each loop is registered as.
        """
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
                    paused=paused(site_id) if paused is not None else None,
                )
                for site_id in self.site_ids
            )
        )
