"""Compute-domain torch-based negotiation strategy.

Replaces the legacy ``negotiation_action_torch_arkhai`` policy callable
that fired on the (now-removed) NegotiationEvent. Conforms to the
asymmetric ``NegotiationStrategy`` interface: takes a
``NegotiationRoundInput`` and returns a ``NegotiationDecision``.

Loads one of two pufferlib checkpoints based on ``direction``:
- ``maximize`` (seller-side): ``arkhai_negotiator_seller.pt``
- ``minimize`` (buyer-side):  ``arkhai_negotiator_buyer.pt``

Self-registers under the name ``"rl"`` when this module is imported,
so callers just need to ensure the module loads at startup. The
storefront's runtime imports the compute-domain policy package as part
of its own initialization; the buyer CLI does the same when its
[rl]-installed startup hook fires.

Model files are optional via env vars:
    ARKHAI_NEGOTIATOR_SELLER_MODEL_PATH
    ARKHAI_NEGOTIATOR_BUYER_MODEL_PATH

Falls back to checkpoints shipped under
``domain/compute/agent/app/policy/models/``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from market_policy.negotiation_strategy import (
    NegotiationDecision,
    NegotiationRoundInput,
    register_strategy,
)

logger = logging.getLogger(__name__)

_DEFAULT_SELLER_MODEL_PATH = (
    Path(__file__).resolve().parent / "models" / "arkhai_negotiator_seller.pt"
)
_DEFAULT_BUYER_MODEL_PATH = (
    Path(__file__).resolve().parent / "models" / "arkhai_negotiator_buyer.pt"
)

# 9 price multipliers around our_reference_price, -20% to +20% in 5% steps
_MULTIPLIERS = [-0.20, -0.15, -0.10, -0.05, 0.00, +0.05, +0.10, +0.15, +0.20]

CONVERGENCE_RATIO = 0.01
REASONABLE_MULTIPLIER = 1.5


class TorchArkhaiStrategy:
    """RL negotiation policy using bilateral pufferlib checkpoints.

    Picks model by ``ri.direction`` (one for seller, one for buyer).
    Builds a price-anchored observation, runs a torch forward pass,
    decodes a price-multiplier index, and applies the same convergence
    / reasonable-range thresholds as ``BisectionStrategy`` to wrap the
    multiplier in an accept / counter / exit decision.

    Constructor accepts optional explicit model paths; otherwise reads
    env vars or falls back to the bundled defaults.
    """

    def __init__(
        self,
        *,
        seller_model_path: str | Path | None = None,
        buyer_model_path: str | Path | None = None,
        convergence_ratio: float = CONVERGENCE_RATIO,
        reasonable_multiplier: float = REASONABLE_MULTIPLIER,
    ) -> None:
        self._seller_path = Path(seller_model_path) if seller_model_path else _DEFAULT_SELLER_MODEL_PATH
        self._buyer_path = Path(buyer_model_path) if buyer_model_path else _DEFAULT_BUYER_MODEL_PATH
        self._conv = convergence_ratio
        self._reasonable = reasonable_multiplier
        self._models: dict[str, Any] = {}  # cache: direction → loaded model

    # ------------------------------------------------------------------
    # Model loading (lazy; one model per direction, cached)
    # ------------------------------------------------------------------

    def _get_model(self, direction: str) -> Optional[Any]:
        if direction in self._models:
            return self._models[direction]

        from domain.compute.agent.app.policy.arkhai_common import (
            get_model,
            obs_dim,
            parse_node_types,
        )

        node_types = parse_node_types()
        obs_dim_val = obs_dim(node_types)

        if direction == "maximize":
            model = get_model(
                "ARKHAI_NEGOTIATOR_SELLER_MODEL_PATH",
                self._seller_path,
                obs_dim_val,
            )
        elif direction == "minimize":
            model = get_model(
                "ARKHAI_NEGOTIATOR_BUYER_MODEL_PATH",
                self._buyer_path,
                obs_dim_val,
            )
        else:
            return None

        self._models[direction] = model
        return model

    # ------------------------------------------------------------------
    # Observation builder (compute-domain features mostly zeroed in the
    # asymmetric flow; the price-ratio + round-progress features are
    # what the model leans on for negotiation).
    # ------------------------------------------------------------------

    @staticmethod
    def _build_observation(ri: NegotiationRoundInput, node_types: int) -> Optional[Any]:
        try:
            import torch
        except ImportError:
            return None
        import time as _time

        from domain.compute.agent.app.policy.arkhai_common import obs_dim, MAX_GPU

        obs = torch.zeros((1, obs_dim(node_types)), dtype=torch.float32)

        # 0: time of day
        obs[0, 0] = (_time.localtime().tm_hour % 24) / 24.0

        # 1..(1 + 2N): cluster GPU totals/frees per slot — zeroed (no
        # portfolio context in the asymmetric flow).

        # base = 12: start of request features. cluster slots zeroed,
        # request slots zeroed, request_tb zeroed.
        base = 12

        # base + node_types + 1: round_num / episode_length
        round_num = float(len(ri.history))
        obs[0, base + node_types + 1] = min(1.0, round_num / 100.0)

        # base + node_types + 2: duration_norm — zeroed (we don't have
        # the order's duration in the round input)

        # base + node_types + 3: negotiation_count_norm
        obs[0, base + node_types + 3] = min(1.0, round_num / 10.0)

        # base + node_types + 4: price_ratio = their / our_reference,
        # clipped [0, 2]. The most informative feature for negotiation.
        if ri.their_proposed_price is not None and ri.our_reference_price > 0:
            ratio = float(ri.their_proposed_price) / float(ri.our_reference_price)
            obs[0, base + node_types + 4] = min(2.0, max(0.0, ratio))

        return obs

    # ------------------------------------------------------------------
    # Strategy contract
    # ------------------------------------------------------------------

    def decide(self, ri: NegotiationRoundInput) -> NegotiationDecision:
        # Open with our reference on the very first call (no peer price yet).
        if ri.their_proposed_price is None:
            return NegotiationDecision(action="counter", price=ri.our_reference_price)

        our_counters = ri.our_previous_counters
        if len(our_counters) >= ri.max_rounds:
            return NegotiationDecision(action="exit", reason="max_rounds")
        if len(our_counters) >= 2 and our_counters[-1] == our_counters[-2]:
            return NegotiationDecision(action="exit", reason="stale_negotiation")

        try:
            import torch
            from domain.compute.agent.app.policy.arkhai_common import (
                extract_actions_from_logits,
                parse_node_types,
            )
        except ImportError as exc:
            logger.warning("[NEGOTIATION][RL] torch / arkhai_common unavailable: %s", exc)
            return NegotiationDecision(action="exit", reason="torch_unavailable")

        model = self._get_model(ri.direction)
        if model is None:
            logger.warning("[NEGOTIATION][RL] Model unavailable for direction=%s", ri.direction)
            return NegotiationDecision(action="exit", reason="rl_model_unavailable")

        node_types = parse_node_types()
        obs = self._build_observation(ri, node_types)
        if obs is None:
            return NegotiationDecision(action="exit", reason="obs_build_failed")

        try:
            with torch.no_grad():
                output = model(obs)
        except Exception as exc:
            logger.error("[NEGOTIATION][RL] Inference failed: %s", exc)
            return NegotiationDecision(action="exit", reason=f"inference_failed:{exc}")

        price_idx, _sell_flag = extract_actions_from_logits(output)
        proposed = ri.our_reference_price * (1.0 + _MULTIPLIERS[price_idx])

        their = ri.their_proposed_price
        our = ri.our_reference_price

        if ri.direction == "maximize":
            # Seller: peer price > our floor is good. Accept if close to
            # proposed; counter if reasonable; exit if too low.
            if their >= proposed * (1 - self._conv):
                return NegotiationDecision(action="accept", price=their, reason="convergence")
            if their >= our / self._reasonable:
                return NegotiationDecision(action="counter", price=proposed)
            return NegotiationDecision(action="exit", reason="price_unreasonable")

        if ri.direction == "minimize":
            # Buyer: peer price < our ceiling is good. Cap counter at our ceiling.
            if their <= proposed * (1 + self._conv):
                return NegotiationDecision(action="accept", price=their, reason="convergence")
            if their <= our * self._reasonable:
                if proposed > our:
                    proposed = our
                return NegotiationDecision(action="counter", price=proposed)
            return NegotiationDecision(action="exit", reason="price_unreasonable")

        return NegotiationDecision(action="reject", reason=f"unknown_direction:{ri.direction!r}")


# Self-register on module import. Callers (storefront, buyer) import
# this module at startup; ``load_strategy("rl", ...)`` then resolves.
register_strategy("rl", lambda cfg: TorchArkhaiStrategy(**cfg))
