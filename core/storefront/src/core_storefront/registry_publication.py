"""Schema-agnostic registry publication helpers.

The core owns the invariant publication flow: normalize a listing payload,
construct registry protocol requests through injected factories, fan out
through an injected registry client, and report stable status dictionaries.
Storefront-specific configuration, client construction, persistence, and
event logging stay outside this module.
"""

from __future__ import annotations

import inspect
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

RegistryClientFactory = Callable[[], Any]
RecordPublications = Callable[[str, list[dict[str, Any]]], Awaitable[None]]
RegistryTargetSelector = Callable[[str, list[str]], Awaitable[list[str]]]
ListingRequestFactory = Callable[..., Any]
UpdateListingRequestFactory = Callable[..., Any]
PublishEvent = Callable[..., Any]


def ensure_json_obj(value: Any, default: Any) -> Any:
    """Coerce a maybe-stringified JSON blob into a Python object."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return default
    return default if value is None else value


async def publish_listing_to_registries(
    listing: Any,
    *,
    enabled: bool,
    registry_client_factory: RegistryClientFactory,
    listing_request_factory: ListingRequestFactory,
    private_key: str,
    storefront_url: str | None,
    record_publications: RecordPublications | None = None,
    on_published: PublishEvent | None = None,
) -> dict[str, Any]:
    """Publish a listing to every configured registry.

    ``listing`` may be a plain dict or a model exposing ``model_dump``.
    Request construction and client behavior are injected so the helper
    stays independent of a concrete registry-client package.
    """
    listing_dict = _listing_to_dict(listing)
    listing_id = _listing_id(listing, listing_dict)

    if not enabled:
        return {"status": "disabled", "listing_id": listing_id}

    offer_resource = ensure_json_obj(listing_dict.get("offer_resource"), {})
    accepted_escrows = ensure_json_obj(listing_dict.get("accepted_escrows"), [])
    demands = ensure_json_obj(listing_dict.get("demands"), [])
    max_duration_seconds = listing_dict.get("max_duration_seconds")

    try:
        async with registry_client_factory() as registry_client:
            request = listing_request_factory(
                listing_id=listing_id,
                offer=offer_resource,
                accepted_escrows=accepted_escrows,
                demands=demands,
                max_duration_seconds=max_duration_seconds,
                storefront_url=listing_dict.get("seller") or storefront_url,
            )
            payloads = {url: request for url in registry_client.urls}
            results = await registry_client.publish_listing_per_registry(
                payloads,
                private_key=private_key,
            )
        if record_publications is not None:
            await record_publications(listing_id, results)
        if any(r["success"] for r in results):
            logger.info("[REGISTRY] Published listing %s", listing_id)
            if on_published is not None:
                await _maybe_await(
                    on_published(
                        listing_id=listing_id,
                        offer_resource=offer_resource,
                        accepted_escrows=accepted_escrows,
                        demands=demands,
                        max_duration_seconds=max_duration_seconds,
                    )
                )
            return {"status": "published", "listing_id": listing_id}

        first_err = next((r["error"] for r in results if r["error"]), "unknown")
        logger.warning(
            "[REGISTRY] Failed to publish listing %s: %s",
            listing_id,
            first_err,
        )
        return {"status": "error", "listing_id": listing_id, "message": first_err}
    except Exception as exc:
        logger.warning("[REGISTRY] Failed to publish listing %s: %s", listing_id, exc)
        return {"status": "error", "listing_id": listing_id, "message": str(exc)}


async def close_listing_in_registries(
    listing_id: str,
    *,
    enabled: bool,
    registry_client_factory: RegistryClientFactory,
    update_listing_request_factory: UpdateListingRequestFactory,
    private_key: str,
    select_target_registries: RegistryTargetSelector,
    record_publications: RecordPublications | None = None,
) -> dict[str, Any]:
    """Mark a listing closed in the registries that should receive updates."""
    if not enabled:
        return {
            "status": "skipped",
            "message": "Registry discovery is disabled; order not updated in registry",
            "listing_id": listing_id,
        }

    try:
        async with registry_client_factory() as registry_client:
            target_urls = await select_target_registries(
                listing_id,
                registry_client.urls,
            )
            request = update_listing_request_factory(
                updates={"status": "closed"},
                private_key=private_key,
            )
            payloads = {url: request for url in target_urls}
            results = await registry_client.update_listing_per_registry(
                listing_id,
                payloads,
            )
        if record_publications is not None:
            await record_publications(listing_id, results)
        first_ok = next(
            (r["response"] for r in results if r["success"] and r["response"]),
            None,
        )
        if first_ok:
            return {
                "status": "closed",
                "message": f"Order {listing_id} marked closed in registry",
                "listing_id": listing_id,
                "registry_result": first_ok,
            }
        return {
            "status": "error",
            "message": f"Failed to update order {listing_id} in registry",
            "listing_id": listing_id,
        }
    except Exception as exc:
        logger.warning("[REGISTRY] Failed to close listing %s: %s", listing_id, exc)
        return {
            "status": "error",
            "message": f"Registry update failed for order {listing_id}: {exc}",
            "listing_id": listing_id,
        }


def _listing_to_dict(listing: Any) -> dict[str, Any]:
    if isinstance(listing, dict):
        return listing
    model_dump = getattr(listing, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    raise TypeError(f"unsupported listing payload: {type(listing).__name__}")


def _listing_id(listing: Any, listing_dict: dict[str, Any]) -> str:
    direct = getattr(listing, "listing_id", None)
    if isinstance(direct, str) and direct:
        return direct
    value = listing_dict.get("listing_id")
    return value if isinstance(value, str) and value else "unknown"


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value
