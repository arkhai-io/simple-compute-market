"""Storefront publication and registry-close orchestration."""

from __future__ import annotations

import logging
from typing import Any

from core_storefront.registry_publication import (
    close_listing_in_registries,
    publish_listing_to_registries,
)
from core_storefront.stage_log import stage_event
from domains.vms.listings.models import Listing
from domains.vms.listings.reconciler import (
    mark_derived_listings_closed,
    stale_open_listing_ids,
)
from market_storefront.utils.config import BASE_URL_OVERRIDE, settings
from market_storefront.utils.sqlite_client import get_sqlite_client
from registry_client import ListingRequest, UpdateListingRequest

logger = logging.getLogger(__name__)


async def close_order(parameters: dict[str, Any] | None = None) -> dict[str, Any]:
    """Close an order locally and in the registry when registry discovery is enabled."""
    parameters = parameters or {}
    order_id = parameters.get("listing_id")
    if not isinstance(order_id, str) or not order_id.strip():
        return {"status": "error", "message": "Missing listing_id for close_listing"}

    try:
        sqlite_client = get_sqlite_client()
        await sqlite_client.update_listing(
            listing_id=order_id,
            status="closed",
        )
    except Exception as exc:
        logger.warning("[LOCAL DB] Failed to update order %s as closed: %s", order_id, exc)

    return await close_listing_in_registries(
        order_id,
        enabled=settings.enable_registry_discovery,
        registry_client_factory=_make_registry_client,
        update_listing_request_factory=UpdateListingRequest,
        private_key=settings.wallet.private_key,
        select_target_registries=_registries_to_target,
        record_publications=_record_publications,
    )


async def close_stale_compute_listings_after_capacity_change(
    db_path: str,
    *,
    member_availability: dict[tuple[str | None, str], int] | None = None,
) -> list[str]:
    """Close open derived compute listings whose GPU slice no longer fits.

    ``member_availability`` carries the aggregated site snapshots keyed
    ``(site, resource_id)``. ``None`` (availability unknown — the
    authority was unreachable) closes nothing: members are assumed
    fully available, and the next delta/reconcile converges.
    """
    closed_listing_ids: list[str] = []
    for listing_id in stale_open_listing_ids(
        db_path, member_availability=member_availability,
    ):
        result = await close_order({"listing_id": listing_id})
        if str(result.get("status", "?")) in ("closed", "skipped", "queued"):
            closed_listing_ids.append(listing_id)
            continue
        row = await get_sqlite_client().load_listing(listing_id=listing_id)
        if row and row.get("status") == "closed":
            closed_listing_ids.append(listing_id)
    mark_derived_listings_closed(db_path, closed_listing_ids)
    return closed_listing_ids


async def reopen_available_compute_listings_after_capacity_change(
    db_path: str,
    *,
    member_availability: dict[tuple[str | None, str], int] | None = None,
) -> list[str]:
    """Reopen closed derived listings whose slice fits capacity again.

    The freeing counterpart of the close path above, run for "released"
    capacity deltas — same mechanics as the admin fulfillment-event
    handlers' reopen step. ``None`` availability (authority unreachable)
    reopens nothing: with no consumption information everything would
    look free, and reopening on ignorance over-sells.
    """
    from domains.vms.listings.reconciler import (
        closed_available_listing_ids,
        mark_derived_listings_open,
    )

    if member_availability is None:
        return []
    reopened_listing_ids = closed_available_listing_ids(
        db_path, member_availability=member_availability,
    )
    for listing_id in reopened_listing_ids:
        await get_sqlite_client().update_listing(listing_id=listing_id, status="open")
    mark_derived_listings_open(db_path, reopened_listing_ids)
    return reopened_listing_ids


def _make_registry_client() -> "MultiRegistryClient":
    """Construct a multi-registry client wrapping every configured URL."""
    from market_storefront.utils.multi_registry_client import MultiRegistryClient

    urls = list(settings.registry.urls) if settings.registry.urls else ["http://localhost:8080"]
    return MultiRegistryClient(
        urls,
        timeout=settings.registry.discovery_timeout,
        auth=settings.registry.auth,
    )


async def publish_order_to_registry(order: Listing | dict) -> dict[str, Any]:
    """Publish a new listing to every configured registry."""
    return await publish_listing_to_registries(
        order,
        enabled=settings.enable_registry_discovery,
        registry_client_factory=_make_registry_client,
        listing_request_factory=ListingRequest,
        private_key=settings.wallet.private_key,
        storefront_url=BASE_URL_OVERRIDE,
        record_publications=_record_publications,
        on_published=_record_listing_published_stage_event,
    )


def _record_listing_published_stage_event(
    *,
    listing_id: str,
    offer_resource: dict[str, Any],
    accepted_escrows: list[dict[str, Any]],
    demands: list[dict[str, Any]],
    max_duration_seconds: int | None,
) -> None:
    stage_event(
        "discovery", "order_published",
        order_id=listing_id,
        agent_url=BASE_URL_OVERRIDE,
        offer=offer_resource,
        accepted_escrows=accepted_escrows,
        demands=demands,
        max_duration_seconds=max_duration_seconds,
    )


async def _registries_to_target(
    listing_id: str, fallback_urls: list[str],
) -> list[str]:
    """Return registry URLs that should receive update/delete for ``listing_id``."""
    try:
        sqlite_client = get_sqlite_client()
        pubs = await sqlite_client.load_publications(listing_id=listing_id)
    except Exception:
        return list(fallback_urls)
    active = [p["registry_url"] for p in pubs if p.get("status") != "unpublished"]
    return active if active else list(fallback_urls)


async def _record_publications(
    listing_id: str, results: list[dict[str, Any]],
) -> None:
    """Persist one ``publications`` row per per-registry write result."""
    try:
        sqlite_client = get_sqlite_client()
    except Exception:
        return
    for result in results:
        payload = result.get("payload") or {}
        status = "published" if result.get("success") else "failed"
        try:
            await sqlite_client.upsert_publication(
                listing_id=listing_id,
                registry_url=result["registry_url"],
                payload=payload,
                status=status,
                registry_assigned_id=result.get("registry_assigned_id"),
                last_error=result.get("error"),
            )
        except Exception as exc:
            logger.warning(
                "[PUBLICATIONS] Failed to record publication for %s @ %s: %s",
                listing_id, result.get("registry_url"), exc,
            )
