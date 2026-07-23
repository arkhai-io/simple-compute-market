"""Core command helper for storefront publication entrypoints.

This module is the reusable executable-facing layer: concrete storefronts choose
or build a publication source selection, provide local infrastructure callbacks
(payload construction and listing creation), and core runs the command with a
stable config/result surface.
"""

from __future__ import annotations

from dataclasses import dataclass

from .publication_runner import (
    PayloadBuilder,
    PublicationCommand,
    PublicationCommandResult,
    PublicationSourceSelection,
    PublishOffer,
)


@dataclass(frozen=True)
class StorefrontPublicationCommandConfig:
    """Runtime config for one storefront publication command invocation."""

    db_path: str
    base_url: str
    private_key: str | None
    close_stale: bool = True
    skip_open: bool = True


@dataclass(frozen=True)
class StorefrontPublicationCommandCallbacks:
    """Infrastructure callbacks supplied by a concrete storefront executable."""

    build_payload: PayloadBuilder
    publish_offer: PublishOffer


def build_storefront_publication_command(
    selection: PublicationSourceSelection,
    *,
    config: StorefrontPublicationCommandConfig,
    callbacks: StorefrontPublicationCommandCallbacks,
) -> PublicationCommand:
    """Build a reusable publication command from selection + infrastructure."""
    return selection.command(
        db_path=config.db_path,
        base_url=config.base_url,
        private_key=config.private_key,
        build_payload=callbacks.build_payload,
        publish_offer=callbacks.publish_offer,
    )


def run_storefront_publication_command(
    selection: PublicationSourceSelection,
    *,
    config: StorefrontPublicationCommandConfig,
    callbacks: StorefrontPublicationCommandCallbacks,
    skip_ids: set[str] | None = None,
) -> PublicationCommandResult:
    """Run one core-owned storefront publication command."""
    return build_storefront_publication_command(
        selection,
        config=config,
        callbacks=callbacks,
    ).run(
        skip_ids=skip_ids,
        close_stale=config.close_stale,
        skip_open=config.skip_open,
    )
