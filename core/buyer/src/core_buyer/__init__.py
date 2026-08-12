"""Core buyer role contracts and orchestration helpers."""

from core_buyer.plugins import DOMAIN_GROUP, discover_domains
from core_buyer.registry_config import (
    RegistryAuthority,
    resolve_discovery_timeout,
    resolve_indexer_urls,
    resolve_registry_api_keys,
    resolve_registry_authorities,
)
from core_buyer.buyer_config import (
    IDENTITY_CREDENTIAL_ENV,
    IdentityConfig,
    resolve_buyer_signer,
    resolve_identity_config,
    resolve_identity_credential,
)
from core_buyer.orchestrator import (
    DEFAULT_HTTP_TIMEOUT,
    BuyConfig,
    BuyConstraints,
    BuyResult,
    NegotiationResult,
    NegotiateFn,
    SettleFn,
    fetch_listing_dict,
    fetch_listing_dict_multi,
    query_registry_for_matches,
    query_registry_for_matches_multi,
    run_buy,
)

__all__ = [
    "RegistryAuthority",
    "DOMAIN_GROUP",
    "discover_domains",
    "resolve_discovery_timeout",
    "resolve_registry_api_keys",
    "resolve_registry_authorities",
    "resolve_indexer_urls",
    "IDENTITY_CREDENTIAL_ENV",
    "IdentityConfig",
    "resolve_buyer_signer",
    "resolve_identity_config",
    "resolve_identity_credential",
    "DEFAULT_HTTP_TIMEOUT",
    "BuyConfig",
    "BuyConstraints",
    "BuyResult",
    "NegotiationResult",
    "NegotiateFn",
    "SettleFn",
    "fetch_listing_dict",
    "fetch_listing_dict_multi",
    "query_registry_for_matches",
    "query_registry_for_matches_multi",
    "run_buy",
]
