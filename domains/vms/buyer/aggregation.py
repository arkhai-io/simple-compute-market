"""Compatibility shim — across-seller aggregation moved to
``core_buyer.aggregation`` when the API-tokens domain became the second
schema plugin. The policy registry, file discovery, and built-ins are
shared; tests that patch module internals target the core module."""

from core_buyer.aggregation import (  # noqa: F401
    AggregationPolicy,
    DEFAULT_POLICY_NAME,
    NegotiateFn,
    _REGISTRY,
    _default_policy_dir,
    _discover_file_policies,
    _extract_advertised_price,
    _load_buyer_config,
    _pick_min_agreed,
    _register_file_policy,
    _resolve_best_price_timeout,
    _resolve_extra_policy_paths,
    _sequential_first_agreed,
    gather_outcomes,
    list_aggregation_policies,
    load_aggregation_policy,
    register_aggregation_policy,
)
