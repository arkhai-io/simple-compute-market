"""Action execution simulation (logging only for now)."""

from __future__ import annotations

import logging
from typing import Any

from app.schema.pydantic_models import (
    Action,
    ActionType,
    MarketOrder,
    Tag
)

logger = logging.getLogger(__name__)


async def execute_action(action: Action) -> dict[str, Any]:
    """Execute an action and return outcome. Currently simulated/logged only.
    
    TODO: Replace simulation with real tool function calls:
    - ACCEPT_OFFER: call accept_offer() tool
    - REJECT_OFFER: call reject_offer() tool
    - MAKE_OFFER: call make_offer() with params
    - RESOLVE_INTERNALLY: call rebalance_internal_resources() tool
    - Other actions: implement corresponding tool functions
    """
    action_type = action.action_type
    if isinstance(action_type, str):
        action_type_str = action_type
    else:
        action_type_str = action_type.value
    
    parameters = action.parameters or {}
    
    logger.info(f"[ACTION] Simulating execution: {action_type_str} with params: {parameters}")
    
    # Simulate different action types
    outcome = {
        "action_type": action_type_str,
        "status": "simulated",
        "parameters": parameters,
    }
    
    match action_type_str:
        case ActionType.ACCEPT_OFFER.value:
            logger.info(f"[ACTION] [SIMULATED] Accepting offer with params: {parameters}")
            result = accept_offer()
            outcome["result"] = result
            outcome["message"] = "Offer accepted (simulated)"
            
        case ActionType.REJECT_OFFER.value:
            result = reject_offer()
            logger.info(f"[ACTION] [SIMULATED] Rejecting offer with params: {parameters}")
            outcome["result"] = result
            outcome["message"] = "Offer rejected (simulated)"
            
        case ActionType.MAKE_OFFER.value:
            gpu_model = parameters.get("gpu_model", "unknown")
            tag = parameters.get("tag", "unknown")
            logger.info(f"[ACTION] Creating {tag} order for {gpu_model} with params: {parameters}")
            if parameters.get("tag") == "buy":
                order = create_order(Tag.BUY, parameters.get("gpu_model"), parameters.get("sla"), parameters.get("region"))
            else:
                order = create_order(Tag.SELL, parameters.get("gpu_model"), parameters.get("sla"), parameters.get("region"))
            outcome["result"] = {"order_id": f"sim_{action.timestamp.isoformat()}"}
            outcome["message"] = f"Order created: {tag} for {gpu_model}"
            # Then, call make_offer to propagate to the network.
            
        case ActionType.RESOLVE_INTERNALLY.value:
            result = rebalance_internal_resources()
            logger.info(f"[ACTION] [SIMULATED] Resolving resource imbalance internally with params: {parameters}")
            outcome["result"] = result
            outcome["message"] = "Resources rebalanced internally (simulated)"
            
        case ActionType.COUNTER_OFFER.value:
            logger.info(f"[ACTION] [SIMULATED] Countering offer with params: {parameters}")
            outcome["result"] = {"counter_offer_id": f"sim_{action.timestamp.isoformat()}"}
            outcome["message"] = "Counter offer created (simulated)"
            
        case ActionType.NOOP.value:
            logger.info(f"[ACTION] [SIMULATED] No operation required")
            outcome["result"] = None
            outcome["message"] = "No operation (simulated)"
            
        case _:
            logger.warning(f"[ACTION] [SIMULATED] Unknown action type: {action_type_str}")
            outcome["result"] = None
            outcome["message"] = f"Unknown action type (simulated): {action_type_str}"
    
    # Calculate simple utility (can be enhanced later)
    utility = 0.5  # Default neutral utility
    if outcome.get("result") is True:
        utility = 1.0
    elif outcome.get("result") is False:
        utility = 0.0
    elif outcome.get("result") is not None:
        utility = 0.75  # Partial success
    
    outcome["utility"] = utility
    
    return outcome


def rebalance_internal_resources() -> bool:
    """Reallocate internal resources to optimize usage.

    Returns:
        True if the process was successfully initiated.
    """
    logger.info("[TOOL] Rebalancing resources...")
    return True


def reject_offer() -> bool:
    """Reject a received offer.

    Returns:
        True if the rejection was successfully communicated.
    """
    logger.info("[TOOL] Rejecting received offer.")
    return True


def accept_offer() -> bool:
    """Accept a received offer.

    Returns:
        String UUID with which to fill up if the rejection was successfully communicated.
    """
    logger.info("[TOOL] Accepting received offer.")
    return True


def create_order(order_tag: Tag, gpu_model_str: str, sla: float, region_str: str) -> dict | None:
    """Create an order in the market.

    This only locally assembles the details of an order, without yet propagating it into the market,
    and so should be considered a helper function towards making the offer.

    Not to be confused with make_offer, which propagates the order to the market.

    Args:
        order_tag: The type of transaction (OrderTag.BUY or OrderTag.SELL).
        gpu_model_str: The GPU model, one of: {"H200", "Tesla V100", "RTX 5080"}
        sla: SLA required for the order.
        region_str: Geographic region, one of: {"California, US", "New York, US, "Tokyo, JP"}

    Returns:
        The created order as a dictionary if the order was successfully created, or None otherwise.
        This creates a UUID identifying the new order, and the details should match the provided arguments.
    """
    logger.info(f"[TOOL] Creating order of type {order_tag} for resource.")
    order = MarketOrder(
        order_id=str(uuid.uuid4()),
        tag=order_tag,
        order_maker=BASE_URL_OVERRIDE,
        order_taker=None,
        offer_resource=ComputeResource(
            gpu_model=GPUModel(gpu_model_str),
            quantity=1,
            sla=sla,
            region=Region(region_str),
        ),
        demand_resource=TokenResource(
            token="USDT",
            amount=9 * 10**18
        ),
        quantity=1,
        duration=1,
        maker_attestation=None,
        taker_attestation=None
    )
    return order.model_dump()

def make_offer(order: MarketOrder):
    """Propegate an offer to the network.

    [PROTOTYPE] This is currently set to send a message to one other remote agent.
    """
    return None
