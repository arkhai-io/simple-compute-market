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
from typing import Any, TypedDict

logger = logging.getLogger(__name__)

RegistryClientFactory = Callable[[], Any]
RecordPublications = Callable[[str, list[dict[str, Any]]], Awaitable[None]]
RegistryTargetSelector = Callable[[str, list[str]], Awaitable[list[str]]]
ListingRequestFactory = Callable[..., Any]
UpdateListingRequestFactory = Callable[..., Any]
PublishEvent = Callable[..., Any]


class RegistryPublicationResult(TypedDict):
    """Public per-target outcome without request or credential-bearing detail."""

    registry_url: str
    success: bool
    registry_assigned_id: str | None
    error_type: str | None
    status_code: int | None


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
    settlement_options = ensure_json_obj(listing_dict.get("settlement_options"), [])
    demands = ensure_json_obj(listing_dict.get("demands"), [])
    max_duration_seconds = listing_dict.get("max_duration_seconds")

    listing_storefront_url = listing_dict.get("storefront_url")
    if not isinstance(listing_storefront_url, str) or not listing_storefront_url:
        return {
            "status": "error",
            "listing_id": listing_id,
            "message": "listing storefront_url is required for publication",
        }
    if storefront_url is not None and listing_storefront_url != storefront_url:
        return {
            "status": "error",
            "listing_id": listing_id,
            "message": "listing storefront_url differs from configured storefront URL",
        }

    try:
        request = listing_request_factory(
            listing_id=listing_id,
            offer=offer_resource,
            accepted_escrows=accepted_escrows,
            settlement_options=settlement_options,
            demands=demands,
            max_duration_seconds=max_duration_seconds,
            storefront_url=listing_storefront_url,
        )
    except Exception as exc:
        return _publication_failure(listing_id, "preparation", exc)

    results: list[dict[str, Any]] | None = None
    failure_stage = "setup"
    try:
        registry_context = registry_client_factory()
        async with registry_context as registry_client:
            failure_stage = "fanout"
            payloads = {url: request for url in registry_client.urls}
            results = await registry_client.publish_listing_per_registry(
                payloads=payloads,
            )
            failure_stage = "context"
    except Exception as exc:
        return _publication_failure(
            listing_id,
            failure_stage,
            exc,
            results=results,
        )
    if results is None:
        return _publication_failure(
            listing_id,
            "fanout",
            RuntimeError("registry fanout returned no result collection"),
        )

    if record_publications is not None:
        try:
            await record_publications(listing_id, results)
        except Exception as exc:
            return _publication_failure(
                listing_id,
                "persistence",
                exc,
                results=results,
            )

    if any(r["success"] for r in results):
        if on_published is not None:
            try:
                await _maybe_await(
                    on_published(
                        listing_id=listing_id,
                        storefront_url=listing_storefront_url,
                        seller_principal=listing_dict.get("seller_principal"),
                        offer_resource=offer_resource,
                        accepted_escrows=accepted_escrows,
                        settlement_options=settlement_options,
                        demands=demands,
                        max_duration_seconds=max_duration_seconds,
                    )
                )
            except Exception as exc:
                return _publication_failure(
                    listing_id,
                    "event",
                    exc,
                    results=results,
                )
        logger.info("[REGISTRY] Published listing %s", listing_id)
        return {
            "status": "published",
            "listing_id": listing_id,
            "registry_results": _public_registry_results(results),
        }

    public_results = _public_registry_results(results)
    failure_message = _registry_failure_message(public_results)
    logger.warning(
        "[REGISTRY] Failed to publish listing %s: %s",
        listing_id,
        failure_message,
    )
    return {
        "status": "error",
        "listing_id": listing_id,
        "message": failure_message,
        "registry_results": public_results,
    }


async def close_listing_in_registries(
    listing_id: str,
    *,
    enabled: bool,
    registry_client_factory: RegistryClientFactory,
    update_listing_request_factory: UpdateListingRequestFactory,
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
            request = update_listing_request_factory(updates={"status": "closed"})
            payloads = {url: request for url in target_urls}
            results = await registry_client.update_listing_per_registry(
                listing_id=listing_id,
                payloads=payloads,
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


def _public_registry_results(
    results: list[dict[str, Any]],
) -> list[RegistryPublicationResult]:
    """Project internal write receipts into stable, non-sensitive outcomes."""
    return [
        RegistryPublicationResult(
            registry_url=result["registry_url"],
            success=result["success"],
            registry_assigned_id=result.get("registry_assigned_id"),
            error_type=result.get("error_type"),
            status_code=result.get("status_code"),
        )
        for result in results
    ]


def _registry_failure_message(
    results: list[RegistryPublicationResult],
) -> str:
    """Describe the first failure without exposing exception or response text."""
    failure = next((result for result in results if not result["success"]), None)
    if failure is None:
        return "registry publication failed"
    error_type = failure["error_type"] or "RegistryError"
    status_code = failure["status_code"]
    if status_code is not None:
        return f"registry publication failed ({error_type}, HTTP {status_code})"
    return f"registry publication failed ({error_type})"


def _publication_failure(
    listing_id: str,
    failure_stage: str,
    exc: Exception,
    *,
    results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return an orchestration failure without exposing exception detail."""
    error_type = type(exc).__name__
    status_code = getattr(exc, "status_code", None)
    if not isinstance(status_code, int):
        status_code = None
    status_suffix = f", HTTP {status_code}" if status_code is not None else ""
    message = (
        f"registry publication {failure_stage} failed "
        f"({error_type}{status_suffix})"
    )
    logger.warning("[REGISTRY] Listing %s: %s", listing_id, message)
    response: dict[str, Any] = {
        "status": "error",
        "listing_id": listing_id,
        "message": message,
        "failure_stage": failure_stage,
        "error_type": error_type,
        "status_code": status_code,
    }
    if results is not None:
        response["registry_results"] = _public_registry_results(results)
    return response
