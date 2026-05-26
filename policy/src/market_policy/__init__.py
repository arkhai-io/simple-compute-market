"""Domain-agnostic policy engine.

Provides:
- A callable registry (`@policy_callable`) plus discovery helpers.
- A composable policy store backed by a persistence port.
- A negotiation thread store keyed off an injected `Identity`.
- A symmetric negotiation middleware chain (`NegotiationMiddleware`,
  `run_negotiation_chain`) with built-in bisection terminal + ported
  guards (inventory match, escrow shape, max rounds).

Both buyer and provider drive negotiation through the same chain
abstraction. Data model is symmetric; nothing here depends on a
specific server runtime or protocol.
"""

from market_policy.negotiation_middleware import (
    NegotiationContext,
    NegotiationDecision,
    NegotiationMiddleware,
    NegotiationRound,
    NegotiationStep,
    bisection_middleware,
    escrow_shape_guard,
    has_matching_inventory_guard,
    load_negotiation_chain,
    max_rounds_guard,
    register_negotiation_middleware,
    run_negotiation_chain,
)

__all__ = [
    "NegotiationContext",
    "NegotiationDecision",
    "NegotiationMiddleware",
    "NegotiationRound",
    "NegotiationStep",
    "bisection_middleware",
    "escrow_shape_guard",
    "has_matching_inventory_guard",
    "load_negotiation_chain",
    "max_rounds_guard",
    "register_negotiation_middleware",
    "run_negotiation_chain",
]
