"""Concrete publication wiring for the bare-metal storefront."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from arkhai_bare_metal.projections import TrustedBareMetalProjection
from core_storefront.publication_command import (
    StorefrontPublicationCommandCallbacks,
    StorefrontPublicationCommandConfig,
    run_storefront_publication_command,
)
from core_storefront.publication_composition import (
    build_storefront_publication_selection,
)
from core_storefront.publication_runner import (
    PublicationCommandResult,
    PublicationSourceSelection,
)

ProjectionSnapshot = Callable[
    [],
    Iterable[TrustedBareMetalProjection] | None,
]
CloseListing = Callable[[str, str, str | None], dict[str, Any]]
PublishExistingListing = Callable[..., dict[str, Any]]


def build_bare_metal_publication_selection(
    *,
    projection_snapshot: ProjectionSnapshot,
    close_listing: CloseListing,
    publish_existing_listing: PublishExistingListing,
) -> PublicationSourceSelection:
    """Select only the installed bare-metal publication capability."""
    return build_storefront_publication_selection(
        ["bare_metal"],
        source_kwargs_by_name={
            "bare_metal": {
                "projection_snapshot": projection_snapshot,
                "close_listing": close_listing,
                "publish_existing_listing": publish_existing_listing,
            },
        },
    )


def run_bare_metal_publication(
    selection: PublicationSourceSelection,
    *,
    config: StorefrontPublicationCommandConfig,
    callbacks: StorefrontPublicationCommandCallbacks,
    skip_ids: set[str] | None = None,
) -> PublicationCommandResult:
    """Run one schema-opaque core publication round."""
    return run_storefront_publication_command(
        selection,
        config=config,
        callbacks=callbacks,
        skip_ids=skip_ids,
    )
