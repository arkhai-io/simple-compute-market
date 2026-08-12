"""VM market-domain contribution for the core ``market`` buyer CLI."""

from __future__ import annotations

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
from .chain_cli import chain_app
from .config_cli import config_app
from .logs_cli import logs_app
from .network_cli import network_app
from . import negotiate_cli as negotiate_module
from . import settle_cli as settle_module
from . import service_cli as service_module
from .escrow_cli import escrow_app
from .listing_cli import listing_app


def register(app: typer.Typer) -> None:
    """Register the VM compute schema's buyer commands on the core app."""
    app.add_typer(
        listing_app, name="listing", help="Browse marketplace listings (list/show)."
    )
    app.add_typer(
        config_app,
        name="config",
        help="Inspect or edit the buyer.toml (path/show/get/set/init-user).",
    )
    app.add_typer(
        logs_app,
        name="logs",
        help="Inspect past buy/negotiate runs (run-log JSONL files).",
    )
    app.add_typer(
        escrow_app, name="escrow", help="Buyer-side escrow lifecycle (create, reclaim)."
    )
    app.add_typer(
        network_app,
        name="network",
        help="Join the operator's ZeroTier network and list peers.",
    )
    app.add_typer(
        chain_app,
        name="chain",
        help="Sanity-check chain config (eth_getCode against configured addresses).",
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
