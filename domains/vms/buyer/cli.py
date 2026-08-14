"""VM market-domain contribution for the core ``market`` buyer CLI."""

from __future__ import annotations
import asyncio
import json

from dataclasses import replace

import typer
from arkhai_vms import make_vm_provision_terms
from arkhai_vms.domain_runtime import market_domain
from core_buyer.cli import build_app
from market_core import (
    DomainCapability,
    ImmutableBuyerCapability,
    MarketDomainContract,
)

from . import buy_cli as buy_module
from . import negotiate_cli as negotiate_module
from . import service_cli as service_module
from . import settle_cli as settle_module
from .config_cli import config_app
from .listing_cli import listing_app
from .logs_cli import logs_app
from .settlement_composition import (
    buyer_settlement_readiness,
    buyer_settlement_registry,
)
from .network_cli import network_app


def _settlement_status(
    as_json: bool = typer.Option(False, "--json", help="Emit sanitized JSON."),
) -> None:
    """Observe every installed buyer settlement mechanism without mutation."""

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


def register(app: typer.Typer) -> None:
    """Register the VM compute schema's buyer commands on the core app."""
    app.add_typer(
        listing_app, name="listing", help="Browse marketplace listings (list/show)."
    )
    app.add_typer(
        config_app,
        name="config",
        help="Inspect, edit, initialize, or migrate the buyer.toml.",
    )
    app.add_typer(
        logs_app,
        name="logs",
        help="Inspect past buy/negotiate runs (run-log JSONL files).",
    )
    settlement_app = typer.Typer(
        no_args_is_help=True,
        help="Mechanism-owned raw settlement utilities.",
    )
    settlement_app.command("status")(_settlement_status)
    for registration in buyer_settlement_registry().registrations:
        if registration.command_group is None:
            continue
        settlement_app.add_typer(
            registration.command_group,
            name=registration.config_key,
        )
    app.add_typer(settlement_app, name="settlement")
    app.add_typer(
        network_app,
        name="network",
        help="Join the operator's ZeroTier network and list peers.",
    )

    buy_module.register(app)
    negotiate_module.register(app)
    settle_module.register(app)
    service_module.register(app)


def _buyer_market_domain() -> MarketDomainContract:
    base = market_domain()
    from .policy_surface import configured_buyer_policy

    return replace(
        base,
        declared_capabilities=(base.declared_capabilities | {DomainCapability.BUYER}),
        buyer=ImmutableBuyerCapability(
            register_commands=register,
            build_provision_terms=make_vm_provision_terms,
            select_policy=configured_buyer_policy,
            decode_result=base.codecs.result,
        ),
    )


#: Loaded by ``market.buyer_domains`` discovery.
domain = _buyer_market_domain()

#: Pre-assembled app for the PyInstaller binary, which cannot rely on installed
#: entry-point metadata inside the frozen bundle.
app = build_app(domains=[domain])


if __name__ == "__main__":
    app()
