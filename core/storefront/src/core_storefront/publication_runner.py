"""Core orchestration for automated storefront publication sources.

Domain packages provide :class:`PublicationSource` adapters. Concrete
storefront composition roots provide infrastructure callbacks for settlement
payload construction and listing publication. This module owns only the generic
control flow over sources.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from .publication_plugins import build_publication_source
from .publication_sources import PublicationSource

Payload = tuple[list[dict[str, Any]], list[dict[str, Any]], int | None]
PayloadBuilder = Callable[
    [PublicationSource, dict[str, Any], dict[str, Any]],
    Payload | str,
]
PublishOffer = Callable[
    [
        dict[str, Any],
        list[dict[str, Any]],
        list[dict[str, Any]],
        int | None,
    ],
    dict[str, Any],
]


def close_stale_publication_listings(
    sources: Iterable[PublicationSource],
    *,
    db_path: str,
    base_url: str,
    private_key: str | None,
) -> dict[str, list[str]]:
    """Close stale listings for every configured publication source."""
    return {
        source.name: source.close_stale(db_path, base_url, private_key)
        for source in sources
    }


def open_publication_keys(
    sources: Iterable[PublicationSource],
    db_path: str,
) -> set[str]:
    """Return the union of keys already covered by open listings."""
    covered: set[str] = set()
    for source in sources:
        covered.update(source.open_keys(db_path))
    return covered


def publish_source_by_name(
    source_name: str,
    *,
    source_kwargs: dict[str, Any] | None = None,
    db_path: str,
    base_url: str,
    private_key: str | None,
    build_payload: PayloadBuilder,
    publish_offer: PublishOffer,
    skip_ids: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[tuple[dict[str, Any], str]], list[dict[str, Any]]]:
    """Load one publication source by name and publish one round."""
    source = build_publication_source(source_name, **(source_kwargs or {}))
    return publish_round(
        [source],
        db_path=db_path,
        base_url=base_url,
        private_key=private_key,
        build_payload=build_payload,
        publish_offer=publish_offer,
        skip_ids=skip_ids,
    )


def publish_round(
    sources: Iterable[PublicationSource],
    *,
    db_path: str,
    base_url: str,
    private_key: str | None,
    build_payload: PayloadBuilder,
    publish_offer: PublishOffer,
    skip_ids: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[tuple[dict[str, Any], str]], list[dict[str, Any]]]:
    """Publish one round of candidates from the configured sources.

    Returns ``(published, failed, skipped)``. Domain semantics live in each
    ``PublicationSource``; settlement and HTTP side effects live in caller
    callbacks. The control flow is intentionally schema-opaque.
    """
    skip_ids = skip_ids or set()
    published: list[dict[str, Any]] = []
    failed: list[tuple[dict[str, Any], str]] = []
    skipped: list[dict[str, Any]] = []

    for source in sources:
        for candidate in source.available_candidates(db_path):
            if source.skip_keys(candidate) & skip_ids:
                skipped.append(candidate)
                continue

            offer = source.offer_resource(candidate)
            payload = build_payload(source, candidate, offer)
            if isinstance(payload, str):
                failed.append((candidate, payload))
                continue
            accepted_escrows, demands, max_duration_seconds = payload

            try:
                reopened = source.reopen_existing(
                    db_path,
                    base_url,
                    candidate,
                    offer,
                    accepted_escrows,
                    demands,
                    max_duration_seconds,
                    private_key,
                )
            except Exception as exc:
                failed.append((candidate, f"{source.reopen_error_label}: {exc}"))
                continue

            if reopened is not None:
                if reopened.get("status") in {"published", "disabled"}:
                    published.append({
                        "resource": candidate,
                        "response": reopened,
                        "accepted_escrows": accepted_escrows,
                        "demands": demands,
                    })
                else:
                    failed.append((
                        candidate,
                        reopened.get("message") or str(reopened),
                    ))
                continue

            try:
                response = publish_offer(
                    offer,
                    accepted_escrows,
                    demands,
                    max_duration_seconds,
                )
                if response.get("listing_id"):
                    source.record_published(
                        db_path,
                        candidate,
                        str(response["listing_id"]),
                    )
                published.append({
                    "resource": candidate,
                    "response": response,
                    "accepted_escrows": accepted_escrows,
                    "demands": demands,
                })
            except Exception as exc:
                failed.append((candidate, str(exc)))

    return published, failed, skipped
