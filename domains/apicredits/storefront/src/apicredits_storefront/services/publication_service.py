"""API-credit candidate hooks composed onto kit-owned publication."""
from __future__ import annotations

from typing import Any

from arkhai_apicredits.listings.reconciler import (
    CreditListingSource,
    reopenable_credit_listing_ids,
    stale_open_credit_listing_ids,
)
from market_capacity_publication import (
    BoundListing,
    CapacityBindingError,
    PublicationBinding,
    PublicationCandidate,
    PublicationRuntime,
    ReconciliationPlan,
    backing_changed,
)
from registry_client import ListingRequest, UpdateListingRequest

from apicredits_storefront.listing_binding import (
    BoundQuotaSource,
    QuotaPool,
    QuotaPoolUnavailable,
    api_credit_listing_binding,
    api_credit_listing_source,
    quota_pool,
)
from apicredits_storefront.services.capacity_client import build_capacity_runtime
from apicredits_storefront.utils.config import (
    BASE_URL_OVERRIDE,
    resolve_registry_authorities,
    settings,
)
from apicredits_storefront.utils.sqlite_client import get_sqlite_client


class ApiCreditPublicationHooks:
    def __init__(self, db: Any) -> None:
        self._db = db

    def validate_candidate(self, candidate: PublicationCandidate[dict[str, Any]]) -> None:
        listing_resource = candidate.payload.get("listing_resource") or {}
        if isinstance(listing_resource, str):
            import json
            listing_resource = json.loads(listing_resource)
        if listing_resource.get("offering_mode") != candidate.binding.offering_mode:
            raise CapacityBindingError("API-credit listing_resource mode differs from binding")

    async def binding_for_listing(
        self, listing_id: str
    ) -> PublicationBinding | None:
        return await api_credit_listing_binding(self._db, listing_id)


def _make_registry_client():
    from core_storefront.multi_registry_client import MultiRegistryClient
    import apicredits_storefront.container as container
    signer = container.resolved_marketplace_signer
    if signer is None:
        raise RuntimeError("storefront marketplace signer is not initialized")
    return MultiRegistryClient(
        list(settings.registry.urls), caller_role="seller",
        expected_registries=resolve_registry_authorities(),
        timeout=settings.registry.discovery_timeout, auth=settings.registry.auth,
        signer=signer,
    )


def build_publication_runtime(db: Any) -> PublicationRuntime[dict[str, Any]]:
    return PublicationRuntime(
        repository=db, hooks=ApiCreditPublicationHooks(db),
        enabled=settings.enable_registry_discovery,
        registry_urls=tuple(settings.registry.urls),
        registry_client_factory=_make_registry_client,
        listing_request_factory=ListingRequest,
        update_listing_request_factory=UpdateListingRequest,
        storefront_url=BASE_URL_OVERRIDE,
    )


async def _candidate(db: Any, row: dict[str, Any]) -> PublicationCandidate[dict[str, Any]]:
    binding = await ApiCreditPublicationHooks(db).binding_for_listing(str(row.get("listing_id") or ""))
    if binding is None:
        raise CapacityBindingError("API-credit listing has no durable capacity binding")
    return PublicationCandidate(str(row["listing_id"]), binding, row)


async def publish_order_to_registry(order: dict[str, Any]) -> dict[str, Any]:
    db = get_sqlite_client()
    return await build_publication_runtime(db).publish(await _candidate(db, order))


async def close_order(parameters: dict[str, Any] | None = None) -> dict[str, Any]:
    listing_id = (parameters or {}).get("listing_id")
    if not isinstance(listing_id, str) or not listing_id.strip():
        return {"status": "error", "message": "Missing listing_id for close_listing"}
    db = get_sqlite_client()
    binding = await ApiCreditPublicationHooks(db).binding_for_listing(listing_id)
    if binding is None:
        raise CapacityBindingError("API-credit listing has no durable capacity binding")
    return await build_publication_runtime(db).close(
        BoundListing(listing_id, binding), closed_by="seller"
    )


async def converge_registries(db: Any) -> dict[str, tuple[str, ...]]:
    """Repair every registry that missed a publish, close, or reopen.

    Run at the end of each capacity reconciliation, the storefront's recurring
    publication pass; a registry still unreachable stays recorded as diverged
    for the next one.
    """
    return await build_publication_runtime(db).converge()


