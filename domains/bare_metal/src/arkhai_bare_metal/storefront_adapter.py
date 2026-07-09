"""Bare-metal storefront publication adapter.

The bare-metal domain package owns this adapter because it is domain semantics:
turn shared site capacity into bare-metal listing candidates and track derived
bare-metal listings. Concrete storefront executables still come from core role
packages and inject local infrastructure callbacks.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from core_storefront.publication_sources import PublicationSource

from .storefront_publication import (
    bare_metal_listing_candidates,
    close_stale_bare_metal_listings,
    open_bare_metal_listing_keys,
    record_derived_bare_metal_listing,
    reopen_derived_bare_metal_listing_if_present,
    stale_open_bare_metal_listing_ids,
)

CapacitySnapshot = Callable[[], list[dict[str, Any]]]
CloseListing = Callable[[str, str, str | None], dict[str, Any]]
PublishExistingListing = Callable[..., dict[str, Any]]


def available_bare_metal_listing_candidates(
    db_path: str,
    *,
    capacity_snapshot: CapacitySnapshot,
) -> list[dict[str, Any]]:
    """Return publishable bare-metal candidates from the shared capacity view."""
    del db_path
    return bare_metal_listing_candidates(capacity_snapshot())


def open_bare_metal_publication_keys(db_path: str) -> set[str]:
    """Return derivation keys already covered by open bare-metal listings."""
    return open_bare_metal_listing_keys(db_path)


def stale_open_bare_metal_publication_ids(
    db_path: str,
    *,
    capacity_snapshot: CapacitySnapshot,
) -> list[str]:
    """Return open bare-metal listing IDs no longer backed by availability."""
    resources = capacity_snapshot()
    if not resources:
        return []
    return stale_open_bare_metal_listing_ids(db_path, resources)


def close_stale_bare_metal_publications(
    *,
    db_path: str,
    base_url: str,
    private_key: str | None,
    capacity_snapshot: CapacitySnapshot,
    close_listing: CloseListing,
) -> list[str]:
    """Close stale derived bare-metal listings and update tracking rows."""
    resources = capacity_snapshot()
    if not resources:
        return []
    return close_stale_bare_metal_listings(
        db_path=db_path,
        resources=resources,
        close_listing=lambda listing_id: close_listing(
            base_url,
            listing_id,
            private_key,
        ),
    )


def bare_metal_candidate_skip_keys(candidate: dict[str, Any]) -> set[str]:
    """Return skip keys that identify one bare-metal publication candidate."""
    keys: set[str] = set()
    for value in (candidate.get("derivation_key"), candidate.get("machine_id")):
        if value is not None:
            keys.add(str(value))
    return keys


def record_published_bare_metal_listing(
    db_path: str,
    candidate: dict[str, Any],
    listing_id: str,
) -> None:
    """Record the local derived-listing row for a new bare-metal listing."""
    record_derived_bare_metal_listing(
        db_path,
        listing_id=listing_id,
        listing=candidate["listing"],
    )


def reopen_bare_metal_listing_adapter(
    db_path: str,
    base_url: str,
    candidate: dict[str, Any],
    offer: dict[str, Any],
    accepted_escrows: list[dict[str, Any]],
    demands: list[dict[str, Any]],
    max_duration_seconds: int | None,
    private_key: str | None,
    *,
    publish_existing_listing: PublishExistingListing,
) -> dict[str, Any] | None:
    """Reopen a tracked bare-metal listing through caller-supplied publisher."""
    return reopen_derived_bare_metal_listing_if_present(
        db_path=db_path,
        base_url=base_url,
        candidate=candidate,
        offer=offer,
        accepted_escrows=accepted_escrows,
        demands=demands,
        max_duration_seconds=max_duration_seconds,
        private_key=private_key,
        publish_existing_listing=publish_existing_listing,
    )


def bare_metal_publication_adapter(
    *,
    capacity_snapshot: CapacitySnapshot,
    close_listing: CloseListing,
    publish_existing_listing: PublishExistingListing,
) -> PublicationSource:
    """Build the bare-metal publication source for a concrete storefront."""

    def reopen_existing(
        db_path: str,
        base_url: str,
        candidate: dict[str, Any],
        offer: dict[str, Any],
        accepted_escrows: list[dict[str, Any]],
        demands: list[dict[str, Any]],
        max_duration_seconds: int | None,
        private_key: str | None,
    ) -> dict[str, Any] | None:
        return reopen_bare_metal_listing_adapter(
            db_path,
            base_url,
            candidate,
            offer,
            accepted_escrows,
            demands,
            max_duration_seconds,
            private_key,
            publish_existing_listing=publish_existing_listing,
        )

    return PublicationSource(
        name="bare_metal",
        open_keys=open_bare_metal_publication_keys,
        close_stale=lambda db_path, base_url, private_key: (
            close_stale_bare_metal_publications(
                db_path=db_path,
                base_url=base_url,
                private_key=private_key,
                capacity_snapshot=capacity_snapshot,
                close_listing=close_listing,
            )
        ),
        available_candidates=lambda db_path: available_bare_metal_listing_candidates(
            db_path,
            capacity_snapshot=capacity_snapshot,
        ),
        skip_keys=bare_metal_candidate_skip_keys,
        offer_resource=lambda candidate: dict(candidate["offer_resource"]),
        record_published=record_published_bare_metal_listing,
        reopen_existing=reopen_existing,
        reopen_error_label="reopen derived bare-metal listing",
    )
