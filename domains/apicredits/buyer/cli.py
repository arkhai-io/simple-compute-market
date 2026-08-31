"""API-credit market-domain contribution for the core ``market`` buyer CLI."""

from __future__ import annotations
import asyncio
import json

from dataclasses import replace

import typer

from core_buyer.cli import build_app
from core_buyer.policy_surface import configured_buyer_policy
from domains.apicredits.domain_runtime import market_domain
from domains.apicredits.negotiation import make_api_credits_provision_terms
from market_core import (
    BUYER_IDENTITY_INJECTION_CONTRACT,
    DomainCapability,
    ImmutableBuyerCapability,
    MarketDomainContract,
)

from . import buy_cli as buy_module
from . import negotiate_cli as negotiate_module
from . import settle_cli as settle_module
from .listing_cli import listing_app
from .settlement_composition import (
    buyer_settlement_readiness,
    buyer_settlement_registry,
)


def _settlement_status(
    as_json: bool = typer.Option(False, "--json", help="Emit sanitized JSON."),
) -> None:
    config, statuses = asyncio.run(buyer_settlement_readiness())
    if as_json:
        typer.echo(
            json.dumps(
                {
                    "schema_version": config.schema_version,
                    "priority": list(config.priority),
                    "mechanisms": [status.safe_projection() for status in statuses],
                },
                separators=(",", ":"),
                sort_keys=True,
            )
        )
    else:
        for status in statuses:
            state = (
                "ready"
                if status.ready
                else "disabled"
                if not status.enabled
                else "unready"
            )
            typer.echo(f"{status.mechanism}: {state}")
            for blocker in status.blockers:
                typer.echo(f"  {blocker.code}: {blocker.message}")
    if not any(status.ready for status in statuses):
        raise typer.Exit(1)


credits_app = typer.Typer(no_args_is_help=True)
credits_app.add_typer(
    listing_app,
    name="listing",
    help="Browse API-credit listings (list/show).",
)
buy_module.register(credits_app)
negotiate_module.register(credits_app)
settle_module.register(credits_app)
settlement_app = typer.Typer(
    no_args_is_help=True,
    help="Shared settlement profile and readiness commands.",
)
settlement_app.command("status")(_settlement_status)
for registration in buyer_settlement_registry().registrations:
    if registration.command_group is not None:
        settlement_app.add_typer(
            registration.command_group,
            name=registration.config_key,
        )
credits_app.add_typer(settlement_app, name="settlement")


def register(app: typer.Typer) -> None:
    """Register the API-credits schema's buyer commands on the core app."""
    app.add_typer(
        credits_app,
        name="credits",
        help="API-credit market: discover, buy, top up keys.",
    )


def _buyer_market_domain() -> MarketDomainContract:
    base = market_domain()
    return replace(
        base,
        declared_capabilities=(base.declared_capabilities | {DomainCapability.BUYER}),
        buyer=ImmutableBuyerCapability(
            identity_injection_contract=BUYER_IDENTITY_INJECTION_CONTRACT,
            register_commands=register,
            build_provision_terms=make_api_credits_provision_terms,
            select_policy=configured_buyer_policy,
            decode_result=base.codecs.result,
        ),
    )


#: Loaded by ``market.buyer_domains`` discovery.
domain = _buyer_market_domain()

#: Pre-assembled app for direct module execution.
app = build_app(domains=[domain])


if __name__ == "__main__":
    app()
