"""VM codecs and configuration composed onto kit-owned publication."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from core_storefront.stage_log import stage_event
from domains.vms.listings.models import Listing
from domains.vms.listings.reconciler import (
    closed_available_listing_ids,
    mark_derived_listings_closed,
    mark_derived_listings_open,
    stale_open_listing_ids,
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

from market_storefront.services.capacity_client import capacity_binding_for_listing
from market_storefront.utils.config import BASE_URL_OVERRIDE, settings


class VmPublicationHooks:
    """VM candidate codec and durable derived-listing binding lookup."""

    def __init__(self, sqlite_client: Any) -> None:
        self._db = sqlite_client

    def validate_candidate(
        self, candidate: PublicationCandidate[Listing]
    ) -> None:
        mode = candidate.payload.offer_resource.virtualization_type
        offering_mode = mode.value if hasattr(mode, "value") else str(mode or "")
        if offering_mode != candidate.binding.offering_mode:
            raise CapacityBindingError(
                "VM offer virtualization_type does not match its capacity binding"
            )

    async def binding_for_listing(self, listing_id: str) -> CapacityBinding | None:
        try:
            return await capacity_binding_for_listing(self._db, listing_id)
        except RuntimeError:
            return None


def _make_registry_client():
    from core_storefront.multi_registry_client import MultiRegistryClient
    import market_storefront.container as container
    from market_storefront.utils.config import get_registry_authorities

    signer = container.resolved_marketplace_signer
    if signer is None:
        raise RuntimeError("marketplace signer is not initialized")
    return MultiRegistryClient(
        list(settings.registry.urls),
        timeout=settings.registry.discovery_timeout,
        auth=settings.registry.auth,
        signer=signer,
        caller_role="seller",
        expected_registries=get_registry_authorities(),
    )


def build_publication_runtime(
    sqlite_client: Any,
    *,
    registry_client_factory: Callable[[], Any],
) -> PublicationRuntime[Listing]:
    """Compose VM schema/persistence hooks with the injected registry transport."""
    return PublicationRuntime(
        repository=sqlite_client,
        hooks=VmPublicationHooks(sqlite_client),
        enabled=settings.enable_registry_discovery,
        registry_urls=tuple(settings.registry.urls),
        registry_client_factory=registry_client_factory,
        listing_request_factory=ListingRequest,
        update_listing_request_factory=UpdateListingRequest,
        storefront_url=BASE_URL_OVERRIDE,
        on_published=_record_listing_published_stage_event,
    )


async def _candidate(sqlite_client: Any, value: Listing | dict) -> PublicationCandidate[Listing]:
    listing = Listing.model_validate(
        value.model_dump(mode="python") if isinstance(value, Listing) else value
    )
    binding = await capacity_binding_for_listing(sqlite_client, listing.listing_id)
    return PublicationCandidate(listing.listing_id, binding, listing)


async def publish_order_to_registry(
    order: Listing | dict,
    *,
    sqlite_client: Any,
) -> dict[str, Any]:
    """Publish a domain-validated, durably bound VM candidate."""
    return await build_publication_runtime(
        sqlite_client,
        registry_client_factory=_make_registry_client,
    ).publish(await _candidate(sqlite_client, order))


async def close_order(
    parameters: dict[str, Any] | None = None,
    *,
    sqlite_client: Any,
) -> dict[str, Any]:
    """Close a VM listing through the kit lifecycle using its exact binding."""
    listing_id = (parameters or {}).get("listing_id")
    if not isinstance(listing_id, str) or not listing_id.strip():
        return {"status": "error", "message": "Missing listing_id for close_listing"}
    binding = await capacity_binding_for_listing(sqlite_client, listing_id)
    return await build_publication_runtime(
        sqlite_client,
        registry_client_factory=_make_registry_client,
    ).close(BoundListing(listing_id, binding))


async def close_stale_compute_listings_after_capacity_change(
    db_path: str,
    *,
    sqlite_client: Any,
    home_site: str,
    configured_site_count: int,
    member_availability: dict[tuple[str, str], int] | None = None,
    site_pool_projection: dict[str, list[dict]] | None = None,
    site_capacity_buckets: dict[str, list[dict]] | None = None,
) -> list[str]:
    """Let VM semantics choose stale candidates; kit executes each close."""
    ids = stale_open_listing_ids(
        db_path,
        home_site=home_site,
        configured_site_count=configured_site_count,
        member_availability=member_availability,
        site_pool_projection=site_pool_projection,
        site_capacity_buckets=site_capacity_buckets,
    )
    bound_items: list[BoundListing] = []
    for listing_id in ids:
        bound_items.append(
            BoundListing(
                listing_id,
                await capacity_binding_for_listing(sqlite_client, listing_id),
            )
        )
    bound = tuple(bound_items)
    result = await build_publication_runtime(
        sqlite_client,
        registry_client_factory=_make_registry_client,
    ).reconcile(ReconciliationPlan(close=bound))
    closed = list(result["closed"])
    mark_derived_listings_closed(
        db_path,
        closed,
        home_site=home_site,
        configured_site_count=configured_site_count,
    )
    return closed


async def reopen_available_compute_listings_after_capacity_change(
    db_path: str,
    *,
    sqlite_client: Any,
    home_site: str,
    member_availability: dict[tuple[str, str], int] | None = None,
    site_pool_projection: dict[str, list[dict]] | None = None,
    site_capacity_buckets: dict[str, list[dict]] | None = None,
) -> list[str]:
    """Let VM semantics choose available candidates; kit executes reopen/publish."""
    if member_availability is None:
        return []
    ids = closed_available_listing_ids(
        db_path,
        home_site=home_site,
        member_availability=member_availability,
        site_pool_projection=site_pool_projection,
        site_capacity_buckets=site_capacity_buckets,
    )
    candidates: list[PublicationCandidate[Listing]] = []
    for listing_id in ids:
        row = await sqlite_client.load_listing(listing_id=listing_id)
        if row is None:
            continue
        candidates.append(await _candidate(sqlite_client, row))
    result = await build_publication_runtime(
        sqlite_client,
        registry_client_factory=_make_registry_client,
    ).reconcile(ReconciliationPlan(reopen=tuple(candidates)))
    reopened = list(result["reopened"])
    mark_derived_listings_open(db_path, reopened)
    return reopened


def _record_listing_published_stage_event(
    *,
    listing_id: str,
    storefront_url: str,
    seller_principal: dict[str, Any],
    offer_resource: dict[str, Any],
    accepted_escrows: list[dict[str, Any]],
    settlement_options: list[dict[str, Any]],
    demands: list[dict[str, Any]],
    max_duration_seconds: int | None,
) -> None:
    stage_event(
        "discovery",
        "order_published",
        order_id=listing_id,
        agent_url=storefront_url,
        seller_principal=seller_principal,
        offer=offer_resource,
        accepted_escrows=accepted_escrows,
        settlement_options=settlement_options,
        demands=demands,
        max_duration_seconds=max_duration_seconds,
    )
