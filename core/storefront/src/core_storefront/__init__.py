"""Storefront protocol helpers owned by market core."""

from .domain_plugins import (
    STOREFRONT_CONTRIBUTION_GROUP,
    StorefrontContributionSelection,
    StorefrontDomainContribution,
    discover_storefront_domain_registry,
    parse_storefront_contribution_selections,
)
from .domain_lifecycle import (
    StorefrontDomainLifecycleError,
    StorefrontFulfillmentContext,
    StorefrontFulfillmentLifecycle,
    StorefrontFulfillmentPorts,
    StorefrontSettlementArtifacts,
    StorefrontSettlementBuildContext,
    build_domain_settlement_artifacts,
    fulfill_domain,
)
from .domain_registry import (
    DomainContractKey,
    PreparedStorefrontDomainArtifact,
    StorefrontDomainBinding,
    StorefrontDomainRegistration,
    StorefrontDomainRegistry,
    StorefrontListingBinding,
    StorefrontThreadBinding,
    build_storefront_derivation_key,
    canonical_source_envelope,
)

__all__ = [
    "DomainContractKey",
    "StorefrontDomainLifecycleError",
    "StorefrontFulfillmentContext",
    "StorefrontFulfillmentLifecycle",
    "StorefrontFulfillmentPorts",
    "StorefrontSettlementArtifacts",
    "StorefrontSettlementBuildContext",
    "PreparedStorefrontDomainArtifact",
    "STOREFRONT_CONTRIBUTION_GROUP",
    "StorefrontContributionSelection",
    "StorefrontDomainBinding",
    "StorefrontDomainContribution",
    "StorefrontDomainRegistration",
    "StorefrontDomainRegistry",
    "StorefrontListingBinding",
    "StorefrontThreadBinding",
    "build_storefront_derivation_key",
    "build_domain_settlement_artifacts",
    "fulfill_domain",
    "canonical_source_envelope",
    "discover_storefront_domain_registry",
    "parse_storefront_contribution_selections",
]
