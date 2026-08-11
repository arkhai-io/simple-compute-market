"""Bare-metal market-domain contract selected by the storefront process."""

from __future__ import annotations

from dataclasses import replace

from arkhai_bare_metal.domain_runtime import market_domain
from core_storefront.escrow_verification import verify_escrow_for_settlement
from market_core import (
    DomainCapability,
    ImmutableSettlementCapability,
    ImmutableStorefrontCapability,
    MarketDomainContract,
    validate_domain_contract,
)

from .negotiation import default_seller_round_hook
from .settlement import build_bare_metal_settlement_plan


def _build_market_domain_contract() -> MarketDomainContract:
    """Build the validated capabilities implemented by this composition."""
    base = market_domain()
    return validate_domain_contract(
        replace(
            base,
            declared_capabilities=(
                (
                    base.declared_capabilities
                    | {
                        DomainCapability.STOREFRONT,
                        DomainCapability.SETTLEMENT,
                    }
                )
                - {DomainCapability.FULFILLMENT}
            ),
            storefront=ImmutableStorefrontCapability(
                run_negotiation_policy=default_seller_round_hook,
            ),
            settlement=ImmutableSettlementCapability(
                verify=verify_escrow_for_settlement,
                build_plan=build_bare_metal_settlement_plan,
            ),
            fulfillment=None,
        ),
    )


BARE_METAL_STOREFRONT_DOMAIN = _build_market_domain_contract()


def get_market_domain_contract() -> MarketDomainContract:
    """Return the immutable contract injected into the storefront shell."""
    return BARE_METAL_STOREFRONT_DOMAIN
