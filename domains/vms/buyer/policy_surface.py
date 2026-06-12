"""The VM domain's buyer policy objects.

Concrete ``BuyerPolicy`` registrations for the scalar-amount escrow
formats the VM market trades in (ARCHITECTURE.md, "Buyer negotiation policy surface").
Both scalar policies share the same parameter surface and format
compatibility; they differ only in the middleware terminal:

- ``listed_price`` (the default): pay the published price — open at it,
  accept within the bound, never counter.
- ``bisection``: opt-in haggling — open low, concede toward the
  ceiling at midpoints.

Importing this module registers the policies, mirroring how middleware
registration works; the buyer CLI imports it during app assembly.
"""

from __future__ import annotations

from typing import Any, Optional

import typer
from rich.console import Console
from rich.table import Table

from market_policy.buyer_policy import (
    BuyerPolicy,
    PolicyParam,
    register_buyer_policy,
)

from .buy_orchestrator import extract_seller_min_price


def entry_uses_scalar_amount(entry: dict[str, Any]) -> bool:
    """Whether an ``accepted_escrows`` entry is a scalar-amount format.

    The listing-side mirror of the proposal-shape test in
    ``domains.vms.negotiation.policies.escrow_shape_uses_scalar_amount``:
    advertised entries carry ``literal_fields`` + ``rates`` rather than
    negotiated ``fields``. A rate on ``amount``, or a fungible token
    literal without a tokenId, marks the format scalar-negotiable.
    """
    if not isinstance(entry, dict):
        return False
    if any(
        (r.get("field") if isinstance(r, dict) else getattr(r, "field", None))
        == "amount"
        for r in (entry.get("rates") or [])
    ):
        return True
    literals = entry.get("literal_fields") or {}
    if not isinstance(literals, dict):
        return False
    return (
        "token" in literals
        and "tokenId" not in literals
        and "token_id" not in literals
    )


_SCALAR_PARAMS = (
    PolicyParam(
        name="initial_price",
        help="Opening bid per negotiation in human / whole-token units, "
             "per-hour rate. Scaled by the token's on-chain decimals "
             "before being sent. Optional — when omitted, opens at the "
             "seller's advertised price.",
    ),
    PolicyParam(
        name="max_price",
        help="Ceiling per negotiation in human / whole-token units, "
             "per-hour rate. Optional — when omitted, equals the "
             "advertised price.",
    ),
    PolicyParam(
        name="price_markup",
        annotation=float,
        default=1.5,
        help="Ceiling headroom when --initial-price alone is given "
             "(max = advertised × markup). The listed_price default "
             "needs none.",
    ),
)


def derive_scalar_prices(
    *,
    params: dict[str, Any],
    matches: list[dict],
    console: Console,
    interactive: bool = False,
) -> tuple[Optional[int], Optional[int]]:
    """Fill missing (initial_price, max_price) from the advertised price.

    The scalar policies' shared derivation: with no explicit flags both
    prices ARE the cheapest candidate's advertised per-hour rate — open
    there, bound there. ``interactive`` (the caller's canonical
    disposition, ``core_buyer.cli.interactive_disposition``) asks for
    one confirmation before proceeding: not because the *price* needs
    deriving — it doesn't — but because in a bundled flow like ``buy``
    this table is the user's first sight of what discovery and the
    aggregation policy picked. Declining returns ``(None, None)``.

    Derivation reads only the advertised rate, never the explicit
    flags: advertised rates are base units while explicit flags are
    human units scaled later by the caller — mixing them would cross
    unit systems. ``price_markup`` only matters for opt-in hagglers:
    with ``--initial-price`` given but no ceiling, the ceiling derives
    as ``advertised × markup``.

    Returns ``(None, None)`` if a missing price cannot be derived
    because no candidate carries a usable advertised rate
    (hidden-reserve listings).
    """
    initial_price: Optional[float] = params.get("initial_price")
    max_price: Optional[float] = params.get("max_price")
    price_markup = float(params.get("price_markup") or 1.5)

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

    if priced and interactive:
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
    if interactive and not typer.confirm(
        "Proceed with these listings at these prices?", default=True,
    ):
        return None, None
    return initial_price, max_price


LISTED_PRICE_POLICY = register_buyer_policy(BuyerPolicy(
    name="listed_price",
    middlewares=("listed_price",),
    cli_params=_SCALAR_PARAMS,
    compatible=entry_uses_scalar_amount,
    derive_prices=derive_scalar_prices,
))

BISECTION_POLICY = register_buyer_policy(BuyerPolicy(
    name="bisection",
    middlewares=("bisection",),
    cli_params=_SCALAR_PARAMS,
    compatible=entry_uses_scalar_amount,
    derive_prices=derive_scalar_prices,
))


def configured_buyer_policy(*, strict: bool = False) -> BuyerPolicy:
    """The policy named by ``[negotiation] policy`` in buyer.toml.

    Default ``listed_price``. An explicit ``[negotiation] policies``
    chain still overrides the policy's middleware list in
    ``_load_buyer_chain`` — the policy object then only contributes the
    parameter surface and format compatibility.

    ``strict`` distinguishes the two call sites: app assembly
    (``strict=False``) tolerates a missing/corrupt config and an
    unknown name so ``market --help`` always renders — the default
    surface is shown and the command body surfaces the real error;
    chain loading (``strict=True``) propagates both, because silently
    negotiating under a policy the user never chose is worse than
    failing.
    """
    from market_policy.buyer_policy import DEFAULT_BUYER_POLICY, get_buyer_policy

    from .common import resolve_config_value

    try:
        name = resolve_config_value(
            toml_path="negotiation.policy", default=DEFAULT_BUYER_POLICY,
        ).strip() or DEFAULT_BUYER_POLICY
    except Exception:
        if strict:
            raise
        name = DEFAULT_BUYER_POLICY
    try:
        return get_buyer_policy(name)
    except KeyError:
        if strict:
            raise
        return get_buyer_policy(DEFAULT_BUYER_POLICY)
