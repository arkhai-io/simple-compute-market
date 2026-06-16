"""Publication and quota-backed listing reconciliation.

Registry fan-out is the shared core machinery
(``core_storefront.registry_publication`` over the hoisted
``MultiRegistryClient``); the domain part is the reconcile rule: a
token listing derives from a quota resource and closes on exhaustion /
reopens on replenishment, driven by capacity deltas from the tokens
service's event feed.
"""

from __future__ import annotations

import logging
from typing import Any

from core_storefront.registry_publication import (
    close_listing_in_registries,
    publish_listing_to_registries,
)
from core_storefront.stage_log import stage_event
from domains.apitokens.listings.reconciler import (
    reopenable_token_listing_ids,
    stale_open_token_listing_ids,
)
from registry_client import ListingRequest, UpdateListingRequest

from apitokens_storefront.utils.config import BASE_URL_OVERRIDE, settings
from apitokens_storefront.utils.sqlite_client import get_sqlite_client

logger = logging.getLogger(__name__)


def _make_registry_client():
    from core_storefront.multi_registry_client import MultiRegistryClient

    urls = (
        list(settings.registry.urls)
        if settings.registry.urls else ["http://localhost:8080"]
    )
    return MultiRegistryClient(
        urls,
        timeout=settings.registry.discovery_timeout,
        auth=settings.registry.auth,
    )


async def publish_order_to_registry(order: dict[str, Any]) -> dict[str, Any]:
    """Publish a listing to every configured registry."""
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


async def close_order(parameters: dict[str, Any] | None = None) -> dict[str, Any]:
    """Close a listing locally and in the registries."""
    parameters = parameters or {}
    listing_id = parameters.get("listing_id")
    if not isinstance(listing_id, str) or not listing_id.strip():
        return {"status": "error", "message": "Missing listing_id for close_listing"}

    try:
        await get_sqlite_client().update_listing(
            listing_id=listing_id, status="closed",
        )
    except Exception as exc:
        logger.warning(
            "[LOCAL DB] Failed to update listing %s as closed: %s",
            listing_id, exc,
        )

    return await close_listing_in_registries(
        listing_id,
        enabled=settings.enable_registry_discovery,
        registry_client_factory=_make_registry_client,
        update_listing_request_factory=UpdateListingRequest,
        private_key=settings.wallet.private_key,
        select_target_registries=_registries_to_target,
        record_publications=_record_publications,
    )


async def close_token_listings_after_capacity_change(
    db: Any,
    capacity: Any,
) -> list[str]:
    """Close open token listings whose quota resource is exhausted."""
    from apitokens_storefront.services.capacity_client import availability_view

    try:
        availability = await availability_view(capacity)
    except Exception as exc:
        logger.warning(
            "[CAPACITY] Quota snapshot unavailable; closing nothing: %s", exc,
        )
        return []
    rows = await db.list_listings(status="open", limit=200)
    closed: list[str] = []
    for listing_id in stale_open_token_listing_ids(rows, availability=availability):
        result = await close_order({"listing_id": listing_id})
        if str(result.get("status", "?")) in ("closed", "skipped", "queued"):
            closed.append(listing_id)
            continue
        row = await db.load_listing(listing_id=listing_id)
        if row and row.get("status") == "closed":
            closed.append(listing_id)
    return closed


async def reopen_token_listings_after_capacity_change(
    db: Any,
    capacity: Any,
) -> list[str]:
    """Reopen closed token listings whose quota has units again."""
    from apitokens_storefront.services.capacity_client import availability_view

    try:
        availability = await availability_view(capacity)
    except Exception as exc:
        logger.warning(
            "[CAPACITY] Quota snapshot unavailable; reopening nothing: %s", exc,
        )
        return []
    rows = await db.list_listings(status="closed", limit=200)
    reopened = reopenable_token_listing_ids(rows, availability=availability)
    for listing_id in reopened:
        await db.update_listing(listing_id=listing_id, status="open")
        await publish_order_to_registry(
            await db.load_listing(listing_id=listing_id) or {},
        )
    return reopened


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
    try:
        pubs = await get_sqlite_client().load_publications(listing_id=listing_id)
    except Exception:
        return list(fallback_urls)
    active = [p["registry_url"] for p in pubs if p.get("status") != "unpublished"]
    return active if active else list(fallback_urls)


async def _record_publications(
    listing_id: str, results: list[dict[str, Any]],
) -> None:
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
