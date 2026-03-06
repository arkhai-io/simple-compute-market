"""Arkhai buyer policy adapter backed by upstream puffer checkpoints.

Mirror of the seller adapter with buyer-specific action thresholds.
Buyers are more price-sensitive: their reward is profit margin
(base_price - negotiated_price) * duration, so lower prices are preferred.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from app.policies.arkhai_common import (
    build_action_parameters,
    build_arkhai_observation,
    detect_agent_role,
    extract_actions_from_logits,
    get_model,
    obs_dim,
    parse_node_types,
    torch,
)
from core.agent.app.policy.registry import policy_callable
from app.schema.pydantic_models import (
    Action as DomainAction,
    ActionType,
    ComputeResource,
    ComputeResourcePortfolio,
    DecisionContext,
    MakeOfferEvent,
)
from core.agent.app.utils.config import CONFIG
from app.utils.validation import extract_resources_from_make_offer_event

logger = logging.getLogger(__name__)

_DEFAULT_MODEL_PATH = Path(__file__).resolve().parent / "models" / "arkhai_buyer.pt"


def _get_model(obs_dim_val: int) -> Optional[Any]:
    """Lazily load the Arkhai buyer model checkpoint."""
    return get_model("ARKHAI_BUYER_MODEL_PATH", _DEFAULT_MODEL_PATH, obs_dim_val)


@policy_callable("mo.action.torch_arkhai_buyer")
async def mo_action_torch_arkhai_buyer(context: DecisionContext) -> DomainAction | None:
    """Model-based Arkhai buyer policy for MakeOffer events."""
    if not isinstance(context.event, MakeOfferEvent):
        return None

    order, offer_resource, demand_resource = extract_resources_from_make_offer_event(context)
    if order is None:
        return None

    if isinstance(demand_resource, ComputeResource):
        portfolio_dict = context.available_resources
        if portfolio_dict and "resources" in portfolio_dict:
            try:
                portfolio = ComputeResourcePortfolio.model_validate(portfolio_dict)
                if not portfolio.has_capacity(demand_resource):
                    return DomainAction(
                        action_type=ActionType.REJECT_OFFER,
                        parameters={
                            "reason": "insufficient_capacity",
                            "order_id": order.order_id,
                            "demand_resource": demand_resource.model_dump(mode="json"),
                            "offer_resource": offer_resource.model_dump(mode="json"),
                        },
                    )
            except Exception as exc:
                logger.warning("[ARKHAI BUYER POLICY] Failed to validate portfolio: %s", exc)

    node_types = parse_node_types()
    model = _get_model(obs_dim(node_types))
    if model is None or torch is None:
        logger.warning("[ARKHAI BUYER POLICY] Model unavailable; returning None")
        return None

    observation = build_arkhai_observation(context, offer_resource, demand_resource, order)
    if observation is None:
        logger.warning("[ARKHAI BUYER POLICY] Failed to build observation; returning None")
        return None

    try:
        with torch.no_grad():
            output = model(observation)
    except Exception as exc:
        logger.error("[ARKHAI BUYER POLICY] Inference failed: %s", exc)
        return None

    price_idx, sell_flag = extract_actions_from_logits(output)

    agent_role = detect_agent_role(
        offer_resource, demand_resource, order, CONFIG.base_url_override,
    )

    # Buyer thresholds: buyers are more price-sensitive (want low prices).
    # Lower price_idx = lower offered price = better for buyer.
    if agent_role == "buyer":
        action_type = (
            ActionType.ACCEPT_OFFER
            if price_idx <= 5
            else ActionType.COUNTER_OFFER
            if price_idx <= 7
            else ActionType.REJECT_OFFER
        )
    else:
        # When acting as seller (fallback), use seller-like thresholds.
        action_type = (
            ActionType.ACCEPT_OFFER
            if price_idx <= 7
            else ActionType.COUNTER_OFFER
            if price_idx == 8
            else ActionType.REJECT_OFFER
        )

    parameters = build_action_parameters(
        order_id=order.order_id,
        offer_resource=offer_resource,
        demand_resource=demand_resource,
        price_idx=price_idx,
        sell_flag=sell_flag,
        order=order if action_type == ActionType.ACCEPT_OFFER else None,
    )
    return DomainAction(action_type=action_type, parameters=parameters)
