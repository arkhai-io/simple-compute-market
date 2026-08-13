"""API-credit market-domain contribution for the core ``market`` buyer CLI."""

from __future__ import annotations

from dataclasses import replace

import typer

from core_buyer.cli import build_app
from core_buyer.policy_surface import configured_buyer_policy
from domains.apicredits.domain_runtime import market_domain
from domains.apicredits.negotiation import make_api_credits_provision_terms
from market_core import (
    DomainCapability,
    ImmutableBuyerCapability,
    ImmutableNegotiationCapability,
    MarketDomainContract,
)

from . import buy_cli as buy_module
from . import negotiate_cli as negotiate_module
from . import settle_cli as settle_module
from .listing_cli import listing_app


credits_app = typer.Typer(no_args_is_help=True)
credits_app.add_typer(
    listing_app, name="listing",
    help="Browse API-credit listings (list/show).",
)
buy_module.register(credits_app)
negotiate_module.register(credits_app)
settle_module.register(credits_app)


def register(app: typer.Typer) -> None:
    """Register the API-credits schema's buyer commands on the core app."""
    app.add_typer(
        credits_app, name="credits",
        help="API-credit market: discover, buy, top up keys.",
    )


def _buyer_market_domain() -> MarketDomainContract:
    base = market_domain()
    from domains.apicredits.negotiation.policy_sources import (
        api_credits_policy_sources,
    )

    return replace(
        base,
        declared_capabilities=(
            base.declared_capabilities
            | {DomainCapability.BUYER, DomainCapability.NEGOTIATION}
        ),
        buyer=ImmutableBuyerCapability(
            register_commands=register,
            build_provision_terms=make_api_credits_provision_terms,
            select_policy=configured_buyer_policy,
            decode_result=base.codecs.result,
        ),
        # Declared on the buyer contract as well as the storefront's: this
        # domain's key-challenge responder is buyer-side, and the buyer role
        # composes its catalogue from the contracts its own plugin discovery
        # returns.
        negotiation=ImmutableNegotiationCapability(
            policy_sources=api_credits_policy_sources,
        ),
    )


#: Loaded by ``market.buyer_domains`` discovery.
domain = _buyer_market_domain()

#: Pre-assembled app for direct module execution.
app = build_app(domains=[domain])


if __name__ == "__main__":
    app()
