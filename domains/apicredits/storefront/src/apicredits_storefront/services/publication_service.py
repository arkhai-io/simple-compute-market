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
from market_resource_pools_contracts.backing import CapacityBacking
from registry_client import ListingRequest, UpdateListingRequest

from apicredits_storefront.listing_binding import (
    QuotaPoolUnavailable,
    api_credit_listing_binding,
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
) -> tuple[list[CreditListingSource], dict[str, PublicationBinding]]:
    """Each listing's status and durable binding, read for reconciliation."""
    sources: list[CreditListingSource] = []
    bindings: dict[str, PublicationBinding] = {}
    for row in rows:
        listing_id = str(row.get("listing_id") or "")
        binding = await api_credit_listing_binding(db, listing_id)
        if binding is None:
            raise CapacityBindingError("API-credit listing has no durable capacity binding")
        bindings[listing_id] = binding
        sources.append(
            CreditListingSource(
                listing_id=listing_id,
                status=str(row.get("status") or ""),
                closed_by=row.get("closed_by"),
                site_id=binding.site_id,
                resource_id=binding.source_id,
            )
        )
    return sources, bindings


async def close_token_listings_after_capacity_change(db: Any, availability: dict) -> list[str]:
    rows = await db.list_listings(status="open", limit=200)
    sources, bindings = await _credit_listing_sources(db, rows)
    ids = stale_open_credit_listing_ids(
        sources,
        availability=availability,
        judge=lambda source, available: bindings[source.listing_id].backing.judge(
            lambda: None, available
        ),
    )
    plan = ReconciliationPlan(
        close=tuple(BoundListing(listing_id, bindings[listing_id]) for listing_id in ids)
    )
    result = await build_publication_runtime(db).reconcile(plan)
    return list(result["closed"])


async def _source_backings(
    bindings: dict[str, PublicationBinding], db: Any
) -> dict[str, CapacityBacking | None]:
    """The backing each listing's pool declares now, or ``None`` if unreadable.

    Read once per site from its resource-pool projection; a site that cannot
    be read leaves its listings' backing unknown, which reopens nothing.
    """
    capacity = build_capacity_runtime(lambda: db)
    pools_by_site: dict[str, list[dict[str, Any]] | None] = {}
    backings: dict[str, CapacityBacking | None] = {}
    for listing_id, binding in bindings.items():
        if binding.site_id not in pools_by_site:
            try:
                projection = await capacity.site_client(
                    binding.site_id
                ).resource_pool_projection()
                pools_by_site[binding.site_id] = list(projection["resource_pools"])
            except Exception:  # noqa: BLE001 - an unreadable site reopens nothing
                pools_by_site[binding.site_id] = None
        pools = pools_by_site[binding.site_id]
        try:
            backings[listing_id] = (
                quota_pool(pools, resource_id=binding.source_id).declaration.backing
                if pools is not None
                else None
            )
        except QuotaPoolUnavailable:
            backings[listing_id] = None
    return backings


async def reopen_token_listings_after_capacity_change(db: Any, availability: dict) -> list[str]:
    rows = await db.list_listings(status="closed", limit=200)
    sources, bindings = await _credit_listing_sources(db, rows)
    if availability is None or not sources:
        return []
    source_backings = await _source_backings(bindings, db)

    def declared(listing_id: str) -> str | None:
        # A listing's backing is fixed for the life of its binding: one whose
        # pool now declares another, or cannot be read, is not reopened.
        source_backing = source_backings.get(listing_id)
        if source_backing is None:
            return "source_unconfirmed"
        if backing_changed(bindings[listing_id], source_backing):
            return "backing_changed"
        return None

    ids = reopenable_credit_listing_ids(
        sources,
        availability=availability,
        judge=lambda source, available: bindings[source.listing_id].backing.judge(
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
