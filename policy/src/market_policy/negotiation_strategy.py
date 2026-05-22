"""Negotiation strategy interface — symmetric, swappable, side-agnostic.

A negotiation strategy decides what to do for one round given the
current price proposal and history. The interface is identical for
buyer and seller; the asymmetry is captured by ``direction`` plus the
conventional reading of ``our_reference_price``.

A strategy implementation is just a Python object exposing
``decide(NegotiationRoundInput) -> NegotiationDecision``. Strategies
can be stateless functions wrapped in a class, or hold expensive
resources (loaded torch models, RPC clients) initialized once at
``__init__`` and reused across many decisions.

Loading by name::

    from market_policy.negotiation_strategy import load_strategy
    strategy = load_strategy("rl", config={"seller_model_path": "..."})
    decision = strategy.decide(round_input)

Registering a strategy from outside (e.g. a compute-domain torch
strategy that lives in domain/compute and self-registers when its
module is imported)::

    from market_policy.negotiation_strategy import register_strategy
    register_strategy("my.strategy.v2", lambda cfg: MyStrategy(**cfg))

Third-party plugins should publish a Python entry point in the group
``market_policy.negotiation_strategies``; ``load_strategy`` consults
that group as a fallback after the in-process registry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Protocol


# ---------------------------------------------------------------------------
# Inputs / outputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NegotiationRound:
    """One round's transcript entry. Both parties contribute one of these per round."""

    round_number: int
    sender: Literal["us", "them"]
    action: Literal["initial", "counter", "accept", "exit", "reject"]
    price: float | None = None  # set for initial / counter / accept; base units per hour


@dataclass(frozen=True)
class NegotiationRoundInput:
    """What a strategy sees when asked to decide.

    Symmetric — applies whether we're the buyer (``direction="minimize"``,
    minimizing the peer's price) or the seller (``direction="maximize"``,
    maximizing it). The asymmetry is one field plus the conventional
    reading of ``our_reference_price``:

    - ``minimize``: ``our_reference_price`` is our ceiling — we won't
      pay more.
    - ``maximize``: ``our_reference_price`` is our floor — we won't
      accept less.
    """

    direction: Literal["minimize", "maximize"]
    our_reference_price: float
    their_proposed_price: float | None  # None on the very first call (we open)
    history: list[NegotiationRound] = field(default_factory=list)
    max_rounds: int = 10

    @property
    def our_previous_counters(self) -> list[float]:
        """Prices we've counter-proposed in earlier rounds, oldest first."""
        return [
            h.price for h in self.history
            if h.sender == "us" and h.action == "counter" and h.price is not None
        ]


@dataclass(frozen=True)
class NegotiationDecision:
    """One round's resulting decision. Symmetric for both sides."""

    action: Literal["accept", "counter", "exit", "reject"]
    price: float | None = None  # required for counter / accept; base units per hour
    reason: str | None = None  # required for exit / reject; optional otherwise

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"action": self.action}
        if self.price is not None:
            d["price"] = self.price
        if self.reason is not None:
            d["reason"] = self.reason
        return d


class NegotiationStrategy(Protocol):
    """The contract third-party strategies implement.

    ``decide`` must be:
    - Sync: simple to call from both async (storefront) and sync (CLI)
      code paths. Slow strategies wrap themselves in ``asyncio.to_thread``
      at the caller boundary.
    - Pure with respect to the input: same ``NegotiationRoundInput``
      yields the same decision (or the same distribution, for
      stochastic strategies).
    - Side-effect-free: no logging beyond debug, no I/O, no state
      writes. The caller logs the decision into the run-log and the
      thread store.
    """

    def decide(self, ri: NegotiationRoundInput) -> NegotiationDecision: ...


# ---------------------------------------------------------------------------
# Built-in: bisection strategy (port of the old decide_response /
# decide_buyer_response, unified via direction)
# ---------------------------------------------------------------------------


DEFAULT_MAX_ROUNDS = 10
DEFAULT_CONVERGENCE_RATIO = 0.01  # accept when peer is within 1% of our reference
DEFAULT_REASONABLE_MULTIPLIER = 1.5  # exit when peer is more than 1.5× off our reference


