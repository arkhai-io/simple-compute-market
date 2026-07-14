"""Discovery for domain-owned storefront publication sources.

Core storefront owns the runner/executable side; domain packages expose
publication-source factories through this entry-point group when they support
optional seller inventory publication.
"""

from __future__ import annotations

from collections.abc import Callable
from importlib.metadata import entry_points
from typing import Any, Protocol

from .publication_sources import PublicationSource

PUBLICATION_SOURCE_GROUP = "market.storefront_publication_sources"


class PublicationSourceFactory(Protocol):
    """Factory loaded from ``market.storefront_publication_sources``.

    Concrete storefront composition roots pass the callbacks required by the
    selected domain adapter. The core loader intentionally does not prescribe
    those kwargs; it only resolves the named factory.
    """

    def __call__(self, **kwargs: Any) -> PublicationSource: ...


def _iter_entry_points() -> list[Any]:
    return list(entry_points(group=PUBLICATION_SOURCE_GROUP))


def load_publication_source_factory(name: str) -> PublicationSourceFactory:
    """Load a domain publication-source factory by entry-point name."""
    normalized = name.replace("-", "_")
    matches = [
        ep for ep in _iter_entry_points()
        if ep.name == name or ep.name.replace("-", "_") == normalized
    ]
    if not matches:
        available = ", ".join(list_publication_source_factories()) or "(none)"
        raise KeyError(
            f"Unknown storefront publication source {name!r}. "
            f"Installed sources: {available}"
        )
    if len(matches) > 1:
        providers = ", ".join(
            f"{getattr(ep, 'value', ep)!s}" for ep in matches
        )
        raise RuntimeError(
            f"Multiple storefront publication sources named {name!r}: {providers}"
        )
    factory = matches[0].load()
    if not callable(factory):
        raise TypeError(
            f"Storefront publication source {name!r} did not load a callable"
        )
    return factory


def build_publication_source(name: str, **kwargs: Any) -> PublicationSource:
    """Load and call a named publication-source factory."""
    source = load_publication_source_factory(name)(**kwargs)
    if not isinstance(source, PublicationSource):
        raise TypeError(
            f"Storefront publication source {name!r} returned "
            f"{type(source).__name__}, expected PublicationSource"
        )
    return source


def list_publication_source_factories() -> list[str]:
    """List installed publication-source entry-point names."""
    return sorted({ep.name for ep in _iter_entry_points()})
