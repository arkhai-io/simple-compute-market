"""Shared CLI helpers used by ``market buy`` and ``market negotiate``.

Lives next to the per-command modules in ``groups/`` rather than at the
package root so callers don't see it as part of the public API.
"""
from __future__ import annotations

from typing import Optional

from rich.console import Console

from core_buyer.cli import parse_filter_options  # noqa: F401 — moved to core


def resolve_prices_from_matches(
    *,
    matches: list[dict],
    console: Console,
    params: dict | None = None,
    interactive: bool = False,
) -> tuple[Optional[int], Optional[int]]:
    """Fill missing prices via the configured buyer policy's derivation.

    Thin dispatch carrying only the canonical hook arguments — the
    policy's own values travel inside ``params`` (its namespace), so
    this dispatcher knows no policy's vocabulary. A policy with no
    derivation hook passes its explicit values through.
    """
    from .policy_surface import configured_buyer_policy

    params = dict(params or {})
    policy = configured_buyer_policy()
    if policy.derive_prices is None:
        return params.get("initial_price"), params.get("max_price")
    return policy.derive_prices(
        params=params,
        matches=matches,
        console=console,
        interactive=interactive,
    )


