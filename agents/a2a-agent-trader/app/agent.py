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

import asyncio
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
    TokenResource,
    ComputeResource,
    ComputeResourcePortfolio,
    MarketOrder,
)

from .policies.store import PolicyStore, simple_negotiation_random
from .policies.sqlite_client import SQLiteClient
from .schema.pydantic_models import DecisionContext, Action, Decision
from .utils.event_ingestion import (
    queue_event,
    pop_event,
    has_queued_events,
    start_redis_subscriber,
    stop_redis_subscriber,
)
from .utils.market_provider import create_market_provider, MarketProvider
from .utils.action_executor import execute_action
from pydantic import PrivateAttr

def rebalance_internal_resources() -> bool:
    """Reallocate internal resources to optimize usage.

    Returns:
        True if the process was successfully initiated.
    """
    logger.info("[TOOL] Rebalancing resources...")
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

def connect_to_remote_agent(agent_url=REMOTE_AGENT_URL_OVERRIDE):
    agent_card_url=f"{agent_url}{AGENT_CARD_WELL_KNOWN_PATH}"
    remote_agent = RemoteA2aAgent(
        name=f"remote_agent_{PORT}",
        description="A helpful AI assistant trading compute resources with others.",
        agent_card=agent_card_url,
    )
    return remote_agent

class TraderAgent(BaseAgent):
    """
    Custom agent for trading computational resources.
    """
    resource_portfolio: dict
    _policy_store: PolicyStore = PrivateAttr()
    _sqlite_client: SQLiteClient = PrivateAttr()
    _market_provider: MarketProvider = PrivateAttr()

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
        
        # Initialize SQLite client (shared for policies and decisions)
        self._sqlite_client = SQLiteClient(db_path=POLICY_DB_PATH)
        
        # Initialize PolicyStore (private attribute to avoid Pydantic field requirements)
        self._policy_store = PolicyStore(self._sqlite_client)
        
        # Register simple_negotiation_random callable
        self._policy_store.register_callable(
            "simple_negotiation_random",
            simple_negotiation_random()
        )
        
        # Initialize market provider
        self._market_provider = create_market_provider()
        
        # Save policy for negotiation events (will be done asynchronously on first use)
        # We'll handle this in an async initialization if needed, or save it here sync
        # For now, we'll let it be registered and saved on-demand

    async def send_to_remote_agent(self, ctx, event: Event, remote_agent = None):
        if remote_agent is None:
            remote_agent = connect_to_remote_agent()

        # Examples of Events:
        # Text:
        #   Event(
        #       author=self.name,
        #       content=genai_types.Content(
        #           role="model",
        #           parts=[genai_types.Part.from_text(text="Offer successfully received.")],
        #       ),
        #       invocation_id=ctx.invocation_id,
        #       branch=ctx.branch,
        #   ))
        # Structured:
        #   Event(
        #       author=self.name,
        #       content=genai_types.Content(
        #           role="model",
        #           # parts=[genai_types.Part.from_text(text="This is an offer.")],
        #           parts=[
        #               genai_types.Part.from_function_response(
        #                   name="make_offer",
        #                   response={
        #                       "event_type": EventType.MAKE_OFFER,
        #                       "offer": order
        #                   })
        #               ],
        #       ),
        #       invocation_id=ctx.invocation_id,
        #       branch=ctx.branch,
        #   ))

        await ctx.session_service.append_event(ctx.session, event)
        async for event in remote_agent.run_async(ctx):
            #text_from_remote = _extract_text_from_content(event.content)
            if event.is_final_response():
                return event


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

    async def _build_domain_context(self, event: Event | DomainEvent) -> Tuple[DomainEvent, dict]:
        """Build domain context from ADK Event, converting to DomainEvent.
        
        Includes: event, agent state, past experiences, market conditions.
        """
        # Handle both ADK Event and DomainEvent
        if isinstance(event, DomainEvent):
            domain_event = event
        else:
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
        
        # Get resource portfolio
        resource_portfolio = await self.get_resource_portfolio()
        
        # Load market state
        market_state = await self._market_provider.get_state()
        
        # Load past experiences (recent decisions for same event type)
        past_experiences = await self._sqlite_client.load_recent_decisions(
            agent_id=self.name,
            limit=10,
            event_type=domain_event.event_type.value,
        )
        
        # Negotiation history (empty for now, can be populated from negotiation events)
        negotiation_history = []
        
        return (domain_event, {
            "resource_portfolio": resource_portfolio,
            "market_state": market_state,
            "past_experiences": past_experiences,
            "negotiation_history": negotiation_history,
        })

    async def _consult_policy(self, context: Tuple[DomainEvent, dict]) -> Action | None:
        """Given a triggering event, use PolicyStore to determine the next action to take.

        Returns:
            Action object if policy matched, None otherwise.
        """
        domain_event, context_data = context
        event_type = domain_event.event_type
        
        # Ensure negotiation policy is saved for negotiation events
        if event_type == EventType.NEGOTIATION:
            await self._ensure_negotiation_policy()
        
        # Build DecisionContext for PolicyStore
        decision_context = DecisionContext(
            event=domain_event,
            agent_id=self.name,
            available_resources=context_data.get("resource_portfolio", {}),
            market_state=context_data.get("market_state", {}),
            negotiation_history=context_data.get("negotiation_history", []),
            past_experiences=context_data.get("past_experiences", []),
        )
        
        # Evaluate policy using PolicyStore
        try:
            action = await self._policy_store.evaluate_policy(
                agent_id=self.name,
                context=decision_context,
            )
            if action:
                logger.info(f"[POLICY] PolicyStore returned action: {action.action_type}")
                return action
        except Exception as e:
            logger.warning(f"PolicyStore evaluation failed: {e}, falling back to default behavior")
        
        return None
    
    async def _process_event_with_pipeline(self, domain_event: DomainEvent) -> str:
        """Process event through full reactive pipeline: context -> policy -> action -> execution -> recording."""
        # [1] Event detection - already done (domain_event received)
        # [2] Context building
        context = await self._build_domain_context(domain_event)
        domain_event, context_data = context
        
        # [3] Policy evaluation
        action = await self._consult_policy(context)
        
        if not action:
            logger.warning(f"[PIPELINE] No action determined for event {domain_event.event_id}")
            return "NO ACTION. No policy matched."
        
        # Create Decision record
        decision = Decision(
            decision_id=f"dec_{uuid.uuid4()}",
            agent_id=self.name,
            context=DecisionContext(
                event=domain_event,
                agent_id=self.name,
                available_resources=context_data.get("resource_portfolio", {}),
                market_state=context_data.get("market_state", {}),
                negotiation_history=context_data.get("negotiation_history", []),
                past_experiences=context_data.get("past_experiences", []),
            ),
            action=action,
            policy_used=action.action_type.value if hasattr(action.action_type, "value") else str(action.action_type),
            confidence=getattr(action, "confidence", 1.0),
        )
        
        # [4] Action execution (simulated)
        outcome = await execute_action(action)
        
        # [5] Experience recording
        try:
            import json as json_lib
            action_type_str = action.action_type.value if hasattr(action.action_type, "value") else str(action.action_type)
            await self._sqlite_client.save_decision(
                decision_id=decision.decision_id,
                event_id=domain_event.event_id,
                event_type=domain_event.event_type.value,
                agent_id=self.name,
                policy_used=decision.policy_used,
                action_type=action_type_str,
                confidence=decision.confidence,
                timestamp=decision.timestamp.isoformat(),
                context_json=json_lib.dumps(decision.context.model_dump()),
            )
            
            await self._sqlite_client.save_decision_outcome(
                decision_id=decision.decision_id,
                utility=outcome.get("utility"),
                outcome_json=json_lib.dumps(outcome),
                timestamp=datetime.now().isoformat(),
            )
            logger.info(f"[PIPELINE] Recorded decision {decision.decision_id} with outcome")
        except Exception as e:
            logger.error(f"[PIPELINE] Failed to record decision: {e}")
        
        # Return response string for backward compatibility
        action_type_str = action.action_type.value if hasattr(action.action_type, "value") else str(action.action_type)
        action_mappings = {
            "accept_offer": "ACCEPT the offer.",
            "reject_offer": "REJECT the offer.",
            "counter_offer": "COUNTER the offer.",
            "make_offer": "MAKE OFFER. Create market order.",
            "resolve_internally": "RESOLVE INTERNALLY. Run rebalance_internal_resources utility.",
            "noop": "NOOP. No action required.",
        }
        
        return action_mappings.get(action_type_str.lower(), f"{action_type_str.upper()} action executed.")

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

        # Process through full reactive pipeline
        context = await self._build_domain_context(last_event)
        domain_event, _ = context
        
        policy_recommendation = await self._process_event_with_pipeline(domain_event)

        logger.info(f"Policy recommendation: {policy_recommendation}")

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
    # Validate and queue event if enabled
    queue_event(alert)
    
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
    
    # Parse as DomainEvent and process through pipeline
    try:
        domain_event = _parse_domain_event(alert)
        response_text = await root_agent._process_event_with_pipeline(domain_event)
        return response_text
    except Exception as e:
        logger.error(f"Error processing alert through pipeline: {e}")
        # Fallback to original method
        pass
    
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


