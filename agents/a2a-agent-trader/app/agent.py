# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import os
import random
import uuid
from datetime import datetime
from typing import Optional, override, AsyncGenerator, Any, Dict, Tuple
from enum import Enum

import google.auth
from a2a.types import AgentCapabilities, AgentCard, AgentSkill
from fastapi import HTTPException
from google.adk.a2a.utils.agent_to_a2a import to_a2a
from google.adk.agents import BaseAgent,  InvocationContext
from google.adk.agents.remote_a2a_agent import (
    AGENT_CARD_WELL_KNOWN_PATH,
    RemoteA2aAgent,
)
from google.adk.events import Event
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools.agent_tool import AgentTool
from google.adk.tools.mcp_tool import MCPToolset, StreamableHTTPConnectionParams
from google.genai import types as genai_types
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
import logging
logger = logging.getLogger(__name__)

from .utils.config import CONFIG
MCP_SERVER_URL = CONFIG.mcp_server_url
BASE_URL_OVERRIDE = CONFIG.base_url_override
PORT = CONFIG.port
REMOTE_AGENT_URL_OVERRIDE = CONFIG.remote_agent_url_override
POLICY_DB_PATH = CONFIG.policy_db_path


from .schema.pydantic_models import (
    EventType,
    DomainEvent,
    MarketOrderEvent,
    ResourceImbalanceEvent,
    NegotiationEvent,
    GPUModel,
    Region,
    Tag,
    ComputeResource,
    ComputeResourcePortfolio,
    MarketOrder,
)

from .policies.store import PolicyStore, simple_negotiation_random
from .policies.sqlite_client import SQLiteClient
from .schema.pydantic_models import DecisionContext
from pydantic import PrivateAttr

def rebalance_internal_resources() -> bool:
    """Reallocate internal resources to optimize usage.

    Returns:
        True if the process was successfully initiated.
    """
    logger.info("[TOOL] Rebalancing resources...")
    return True