class BisectionStrategy:
    """Simple price-midpoint counter-offer with convergence + stale guards.

    The historical default. Rule-based, deterministic, no model files.

    For ``direction="minimize"`` (buyer-shape): accept if peer price ≤
    our ceiling × (1 + ε); counter at the midpoint of (our_ceiling,
    their_price), clamped to ≤ our_ceiling; exit if peer price > our
    ceiling × 1.5.

    For ``direction="maximize"`` (seller-shape): accept if peer price ≥
    our floor × (1 - ε); counter at the midpoint of (our_floor,
    their_price); exit if peer price < our_floor / 1.5.

    Both sides exit after ``max_rounds`` rounds or two consecutive
    identical counters (stale-counter guard).
    """

    def __init__(
        self,
        *,
        convergence_ratio: float = DEFAULT_CONVERGENCE_RATIO,
        reasonable_multiplier: float = DEFAULT_REASONABLE_MULTIPLIER,
    ) -> None:
        self._conv = convergence_ratio
        self._reasonable = reasonable_multiplier

    def decide(self, ri: NegotiationRoundInput) -> NegotiationDecision:
        our_counters = ri.our_previous_counters

        if len(our_counters) >= ri.max_rounds:
            return NegotiationDecision(action="exit", reason="max_rounds")
        if len(our_counters) >= 2 and our_counters[-1] == our_counters[-2]:
            return NegotiationDecision(action="exit", reason="stale_negotiation")

        our_price = ri.our_reference_price
        their_price = ri.their_proposed_price
        if their_price is None:
            # First round: open with our reference (ceiling for minimize,
            # floor for maximize).
            return NegotiationDecision(action="counter", price=our_price)

        if ri.direction == "minimize":
            if their_price <= our_price * (1 + self._conv):
                return NegotiationDecision(
                    action="accept", price=their_price, reason="convergence",
                )
            if their_price <= our_price * self._reasonable:
                proposed = (our_price + their_price) / 2
                if proposed > our_price:
                    proposed = our_price  # never counter above our ceiling
                return NegotiationDecision(action="counter", price=proposed)
            return NegotiationDecision(action="exit", reason="price_unreasonable")

        if ri.direction == "maximize":
            if their_price >= our_price * (1 - self._conv):
                return NegotiationDecision(
                    action="accept", price=their_price, reason="convergence",
                )
            if their_price >= our_price / self._reasonable:
                proposed = (our_price + their_price) / 2
                return NegotiationDecision(action="counter", price=proposed)
            return NegotiationDecision(action="exit", reason="price_unreasonable")

        return NegotiationDecision(action="reject", reason=f"unknown_direction:{ri.direction!r}")


# ---------------------------------------------------------------------------
# Registry + loader
# ---------------------------------------------------------------------------


# Default strategy when no name is configured. Set to the trained RL
# strategy so production deployments and integration tests get the
# learned policy by default; opt-out by configuring "bisection".
DEFAULT_STRATEGY = "rl"


_REGISTRY: dict[str, Callable[[dict[str, Any]], NegotiationStrategy]] = {
    "bisection": lambda cfg: BisectionStrategy(**cfg),
}


def register_strategy(
    name: str,
    factory: Callable[[dict[str, Any]], NegotiationStrategy],
) -> None:
    """Register a strategy factory under ``name``.

    Used by in-tree extensions (e.g. the compute-domain torch strategy)
    that aren't separately packaged with their own entry point. Call at
    module import time so the strategy becomes available as a side
    effect of importing its module.
    """
    _REGISTRY[name] = factory


def load_strategy(
    name: str | None = None,
    config: dict[str, Any] | None = None,
) -> NegotiationStrategy:
    """Construct a strategy by name + optional config dict.

    Lookup order:
    1. In-process ``_REGISTRY`` (built-ins + anything ``register_strategy``'d).
    2. Python entry points in group ``market_policy.negotiation_strategies``.

    Raises ``KeyError`` with an actionable message if not found.
    """
    name = name or DEFAULT_STRATEGY
    cfg = config or {}

    if name in _REGISTRY:
        return _REGISTRY[name](cfg)

    # Third-party plugins via Python entry points
    try:
        import importlib.metadata as md
        eps = md.entry_points(group="market_policy.negotiation_strategies")
    except Exception:
        eps = []
    for ep in eps:
        if ep.name == name:
            return ep.load()(cfg)

    available = sorted(_REGISTRY.keys())
    raise KeyError(
        f"Unknown negotiation strategy: {name!r}. "
        f"Built-in / registered strategies: {available}. "
        f"For 'rl', the torch_arkhai_strategy module needs to be importable "
        f"(install with [rl] extras and ensure domain.compute is on path)."
    )
