"""Core buyer domain contribution for bare-metal purchases."""

from __future__ import annotations

from dataclasses import replace

from arkhai_bare_metal import make_bare_metal_provision_terms
from arkhai_bare_metal.domain_runtime import market_domain
from market_core import (
    BUYER_IDENTITY_INJECTION_CONTRACT,
    DomainCapability,
    ImmutableBuyerCapability,
    MarketDomainContract,
)


def _register_commands(app: object) -> None:
    from .cli import register_commands

    register_commands(app)


def _buyer_market_domain() -> MarketDomainContract:
    """Return the installed bare-metal buyer contract."""

    base = market_domain()
    buyer = ImmutableBuyerCapability(
        identity_injection_contract=BUYER_IDENTITY_INJECTION_CONTRACT,
        register_commands=_register_commands,
        build_provision_terms=make_bare_metal_provision_terms,
        select_policy=lambda configured: configured,
        decode_result=base.codecs.result,
    )
    return replace(
        base,
        declared_capabilities=frozenset(
            set(base.declared_capabilities) | {DomainCapability.BUYER}
        ),
        buyer=buyer,
    )


#: Loaded by ``market.buyer_domains`` discovery.
domain = _buyer_market_domain()
