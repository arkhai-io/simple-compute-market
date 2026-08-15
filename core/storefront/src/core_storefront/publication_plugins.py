"""Publication-source construction from the frozen storefront registry."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .domain_registry import StorefrontDomainRegistry
from .publication_sources import PublicationSource


def build_registry_publication_sources(
    registry: StorefrontDomainRegistry,
    *,
    source_kwargs_by_contribution: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[PublicationSource, ...]:
    """Build each configured source once from its registered exact contract.

    Entry points were already loaded and validated while constructing ``registry``.
    This function therefore cannot discover a different contract during a publish
    cycle and has no one-domain/default path.
    """

    kwargs_by_contribution = source_kwargs_by_contribution or {}
    unknown = set(kwargs_by_contribution).difference(
        registration.contribution_id for registration in registry.registrations
    )
    if unknown:
        raise KeyError(
            "publication source kwargs name unknown contributions: "
            + ", ".join(sorted(unknown))
        )

    sources: list[PublicationSource] = []
    seen_names: set[str] = set()
    for registration in registry.registrations:
        publication = registration.contract.publication
        if publication is None or publication.source_factory is None:
            raise TypeError(
                f"storefront contribution {registration.contribution_id!r} has no "
                "publication source factory"
            )
        source = publication.source_factory(
            **dict(kwargs_by_contribution.get(registration.contribution_id, {}))
        )
        if not isinstance(source, PublicationSource):
            raise TypeError(
                f"storefront contribution {registration.contribution_id!r} returned "
                f"{type(source).__name__}, expected PublicationSource"
            )
        if source.name in seen_names:
            raise ValueError(f"duplicate publication source name {source.name!r}")
        seen_names.add(source.name)
        sources.append(source)
    return tuple(sources)