async def _credit_listing_sources(
    db: Any, rows: list[dict[str, Any]]
) -> tuple[list[CreditListingSource], dict[str, BoundQuotaSource]]:
    """Each listing's status and durable binding, read for reconciliation."""
    sources: list[CreditListingSource] = []
    bound: dict[str, BoundQuotaSource] = {}
    for row in rows:
        listing_id = str(row.get("listing_id") or "")
        source = await api_credit_listing_source(db, listing_id)
        if source is None:
            raise CapacityBindingError("API-credit listing has no durable capacity binding")
        bound[listing_id] = source
        binding = source.binding
        sources.append(
            CreditListingSource(
                listing_id=listing_id,
                status=str(row.get("status") or ""),
                closed_by=row.get("closed_by"),
                site_id=binding.site_id,
                resource_id=binding.source_id,
            )
        )
    return sources, bound


async def close_token_listings_after_capacity_change(db: Any, availability: dict) -> list[str]:
    rows = await db.list_listings(status="open", limit=200)
    sources, bound = await _credit_listing_sources(db, rows)
    ids = stale_open_credit_listing_ids(
        sources,
        availability=availability,
        judge=lambda source, available: bound[source.listing_id].binding.backing.judge(
            lambda: None, available
        ),
    )
    plan = ReconciliationPlan(
        close=tuple(
            BoundListing(listing_id, bound[listing_id].binding) for listing_id in ids
        )
    )
    result = await build_publication_runtime(db).reconcile(plan)
    return list(result["closed"])


#: The listing's bound pool could not be read; nothing about its source is known.
SOURCE_UNCONFIRMED = "source_unconfirmed"
#: The bound pool no longer holds, enables, or advertises the listing's resource.
SOURCE_MISMATCH = "source_mismatch"
#: The bound pool declares a backing other than the listing's.
BACKING_CHANGED = "backing_changed"


async def _bound_pools(
    bound: dict[str, BoundQuotaSource], db: Any
) -> dict[str, QuotaPool | QuotaPoolUnavailable | None]:
    """Each listing's bound pool as its site declares it now.

    Read once per site from its resource-pool projection. A pool that cannot
    back the listing is its refusal; a site that cannot be read is ``None``,
    which says nothing about the source either way.
    """
    capacity = build_capacity_runtime(lambda: db)
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
                site_pools, resource_id=binding.source_id, pool_id=source.pool_id
            )
        except QuotaPoolUnavailable as exc:
            pools[listing_id] = exc
    return pools


def _source_problem(
    source: BoundQuotaSource, pool: QuotaPool | QuotaPoolUnavailable | None
) -> str | None:
    """Why ``source`` no longer matches its bound pool, or ``None`` if it does.

    A listing's backing is fixed for the life of its binding, so a pool that
    now declares another is a mismatch whatever else it declares.
    """
    if pool is None:
        return SOURCE_UNCONFIRMED
    if isinstance(pool, QuotaPoolUnavailable):
        return SOURCE_MISMATCH
    if backing_changed(source.binding, pool.declaration.backing):
        return BACKING_CHANGED
    return None


async def close_token_listings_on_source_mismatch(db: Any) -> list[str]:
    """Close every open listing its bound pool no longer supports.

    Source reconciliation applies to every listing, whatever its backing, and
    closes only on a definite mismatch: a site that cannot be read leaves its
    listings as they are. The reopen pass refuses the same mismatches, so a
    listing closed here reopens only once its bound pool supports it again,
    and never after a backing change.
    """
    rows = await db.list_listings(status="open", limit=200)
    _sources, bound = await _credit_listing_sources(db, rows)
    if not bound:
        return []
    pools = await _bound_pools(bound, db)
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
    result = await build_publication_runtime(db).reconcile(plan)
    return list(result["closed"])


async def reopen_token_listings_after_capacity_change(db: Any, availability: dict) -> list[str]:
    rows = await db.list_listings(status="closed", limit=200)
    sources, bound = await _credit_listing_sources(db, rows)
    if availability is None or not sources:
        return []
    pools = await _bound_pools(bound, db)

    def declared(listing_id: str) -> str | None:
        # A listing reopens only while its bound pool is known to support it.
        return _source_problem(bound[listing_id], pools[listing_id])

    ids = reopenable_credit_listing_ids(
        sources,
        availability=availability,
        judge=lambda source, available: bound[source.listing_id].binding.backing.judge(
            lambda: declared(source.listing_id), available
        ),
    )
    candidates = []
    for listing_id in ids:
        row = await db.load_listing(listing_id=listing_id)
        if row is not None:
            candidates.append(await _candidate(db, row))
    result = await build_publication_runtime(db).reconcile(
        ReconciliationPlan(reopen=tuple(candidates))
    )
    return list(result["reopened"])
