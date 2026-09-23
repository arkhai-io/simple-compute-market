"""Publication-source construction from the frozen storefront registry."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from typing import Any

from .domain_registry import StorefrontDomainRegistry
from .publication_sources import PublicationSource


def build_registry_publication_sources(
    registry: StorefrontDomainRegistry,
    *,
    contributions: Collection[str],
    source_kwargs_by_contribution: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[PublicationSource, ...]:
    """Build the named contributions' sources once from their registered contracts.

    Entry points were already loaded and validated while constructing ``registry``.
    This function therefore cannot discover a different contract during a publish
    cycle and has no one-domain/default path.

    ``contributions`` names exactly the sources the caller publishes. A storefront
    may register several domains whose publication runs in different places — one
    as a storefront loop, another as an operator command — and each publisher
    supplies only its own sources' arguments, so building every registration
    would call a factory without the arguments it requires. A name no
    registration carries fails before any factory runs.
    """

    if isinstance(contributions, str):
        raise TypeError("contributions must be a collection of contribution IDs")
    selected = frozenset(contributions)
    if not selected:
        raise ValueError("publication must name at least one contribution to build")
    registered = {
        registration.contribution_id for registration in registry.registrations
    }
    kwargs_by_contribution = source_kwargs_by_contribution or {}
    unknown = (selected | set(kwargs_by_contribution)).difference(registered)
    if unknown:
        raise KeyError(
            "publication names unknown contributions: " + ", ".join(sorted(unknown))
        )
    unbuilt = set(kwargs_by_contribution).difference(selected)
    if unbuilt:
        raise KeyError(
            "publication source kwargs name contributions not being built: "
            + ", ".join(sorted(unbuilt))
        )

    sources: list[PublicationSource] = []
    seen_names: set[str] = set()
    for registration in registry.registrations:
        if registration.contribution_id not in selected:
            continue
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
