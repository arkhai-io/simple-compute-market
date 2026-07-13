"""Core buyer role contracts and orchestration helpers."""

from core_buyer.plugins import DOMAIN_GROUP, discover_domains
from core_buyer.registry_config import (
    resolve_discovery_timeout,
    resolve_indexer_auth,
    resolve_indexer_urls,
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
    "DOMAIN_GROUP",
    "discover_domains",
    "resolve_discovery_timeout",
    "resolve_indexer_auth",
    "resolve_indexer_urls",
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
