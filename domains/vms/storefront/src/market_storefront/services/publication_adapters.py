"""Publication adapter shape for storefront domain publishers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class PublicationAdapter:
    """Uniform publication hooks for one storefront publication domain."""

    name: str
    open_keys: Callable[[str], set[str]]
    close_stale: Callable[[str, str, str | None], list[str]]
    available_candidates: Callable[[str], list[dict]]
    skip_keys: Callable[[dict], set[str]]
    offer_resource: Callable[[dict], dict]
    record_published: Callable[[str, dict, str], None]
    reopen_existing: Callable[
        [str, str, dict, dict, list[dict], list[dict], int | None, str | None],
        dict | None,
    ]
    reopen_error_label: str
