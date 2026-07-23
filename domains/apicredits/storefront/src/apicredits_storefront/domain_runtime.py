"""Storefront composition root for the API-credit market-domain contract."""

from __future__ import annotations
from dataclasses import replace

from market_core import (
    DomainCapability,
    ImmutableFulfillmentCapability,
    ImmutablePublicationCapability,
    ImmutableSettlementCapability,
    ImmutableStorefrontCapability,
    MarketDomainContract,
    validate_domain_contract,
)


def _build_market_domain_contract() -> MarketDomainContract:
    """Build and validate the API-credit contract for the storefront role."""
    from apicredits_storefront.services.fulfillment_service import (
        fulfill_credit_obligation,
    )
    from apicredits_storefront.services.publication_service import (
        publish_order_to_registry,
    )
    from apicredits_storefront.utils.sync_negotiation import (
        _accepted_escrow_artifacts,
    )
    from core_storefront.escrow_verification import verify_escrow_for_settlement
    from domains.apicredits.domain_runtime import market_domain
    from domains.apicredits.negotiation.storefront_round import (
        default_seller_round_hook,
    )

    base = market_domain()
    capabilities = {
        DomainCapability.STOREFRONT,
        DomainCapability.PUBLICATION,
        DomainCapability.SETTLEMENT,
        DomainCapability.FULFILLMENT,
    }
    return validate_domain_contract(replace(
        base,
        declared_capabilities=base.declared_capabilities | capabilities,
        storefront=ImmutableStorefrontCapability(
            run_negotiation_policy=default_seller_round_hook,
        ),
        publication=ImmutablePublicationCapability(
            publish=publish_order_to_registry,
        ),
        settlement=ImmutableSettlementCapability(
            verify=verify_escrow_for_settlement,
            build_plan=_accepted_escrow_artifacts,
        ),
        fulfillment=ImmutableFulfillmentCapability(
            fulfill=fulfill_credit_obligation,
        ),
    ))


#: Installed storefront-domain entry points load concrete validated contracts,
#: not factories. Keeping this immutable object module-local also ensures every
#: service in one process consumes the same composed capability set.
APICREDITS_STOREFRONT_DOMAIN = _build_market_domain_contract()


def get_market_domain_contract() -> MarketDomainContract:
    """Return the validated API-credit contract injected into this storefront."""
    return APICREDITS_STOREFRONT_DOMAIN
