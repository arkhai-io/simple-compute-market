"""Domain-agnostic policy engine.

Provides:
- A callable registry (`@policy_callable`) plus discovery helpers.
- A composable policy store backed by a persistence port.
- A negotiation thread store keyed off an injected `Identity`.
- Action builders that produce symmetric, transport-agnostic outputs.
- A swappable per-round negotiation strategy interface (bisection +
  pluggable RL via entry points / register_strategy).

Both buyer and provider can drive negotiation through this engine; the
data model is symmetric and nothing here depends on a specific server
runtime or protocol.
"""

from market_policy.negotiation_strategy import (
    BisectionStrategy,
    DEFAULT_MAX_ROUNDS,
    DEFAULT_STRATEGY,
    NegotiationDecision,
    NegotiationRound,
    NegotiationRoundInput,
    NegotiationStrategy,
    load_strategy,
    register_strategy,
)

__all__ = [
    "BisectionStrategy",
    "DEFAULT_MAX_ROUNDS",
    "DEFAULT_STRATEGY",
    "NegotiationDecision",
    "NegotiationRound",
    "NegotiationRoundInput",
    "NegotiationStrategy",
    "load_strategy",
    "register_strategy",
]
