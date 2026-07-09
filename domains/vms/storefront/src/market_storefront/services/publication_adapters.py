"""Publication lifecycle adapter shape for storefront domain publishers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class PublicationLifecycleAdapter:
    """Uniform lifecycle hooks for one storefront publication domain."""

    name: str
    open_keys: Callable[[str], set[str]]
    close_stale: Callable[[str, str, str | None], list[str]]

