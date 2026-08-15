"""Installed contribution consumed by the shared storefront shell."""

from core_storefront.domain_plugins import StorefrontDomainContribution

from .domain_runtime import get_market_domain_contract


BARE_METAL_STOREFRONT_CONTRIBUTION = StorefrontDomainContribution(
    contribution_id="bare_metal",
    build_contract=get_market_domain_contract,
)
