"""Core-owned, schema-opaque publication composition."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .domain_registry import StorefrontDomainRegistry
from .publication_plugins import build_registry_publication_sources
from .publication_runner import PublicationSourceSelection


def build_storefront_publication_selection(
    registry: StorefrontDomainRegistry,
    *,
    source_kwargs_by_contribution: Mapping[str, Mapping[str, Any]] | None = None,
) -> PublicationSourceSelection:
    """Build all sources once from the already validated startup registry."""

    return PublicationSourceSelection(
        sources=build_registry_publication_sources(
            registry,
            source_kwargs_by_contribution=source_kwargs_by_contribution,
        )
    )
