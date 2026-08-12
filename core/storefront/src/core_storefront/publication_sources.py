"""Core storefront interfaces for automated seller publication sources.

This is an optional storefront role dependency: domains or seller automation
packages can provide a source that derives local inventory into listings for
the storefront to publish. It is not the complete domain storefront API.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PublicationSource:
    """A source of local candidates for automated listing publication."""

    name: str
    open_keys: Callable[[str], set[str]]
    close_stale: Callable[[str, str], list[str]]
    available_candidates: Callable[[str], list[dict[str, Any]]]
    skip_keys: Callable[[dict[str, Any]], set[str]]
    offer_resource: Callable[[dict[str, Any]], dict[str, Any]]
    record_published: Callable[[str, dict[str, Any], str], None]
    reopen_existing: Callable[
        [
            str,
            str,
            dict[str, Any],
            dict[str, Any],
            list[dict[str, Any]],
            list[dict[str, Any]],
            int | None,
        ],
        dict[str, Any] | None,
    ]
    reopen_error_label: str
    pricing_resource: Callable[
        [dict[str, Any], dict[str, Any]],
        dict[str, Any],
    ] = field(
        default=lambda candidate, _offer: candidate,
    )
