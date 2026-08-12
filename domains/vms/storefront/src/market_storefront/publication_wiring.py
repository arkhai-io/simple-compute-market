"""Publication-source wiring for the VM storefront package.

The CLI owns argument parsing and output. This module owns the transitional
storefront-side callback assembly used to compose VM and bare-metal publication
sources until a standalone core storefront executable exists.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from core_storefront.publication_composition import (
    build_storefront_publication_selection as _build_core_publication_selection,
)
from core_storefront.publication_runner import PublicationSourceSelection


@dataclass(frozen=True)
class VmPublicationSourceCallbacks:
    """Storefront infrastructure callbacks required by the VM adapter."""

    open_keys: Callable[[str], set[str]]
    close_stale: Callable[[str, str], list[str]]
    available_candidates: Callable[[str], list[dict[str, Any]]]
    offer_resource: Callable[[dict[str, Any]], dict[str, Any]]
    record_published: Callable[[str, dict[str, Any], str], None]
    reopen_existing: Callable[
        [
            str,
            str,
            dict[str, Any],
            dict[str, Any],
            list[dict],
            list[dict],
            int | None,
        ],
        dict[str, Any] | None,
    ]


@dataclass(frozen=True)
class BareMetalPublicationSourceCallbacks:
    """Storefront infrastructure callbacks required by bare-metal publication."""

    capacity_snapshot: Callable[[], list[dict[str, Any]] | None]
    close_listing: Callable[[str, str], dict[str, Any]]
    publish_existing_listing: Callable[..., dict[str, Any]]


def build_vm_publication_source_kwargs(
    callbacks: VmPublicationSourceCallbacks,
) -> dict[str, Any]:
    """Build entry-point kwargs for the VM publication adapter."""
    return {
        "open_keys": callbacks.open_keys,
        "close_stale": callbacks.close_stale,
        "available_candidates": callbacks.available_candidates,
        "offer_resource": callbacks.offer_resource,
        "record_published": callbacks.record_published,
        "reopen_existing": callbacks.reopen_existing,
    }


def build_bare_metal_publication_source_kwargs(
    callbacks: BareMetalPublicationSourceCallbacks,
) -> dict[str, Any]:
    """Build entry-point kwargs for the bare-metal publication adapter."""
    return {
        "capacity_snapshot": lambda: callbacks.capacity_snapshot() or [],
        "close_listing": callbacks.close_listing,
        "publish_existing_listing": callbacks.publish_existing_listing,
    }


def build_vm_storefront_publication_selection(
    callbacks: VmPublicationSourceCallbacks,
) -> PublicationSourceSelection:
    """Build the VM-only publication selection."""
    return _build_core_publication_selection(
        ("vms",),
        source_kwargs_by_name={
            "vms": build_vm_publication_source_kwargs(callbacks),
        },
    )


def build_bare_metal_storefront_publication_selection(
    callbacks: BareMetalPublicationSourceCallbacks,
) -> PublicationSourceSelection:
    """Build a bare-metal-only publication selection."""
    return _build_core_publication_selection(
        ("bare_metal",),
        source_kwargs_by_name={
            "bare_metal": build_bare_metal_publication_source_kwargs(callbacks),
        },
    )


def build_storefront_publication_selection(
    *,
    source_names: tuple[str, ...],
    vm_callbacks: VmPublicationSourceCallbacks,
    bare_metal_callbacks: BareMetalPublicationSourceCallbacks,
) -> PublicationSourceSelection:
    """Build a selected VM/bare-metal publication-source composition."""
    return _build_core_publication_selection(
        source_names,
        source_kwargs_by_name={
            "vms": build_vm_publication_source_kwargs(vm_callbacks),
            "bare_metal": build_bare_metal_publication_source_kwargs(
                bare_metal_callbacks,
            ),
        },
    )
