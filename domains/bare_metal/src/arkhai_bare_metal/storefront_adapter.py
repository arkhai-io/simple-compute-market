"""Bare-metal publication source composed over trusted site generations."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from core_storefront.publication_sources import PublicationSource

from .projections import TrustedBareMetalProjection
from .storefront_publication import (
    bare_metal_listing_candidates,
    close_stale_bare_metal_listings,
    open_bare_metal_listing_keys,
    record_derived_bare_metal_listing,
    reopen_derived_bare_metal_listing_if_present,
)

ProjectionSnapshot = Callable[
    [],
    Iterable[TrustedBareMetalProjection] | None,
]
CloseListing = Callable[[str, str, str | None], dict[str, Any]]
PublishExistingListing = Callable[..., dict[str, Any]]


def _complete_projections(
    projection_snapshot: ProjectionSnapshot,
) -> list[TrustedBareMetalProjection]:
    snapshot = projection_snapshot()
    if snapshot is None:
        return []
    return list(snapshot)


def available_bare_metal_listing_candidates(
    db_path: str,
    *,
    projection_snapshot: ProjectionSnapshot,
) -> list[dict[str, Any]]:
    """Return candidates from retained complete trusted generations."""
    del db_path
    return bare_metal_listing_candidates(
        _complete_projections(projection_snapshot),
    )


def close_stale_bare_metal_publications(
    *,
    db_path: str,
    base_url: str,
    private_key: str | None,
    projection_snapshot: ProjectionSnapshot,
    close_listing: CloseListing,
) -> list[str]:
    """Close stale listings only where a complete generation is available."""
    return close_stale_bare_metal_listings(
        db_path=db_path,
        projections=_complete_projections(projection_snapshot),
        close_listing=lambda listing_id: close_listing(
            base_url,
            listing_id,
            private_key,
        ),
    )


def bare_metal_candidate_skip_keys(candidate: dict[str, Any]) -> set[str]:
    """Return the one authority-scoped key identifying a candidate."""
    return {str(candidate["derivation_key"])}


def record_published_bare_metal_listing(
    db_path: str,
    candidate: dict[str, Any],
    listing_id: str,
) -> None:
    """Record publication provenance for a newly created listing."""
    record_derived_bare_metal_listing(
        db_path,
        listing_id=listing_id,
        candidate=candidate,
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
    """Reopen a tracked listing through caller-supplied publication."""
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
    projection_snapshot: ProjectionSnapshot,
    close_listing: CloseListing,
    publish_existing_listing: PublishExistingListing,
) -> PublicationSource:
    """Build the source selected by the concrete bare-metal storefront."""

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
        open_keys=open_bare_metal_listing_keys,
        close_stale=lambda db_path, base_url, private_key: (
            close_stale_bare_metal_publications(
                db_path=db_path,
                base_url=base_url,
                private_key=private_key,
                projection_snapshot=projection_snapshot,
                close_listing=close_listing,
            )
        ),
        available_candidates=lambda db_path: (
            available_bare_metal_listing_candidates(
                db_path,
                projection_snapshot=projection_snapshot,
            )
        ),
        skip_keys=bare_metal_candidate_skip_keys,
        offer_resource=lambda candidate: dict(candidate["offer_resource"]),
        pricing_resource=lambda _candidate, offer: offer,
        record_published=record_published_bare_metal_listing,
        reopen_existing=reopen_existing,
        reopen_error_label="reopen derived bare-metal listing",
    )
