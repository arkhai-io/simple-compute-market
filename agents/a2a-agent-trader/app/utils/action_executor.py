"""Action execution simulation (logging only for now)."""

from __future__ import annotations

import uuid
import logging
from typing import Any

from google.adk.agents import InvocationContext
from google.adk.events import Event
from google.adk.agents.remote_a2a_agent import (
    AGENT_CARD_WELL_KNOWN_PATH,
    RemoteA2aAgent,
)

from google.genai import types as genai_types

from app.schema.pydantic_models import (
    Action,
    ActionType,
    ComputeResource,
    EventType,
    GPUModel,
    MarketOrder,
    Region,
    TokenResource
)

from .config import CONFIG
from .token_registry import TOKEN_REGISTRY

BASE_URL_OVERRIDE = CONFIG.base_url_override
REMOTE_AGENT_URL_OVERRIDE = CONFIG.remote_agent_url_override
PORT = CONFIG.port
REMOTE_AGENT_PORT = CONFIG.remote_agent_port
AGENT_ID = CONFIG.agent_id

logger = logging.getLogger(__name__)


async def execute_action(action: Action, ctx: InvocationContext | None = None) -> dict[str, Any]:
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
            outcome["message"] = "Offer accepted"
            
        case ActionType.REJECT_OFFER.value:
            result = reject_offer()
            logger.info(f"[ACTION] [SIMULATED] Rejecting offer with params: {parameters}")
            outcome["result"] = result
            outcome["message"] = "Offer rejected (simulated)"
            
        case ActionType.MAKE_OFFER.value:
            gpu_model = parameters.get("gpu_model", "unknown")
            logger.info(f"[ACTION] Creating order for {gpu_model} with params: {parameters}")
            order = create_order(
                gpu_model_str=parameters.get("gpu_model"),
                sla=parameters.get("sla"),
                region_str=parameters.get("region")
            )
            outcome["result"] = {"order_id": f"sim_{action.timestamp.isoformat()}"}
            outcome["message"] = f"Order created for {gpu_model}"
            # Then, call make_offer to propagate to the network.
            make_offer_result = await make_offer(ctx=ctx, order=order)
            for part in getattr(make_offer_result.content, "parts", []):
                logger.info(f"[ACTION] Received response: {part.text}")
                outcome["message"] = part.text
            
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
    
    return outcome


def connect_to_remote_agent(agent_url=REMOTE_AGENT_URL_OVERRIDE):
    agent_card_url=f"{agent_url}{AGENT_CARD_WELL_KNOWN_PATH}"
    remote_agent = RemoteA2aAgent(
        name=f"remote_agent_{REMOTE_AGENT_PORT}",
        description="A helpful AI assistant trading compute resources with others.",
        agent_card=agent_card_url,
    )
    return remote_agent

async def send_to_remote_agent(
    ctx: InvocationContext,
    event: Event,
    remote_agent: RemoteA2aAgent = None
):
    """Takes an event and sends it to a specified remote agent via A2A.

    Examples of Events:
        Text:
            Event(
                author=self.name,
                content=genai_types.Content(
                    role="model",
                    parts=[genai_types.Part.from_text(text="Offer successfully received.")],
                ),
                invocation_id=ctx.invocation_id,
                branch=ctx.branch,
            )

        Structured:
            Event(
                author=self.name,
                content=genai_types.Content(
                    role="model",
                    parts=[
                        genai_types.Part.from_function_response(
                            name="make_offer",
                            response={
                                "event_type": EventType.MAKE_OFFER,
                                "offer": order
                            })
                        ],
                ),
                invocation_id=ctx.invocation_id,
                branch=ctx.branch,
            )
    """
    if remote_agent is None:
        remote_agent = connect_to_remote_agent()

    logger.info(f"[A2A] Sending event to remote agent: {event}")

    await ctx.session_service.append_event(ctx.session, event)
    async for event in remote_agent.run_async(ctx):
        #text_from_remote = _extract_text_from_content(event.content)
        if event.is_final_response():
            logger.info(f"[A2A] Received from remote agent: {event}")
            return event


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
        True if the acceptance was successfully communicated.
    """
    logger.info("[TOOL] Accepting received offer.")
    return True


def create_order(gpu_model_str: str, sla: float, region_str: str) -> dict | None:
    """Create an order in the market.

    This only locally assembles the details of an order, without yet propagating it into the market,
    and so should be considered a helper function towards making the offer.

    Not to be confused with make_offer, which propagates the order to the market.

    Args:
        gpu_model_str: The GPU model, one of: {"H200", "Tesla V100", "RTX 5080"}
        sla: SLA required for the order.
        region_str: Geographic region, one of: {"California, US", "New York, US, "Tokyo, JP"}

    Returns:
        The created order as a dictionary if the order was successfully created, or None otherwise.
        This creates a UUID identifying the new order, and the details should match the provided arguments.
    """
    settlement_token = TOKEN_REGISTRY.require("USDC")
    logger.info("[TOOL] Creating order for resource.")
    order = MarketOrder(
        order_id=str(uuid.uuid4()),
        order_maker=BASE_URL_OVERRIDE,
        order_taker=None,
        offer_resource=ComputeResource(
            gpu_model=GPUModel(gpu_model_str),
            quantity=1,
            sla=sla,
            region=Region(region_str),
        ),
        demand_resource=TokenResource(
            token=settlement_token.symbol,
            amount=9 * 10**settlement_token.decimals,
        ),
        duration=1,
        maker_attestation=None,
        taker_attestation=None
    )
    return order.model_dump(mode='json')

async def make_offer(ctx: InvocationContext, order: MarketOrder):
    """Propegate an offer to the network.

    [PROTOTYPE] This is currently set to send a message to one other remote agent.
    """
    event = Event(
          author=AGENT_ID,
          content=genai_types.Content(
              role="model",
              parts=[
                  genai_types.Part.from_function_response(
                      name="make_offer",
                      response={
                          "event_type": EventType.MAKE_OFFER.value,
                          "offer": order
                      })
                  ],
          ),
          invocation_id=ctx.invocation_id,
          branch=ctx.branch,
      )
    try:
        result = await send_to_remote_agent(ctx, event)
        return result
    except Exception as e:
        logger.error(f"[TOOL] Failed to make offer: {e}.")
