"""Bare-metal market-domain contract selected by the storefront process."""

from __future__ import annotations

from dataclasses import replace

from arkhai_bare_metal.domain_runtime import market_domain
from market_alkahest import create_alkahest_registration
from core_storefront import StorefrontSettlementBuildContext
from market_core import (
    DomainCapability,
    ImmutableSettlementCapability,
    ImmutableFulfillmentCapability,
    ImmutableStorefrontCapability,
    MarketDomainContract,
    validate_domain_contract,
)

from .negotiation import default_seller_round_hook
from .settlement import build_bare_metal_settlement_plan
from .fulfillment_service import fulfill_bare_metal


def _build_settlement_from_context(
    *,
    context: StorefrontSettlementBuildContext,
) -> dict[str, object]:
    return build_bare_metal_settlement_plan(
        proposal=context.proposal,
        agreed_amount=context.agreed_amount,
        duration_seconds=context.duration_seconds,
        buyer_principal=context.buyer_principal,
        seller_principal=context.seller_principal,
        seller_wallet_address=context.seller_wallet_address,
        chain_config_paths=context.chain_config_paths,
    )


def _build_market_domain_contract() -> MarketDomainContract:
    """Build the validated capabilities implemented by this composition."""
    base = market_domain()
    return validate_domain_contract(
        replace(
            base,
            declared_capabilities=(
                base.declared_capabilities
                | {
                    DomainCapability.STOREFRONT,
                    DomainCapability.SETTLEMENT,
                    DomainCapability.FULFILLMENT,
                }
            ),
            storefront=ImmutableStorefrontCapability(
                run_negotiation_policy=default_seller_round_hook,
            ),
            settlement=ImmutableSettlementCapability(
                verify=create_alkahest_registration().settlement_verifier,
                build_plan=_build_settlement_from_context,
            ),
            fulfillment=ImmutableFulfillmentCapability(
                fulfill=fulfill_bare_metal,
            ),
        ),
    )


BARE_METAL_STOREFRONT_DOMAIN = _build_market_domain_contract()


def get_market_domain_contract() -> MarketDomainContract:
    """Return the immutable contract injected into the storefront shell."""
    return BARE_METAL_STOREFRONT_DOMAIN
