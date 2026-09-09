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
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, TypedDict

from market_config.registry_url import normalize_registry_url

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


@dataclass(frozen=True, slots=True)
class _PreparedListingPublication:
    listing_id: str
    listing_dict: dict[str, Any]
    request: Any
    storefront_url: str
    offer_resource: Any
    accepted_escrows: Any
    settlement_options: Any
    demands: Any
    max_duration_seconds: Any


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

    prepared = _prepare_listing_publication(
        listing_dict,
        listing_id=listing_id,
        listing_request_factory=listing_request_factory,
        storefront_url=storefront_url,
        status=None,
    )
    if isinstance(prepared, dict):
        return prepared

    fanout_result: list[dict[str, Any]] | dict[str, Any] | None = None
    failure_stage = "setup"
    try:
        registry_context = registry_client_factory()
        async with registry_context as registry_client:
            failure_stage = "fanout"
            fanout_result = await _fanout_prepared_listing_with_client(
                prepared,
                registry_client=registry_client,
                target_registry_urls=None,
            )
            failure_stage = "context"
    except Exception as exc:
        return _publication_failure(
            listing_id,
            failure_stage,
            exc,
            public_results=_known_public_results(fanout_result),
        )
    if fanout_result is None:
        return _publication_failure(
            listing_id,
            "fanout",
            RuntimeError("registry fanout returned no result collection"),
        )
    if isinstance(fanout_result, dict):
        return fanout_result
    return await _complete_listing_publication(
        prepared,
        results=fanout_result,
        record_publications=record_publications,
        on_published=on_published,
    )


async def publish_listing_with_client(
    listing: Any,
    *,
    registry_client: Any,
    listing_request_factory: ListingRequestFactory,
    storefront_url: str | None,
    target_registry_urls: Sequence[str] | None = None,
    status: str | None = None,
    record_publications: RecordPublications | None = None,
    on_published: PublishEvent | None = None,
) -> dict[str, Any]:
    """Publish through an already-open client, optionally to an exact subset."""
    listing_dict = _listing_to_dict(listing)
    listing_id = _listing_id(listing, listing_dict)
    prepared = _prepare_listing_publication(
        listing_dict,
        listing_id=listing_id,
        listing_request_factory=listing_request_factory,
        storefront_url=storefront_url,
        status=status,
    )
    if isinstance(prepared, dict):
        return prepared
    fanout_result = await _fanout_prepared_listing_with_client(
        prepared,
        registry_client=registry_client,
        target_registry_urls=target_registry_urls,
    )
    if isinstance(fanout_result, dict):
        return fanout_result
    return await _complete_listing_publication(
        prepared,
        results=fanout_result,
        record_publications=record_publications,
        on_published=on_published,
    )


def _prepare_listing_publication(
    listing_dict: dict[str, Any],
    *,
    listing_id: str,
    listing_request_factory: ListingRequestFactory,
    storefront_url: str | None,
    status: str | None,
) -> _PreparedListingPublication | dict[str, Any]:
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
    request_kwargs: dict[str, Any] = {
        "listing_id": listing_id,
        "offer": offer_resource,
        "accepted_escrows": accepted_escrows,
        "settlement_options": settlement_options,
        "demands": demands,
        "max_duration_seconds": max_duration_seconds,
        "storefront_url": listing_storefront_url,
    }
    if status is not None:
        request_kwargs["status"] = status
    try:
        request = listing_request_factory(**request_kwargs)
    except Exception as exc:
        return _publication_failure(listing_id, "preparation", exc)
    return _PreparedListingPublication(
        listing_id=listing_id,
        listing_dict=listing_dict,
        request=request,
        storefront_url=listing_storefront_url,
        offer_resource=offer_resource,
        accepted_escrows=accepted_escrows,
        settlement_options=settlement_options,
        demands=demands,
        max_duration_seconds=max_duration_seconds,
    )


