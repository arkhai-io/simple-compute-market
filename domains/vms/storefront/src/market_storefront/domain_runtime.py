"""Storefront composition root for the VM market-domain contract."""

from __future__ import annotations
from dataclasses import replace

from market_core import (
    DomainCapability,
    ImmutableSettlementCapability,
    ImmutableStorefrontCapability,
    MarketDomainContract,
    validate_domain_contract,
)


def get_market_domain_contract() -> MarketDomainContract:
    """Return the validated VM contract injected into this storefront."""
    from arkhai_vms.domain_runtime import market_domain
    from core_storefront.escrow_verification import verify_escrow_for_settlement
    from domains.vms.negotiation.storefront_round import default_seller_round_hook
    from market_storefront.utils.sync_negotiation import (
        _accepted_escrow_artifacts,
    )

    base = market_domain()
    capabilities = {
        DomainCapability.STOREFRONT,
        DomainCapability.SETTLEMENT,
    }
    return validate_domain_contract(replace(
        base,
        declared_capabilities=base.declared_capabilities | capabilities,
        storefront=ImmutableStorefrontCapability(
            run_negotiation_policy=default_seller_round_hook,
        ),
        settlement=ImmutableSettlementCapability(
            verify=verify_escrow_for_settlement,
            build_plan=_accepted_escrow_artifacts,
        ),
    ))

