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
import ast
from typing import AsyncGenerator, Any, Dict, Optional, override, Tuple
from enum import Enum
import re

import google.auth
from a2a.types import AgentCapabilities, AgentCard, AgentSkill
from fastapi import HTTPException
from google.adk.a2a.utils.agent_to_a2a import to_a2a
from google.adk.agents import BaseAgent,  InvocationContext
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

BASE_URL_OVERRIDE = CONFIG.base_url_override
MCP_SERVER_URL = CONFIG.mcp_server_url
PORT = CONFIG.port
POLICY_DB_PATH = CONFIG.policy_db_path


from .schema.pydantic_models import (
    ActionType,
    EventType,
    DomainEvent,
    MarketOrder,
    MakeOfferEvent,
    ResourceImbalanceEvent,
    NegotiationEvent,
    GPUModel,
    Region,
    ComputeResource,
    ComputeResourcePortfolio,
)

from .policies.store import PolicyStore
from .policies.manager import PolicyManager
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
from .utils.serializer import json_serializer
from pydantic import PrivateAttr


INCOMING_A2A_PATTERN = re.compile(
    r"""\[(?P<agent>[^\]]+)\] `(?P<tool>[^`]+)` tool returned result: (?P<payload>\{.*\})*$""",
    re.DOTALL
)

# Convert "<EventType.MAKE_OFFER: 'make_offer'>" → "'make_offer'"
ENUM_REPR_PATTERN = re.compile(
    r"<[A-Za-z_][\w.]*:\s*'([^'\\]*(?:\\.[^'\\]*)*)'>"
)

def normalize_enums(payload_text: str) -> str:
    """
    Replace enum reprs like <Enum.Member: 'value'> with just 'value'.
    Handles escaped quotes inside the value.
    """
    return ENUM_REPR_PATTERN.sub(r"'\1'", payload_text)


def safe_literal_eval(payload_text: str, *, max_len: int = 50_000) -> Any:
    """
    Safely parse a Python-literal string (dict/list/tuple/set/str/num/bool/None).
    Guards against large inputs and rejects non-literals.

    Raises:
        TypeError, ValueError on invalid input or policy violations.
    """
    if not isinstance(payload_text, str):
        raise TypeError("payload must be a string")

    if len(payload_text) > max_len:
        raise ValueError(f"payload too large (>{max_len} bytes)")

    leading_trimmed = payload_text.lstrip()
    trailing_trimmed = payload_text.rstrip()
    if not leading_trimmed.startswith("{") or not trailing_trimmed.endswith("}"):
        raise ValueError("payload is not a dict literal (must start with '{' and end with '}')")

    try:
        return ast.literal_eval(payload_text)
    except (SyntaxError, ValueError, MemoryError, RecursionError) as exc:
        raise ValueError(f"failed to parse payload: {exc}") from exc


