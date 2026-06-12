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
    price_markup: float,
    initial_price: Optional[int] = None,
    max_price: Optional[int] = None,
    interactive: bool = False,
) -> tuple[Optional[int], Optional[int]]:
    """Fill missing prices via the configured buyer policy's derivation.

    Thin dispatch: the derivation itself is the policy's
    (``policy_surface.derive_scalar_prices`` for the scalar policies) —
    a policy with no scalar notion derives nothing and the explicit
    values pass through.
    """
    from .policy_surface import configured_buyer_policy

    policy = configured_buyer_policy()
    if policy.derive_prices is None:
        return initial_price, max_price
    return policy.derive_prices(
        matches=matches,
        console=console,
        price_markup=price_markup,
        initial_price=initial_price,
        max_price=max_price,
        interactive=interactive,
    )