# Background task to process queued events
async def process_queued_events():
    """Background task to process events from queue."""
    while True:
        try:
            if has_queued_events():
                event_payload = pop_event()
                if event_payload:
                    try:
                        domain_event = _parse_domain_event(event_payload)
                        await root_agent._process_event_with_pipeline(domain_event)
                        logger.info(f"[QUEUE] Processed queued event: {domain_event.event_id}")
                    except Exception as e:
                        logger.error(f"[QUEUE] Error processing queued event: {e}")
            await asyncio.sleep(1)  # Check every second
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"[QUEUE] Error in queue processing loop: {e}")
            await asyncio.sleep(5)  # Back off on error


# Initialize startup tasks
async def _startup_tasks():
    """Initialize background tasks."""
    from .utils.config import CONFIG
    
    if CONFIG.enable_redis_ingest:
        await start_redis_subscriber()
        logger.info("[STARTUP] Redis subscriber started")
    
    if CONFIG.enable_event_queue:
        # Start queue processor in background
        task = asyncio.create_task(process_queued_events())
        logger.info("[STARTUP] Event queue processor started")
        return task
    
    return None


# Start background tasks when module loads (if asyncio event loop exists)
try:
    loop = asyncio.get_event_loop()
    if loop.is_running():
        # If loop is already running, schedule task
        loop.create_task(_startup_tasks())
    else:
        # Otherwise start tasks synchronously
        asyncio.run(_startup_tasks())
except RuntimeError:
    # No event loop yet, will be started by uvicorn
    pass
except Exception as e:
    logger.warning(f"Could not start background tasks at module load: {e}")
