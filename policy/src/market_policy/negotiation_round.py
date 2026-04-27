"""Per-round negotiation decision logic.

A pure function (`decide_response`) plus its result type
(`SellerDecision`). No DB, no registry, no async — given strategy,
our price, the peer's proposed price, and the history of our counters,
return what to do this round.

This module is the engine's owner of the round-level decision. The
storefront's `/negotiate/*` endpoints and the buyer CLI's negotiate
loop both call into here so a single source of truth governs round
behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


# Constants are deliberately exposed (not inlined) so callers can
# override per-call when needed (e.g., experimental policy modes that
# want to widen the convergence ratio).
DEFAULT_MAX_ROUNDS = 10
DEFAULT_CONVERGENCE_RATIO = 0.01  # accept when peer price is within 1% of ours


@dataclass(frozen=True)
class SellerDecision:
    """One side's resulting decision for a single negotiation round.

    Named "Seller" for historical reasons — the same shape applies to
    either party's per-round output. Renaming is deferred to avoid
    churning the storefront's response wire format.
    """

    action: str  # "counter" | "accept" | "exit" | "reject"
    price: int | None = None        # set when action in {counter, accept}
    reason: str | None = None       # set when action in {exit, reject, accept}

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"action": self.action}
        if self.price is not None:
            d["price"] = self.price
        if self.reason is not None:
            d["reason"] = self.reason
        return d


def decide_response(
    *,
    strategy: str,
    our_price: int,
    their_proposed_price: int,
    our_previous_counters: list[int],
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    convergence_ratio: float = DEFAULT_CONVERGENCE_RATIO,
) -> SellerDecision:
    """Pure policy decision for a single negotiation round.

    `strategy` is "minimize" when we want a lower peer price (e.g., we
    are buying compute and the peer is selling) and "maximize" when we
    want a higher peer price (we are selling). The same function
    serves either party — the strategy field encodes which side of the
    trade we're on, not which role we play in the broader market.

    `our_previous_counters` is the prices we've counter-proposed so far
    in this thread, in order. Used for round + stale guards.
    """
    # Round guard: walk away if we've hit the cap.
    if len(our_previous_counters) >= max_rounds:
        return SellerDecision(action="exit", reason="max_rounds")
    # Stale-price guard: if our last two counters were identical we've
    # converged on an offer the peer won't move off — end the thread.
    if len(our_previous_counters) >= 2 and our_previous_counters[-1] == our_previous_counters[-2]:
        return SellerDecision(action="exit", reason="stale_negotiation")

    if strategy == "minimize":
        if their_proposed_price <= our_price * (1 + convergence_ratio):
            return SellerDecision(
                action="accept", price=their_proposed_price, reason="convergence",
            )
        if their_proposed_price <= our_price * 1.5:
            proposed = (our_price + their_proposed_price) // 2
            return SellerDecision(action="counter", price=proposed)
        return SellerDecision(action="exit", reason="price_unreasonable")

    if strategy == "maximize":
        if their_proposed_price >= our_price * (1 - convergence_ratio):
            return SellerDecision(
                action="accept", price=their_proposed_price, reason="convergence",
            )
        if their_proposed_price >= our_price / 1.5:
            proposed = (our_price + their_proposed_price) // 2
            return SellerDecision(action="counter", price=proposed)
        return SellerDecision(action="exit", reason="price_unreasonable")

    return SellerDecision(action="reject", reason=f"unknown_strategy:{strategy!r}")
