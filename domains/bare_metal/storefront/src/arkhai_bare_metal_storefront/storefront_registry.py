"""The bare-metal storefront's one domain registration."""

from __future__ import annotations

from core_storefront.domain_registry import (
    StorefrontDomainRegistration,
    StorefrontDomainRegistry,
)
from market_core import MarketDomainContract


def build_bare_metal_storefront_registry(
    *,
    domain: MarketDomainContract,
) -> StorefrontDomainRegistry:
    """Build the explicit one-registration bare-metal storefront registry."""

    return StorefrontDomainRegistry(
        (
            StorefrontDomainRegistration(
                offering_mode="bare_metal",
                contract=domain,
                contribution_id="bare_metal",
            ),
        )
    )
