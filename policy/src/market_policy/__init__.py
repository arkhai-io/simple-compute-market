"""Shared negotiation machinery for buyer + seller.

Provides:
- A negotiation middleware chain (`NegotiationMiddleware`,
  `run_negotiation_chain`, `register_negotiation_middleware`,
  `load_negotiation_chain`) with built-in bisection terminal + guards
  (inventory match, escrow shape, max rounds).
- A negotiation thread store keyed off an injected `Identity`.

Both buyer and seller drive per-round negotiation through the same
chain abstraction. Data model is symmetric; nothing here depends on a
specific server runtime or protocol. The seller's chain is configured
in `[negotiation] chain = [...]`; the buyer's CLI builds its chain
internally per `[negotiation] policy_mode`.
"""

from market_policy.negotiation_middleware import (
    NegotiationContext,
    NegotiationDecision,
    NegotiationMiddleware,
    NegotiationRound,
    NegotiationStep,
    bisection_middleware,
    buyer_escrow_shape_guard,
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
    "buyer_escrow_shape_guard",
    "escrow_shape_guard",
    "has_matching_inventory_guard",
    "load_negotiation_chain",
    "max_rounds_guard",
    "register_negotiation_middleware",
    "run_negotiation_chain",
]
