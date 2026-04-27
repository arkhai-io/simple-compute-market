"""Arkhai RL negotiation policy — bilateral price negotiation via puffer checkpoints.

Replaces the bisection-based `price_interval_concession` when
NEGOTIATION_POLICY_MODE=rl is set. Uses separate seller/buyer checkpoints trained
with the bilateral ArkhaiPufferEnv.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from domain.compute.agent.app.policy.arkhai_common import (
    build_negotiation_observation,
    extract_actions_from_logits,
    get_model,
    obs_dim,
    parse_node_types,
    torch,
)
from market_policy.action_builders import NegotiationActionBuilder
from market_policy.registry import policy_callable
from market_storefront.schema.pydantic_models import (
    Action as DomainAction,
    DecisionContext,
    NegotiationEvent,
)

logger = logging.getLogger(__name__)

_DEFAULT_SELLER_MODEL_PATH = (
    Path(__file__).resolve().parent / "models" / "arkhai_negotiator_seller.pt"
)
_DEFAULT_BUYER_MODEL_PATH = (
    Path(__file__).resolve().parent / "models" / "arkhai_negotiator_buyer.pt"
)

# 9 price multipliers: -20% to +20% in 5% steps around our_initial_price
_MULTIPLIERS = [-0.20, -0.15, -0.10, -0.05, 0.00, +0.05, +0.10, +0.15, +0.20]

CONVERGENCE_RATIO = 0.01   # Accept when within 1% of proposed price
REASONABLE_MULTIPLIER = 1.5  # Exit threshold


def _get_model(strategy: str, obs_dim_val: int) -> Optional[Any]:
    if strategy == "maximize":
        return get_model(
            "ARKHAI_NEGOTIATOR_SELLER_MODEL_PATH",
            _DEFAULT_SELLER_MODEL_PATH,
            obs_dim_val,
        )
    return get_model(
        "ARKHAI_NEGOTIATOR_BUYER_MODEL_PATH",
        _DEFAULT_BUYER_MODEL_PATH,
        obs_dim_val,
    )


@policy_callable("negotiation.action.torch_arkhai_negotiator")
def negotiation_action_torch_arkhai(context: DecisionContext) -> DomainAction | None:
    """RL-based bilateral negotiation callable using puffer Arkhai checkpoints.

    Replaces price_interval_concession when NEGOTIATION_POLICY_MODE=rl.
    Uses separate seller/buyer models selected by the agent's strategy.
    """
    et = context.event.event_type
    trigger = et.value if hasattr(et, "value") else str(et)
    if trigger != "negotiation":
        return None

    if not isinstance(context.event, NegotiationEvent):
        return None

    # Skip terminal message types — guards upstream handle these
    data = context.event.data or {}
    msg_type = data.get("message_type", "")
    if msg_type in ("exit", "accepted"):
        return None

    thread_info = context.market_state.get("thread_info", {}) if context.market_state else {}
    our_initial_price = thread_info.get("our_initial_price")
    strategy = thread_info.get("our_strategy")  # "maximize" | "minimize"
    their_price = data.get("proposed_price")

    if our_initial_price is None or their_price is None or strategy is None:
        logger.debug(
            "[NEGOTIATION][RL] Missing context: our_initial_price=%s their_price=%s strategy=%s",
            our_initial_price,
            their_price,
            strategy,
        )
        return None

    # Ensure negotiation_id and routing info in data for builder
    if context.event.negotiation_id and "negotiation_id" not in data:
        data = {**data, "negotiation_id": context.event.negotiation_id}
    data = {
        **data,
        "our_price": our_initial_price,
        "their_price": their_price,
        "counterparty_url": thread_info.get("their_agent_id"),
    }
    actions = NegotiationActionBuilder(data)

    # Build observation and run inference
    node_types = parse_node_types()
    model = _get_model(strategy, obs_dim(node_types))

    if model is None or torch is None:
        logger.warning(
            "[NEGOTIATION][RL] Model unavailable for strategy=%s; falling through to next policy",
            strategy,
        )
        return None

    observation = build_negotiation_observation(context, node_types=node_types)
    if observation is None:
        logger.warning("[NEGOTIATION][RL] Failed to build observation; falling through")
        return None

    try:
        with torch.no_grad():
            output = model(observation)
    except Exception as exc:
        logger.error("[NEGOTIATION][RL] Inference failed: %s", exc)
        return None

    price_idx, _ = extract_actions_from_logits(output)
    proposed_price = int(our_initial_price * (1.0 + _MULTIPLIERS[price_idx]))

    logger.info(
        "[NEGOTIATION][RL] strategy=%s price_idx=%d → proposed_price=%d "
        "(our_initial=%s their=%s)",
        strategy,
        price_idx,
        proposed_price,
        our_initial_price,
        their_price,
    )

    # Accept / counter / exit using same thresholds as price_interval_concession
    if strategy == "maximize":
        # Seller: wants their_price as high as possible
        if their_price >= proposed_price * (1 - CONVERGENCE_RATIO):
            return actions.accept("convergence")
        if their_price >= our_initial_price / REASONABLE_MULTIPLIER:
            return actions.counter(proposed_price)
        return actions.exit("price_unreasonable")

    if strategy == "minimize":
        # Buyer: wants their_price as low as possible
        if their_price <= proposed_price * (1 + CONVERGENCE_RATIO):
            return actions.accept("convergence")
        if their_price <= our_initial_price * REASONABLE_MULTIPLIER:
            return actions.counter(proposed_price)
        return actions.exit("price_unreasonable")

    return None
