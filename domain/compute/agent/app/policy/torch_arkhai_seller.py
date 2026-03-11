"""Arkhai seller policy adapter backed by upstream puffer checkpoints.

This policy intentionally keeps local logic thin:
- Observation layout follows upstream Arkhai ordering (via arkhai_common).
- Model loading expects puffer `state_dict` checkpoints.
- Action mapping remains local (domain-level accept/counter/reject).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from domain.compute.agent.app.policy.arkhai_common import (
    build_action_parameters,
    build_arkhai_observation,
    detect_agent_role,
    extract_actions_from_logits,
    get_model,
    obs_dim,
    parse_node_types,
    torch,
)
from domain.compute.agent.app.policy.store import get_compute_resource_portfolio
from core.agent.app.policy.registry import policy_callable
from core.agent.app.schema.pydantic_models import (
    Action as DomainAction,
    ActionType,
    ComputeResource,
    DecisionContext,
    MakeOfferEvent,
)
from core.agent.app.utils.config import CONFIG
from core.agent.app.utils.validation import extract_resources_from_make_offer_event

logger = logging.getLogger(__name__)

_DEFAULT_MODEL_PATH = Path(__file__).resolve().parent / "models" / "arkhai_seller.pt"


def _get_model(obs_dim_val: int) -> Optional[Any]:
    """Lazily load the Arkhai seller model checkpoint."""
    return get_model("ARKHAI_SELLER_MODEL_PATH", _DEFAULT_MODEL_PATH, obs_dim_val)


@policy_callable("mo.action.torch_arkhai_seller")
async def mo_action_torch_arkhai_seller(context: DecisionContext) -> DomainAction | None:
    """Model-based Arkhai seller policy for MakeOffer events."""
    if not isinstance(context.event, MakeOfferEvent):
        return None

    order, offer_resource, demand_resource = extract_resources_from_make_offer_event(context)
    if order is None:
        return None

    if isinstance(demand_resource, ComputeResource):
        portfolio = get_compute_resource_portfolio(context)
        if portfolio and not portfolio.has_capacity(demand_resource):
            return DomainAction(
                action_type=ActionType.REJECT_OFFER,
                parameters={
                    "reason": "insufficient_capacity",
                    "order_id": order.order_id,
                    "demand_resource": demand_resource.model_dump(mode="json"),
                    "offer_resource": offer_resource.model_dump(mode="json"),
                },
            )

    node_types = parse_node_types()
    model = _get_model(obs_dim(node_types))
    if model is None or torch is None:
        logger.warning("[ARKHAI SELLER POLICY] Model unavailable; returning None")
        return None

    observation = build_arkhai_observation(context, offer_resource, demand_resource, order)
    if observation is None:
        logger.warning("[ARKHAI SELLER POLICY] Failed to build observation; returning None")
        return None

    try:
        with torch.no_grad():
            output = model(observation)
    except Exception as exc:
        logger.error("[ARKHAI SELLER POLICY] Inference failed: %s", exc)
        return None

    price_idx, sell_flag = extract_actions_from_logits(output)

    agent_role = detect_agent_role(
        offer_resource, demand_resource, order, CONFIG.base_url_override,
    )

    # Seller thresholds: sellers are less price-sensitive (want to sell compute).
    if agent_role == "seller":
        action_type = (
            ActionType.ACCEPT_OFFER
            if price_idx <= 7
            else ActionType.COUNTER_OFFER
            if price_idx == 8
            else ActionType.REJECT_OFFER
        )
    else:
        action_type = (
            ActionType.ACCEPT_OFFER
            if price_idx <= 6
            else ActionType.COUNTER_OFFER
            if price_idx == 7
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