def _extract_content_payload(
    content: Optional[genai_types.Content],
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Parse functionResponse and A2A communications.

    Interim solution for issue https://github.com/google/adk-python/issues/3260
    with WIP PR https://github.com/google/adk-python/pull/3262
    """
    if not content:
        return None, None

    if len(content.parts) == 0:
        return None, None

    tool_name = None
    response_dict = None

    # Get the most recent part
    part = content.parts[-1]

    logger.info(f"[CONTENT PART]: {part}")

    # Skip context messages
    text = getattr(part, "text", None)

    if text:
        tool_pattern_match = INCOMING_A2A_PATTERN.search(text)
        if tool_pattern_match:
            logger.info("[CONTENT PART] Received A2A message:")

            agent_str = tool_pattern_match.group("agent").strip()
            tool_name = tool_pattern_match.group("tool").strip()
            payload_str = tool_pattern_match.group("payload").strip()

            try:
                enum_normalized_payload = normalize_enums(payload_str)
                payload_dict = safe_literal_eval(enum_normalized_payload)
            except (ValueError, TypeError) as e:
                logger.error(f"Failed to parse A2A payload: {e}")
                return None, None

            logger.info(f"[EXTRACT CONTENT PAYLOAD]   [AGENT]: {agent_str}")
            logger.info(f"[EXTRACT CONTENT PAYLOAD]    [TOOL]: {tool_name}")
            logger.info(f"[EXTRACT CONTENT PAYLOAD] [PAYLOAD]: {payload_str}")
            try:
                EventType(tool_name)
            except ValueError:
                logger.warning(
                    f"Unknown event_type from tool '{tool_name}'. "
                    f"Known types: {[e.value for e in EventType]}"
                )
            response_dict = {
                "source": agent_str,
                "event_type": tool_name,
                "message": None,
                "data": payload_dict
            }
            return tool_name, response_dict
        else:
            logger.error(f"Unknown text message received: {text}")
            return None, None
    else:
        function_response = getattr(part, "function_response", None)

        if function_response:
            # function_response has .name and .response (dict-like)
            this_part_tool_name = getattr(function_response, "name", None)
            this_part_response = getattr(function_response, "response", None)

            if this_part_tool_name and this_part_response:
                tool_name = this_part_tool_name
                response_dict = this_part_response

    return tool_name, response_dict


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
    elif event_type == EventType.MAKE_OFFER:
        try:
            offer_data = data.get("offer", data)
            order = MarketOrder.model_validate(offer_data)
            return MakeOfferEvent.from_order(order)
        except (ValueError, KeyError, TypeError) as e:
            logger.warning(f"Failed to create MakeOfferEvent: {e}, falling back to DomainEvent")
    
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
    logger.info(f"[PARSE DOMAIN EVENT] Falling back to event_type {event_type}")
    return DomainEvent(
        event_id=event_id,
        event_type=event_type or EventType.MAKE_OFFER,  # Default if unknown
        timestamp=timestamp,
        source=source,
        data=data,
    )

class TraderAgent(BaseAgent):
    """
    Custom agent for trading computational resources.
    """
    resource_portfolio: dict
    _policy_store: PolicyStore = PrivateAttr()
    _policy_manager: PolicyManager = PrivateAttr()
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
        
        # Initialize PolicyManager for policy lifecycle management
        self._policy_manager = PolicyManager(
            policy_store=self._policy_store,
            sqlite_client=self._sqlite_client,
            agent_id=self.name,
        )
        self._policy_manager.initialize()
        
        # Initialize market provider
        self._market_provider = create_market_provider()

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
            # A2A messages come in as text
            content = _extract_content_payload(event.content)
            # content = _extract_tool_payload(event.content)
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
        
        # Ensure policy exists for this event type (lazy policy setup)
        await self._policy_manager.ensure_policy_for_event_type(event_type)
        
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
    
    async def _process_event_with_pipeline(self, domain_event: DomainEvent, *, ctx: InvocationContext | None = None) -> str:
        """Process event through full reactive pipeline: context -> policy -> action -> execution -> recording."""
        # [1] Event detection - already done (domain_event received)
        # [2] Context building
        domain_context = await self._build_domain_context(domain_event)
        domain_event, context_data = domain_context
        
        # [3] Policy evaluation
        action = await self._consult_policy(domain_context)
        if not action:
            logger.info(f"[PROCESS EVENT] No policy matched for event: {domain_event}")

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
        )
        
        # [4] Action execution (simulated)
        outcome = await execute_action(action=action, ctx=ctx)
        
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
                timestamp=decision.timestamp.isoformat(),
                context_json=decision.context.model_dump_json(),
            )
            
            await self._sqlite_client.save_decision_outcome(
                decision_id=decision.decision_id,
                outcome_json=json_lib.dumps(outcome, default=json_serializer),
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
        outcome_message = outcome.get("message", None)
        fallback_message = action_mappings.get(action_type_str.lower(), f"{action_type_str.upper()} action executed.")
        logger.info(f"{outcome} {outcome_message}")
        return outcome_message or fallback_message

    @override
    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        if len(ctx.session.events[-1].content.parts) > 10:
            yield Event(
            author=self.name,
            content=genai_types.Content(
                role="model",
                parts=[genai_types.Part.from_text(text=f"Too many message parts. Aborting.")],
            ),
            invocation_id=ctx.invocation_id,
            branch=ctx.branch,
        )
        last_event = ctx.session.events[-1]
        logger.info(f"[RUN ASYNC]: Last Event {last_event}")

        logger.info("[RUN ASYNC] CONTENT:")

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

        name, content = _extract_content_payload(last_event.content)
        logger.info(f"{name}: {content}")

        # Process through full reactive pipeline
        domain_event = _parse_domain_event(content)
        policy_recommendation = await self._process_event_with_pipeline(domain_event, ctx=ctx)

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
    name=CONFIG.agent_id,
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
    if CONFIG.enable_event_queue:
        queue_event(alert)
        return "Alert processing queued."
    
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


# Background task to process queued events
# TODO Refactor this to run through _run_async_impl for it to have access to ctx
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