def make_order(order_tag: Tag, gpu_model_str: str, sla: float, region_str: str) -> dict | None:
    """Create an order in the market.

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
        compute_resource=ComputeResource(
            gpu_model=GPUModel(gpu_model_str),
            quantity=1,
            sla=sla,
            region=Region(region_str),
        ),
        quantity=1,
        duration=1,
        attestation=None,
    )
    return order.model_dump()

def make_sell_order(gpu_model_str: str, sla: float, region_str: str) -> dict | None:
    """Create a SELL order in the market, selling available resources. After order creation, save it to Redis,
    report to confirm order details, and signal for the remote_agent to evaluate the order on their end.
    Provide the remote_agent the order_id.

    Args:
        order_tag: The type of transaction (OrderTag.BUY or OrderTag.SELL).
        gpu_model_str: The GPU model, one of: {"H200", "Tesla V100", "RTX 5080"}
        sla: SLA required for the order.
        region_str: Geographic region, one of: {"California, US", "New York, US, "Tokyo, JP"}

    Returns:
        The order as a dictionary if the order was successfully created, or None otherwise.
    """
    return make_order(Tag.SELL, gpu_model_str, sla, region_str)

def make_buy_order(gpu_model_str: str, sla: float, region_str: str) -> dict | None:
    """Create a BUY order in the market. After order creation, report to confirm order details, save it to Redis,
    and signal for the remote_agent to evaluate the order on their end. Provide the remote_agent the order_id.

    Args:
        order_tag: The type of transaction (OrderTag.BUY or OrderTag.SELL).
        gpu_model_str: The GPU model, one of: {"H200", "Tesla V100", "RTX 5080"}
        sla: SLA required for the order.
        region_str: Geographic region, one of: {"California, US", "New York, US, "Tokyo, JP"}

    Returns:
        The order as a dictionary if the order was successfully created, or None otherwise.
    """
    return make_order(Tag.BUY, gpu_model_str, sla, region_str)

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

def evaluate_received_offer(order_id: str) -> str:
    """Given a make_offer event denoting an INCOMING offer from another agent, evaluate whether or not to accept it.
    Following the recommendation, invoke either accept_offer or reject_offer.

    Returns:
        String with policy recommendation of next action to take.
    """
    # This function is kept for backward compatibility but will be handled by PolicyStore
    logger.info(f"[TOOL] Evaluating received offer {order_id}.")
    return "ACCEPT or REJECT based on policy evaluation."


def _extract_text_from_content(content: genai_types.Content | None) -> str:
    """Concatenate text parts from generative content."""
    if not content or not getattr(content, "parts", None):
        return ""
    text_parts: list[str] = []
    for part in content.parts:
        if getattr(part, "text", None):
            text_parts.append(part.text)  # type: ignore[arg-type]
    return "".join(text_parts).strip()

def _extract_tool_payload(
    content: Optional[genai_types.Content],
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Return (tool_name, response_dict) if the message contains a functionResponse part."""
    if not content:
        return None, None
    for part in content.parts or []:
        function_response = getattr(part, "function_response", None)
        if function_response:
            # function_response has .name and .response (dict-like)
            return getattr(function_response, "name", None), getattr(function_response, "response", None)
    return None, None


def _parse_domain_event(payload: Dict[str, Any]) -> DomainEvent:
    """Convert a domain event payload dictionary to a DomainEvent instance."""
    if not payload:
        raise ValueError("Cannot parse empty payload as DomainEvent")
    
    event_type_str = payload.get("event_type")
    if not event_type_str:
        raise ValueError("Missing event_type in payload")
    
    try:
        event_type = EventType(event_type_str)
    except ValueError:
        # If it's not a known EventType, create a basic DomainEvent
        event_type = None
    
    event_id = payload.get("event_id", f"evt_{uuid.uuid4()}")
    source = payload.get("source", "unknown")
    timestamp_str = payload.get("timestamp")
    timestamp = datetime.fromisoformat(timestamp_str) if timestamp_str else datetime.now()
    data = payload.get("data", payload.copy())  # Use data if available, otherwise use payload
    
    # Try to create specific event types
    if event_type == EventType.RESOURCE_IMBALANCE:
        resource_data = data.get("resource", data)
        try:
            resource = ComputeResource(
                gpu_model=GPUModel(resource_data.get("gpu_model", data.get("gpu_model", "H200"))),
                quantity=resource_data.get("quantity", data.get("quantity", 1)),
                sla=resource_data.get("sla", data.get("sla", 90.0)),
                region=Region(resource_data.get("region", data.get("region", "California, US"))),
            )
            return ResourceImbalanceEvent.create(
                event_id=event_id,
                source=source,
                resource=resource,
                imbalance_type=data.get("imbalance_type", "surplus"),
                severity=float(data.get("severity", 0.5)),
            )
        except (ValueError, KeyError, TypeError) as e:
            logger.warning(f"Failed to create ResourceImbalanceEvent: {e}, falling back to DomainEvent")
    
    elif event_type == EventType.MARKET_ORDER:
        try:
            order_data = data.get("order", data)
            order = MarketOrder.model_validate(order_data)
            return MarketOrderEvent.from_order(order)
        except (ValueError, KeyError, TypeError) as e:
            logger.warning(f"Failed to create MarketOrderEvent: {e}, falling back to DomainEvent")
    
    elif event_type == EventType.NEGOTIATION:
        try:
            return NegotiationEvent.create(
                event_id=event_id,
                negotiation_id=data.get("negotiation_id", event_id),
                message_type=data.get("message_type", "offer"),
                sender=data.get("sender", source),
                data=data,
            )
        except (ValueError, KeyError, TypeError) as e:
            logger.warning(f"Failed to create NegotiationEvent: {e}, falling back to DomainEvent")
    
    # Fallback to base DomainEvent
    return DomainEvent(
        event_id=event_id,
        event_type=event_type or EventType.MAKE_OFFER,  # Default if unknown
        timestamp=timestamp,
        source=source,
        data=data,
    )

remote_agent = RemoteA2aAgent(
    name=f"remote_agent_{PORT}",
    description="A helpful AI assistant trading compute resources with others.",
    agent_card=f"{REMOTE_AGENT_URL_OVERRIDE}{AGENT_CARD_WELL_KNOWN_PATH}",
)

class TraderAgent(BaseAgent):
    """
    Custom agent for trading computational resources.
    """
    resource_portfolio: dict
    _policy_store: PolicyStore = PrivateAttr()

    def __init__(
        self,
        name: str,
    ):
        """
        Initializes the Trader Agent.
        """

        logger.info("Starting TraderAgent.")

        super().__init__(
            name=name,
            resource_portfolio={}
        )

        # In-memory stand-in for compute nodes under the Agent's control.
        self.resource_portfolio =  ComputeResourcePortfolio(
            resources=[
                ComputeResource(
                    gpu_model=GPUModel.H200,
                    quantity=3,
                    sla=90.0,
                    region=Region.CALIFORNIA_US,
                ),
                ComputeResource(
                    gpu_model=GPUModel.TESLA_V100,
                    quantity=2,
                    sla=99.9,
                    region=Region.TOKYO_JP,
                ),
            ]
        )
        
        # Initialize PolicyStore (private attribute to avoid Pydantic field requirements)
        sqlite_client = SQLiteClient(db_path=POLICY_DB_PATH)
        self._policy_store = PolicyStore(sqlite_client)
        
        # Register simple_negotiation_random callable
        self._policy_store.register_callable(
            "simple_negotiation_random",
            simple_negotiation_random()
        )
        
        # Save policy for negotiation events (will be done asynchronously on first use)
        # We'll handle this in an async initialization if needed, or save it here sync
        # For now, we'll let it be registered and saved on-demand

    async def _ensure_negotiation_policy(self) -> None:
        """Ensure negotiation policy is saved to the store."""
        try:
            await self._policy_store.save_policy(
                agent_id=self.name,
                policy_name="simple_negotiation_random",
                trigger_type=EventType.NEGOTIATION.value,
                callable_ref="simple_negotiation_random",
            )
        except Exception as e:
            logger.warning(f"Failed to save negotiation policy: {e}")

    async def get_resource_portfolio(self) -> dict:
        """Get the current stock of all resources managed by the node portfolio.

        Returns:
            A dictionary representing the current portfolio stock.
        """
        return self.resource_portfolio.model_dump()

    async def _build_domain_context(self, event: Event) -> Tuple[DomainEvent, dict]:
        """Build domain context from ADK Event, converting to DomainEvent."""
        resource_portfolio = await self.get_resource_portfolio()
        
        # Extract domain event payload
        content = _extract_tool_payload(event.content)
        _, domain_event_payload = content
        
        # Convert payload dict to DomainEvent instance
        if domain_event_payload:
            try:
                domain_event = _parse_domain_event(domain_event_payload)
            except (ValueError, KeyError) as e:
                logger.warning(f"Failed to parse domain event: {e}, creating default")
                # Create a basic DomainEvent as fallback
                domain_event = DomainEvent(
                    event_id=f"evt_{uuid.uuid4()}",
                    event_type=EventType.MAKE_OFFER,
                    source="unknown",
                    data=domain_event_payload or {},
                )
        else:
            # No payload, create default event
            domain_event = DomainEvent(
                event_id=f"evt_{uuid.uuid4()}",
                event_type=EventType.MAKE_OFFER,
                source="unknown",
                data={},
            )
        
        return (domain_event, resource_portfolio)

    async def _consult_policy(self, context: Tuple[DomainEvent, dict]) -> str | None:
        """Given a triggering event, use PolicyStore to determine the next action to take.
        The subsequent action to take will be summarized in CAPITALS.

        Returns:
            A string representing the action to take, or None if no action is available.
        """
        domain_event, resource_portfolio = context
        event_type = domain_event.event_type
        
        # Ensure negotiation policy is saved for negotiation events
        if event_type == EventType.NEGOTIATION:
            await self._ensure_negotiation_policy()
        
        # Build DecisionContext for PolicyStore
        decision_context = DecisionContext(
            event=domain_event,
            agent_id=self.name,
            available_resources=resource_portfolio,
            market_state={},  # Can be enhanced later
            negotiation_history=[],
            past_experiences=[],
        )
        
        # Evaluate policy using PolicyStore
        try:
            action = await self._policy_store.evaluate_policy(
                agent_id=self.name,
                context=decision_context,
            )
            
            if action:
                # Map Action to response string
                action_type = action.action_type
                if isinstance(action_type, str):
                    action_type_str = action_type.upper()
                else:
                    action_type_str = action_type.value.upper()
                
                # Map action types to response strings
                action_mappings = {
                    "ACCEPT_OFFER": "ACCEPT the offer.",
                    "REJECT_OFFER": "REJECT the offer.",
                    "COUNTER_OFFER": "COUNTER the offer.",
                    "MAKE_OFFER": "MAKE OFFER. Create market order.",
                    "RESOLVE_INTERNALLY": "RESOLVE INTERNALLY. Run rebalance_internal_resources utility.",
                    "CREATE_ORDER": "CREATE ORDER.",
                    "NOOP": "NOOP. No action required.",
                }
                
                result = action_mappings.get(action_type_str, f"{action_type_str} action recommended.")
                logger.info(f"[POLICY] PolicyStore returned action: {action_type_str}")
                return result
        except Exception as e:
            logger.warning(f"PolicyStore evaluation failed: {e}, falling back to default behavior")
        
        # Fallback to random choices if PolicyStore doesn't return an action
        event_type_value = event_type.value
        match event_type_value:
            case EventType.MAKE_OFFER.value:
                result = random.choice([
                    "ACCEPT the offer.",
                    "REJECT the offer.",
                ])
            case EventType.RESOURCE_IMBALANCE.value:
                result = random.choice([
                    "MAKE OFFER. Create market order. If resource usage is HIGH, then make a BUY order matching the resource model and region. If resource usage is LOW, then make a SELL order to sell the excess.",
                    "RESOLVE INTERALLY. Run rebalance_internal_resources utility.",
                ])
            case EventType.CRON_JOB.value:
                result = "UNAVAILABLE. No actions available for event type."
            case EventType.ARBITRAGE_OPPORTUNITY.value:
                result = "UNAVAILABLE. No actions available for event type."
            case _:
                result = "INVALID. Invalid event type."

        logger.info(f"[TOOL] Fallback response to {event_type_value}: {result}")
        return result

    @override
    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        logger.info(f"[{self.name}]: {ctx}")
        last_event = ctx.session.events[-1]
        logger.info("CONTENT:")

        if last_event.content is None:
            yield Event(
                author=self.name,
                content=genai_types.Content(
                    role="model",
                    parts=[genai_types.Part.from_text(text="No content provided.")],
                ),
                invocation_id=ctx.invocation_id,
                branch=ctx.branch,
            )

        name, content = _extract_tool_payload(last_event.content)
        logger.info(f"{name}: {content}")

        context = await self._build_domain_context(last_event)

        policy_recommendation = await self._consult_policy(context)

        logger.info(f"Policy recommendation: {policy_recommendation}")

        # Send a message to a remote agent with:
        # await ctx.session_service.append_event(ctx.session, Event(
        #     author=self.name,
        #     content=genai_types.Content(
        #         role="model",
        #         parts=[genai_types.Part.from_text(text="hello there")],
        #     ),
        #     invocation_id=ctx.invocation_id,
        #     branch=ctx.branch,
        # ))
        #
        # Then receive the response from the remote agent:
        # async for event in remote_agent.run_async(ctx):
        #     text_from_remote = _extract_text_from_content(event.content)

        yield Event(
            author=self.name,
            content=genai_types.Content(
                role="model",
                parts=[genai_types.Part.from_text(text=f"{policy_recommendation}")],
            ),
            invocation_id=ctx.invocation_id,
            branch=ctx.branch,
        )

root_agent = TraderAgent(
    name="root_agent",
)

# Create a2a app

# Define the skill for the root agent
# In the future, we prefer to use agent-card.json to define the skills and capabilities of the agent. https://google.github.io/adk-docs/a2a/quickstart-exposing/#getting-the-sample-code

public_agent_card = AgentCard(
    name="A2A Agent",
    description="A helpful AI assistant designed to trade compute resources with others.",
    url=BASE_URL_OVERRIDE,
    version="0.1.0",
    default_input_modes=["text"],
    default_output_modes=["text"],
    skills=[],
    capabilities=AgentCapabilities(streaming=True),
)

ALERTS_APP_NAME = "alerts"
ALERTS_USER_ID = "resource-monitor"


async def _run_alert_conversation(alert: dict) -> str:
    """Route alert details through the root agent so it can decide on next steps."""
    session_service = InMemorySessionService()
    session = session_service.create_session_sync(
        app_name=ALERTS_APP_NAME,
        user_id=ALERTS_USER_ID,
    )
    runner = Runner(
        agent=root_agent,
        app_name=ALERTS_APP_NAME,
        session_service=session_service,
    )

    # Convert alert dict to ResourceImbalanceEvent structure
    alert['event_type'] = EventType.RESOURCE_IMBALANCE.value
    if 'source' not in alert:
        alert['source'] = ALERTS_USER_ID
    if 'event_id' not in alert:
        alert['event_id'] = f"alert_{uuid.uuid4()}"
    
    message = genai_types.Content(
        role="user",
        parts=[
            genai_types.Part.from_function_response(
                name="get_alert",
                response=alert
            )
        ],
    )

    final_response: str | None = None
    async for event in runner.run_async(
        user_id=ALERTS_USER_ID,
        session_id=session.id,
        new_message=message,
    ):
        if event.is_final_response() and event.content and event.content.parts:
            text_parts = [
                part.text
                for part in event.content.parts
                if hasattr(part, "text") and part.text
            ]
            if text_parts:
                final_response = "".join(text_parts)
                break

    if not final_response:
        raise HTTPException(
            status_code=500,
            detail="root_agent did not provide a response to the resource alert.",
        )
    return final_response


async def handle_resource_alert(request: Request) -> JSONResponse:
    """Expose an endpoint that forwards resource alerts to the root agent."""
    try:
        alert = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON in request body"}, status_code=400)

    response_text = await _run_alert_conversation(alert)
    response = dict(alert)
    response["root_agent_response"] = response_text

    return JSONResponse(response)


# Create Starlette route for the alert endpoint
alert_route = Route("/alerts/resource", handle_resource_alert, methods=["POST"])


a2a_app = to_a2a(root_agent, port=PORT, agent_card=public_agent_card)

# Add the alert route to the A2A app
a2a_app.routes.append(alert_route)
