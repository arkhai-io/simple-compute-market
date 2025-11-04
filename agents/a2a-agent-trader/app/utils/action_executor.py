"""Action execution simulation (logging only for now)."""

from __future__ import annotations

import logging
from typing import Any

from app.schema.pydantic_models import Action, ActionType

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
            # TODO: Replace with: result = accept_offer()
            logger.info(f"[ACTION] [SIMULATED] Accepting offer with params: {parameters}")
            outcome["result"] = True
            outcome["message"] = "Offer accepted (simulated)"
            
        case ActionType.REJECT_OFFER.value:
            # TODO: Replace with: result = reject_offer()
            logger.info(f"[ACTION] [SIMULATED] Rejecting offer with params: {parameters}")
            outcome["result"] = True
            outcome["message"] = "Offer rejected (simulated)"
            
        case ActionType.MAKE_OFFER.value:
            # TODO: Replace with: 
            #   if parameters.get("tag") == "buy":
            #       result = create_order(Tag.BUY, parameters.get("gpu_model"), parameters.get("sla"), parameters.get("region"))
            #   else:
            #       result = create_order(Tag.SELL, parameters.get("gpu_model"), parameters.get("sla"), parameters.get("region"))
            gpu_model = parameters.get("gpu_model", "unknown")
            tag = parameters.get("tag", "unknown")
            logger.info(f"[ACTION] [SIMULATED] Creating {tag} order for {gpu_model} with params: {parameters}")
            outcome["result"] = {"order_id": f"sim_{action.timestamp.isoformat()}"}
            outcome["message"] = f"Order created (simulated): {tag} for {gpu_model}"
            
        case ActionType.RESOLVE_INTERNALLY.value:
            # TODO: Replace with: result = rebalance_internal_resources()
            logger.info(f"[ACTION] [SIMULATED] Resolving resource imbalance internally with params: {parameters}")
            outcome["result"] = True
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

