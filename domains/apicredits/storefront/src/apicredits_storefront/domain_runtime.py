"""The API-credit market contract this storefront composes."""

from __future__ import annotations

from dataclasses import replace
from functools import partial

from arkhai_api_selling.negotiation import default_seller_round_hook

from apicredits_storefront.container import (
    ALKAHEST_STAGE,
    QUOTA_PUBLICATION,
    SELLER_STAGES,
    SELLING_CONTRIBUTIONS,
    get_sqlite_client,
)

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
    from arkhai_apicredits.domain_runtime import market_domain

    base = market_domain()
    capabilities = {
        DomainCapability.STOREFRONT,
        DomainCapability.PUBLICATION,
        DomainCapability.SETTLEMENT,
        DomainCapability.FULFILLMENT,
    }
    return validate_domain_contract(
        replace(
            base,
            declared_capabilities=base.declared_capabilities | capabilities,
            storefront=ImmutableStorefrontCapability(
                run_negotiation_policy=partial(
                    default_seller_round_hook,
                    SELLING_CONTRIBUTIONS,
                    normalize_escrow_proposal=ALKAHEST_STAGE.escrow_proposal_step,
                ),
            ),
            publication=ImmutablePublicationCapability(
                publish=lambda listing: QUOTA_PUBLICATION.publish(get_sqlite_client(), listing),
            ),
            settlement=ImmutableSettlementCapability(
                seller_stages=SELLER_STAGES,
            ),
            fulfillment=ImmutableFulfillmentCapability(
                fulfill=fulfill_credit_obligation,
            ),
        )
    )


#: Installed storefront-domain entry points load concrete validated contracts,
#: not factories. Keeping this immutable object module-local also ensures every
#: service in one process consumes the same composed capability set.
APICREDITS_STOREFRONT_DOMAIN = _build_market_domain_contract()


def get_market_domain_contract() -> MarketDomainContract:
    """Return the validated API-credit contract injected into this storefront."""
    return APICREDITS_STOREFRONT_DOMAIN
