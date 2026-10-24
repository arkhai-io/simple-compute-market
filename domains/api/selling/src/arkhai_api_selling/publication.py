"""Publishing quota-backed listings and reconciling them with their quota authorities."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from market_capacity_publication import (
    BoundListing,
    CapacityBindingError,
    CapacityReconcileContext,
    PublicationBinding,
    PublicationCandidate,
    PublicationRuntime,
    ReconciliationPlan,
    backing_changed,
)
from registry_client import ListingRequest, UpdateListingRequest

from arkhai_api_selling.capacity import QuotaCapacity, Reconcile, SQLiteClientFactory
from arkhai_api_selling.contributions import SellingContributions
from arkhai_api_selling.pricing import domain_listing_resource
from arkhai_api_selling.quota_listing import (
    BoundQuotaSource,
    QuotaListingSource,
    QuotaPool,
    QuotaPoolUnavailable,
    listing_binding,
    listing_source,
    quota_pool,
    reopenable_listing_ids,
    stale_open_listing_ids,
)

#: The listing's bound pool could not be read; nothing about its source is known.
SOURCE_UNCONFIRMED = "source_unconfirmed"
#: The bound pool no longer holds, enables, or advertises the listing's resource.
SOURCE_MISMATCH = "source_mismatch"
#: The bound pool declares a backing other than the listing's.
BACKING_CHANGED = "backing_changed"

LISTING_PAGE = 200

_CONSUMING = frozenset({"reserved", "committed", "lease_truncated"})
_MIXED = frozenset({"capacity_changed"})


class PublicationRefused(CapacityBindingError):
    """A domain's publication guard refuses the listing."""


def publication_refusal(
    contributions: SellingContributions, listing_resource: Mapping[str, Any]
) -> str | None:
    """The first of the domain's publication guards to refuse ``listing_resource``, or None."""
    for guard in contributions.publication_guards:
        reason = guard(listing_resource)
        if reason is not None:
            return reason
    return None


@dataclass(frozen=True)
class RegistryPublication:
    """Where and whether the storefront publishes, as configured when a pass runs."""

    enabled: bool
    registry_urls: tuple[str, ...]
    storefront_url: str
    client_factory: Callable[[], Any]


class QuotaPublicationHooks:
    def __init__(self, contributions: SellingContributions, db: Any) -> None:
        self._contributions = contributions
        self._db = db

    def validate_candidate(self, candidate: PublicationCandidate[dict[str, Any]]) -> None:
        noun = self._contributions.refusal_noun
        resource = domain_listing_resource(
            self._contributions, candidate.payload.get("listing_resource")
        )
        if resource is None:
            raise CapacityBindingError(f"{noun} listing_resource is not the domain's")
        if self._contributions.offering_mode != candidate.binding.offering_mode:
            raise CapacityBindingError(f"{noun} listing_resource mode differs from binding")
        reason = publication_refusal(self._contributions, resource)
        if reason is not None:
            raise PublicationRefused(reason)

    async def binding_for_listing(self, listing_id: str) -> PublicationBinding | None:
        return await listing_binding(self._db, listing_id)


async def all_listings(db: Any, *, status: str) -> list[dict[str, Any]]:
    """Every listing with ``status``, each read once.

    Pages run over every status by the store's keyset, which no write changes, so a
    pass that changes statuses while reading neither repeats nor skips a listing.
    """
    rows: list[dict[str, Any]] = []
    before: tuple[str, str] | None = None
    while True:
        page = await db.list_listings(limit=LISTING_PAGE, before=before)
        rows.extend(page)
        if len(page) < LISTING_PAGE:
            break
        before = (page[-1]["created_at"], page[-1]["listing_id"])
    return [row for row in rows if row.get("status") == status]


