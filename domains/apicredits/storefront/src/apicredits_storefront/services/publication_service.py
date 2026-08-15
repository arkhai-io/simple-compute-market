"""API-credit candidate hooks composed onto kit-owned publication."""
from __future__ import annotations

from typing import Any

from domains.apicredits.listings.reconciler import (
    reopenable_credit_listing_ids,
    stale_open_credit_listing_ids,
)
from market_capacity_publication import (
    BoundListing,
    CapacityBinding,
    CapacityBindingError,
    PublicationCandidate,
    PublicationRuntime,
    ReconciliationPlan,
)
from registry_client import ListingRequest, UpdateListingRequest

from apicredits_storefront.services.capacity_client import capacity_binding_from_offer
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
        offer = candidate.payload.get("offer_resource") or {}
        if isinstance(offer, str):
            import json
            offer = json.loads(offer)
        if offer.get("offering_mode") != candidate.binding.offering_mode:
            raise CapacityBindingError("API-credit offer mode differs from binding")

    async def binding_for_listing(self, listing_id: str) -> CapacityBinding | None:
        row = await self._db.load_listing(listing_id=listing_id)
        if row is None:
            return None
        try:
            return capacity_binding_from_offer(row.get("offer_resource") or {})
        except (ValueError, TypeError):
            return None


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
    return await build_publication_runtime(db).close(BoundListing(listing_id, binding))


async def close_token_listings_after_capacity_change(db: Any, availability: dict) -> list[str]:
    rows = await db.list_listings(status="open", limit=200)
    ids = stale_open_credit_listing_ids(rows, availability=availability)
    hooks = ApiCreditPublicationHooks(db)
    closed = []
    for listing_id in ids:
        binding = await hooks.binding_for_listing(listing_id)
        if binding is None:
            raise CapacityBindingError("API-credit listing has no durable capacity binding")
        closed.append(BoundListing(listing_id, binding))
    plan = ReconciliationPlan(close=tuple(closed))
    result = await build_publication_runtime(db).reconcile(plan)
    return list(result["closed"])


async def reopen_token_listings_after_capacity_change(db: Any, availability: dict) -> list[str]:
    rows = await db.list_listings(status="closed", limit=200)
    ids = reopenable_credit_listing_ids(rows, availability=availability)
    candidates = []
    for listing_id in ids:
        row = await db.load_listing(listing_id=listing_id)
        if row is not None:
            candidates.append(await _candidate(db, row))
    result = await build_publication_runtime(db).reconcile(
        ReconciliationPlan(reopen=tuple(candidates))
    )
    return list(result["reopened"])
