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

from core_buyer.cli import parse_filter_options  # noqa: F401 — moved to core

from .buy_orchestrator import extract_seller_min_price


def resolve_prices_from_matches(
    *,
    matches: list[dict],
    console: Console,
    price_markup: float,
    initial_price: Optional[int] = None,
    max_price: Optional[int] = None,
) -> tuple[Optional[int], Optional[int]]:
    """Fill missing (initial_price, max_price) from the advertised price.

    The default buyer policy is ``listed_price`` (pay what's published,
    never haggle — design-negotiation-policy-surface.md), so with no
    explicit flags both prices ARE the cheapest candidate's advertised
    per-hour rate: open there, bound there, done. There is nothing to
    confirm interactively when the answer is "pay what's listed".

    Derivation reads only the advertised rate, never the explicit
    flags: advertised rates are base units while explicit flags are
    human units scaled later by the caller — mixing them would cross
    unit systems. ``price_markup`` only matters for opt-in hagglers:
    with ``--initial-price`` given but no ceiling, the ceiling derives
    as ``advertised × markup`` (headroom for a counter-capable policy
    such as ``bisection``).

    Returns ``(None, None)`` if a missing price cannot be derived
    because no candidate carries a usable advertised rate
    (hidden-reserve listings).
    """
    if initial_price is not None and max_price is not None:
        return initial_price, max_price

    anchor: Optional[int] = None
    priced = [(extract_seller_min_price(m), m) for m in matches]
    # Keep listings with amount=0 (free) as legitimate anchors; only filter
    # out None (hidden reserve) where we genuinely have no price signal.
    priced = [(p, m) for p, m in priced if p is not None]
    if priced:
        priced.sort(key=lambda pm: pm[0])
        anchor = int(priced[0][0])

    if max_price is None and anchor is not None:
        max_price = (
            int(round(anchor * price_markup))
            if initial_price is not None
            else anchor
        )
    if initial_price is None and anchor is not None:
        initial_price = anchor

    if initial_price is None or max_price is None:
        typer.secho(
            "No matched listing carries an advertised price (all hidden-reserve); "
            "pass --initial-price / --max-price explicitly.",
            err=True, fg=typer.colors.RED,
        )
        return None, None

    if priced and os.isatty(0):
        table = Table(title="Matched listings (per-hour rates)", show_header=True)
        table.add_column("#", justify="right", style="dim")
        table.add_column("Listing ID", overflow="fold")
        table.add_column("Storefront URL", overflow="fold")
        table.add_column("advertised", justify="right")
        for i, (p, m) in enumerate(priced, start=1):
            table.add_row(
                str(i),
                str(m.get("listing_id", "-")),
                str(m.get("storefront_url") or m.get("seller", "-"))[:48],
                str(p),
            )
        console.print(table)
    typer.echo(
        f"Prices: --initial-price={initial_price} --max-price={max_price}"
        + (f" (anchored on advertised={anchor})" if anchor is not None else "")
    )
    return initial_price, max_price


