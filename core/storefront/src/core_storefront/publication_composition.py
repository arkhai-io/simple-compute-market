"""Core-owned, schema-opaque publication composition."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .publication_runner import PublicationSourceSelection


def build_storefront_publication_selection(
    domain_names: Sequence[str],
    *,
    source_kwargs_by_name: Mapping[str, Mapping[str, Any]] | None = None,
) -> PublicationSourceSelection:
    """Build a publication selection from installed domain entry-point names."""
    kwargs_by_name = source_kwargs_by_name or {}
    return PublicationSourceSelection(
        source_names=tuple(domain_names),
        source_kwargs_by_name={
            name: dict(kwargs_by_name[name])
            for name in domain_names
            if name in kwargs_by_name
        },
    )
