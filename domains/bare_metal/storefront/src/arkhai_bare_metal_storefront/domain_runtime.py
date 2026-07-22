"""Bare-metal market-domain contract selected by the storefront process."""

from __future__ import annotations

from arkhai_bare_metal.domain_runtime import market_domain
from market_core import MarketDomainContract, validate_domain_contract


def _build_market_domain_contract() -> MarketDomainContract:
    """Validate the capabilities currently implemented by the composition."""
    return validate_domain_contract(market_domain())


BARE_METAL_STOREFRONT_DOMAIN = _build_market_domain_contract()


def get_market_domain_contract() -> MarketDomainContract:
    """Return the immutable contract injected into the storefront shell."""
    return BARE_METAL_STOREFRONT_DOMAIN