async def _fanout_prepared_listing_with_client(
    prepared: _PreparedListingPublication,
    *,
    registry_client: Any,
    target_registry_urls: Sequence[str] | None,
) -> list[dict[str, Any]] | dict[str, Any]:
    try:
        targets = _ordered_registry_targets(
            registry_client.urls,
            target_registry_urls,
        )
    except Exception as exc:
        return _publication_failure(prepared.listing_id, "targeting", exc)
    if target_registry_urls is not None and not targets:
        return _publication_failure(
            prepared.listing_id,
            "targeting",
            ValueError("registry publication target subset is empty"),
        )

    try:
        payloads = {url: prepared.request for url in targets}
        results = await registry_client.publish_listing_per_registry(
            payloads=payloads,
        )
    except Exception as exc:
        return _publication_failure(prepared.listing_id, "fanout", exc)
    if results is None:
        return _publication_failure(
            prepared.listing_id,
            "fanout",
            RuntimeError("registry fanout returned no result collection"),
        )
    return results


async def _complete_listing_publication(
    prepared: _PreparedListingPublication,
    *,
    results: list[dict[str, Any]],
    record_publications: RecordPublications | None,
    on_published: PublishEvent | None,
) -> dict[str, Any]:
    if record_publications is not None:
        try:
            await record_publications(prepared.listing_id, results)
        except Exception as exc:
            return _publication_failure(
                prepared.listing_id,
                "persistence",
                exc,
                results=results,
            )

    if any(r["success"] for r in results):
        if on_published is not None:
            try:
                await _maybe_await(
                    on_published(
                        listing_id=prepared.listing_id,
                        storefront_url=prepared.storefront_url,
                        seller_principal=prepared.listing_dict.get("seller_principal"),
                        offer_resource=prepared.offer_resource,
                        accepted_escrows=prepared.accepted_escrows,
                        settlement_options=prepared.settlement_options,
                        demands=prepared.demands,
                        max_duration_seconds=prepared.max_duration_seconds,
                    )
                )
            except Exception as exc:
                return _publication_failure(
                    prepared.listing_id,
                    "event",
                    exc,
                    results=results,
                )
        logger.info("[REGISTRY] Published listing %s", prepared.listing_id)
        return {
            "status": "published",
            "listing_id": prepared.listing_id,
            "registry_results": _public_registry_results(results),
        }

    public_results = _public_registry_results(results)
    failure_message = _registry_failure_message(public_results)
    logger.warning(
        "[REGISTRY] Failed to publish listing %s: %s",
        prepared.listing_id,
        failure_message,
    )
    return {
        "status": "error",
        "listing_id": prepared.listing_id,
        "message": failure_message,
        "registry_results": public_results,
    }


def _known_public_results(
    fanout_result: list[dict[str, Any]] | dict[str, Any] | None,
) -> list[RegistryPublicationResult] | None:
    if isinstance(fanout_result, list):
        return _public_registry_results(fanout_result)
    if isinstance(fanout_result, dict):
        results = fanout_result.get("registry_results")
        if isinstance(results, list):
            return results
    return None


def _ordered_registry_targets(
    configured_urls: Sequence[str],
    requested_urls: Sequence[str] | None,
) -> tuple[str, ...]:
    configured = tuple(configured_urls)
    if requested_urls is None:
        return configured
    requested = tuple(requested_urls)
    normalized_requested = tuple(normalize_registry_url(url) for url in requested)
    if len(normalized_requested) != len(set(normalized_requested)):
        raise ValueError("registry publication target subset contains duplicates")
    configured_by_normalized = {
        normalize_registry_url(url): url for url in configured
    }
    if any(url not in configured_by_normalized for url in normalized_requested):
        raise ValueError("registry publication target is not configured")
    selected = set(normalized_requested)
    return tuple(
        url for url in configured if normalize_registry_url(url) in selected
    )


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
    public_results: list[RegistryPublicationResult] | None = None,
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
    if public_results is not None:
        response["registry_results"] = public_results
    elif results is not None:
        response["registry_results"] = _public_registry_results(results)
    return response
