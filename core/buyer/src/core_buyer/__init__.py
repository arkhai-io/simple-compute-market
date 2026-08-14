"""Core buyer role contracts and orchestration helpers."""

from core_buyer.action_policy import (
    ACTION_REQUIRED_EXIT_CODE,
    BuyerActionHandler,
    BuyerActionMetadata,
    BuyerActionPolicy,
    BuyerActionRequired,
    resolve_buyer_action_policy,
)

from core_buyer.buyer_config import (
    IDENTITY_CREDENTIAL_ENV,
    IdentityConfig,
    resolve_buyer_signer,
    resolve_identity_config,
    resolve_identity_credential,
)
from core_buyer.explanation import (
    EXPLANATION_SCHEMA_VERSION,
    build_buyer_explanation,
    format_buyer_explanation,
)
from core_buyer.orchestrator import (
    DEFAULT_HTTP_TIMEOUT,
    BuyConfig,
    BuyConstraints,
    BuyResult,
    NegotiateFn,
    RegistryDiscovery,
    RegistryQueryPlan,
    explain_registry_query,
    NegotiationResult,
    SettleFn,
    fetch_listing_dict,
    fetch_listing_dict_multi,
    query_registry_for_matches,
    query_registry_for_matches_multi,
    run_buy,
)
from core_buyer.plugins import DOMAIN_GROUP, discover_domains
from core_buyer.registry_config import (
    RegistryAuthority,
    resolve_discovery_timeout,
    resolve_indexer_urls,
    resolve_registry_api_keys,
    resolve_registry_authorities,
)
from core_buyer.settlement import (
    BuyerSettlementExplanation,
    BuyerSettlementPolicy,
    SelectedSettlementOption,
    SettlementClauseStage,
)

__all__ = [
    "ACTION_REQUIRED_EXIT_CODE",
    "DEFAULT_HTTP_TIMEOUT",
    "DOMAIN_GROUP",
    "IDENTITY_CREDENTIAL_ENV",
    "BuyConfig",
    "EXPLANATION_SCHEMA_VERSION",
    "BuyConstraints",
    "BuyResult",
    "BuyerActionHandler",
    "BuyerActionMetadata",
    "BuyerSettlementExplanation",
    "BuyerActionPolicy",
    "BuyerActionRequired",
    "BuyerSettlementPolicy",
    "IdentityConfig",
    "NegotiateFn",
    "NegotiationResult",
    "RegistryDiscovery",
    "RegistryQueryPlan",
    "RegistryAuthority",
    "SelectedSettlementOption",
    "SettleFn",
    "SettlementClauseStage",
    "build_buyer_explanation",
    "discover_domains",
    "fetch_listing_dict",
    "explain_registry_query",
    "format_buyer_explanation",
    "fetch_listing_dict_multi",
    "query_registry_for_matches",
    "query_registry_for_matches_multi",
    "resolve_buyer_signer",
    "resolve_discovery_timeout",
    "resolve_identity_config",
    "resolve_identity_credential",
    "resolve_indexer_urls",
    "resolve_registry_api_keys",
    "resolve_registry_authorities",
    "resolve_buyer_action_policy",
    "run_buy",
]
