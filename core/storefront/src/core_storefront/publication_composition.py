"""Core-owned publication source composition helpers.

Concrete storefront executables provide infrastructure callbacks for each
selected domain source. This module owns the reusable naming/composition surface
so callers do not hand-roll VM-only, bare-metal-only, or combined selections.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .publication_runner import PublicationSourceSelection

VM_PUBLICATION_SOURCE = "vms"
BARE_METAL_PUBLICATION_SOURCE = "bare_metal"


def build_storefront_publication_selection(
    source_names: Sequence[str],
    *,
    source_kwargs_by_name: Mapping[str, Mapping[str, Any]] | None = None,
) -> PublicationSourceSelection:
    """Build a selected publication-source composition for a storefront.

    Source names are entry-point names from
    ``market.storefront_publication_sources``. Unknown kwargs are intentionally
    ignored here; plugin loading remains responsible for validating whether a
    selected source received the callbacks it requires.
    """
    kwargs_by_name = source_kwargs_by_name or {}
    return PublicationSourceSelection(
        source_names=tuple(source_names),
        source_kwargs_by_name={
            name: dict(kwargs_by_name[name])
            for name in source_names
            if name in kwargs_by_name
        },
    )


def build_vm_publication_selection(
    source_kwargs: Mapping[str, Any],
) -> PublicationSourceSelection:
    """Build the VM-only publication selection."""
    return build_storefront_publication_selection(
        (VM_PUBLICATION_SOURCE,),
        source_kwargs_by_name={VM_PUBLICATION_SOURCE: source_kwargs},
    )


def build_bare_metal_publication_selection(
    source_kwargs: Mapping[str, Any],
) -> PublicationSourceSelection:
    """Build the bare-metal-only publication selection."""
    return build_storefront_publication_selection(
        (BARE_METAL_PUBLICATION_SOURCE,),
        source_kwargs_by_name={BARE_METAL_PUBLICATION_SOURCE: source_kwargs},
    )


def build_multi_domain_publication_selection(
    *,
    vm_source_kwargs: Mapping[str, Any] | None = None,
    bare_metal_source_kwargs: Mapping[str, Any] | None = None,
    source_names: Sequence[str] = (
        VM_PUBLICATION_SOURCE,
        BARE_METAL_PUBLICATION_SOURCE,
    ),
) -> PublicationSourceSelection:
    """Build a VM + bare-metal publication selection.

    ``source_names`` allows callers to preserve a deterministic ordering or
    select a subset while reusing the same callback map.
    """
    kwargs_by_name: dict[str, Mapping[str, Any]] = {}
    if vm_source_kwargs is not None:
        kwargs_by_name[VM_PUBLICATION_SOURCE] = vm_source_kwargs
    if bare_metal_source_kwargs is not None:
        kwargs_by_name[BARE_METAL_PUBLICATION_SOURCE] = bare_metal_source_kwargs
    return build_storefront_publication_selection(
        source_names,
        source_kwargs_by_name=kwargs_by_name,
    )