class QuotaPublication:
    """Publication, closure, and reconciliation of one storefront's quota-backed listings."""

    def __init__(
        self,
        contributions: SellingContributions,
        *,
        capacity: QuotaCapacity,
        registry: Callable[[], RegistryPublication],
    ) -> None:
        self._contributions = contributions
        self._capacity = capacity
        self._registry = registry

    def runtime(self, db: Any) -> PublicationRuntime[dict[str, Any]]:
        registry = self._registry()
        return PublicationRuntime(
            repository=db,
            hooks=QuotaPublicationHooks(self._contributions, db),
            enabled=registry.enabled,
            registry_urls=registry.registry_urls,
            registry_client_factory=registry.client_factory,
            listing_request_factory=ListingRequest,
            update_listing_request_factory=UpdateListingRequest,
            storefront_url=registry.storefront_url,
        )

    async def _candidate(
        self, db: Any, row: Mapping[str, Any]
    ) -> PublicationCandidate[dict[str, Any]]:
        listing_id = str(row.get("listing_id") or "")
        binding = await listing_binding(db, listing_id)
        if binding is None:
            raise CapacityBindingError(
                f"{self._contributions.refusal_noun} listing has no durable capacity binding"
            )
        return PublicationCandidate(str(row["listing_id"]), binding, dict(row))

    def refusal(self, listing: Mapping[str, Any]) -> str | None:
        """Why the domain's publication guards refuse a stored listing, or None."""
        resource = domain_listing_resource(self._contributions, listing.get("listing_resource"))
        return None if resource is None else publication_refusal(self._contributions, resource)

    async def publish(self, db: Any, listing: Mapping[str, Any]) -> dict[str, Any]:
        return await self.runtime(db).publish(await self._candidate(db, listing))

    async def close(self, db: Any, listing_id: Any) -> dict[str, Any]:
        """Close the listing as its seller."""
        if not isinstance(listing_id, str) or not listing_id.strip():
            return {"status": "error", "message": "Missing listing_id for close_listing"}
        binding = await listing_binding(db, listing_id)
        if binding is None:
            raise CapacityBindingError(
                f"{self._contributions.refusal_noun} listing has no durable capacity binding"
            )
        return await self.runtime(db).close(BoundListing(listing_id, binding), closed_by="seller")

    async def converge(self, db: Any) -> dict[str, tuple[str, ...]]:
        """Repair every registry that missed a publish, close, or reopen.

        The repair republishes an open listing without the publication hook, so
        an open listing the domain's guards refuse is left out and reported
        unrepaired: it is never republished.
        """
        runtime = self.runtime(db)
        repairable, refused = [], []
        for divergence in await runtime.publication_divergence():
            listing = (
                await db.load_listing(listing_id=divergence.listing_id)
                if divergence.listing_status != "closed"
                else None
            )
            if listing is not None and self.refusal(listing) is not None:
                refused.append(divergence.listing_id)
            else:
                repairable.append(divergence)
        result = await runtime.converge(repairable)
        return {**result, "unrepaired": (*result["unrepaired"], *refused)}

    async def _sources(
        self, db: Any, rows: list[dict[str, Any]]
    ) -> tuple[list[QuotaListingSource], dict[str, BoundQuotaSource]]:
        """Each listing's status and durable binding, read for reconciliation."""
        sources: list[QuotaListingSource] = []
        bound: dict[str, BoundQuotaSource] = {}
        for row in rows:
            listing_id = str(row.get("listing_id") or "")
            source = await listing_source(db, listing_id)
            if source is None:
                raise CapacityBindingError(
                    f"{self._contributions.refusal_noun} listing has no durable capacity binding"
                )
            bound[listing_id] = source
            sources.append(
                QuotaListingSource(
                    listing_id=listing_id,
                    status=str(row.get("status") or ""),
                    closed_by=row.get("closed_by"),
                    site_id=source.binding.site_id,
                    resource_id=source.binding.source_id,
                )
            )
        return sources, bound

    async def close_after_capacity_change(self, db: Any, availability: dict) -> list[str]:
        sources, bound = await self._sources(db, await all_listings(db, status="open"))
        ids = stale_open_listing_ids(
            sources,
            availability=availability,
            judge=lambda source, available: bound[source.listing_id].binding.backing.judge(
                lambda: None, available
            ),
        )
        plan = ReconciliationPlan(
            close=tuple(BoundListing(listing_id, bound[listing_id].binding) for listing_id in ids)
        )
        result = await self.runtime(db).reconcile(plan)
        return list(result["closed"])

    async def _bound_pools(
        self, bound: dict[str, BoundQuotaSource], db: Any
    ) -> dict[str, QuotaPool | QuotaPoolUnavailable | None]:
        """Each listing's bound pool as its site declares it now; ``None`` where the site cannot be read."""
        capacity = self._capacity.runtime(lambda: db)
        pools_by_site: dict[str, list[dict[str, Any]] | None] = {}
        pools: dict[str, QuotaPool | QuotaPoolUnavailable | None] = {}
        for listing_id, source in bound.items():
            binding = source.binding
            if binding.site_id not in pools_by_site:
                try:
                    projection = await capacity.site_client(
                        binding.site_id
                    ).resource_pool_projection()
                    pools_by_site[binding.site_id] = list(projection["resource_pools"])
                except Exception:  # noqa: BLE001 - an unreadable site confirms nothing
                    pools_by_site[binding.site_id] = None
            site_pools = pools_by_site[binding.site_id]
            if site_pools is None:
                pools[listing_id] = None
                continue
            try:
                pools[listing_id] = quota_pool(
                    self._contributions,
                    site_pools,
                    resource_id=binding.source_id,
                    pool_id=source.pool_id,
                )
            except QuotaPoolUnavailable as exc:
                pools[listing_id] = exc
        return pools

    async def close_on_source_mismatch(self, db: Any) -> list[str]:
        """Close every open listing its bound pool definitely no longer supports; an unreadable site closes nothing."""
        _sources, bound = await self._sources(db, await all_listings(db, status="open"))
        if not bound:
            return []
        pools = await self._bound_pools(bound, db)
        plan = ReconciliationPlan(
            close=tuple(
                BoundListing(listing_id, source.binding)
                for listing_id, source in bound.items()
                if _source_problem(source, pools[listing_id])
                in (SOURCE_MISMATCH, BACKING_CHANGED)
            )
        )
        if not plan.close:
            return []
        result = await self.runtime(db).reconcile(plan)
        return list(result["closed"])

    async def reopen_after_capacity_change(self, db: Any, availability: dict) -> list[str]:
        sources, bound = await self._sources(db, await all_listings(db, status="closed"))
        if availability is None or not sources:
            return []
        pools = await self._bound_pools(bound, db)

        def declared(listing_id: str) -> str | None:
            # A listing reopens only while its bound pool is known to support it.
            return _source_problem(bound[listing_id], pools[listing_id])

        ids = reopenable_listing_ids(
            sources,
            availability=availability,
            judge=lambda source, available: bound[source.listing_id].binding.backing.judge(
                lambda: declared(source.listing_id), available
            ),
        )
        candidates = []
        for listing_id in ids:
            row = await db.load_listing(listing_id=listing_id)
            if row is not None and self.refusal(row) is None:
                candidates.append(await self._candidate(db, row))
        result = await self.runtime(db).reconcile(ReconciliationPlan(reopen=tuple(candidates)))
        return list(result["reopened"])

    def reconciler(self, sqlite_client_factory: SQLiteClientFactory) -> Reconcile:
        """The pass each capacity event, or a resync, runs."""

        async def reconcile(context: CapacityReconcileContext) -> None:
            delta = context.delta
            db = sqlite_client_factory()
            # Every pass: a pool move changes no capacity and arrives as a release.
            await self.close_on_source_mismatch(db)
            if delta is None or delta.kind in _CONSUMING or delta.kind in _MIXED:
                await self.close_after_capacity_change(db, dict(context.availability))
            if delta is None or delta.kind == "released" or delta.kind in _MIXED:
                await self.reopen_after_capacity_change(db, dict(context.availability))
            await self.converge(db)

        return reconcile


def _source_problem(
    source: BoundQuotaSource, pool: QuotaPool | QuotaPoolUnavailable | None
) -> str | None:
    """Why ``source`` no longer matches its bound pool, or ``None``; a changed backing always mismatches."""
    if pool is None:
        return SOURCE_UNCONFIRMED
    if isinstance(pool, QuotaPoolUnavailable):
        return SOURCE_MISMATCH
    if backing_changed(source.binding, pool.declaration.backing):
        return BACKING_CHANGED
    return None
