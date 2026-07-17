"""Discovery of publication capabilities on installed market domains."""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import Any

from market_core import MarketDomainContract, validate_domain_contract

from .publication_sources import PublicationSource

STOREFRONT_DOMAIN_GROUP = "market.storefront_domains"


def _iter_entry_points() -> list[Any]:
    return list(entry_points(group=STOREFRONT_DOMAIN_GROUP))


def _load_domain_entry_point(name: str) -> MarketDomainContract:
    normalized = name.replace("-", "_")
    matches = [
        entry_point
        for entry_point in _iter_entry_points()
        if entry_point.name == name
        or entry_point.name.replace("-", "_") == normalized
    ]
    if not matches:
        available = ", ".join(list_publication_source_factories()) or "(none)"
        raise KeyError(
            f"Unknown storefront market domain {name!r}. "
            f"Installed publication domains: {available}"
        )
    if len(matches) > 1:
        providers = ", ".join(
            str(getattr(entry_point, "value", entry_point))
            for entry_point in matches
        )
        raise RuntimeError(
            f"Multiple storefront market domains named {name!r}: {providers}"
        )
    loaded = matches[0].load()
    if not isinstance(loaded, MarketDomainContract):
        raise TypeError(
            f"Storefront market domain {name!r} must resolve to a "
            f"MarketDomainContract, got {type(loaded).__name__}"
        )
    return validate_domain_contract(loaded)


def build_publication_source(name: str, **kwargs: Any) -> PublicationSource:
    """Build a selected domain's declared publication source."""
    domain = _load_domain_entry_point(name)
    if domain.publication is None:
        raise TypeError(
            f"Storefront market domain {domain.identity!s} does not declare "
            "the publication capability"
        )
    if domain.publication.source_factory is None:
        raise TypeError(
            f"Storefront market domain {domain.identity!s} has direct "
            "publication but no publication source factory"
        )
    source = domain.publication.source_factory(**kwargs)
    if not isinstance(source, PublicationSource):
        raise TypeError(
            f"Storefront market domain {domain.identity!s} returned "
            f"{type(source).__name__}, expected PublicationSource"
        )
    return source


def list_publication_source_factories() -> list[str]:
    """List installed domain entry points that declare publication."""
    names: list[str] = []
    for entry_point in _iter_entry_points():
        loaded = entry_point.load()
        if (
            isinstance(loaded, MarketDomainContract)
            and loaded.publication is not None
            and loaded.publication.source_factory is not None
        ):
            names.append(entry_point.name)
    return sorted(set(names))
