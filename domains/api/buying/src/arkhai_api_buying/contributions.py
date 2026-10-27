"""What a buyer plugin hands the buying library: one frozen bundle of its domain's contributions.

The library discovers or imports no domain.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from arkhai_api.purchase import ProvisionTerms

ResourceText = Callable[[Mapping[str, Any]], str]
"""Renders one value of a listing's ``listing_resource``."""


def _no_details(_resource: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    return ()


@dataclass(frozen=True)
class ListingRendering:
    """How the listing commands show a domain's ``listing_resource``.

    ``resource`` reads the resource from a registry row. The list table shows
    ``summary`` after the listing ID and ``columns`` after the unit price; the
    show command adds ``details`` after the storefront URL.
    """

    resource: Callable[[Any], Mapping[str, Any]]
    summary_header: str
    summary: ResourceText
    columns: tuple[tuple[str, ResourceText], ...] = ()
    details: Callable[[Mapping[str, Any]], tuple[tuple[str, str], ...]] = _no_details


@dataclass(frozen=True)
class BuyingContributions:
    """One domain's contributions to the buying library.

    ``schema_id`` is the registry schema discovery keeps; ``provision_terms`` is
    the domain's binding of the purchase shape. ``command`` names the command
    group and ``noun`` how output and refusals name what is sold.
    """

    schema_id: str
    provision_terms: type[ProvisionTerms]
    command: str
    command_help: str
    noun: str
    resource_query_example: str
    rendering: ListingRendering

    def __post_init__(self) -> None:
        for name in ("schema_id", "command", "noun"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must be non-empty")

    @property
    def command_path(self) -> str:
        return f"market {self.command}"
