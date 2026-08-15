"""Explicit contribution-keyed publication wiring for the VM storefront."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from core_storefront.publication_composition import (
    build_storefront_publication_selection as _build_core_publication_selection,
)
from core_storefront.domain_registry import StorefrontDomainRegistry
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




def build_vm_storefront_publication_selection(
    registry: StorefrontDomainRegistry,
    callbacks: VmPublicationSourceCallbacks,
) -> PublicationSourceSelection:
    """Build the explicitly registered VM publication selection."""
    return _build_core_publication_selection(
        registry,
        source_kwargs_by_contribution={
            "vms": build_vm_publication_source_kwargs(callbacks),
        },
    )


