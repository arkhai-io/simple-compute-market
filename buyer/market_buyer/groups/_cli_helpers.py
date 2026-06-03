"""Shared CLI helpers used by ``market buy`` and ``market negotiate``.

Lives next to the per-command modules in ``groups/`` rather than at the
package root so callers don't see it as part of the public API.
"""
from __future__ import annotations

import os
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from ..buy_orchestrator import extract_seller_min_price


def resolve_prices_from_matches(
    *,
    matches: list[dict],
    console: Console,
    assume_yes: bool,
    price_markup: float,
) -> tuple[Optional[int], Optional[int]]:
    """Derive (initial_price, max_price) from the seller-advertised
    min_price on the candidate listings.

    Strategy: pick the cheapest listing's min_price as the anchor. Set
    ``initial = anchor`` (open at the seller's floor) and
    ``max = round(anchor * price_markup)`` (a ceiling above the floor).

    Interactive only when stdin is a TTY AND ``assume_yes`` is False.
    Otherwise derives silently — same disposition as ``--yes`` propagated
    through every gate.

    Returns ``(None, None)`` if no listing carries a usable min_price or
    the user declines.
    """
    priced = [
        (extract_seller_min_price(m), m)
        for m in matches
    ]
    # Keep listings with amount=0 (free) as legitimate anchors; only filter
    # out None (hidden reserve) where we genuinely have no price signal.
    priced = [(p, m) for p, m in priced if p is not None]
    if not priced:
        typer.secho(
            "No matched listing carries an advertised price (all hidden-reserve); "
            "pass --initial-price / --max-price explicitly.",
            err=True, fg=typer.colors.RED,
        )
        return None, None

    priced.sort(key=lambda pm: pm[0])
    cheapest = priced[0][0]
    derived_initial = cheapest
    # max(0 * 1.5, 0+1) = 1 ensures even a free anchor produces a non-zero
    # ceiling (so the strategy's accept-on-convergence math still works);
    # in practice a free listing with non-zero ceiling means the buyer is
    # willing to pay if the seller counters, but won't be surprised by
    # a non-zero accept.
    derived_max = max(cheapest * price_markup, cheapest + 1)

    interactive = (not assume_yes) and os.isatty(0)
    if not interactive:
        return derived_initial, derived_max

    # Show the candidate listings with their min_prices so the user can
    # cross-check the derived defaults.
    table = Table(title="Matched listings (per-hour rates)", show_header=True)
    table.add_column("#", justify="right", style="dim")
    table.add_column("Listing ID", overflow="fold")
    table.add_column("Storefront URL", overflow="fold")
    table.add_column("min_price", justify="right")
    for i, (p, m) in enumerate(priced, start=1):
        table.add_row(
            str(i),
            str(m.get("listing_id", "-")),
            str(m.get("storefront_url") or m.get("seller", "-"))[:48],
            str(p),
        )
    console.print(table)

    typer.echo(
        f"Defaults: --initial-price={derived_initial} "
        f"--max-price={derived_max} (anchor={cheapest}, markup={price_markup})"
    )
    if not typer.confirm("Use these prices?", default=True):
        try:
            initial_price = typer.prompt(
                "initial-price (raw token base units, per-hour)",
                default=derived_initial,
                type=int,
            )
            max_price = typer.prompt(
                "max-price (raw token base units, per-hour)",
                default=derived_max,
                type=int,
            )
        except typer.Abort:
            return None, None
        return initial_price, max_price
    return derived_initial, derived_max
