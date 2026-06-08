"""Shared negotiation machinery for buyer + seller."""

from market_policy.negotiation_middleware import (
    NegotiationContext,
    NegotiationDecision,
    NegotiationMiddleware,
    NegotiationRound,
    NegotiationStep,
    load_negotiation_chain,
    max_rounds_guard,
    normalize_policies_by_escrow_kind_config,
    normalize_policy_chain_config,
    register_negotiation_middleware,
    run_negotiation_chain,
)

__all__ = [
    "NegotiationContext",
    "NegotiationDecision",
    "NegotiationMiddleware",
    "NegotiationRound",
    "NegotiationStep",
    "load_negotiation_chain",
    "max_rounds_guard",
    "normalize_policies_by_escrow_kind_config",
    "normalize_policy_chain_config",
    "register_negotiation_middleware",
    "run_negotiation_chain",
]

try:
    from market_policy.negotiation_middleware import (
        accept_exact_listing_middleware,
        amount_bisection_middleware,
        bisection_middleware,
        buyer_escrow_shape_guard,
        escrow_shape_guard,
        has_matching_inventory_guard,
        make_escrow_kind_dispatch_middleware,
    )
except ImportError:
    pass
else:
    __all__.extend(
        [
            "accept_exact_listing_middleware",
            "amount_bisection_middleware",
            "bisection_middleware",
            "buyer_escrow_shape_guard",
            "escrow_shape_guard",
            "has_matching_inventory_guard",
            "make_escrow_kind_dispatch_middleware",
        ]
    )
