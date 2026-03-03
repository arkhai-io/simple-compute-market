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
from alkahest_py import AlkahestClient
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
from pydantic import ValidationError
import logging

# Import config first
from core.agent.app.utils.config import CONFIG

# Setup file-based logging early, before any other imports that might log
from core.agent.app.utils.logging_config import setup_file_logging
setup_file_logging(CONFIG.log_file_path, CONFIG.log_level)

logger = logging.getLogger(__name__)

BASE_URL_OVERRIDE = CONFIG.base_url_override
MCP_SERVER_URL = CONFIG.mcp_server_url
PORT = CONFIG.port
AGENT_DB_PATH = CONFIG.agent_db_path
AGENT_PRIV_KEY = CONFIG.agent_priv_key
CHAIN_RPC_URL = CONFIG.chain_rpc_url

from core.agent.app.schema.pydantic_models import (
    ActionType,
    EventType,
    DomainEvent,
    AcceptOfferEvent,
    MarketOrder,
    MakeOfferEvent,
    ReceiveComputeObligationFulfillmentEvent,
    ArbitrationCompleteEvent,
    ResourceImbalanceEvent,
    ResourceAlertRequest,
    NegotiationEvent,
    GPUModel,
    Region,
    ComputeResource,
    ComputeResourcePortfolio,
    TokenResource,
    ComputeDomainResource,
    OrderCreateEvent,
    OrderCloseEvent,
)
from core.agent.app.policy.store import PolicyStore
from core.agent.app.policy.manager import PolicyManager
from core.agent.app.policy.negotiation_thread import get_thread_store
from core.agent.app.policy.seeding import ComputePolicySeeder
from core.agent.app.utils.sqlite_client import SQLiteClient
from core.agent.app.schema.pydantic_models import DecisionContext, Action, Decision
from core.agent.app.utils.event_ingestion import (
    configure_default_ingestion,
    queue_event,
    pop_event,
    has_queued_events,
    start_redis_subscriber,
    stop_redis_subscriber,
)
from core.agent.app.utils.market_provider import create_market_provider, MarketProvider
from core.agent.app.utils.action_executor import execute_action
from core.agent.app.utils.alkahest_config import (
    get_alkahest_network,
    prewarm_alkahest_address_config_cache,
    resolve_alkahest_address_config,
)
from core.agent.app.utils.serializer import json_serializer
from core.agent.app.utils.token_registry import TOKEN_REGISTRY
from core.agent.app.utils.zerotier import get_zerotier_ip
from pydantic import PrivateAttr


def _is_known_event_type(event_type: Any) -> bool:
    try:
        EventType(event_type)
        return True
    except (ValueError, KeyError, TypeError):
        return False


configure_default_ingestion(
    event_validation_mode=CONFIG.event_validation_mode,
    enable_event_queue=CONFIG.enable_event_queue,
    enable_redis_ingest=CONFIG.enable_redis_ingest,
    redis_url=CONFIG.redis_url,
    redis_channels=CONFIG.redis_channels,
    is_known_event_type=_is_known_event_type,
)

ALKAHEST_NETWORK = get_alkahest_network(CONFIG.alkahest_network)

# Limits to keep stored JSON blobs from exploding the SQLite size
MAX_CONTEXT_JSON_CHARS = 100_000
MAX_OUTCOME_JSON_CHARS = 100_000
MAX_PAST_EXPERIENCES = 5


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


def _extract_order_id(outcome: dict | None) -> str | None:
    if not isinstance(outcome, dict):
        return None
    if outcome.get("order_id"):
        return outcome["order_id"]
    result = outcome.get("result")
    if isinstance(result, dict):
        return result.get("order_id") or (result.get("order") or {}).get("order_id")
    return None


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
                "source_url": payload_dict.get("source")
                if isinstance(payload_dict.get("source"), str)
                and payload_dict.get("source", "").startswith(("http://", "https://"))
                else None,
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
    """Convert a domain event payload dictionary to a DomainEvent instance.
    
    Uses Pydantic validation for strict type checking. Raises ValidationError
    for invalid data instead of silently falling back to defaults.
    """
    if not payload:
        raise ValueError("Cannot parse empty payload as DomainEvent")

    event_type_str = payload.get("event_type")
    if not event_type_str:
        raise ValueError("Missing required field: event_type")
    
    try:
        event_type = EventType(event_type_str)
    except ValueError:
        # Unknown event type - log warning and create basic DomainEvent
        logger.warning(f"[PARSE DOMAIN EVENT] Unknown event_type: {event_type_str}, creating basic DomainEvent")
        return DomainEvent.model_validate(payload)
    
    # Extract data - prefer nested 'data' field, fallback to payload itself
    data = payload.get("data", payload)
    
    # Use Pydantic validation for each event type
    try:
        if event_type == EventType.RESOURCE_IMBALANCE:
            # Use ResourceImbalanceEvent.model_validate - model_validator handles resource conversion
            # Ensure resource is present in data for validation
            if "resource" not in data and "resource" not in payload:
                raise ValueError("Missing required field 'resource' in ResourceImbalanceEvent")
            
            # Ensure required fields exist in data
            if "imbalance_type" not in data:
                raise ValueError("Missing required field 'imbalance_type' in ResourceImbalanceEvent data")
            if "severity" not in data:
                raise ValueError("Missing required field 'severity' in ResourceImbalanceEvent data")
            
            # Use model_validate - model_validator will handle resource dict conversion
            return ResourceImbalanceEvent.model_validate(payload)
            
        elif event_type == EventType.ORDER_CREATE:
            offer_data = data.get("offer", data.get("offer_resource"))
            demand_data = data.get("demand", data.get("demand_resource"))
            if not isinstance(offer_data, dict) or not isinstance(demand_data, dict):
                raise ValueError("OrderCreateEvent requires 'offer' and 'demand' dictionaries")

            duration_hours = data.get("duration_hours", payload.get("duration_hours", 1))
            order_create_payload = {
                "event_id": payload.get("event_id") or f"order_create_{uuid.uuid4()}",
                "event_type": EventType.ORDER_CREATE.value,
                "source": payload.get("source") or BASE_URL_OVERRIDE,
                "offer": offer_data,
                "demand": demand_data,
                "duration_hours": duration_hours,
                "data": data,
            }
            return OrderCreateEvent.model_validate(order_create_payload)

        elif event_type == EventType.ORDER_CLOSE:
            order_id = data.get("order_id", payload.get("order_id"))
            if not isinstance(order_id, str) or not order_id.strip():
                raise ValueError("OrderCloseEvent requires 'order_id'")
            order_close_payload = {
                "event_id": payload.get("event_id") or f"order_close_{uuid.uuid4()}",
                "event_type": EventType.ORDER_CLOSE.value,
                "source": payload.get("source") or BASE_URL_OVERRIDE,
                "order_id": order_id,
                "data": data,
            }
            return OrderCloseEvent.model_validate(order_close_payload)

        elif event_type == EventType.MAKE_OFFER:
            # Extract offer data - could be in 'offer' key or directly in 'data'
            offer_data = data.get("offer", data)
            if not isinstance(offer_data, dict):
                raise ValueError("MakeOfferEvent requires 'offer' or order data as dictionary")
            
            # Validate MarketOrder (which will validate resources via model_validator)
            order = MarketOrder.model_validate(offer_data)
            return MakeOfferEvent.from_order(order)
            
        elif event_type == EventType.ACCEPT_OFFER:
            offer_data = data.get("offer", data)
            if not isinstance(offer_data, dict):
                raise ValueError("AcceptOfferEvent requires 'offer' or order data as dictionary")

            order = MarketOrder.model_validate(offer_data)
            escrow_uid = data.get("escrow_uid") or payload.get("escrow_uid")
            ssh_public_key = data.get("ssh_public_key") or payload.get("ssh_public_key")
            return AcceptOfferEvent.from_order(
                order,
                escrow_uid=escrow_uid,
                ssh_public_key=ssh_public_key,
            )
            
        elif event_type == EventType.RECEIVE_COMPUTE_OBLIGATION_FULFILLMENT:
            # Merge top-level source (A2A sender URL) into data so counterparty is known for reply routing
            source_url = payload.get("source_url") or (
                payload.get("source")
                if isinstance(payload.get("source"), str)
                and payload.get("source", "").startswith(("http://", "https://"))
                else None
            )
            fulfillment_payload = {
                **data,
                "source": payload.get("source") or data.get("source", "unknown"),
                "source_url": source_url,
            }
            return ReceiveComputeObligationFulfillmentEvent.from_payload(fulfillment_payload)

        elif event_type == EventType.ARBITRATION_COMPLETE:
            arb_payload = {**data, "source": payload.get("source") or data.get("source", "unknown")}
            return ArbitrationCompleteEvent.from_payload(arb_payload)
            
        elif event_type == EventType.NEGOTIATION:
            # Validate NegotiationEvent with required fields
            required_fields = ["negotiation_id", "message_type", "sender"]
            missing = [f for f in required_fields if f not in data]
            if missing:
                raise ValueError(f"NegotiationEvent missing required fields in data: {missing}")
            
            return NegotiationEvent.model_validate(payload)
            
        else:
            # For other known event types, use model_validate
            return DomainEvent.model_validate(payload)
            
    except ValidationError as e:
        logger.error(f"[PARSE DOMAIN EVENT] Validation failed for {event_type}: {e.errors()}")
        raise ValueError(f"Failed to validate {event_type} event: {e}") from e
    except (ValueError, KeyError, TypeError) as e:
        logger.error(f"[PARSE DOMAIN EVENT] Error parsing {event_type}: {e}")
        raise ValueError(f"Failed to parse {event_type} event: {e}") from e


def _serialize_context_for_storage(decision_context: DecisionContext) -> str:
    """Serialize decision context while trimming heavy fields to avoid huge blobs."""
    ctx_dict = decision_context.model_dump(mode="json")

    past_exps = ctx_dict.get("past_experiences") or []
    trimmed_exps = []
    for exp in past_exps[:MAX_PAST_EXPERIENCES]:
        trimmed_exps.append(
            {
                "decision_id": exp.get("decision_id"),
                "event_id": exp.get("event_id"),
                "event_type": exp.get("event_type"),
                "action_type": exp.get("action_type"),
                "policy_used": exp.get("policy_used"),
                "timestamp": exp.get("timestamp"),
            }
        )
    ctx_dict["past_experiences"] = trimmed_exps

    context_json = json.dumps(ctx_dict, default=json_serializer)
    if len(context_json) > MAX_CONTEXT_JSON_CHARS:
        logger.warning(
            f"[PIPELINE] Context JSON too large ({len(context_json)} chars). Storing truncated metadata."
        )
        context_json = json.dumps(
            {
                "truncated": True,
                "original_length": len(context_json),
                "message": "Context JSON exceeded max size and was trimmed for storage.",
            }
        )
    return context_json


def _serialize_outcome_for_storage(outcome: dict[str, Any]) -> str:
    """Serialize outcome with a size guard to prevent oversized blobs."""
    outcome_json = json.dumps(outcome, default=json_serializer)
    if len(outcome_json) > MAX_OUTCOME_JSON_CHARS:
        logger.warning(
            f"[PIPELINE] Outcome JSON too large ({len(outcome_json)} chars). Storing truncated metadata."
        )
        outcome_json = json.dumps(
            {
                "truncated": True,
                "original_length": len(outcome_json),
                "message": "Outcome JSON exceeded max size and was trimmed for storage.",
            }
        )
    return outcome_json
class TraderAgent(BaseAgent):
    """
    Custom agent for trading computational resources.
    """
    resource_portfolio: dict
    _policy_store: PolicyStore = PrivateAttr()
    _policy_manager: PolicyManager = PrivateAttr()
    _policy_seeder: ComputePolicySeeder = PrivateAttr()
    _sqlite_client: SQLiteClient = PrivateAttr()
    _market_provider: MarketProvider = PrivateAttr()
    _alkahest_client: Any = PrivateAttr()
    _last_action_outcomes: dict[str, dict] = PrivateAttr()

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
        self._last_action_outcomes = {}

        # Log ZeroTier IP if available for the configured network
        zerotier_network = os.getenv("ZEROTIER_NETWORK")
        if zerotier_network:
            zerotier_ip = get_zerotier_ip(zerotier_network)
            if zerotier_ip:
                logger.info("ZeroTier IP (%s): %s", zerotier_network, zerotier_ip)
            else:
                logger.info(
                    "ZeroTier IP not assigned yet for network %s. Ensure the member is authorized.",
                    zerotier_network,
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
        self._sqlite_client = SQLiteClient(db_path=AGENT_DB_PATH)
        
        # Initialize negotiation thread store
        get_thread_store(sqlite_client=self._sqlite_client)
        
        # Initialize PolicyStore (private attribute to avoid Pydantic field requirements)
        self._policy_store = PolicyStore(self._sqlite_client)
        self._policy_seeder = ComputePolicySeeder(
            policy_store=self._policy_store,
            sqlite_client=self._sqlite_client,
            agent_id=self.name,
        )
        
        # Initialize PolicyManager for policy lifecycle management
        self._policy_manager = PolicyManager(
            policy_store=self._policy_store,
            agent_id=self.name,
            seed_policies_for_event_type=self._policy_seeder.ensure_for_event_type,
        )
        self._policy_manager.initialize()
        
        # Initialize market provider
        self._market_provider = create_market_provider()

        # Initialize Alkahest client (only if both keys are provided and non-empty)
        has_priv_key = AGENT_PRIV_KEY and isinstance(AGENT_PRIV_KEY, str) and AGENT_PRIV_KEY.strip()
        has_rpc_url = CHAIN_RPC_URL and isinstance(CHAIN_RPC_URL, str) and CHAIN_RPC_URL.strip()
        
        if has_priv_key and has_rpc_url:
            try:
                prewarm_alkahest_address_config_cache(
                    CONFIG.alkahest_address_config_path
                )
                address_config = resolve_alkahest_address_config(
                    ALKAHEST_NETWORK,
                    config_path=CONFIG.alkahest_address_config_path,
                )
                self._alkahest_client = AlkahestClient(
                    private_key=AGENT_PRIV_KEY,
                    rpc_url=CHAIN_RPC_URL,
                    address_config=address_config,
                )
                logger.info(
                    "[ALKAHEST] Initialized client on network=%s (custom_config=%s)",
                    ALKAHEST_NETWORK,
                    address_config is not None,
                )
            except Exception as e:
                logger.warning(f"[ALKAHEST]: Failed to initialize client: {e}. Continuing without Alkahest client.")
                self._alkahest_client = None
        else:
            logger.debug("[ALKAHEST]: AGENT_PRIV_KEY or CHAIN_RPC_URL not set. Alkahest client will not be initialized.")
            self._alkahest_client = None

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
        
        # Load negotiation history from thread store if this is a NegotiationEvent
        negotiation_history = []
        thread_info = {}
        if isinstance(domain_event, NegotiationEvent):
            thread_store = get_thread_store()
            negotiation_id = domain_event.negotiation_id
            if negotiation_id:
                negotiation_history = await thread_store.get_thread(negotiation_id)
                thread_info = await thread_store.get_thread_info(
                    negotiation_id=negotiation_id,
                    owner_id=self.name
                ) or {}
        
        market_state_with_thread = {**market_state, "thread_info": thread_info}
        
        return (domain_event, {
            "resource_portfolio": resource_portfolio,
            "market_state": market_state_with_thread,
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

        await self._policy_manager.ensure_policy_for_event_type(event_type)

        decision_context = DecisionContext(
            event=domain_event,
            agent_id=self.name,
            available_resources=context_data.get("resource_portfolio", {}),
            market_state=context_data.get("market_state", {}),
            negotiation_history=context_data.get("negotiation_history", []),
            past_experiences=context_data.get("past_experiences", []),
        )

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
    
    async def _demo_alkahest(self) -> None:
        token = TOKEN_REGISTRY.require("MOCK")
        logger.info(
            "[ALKAHEST] Using %s (%s) with %s decimals",
            token.symbol,
            token.contract_address,
            token.decimals,
        )

        approval_value = 100 * (10 ** token.decimals)
        hash = await self._alkahest_client.erc20.approve(
            {"address": token.contract_address, "value": approval_value},
            "escrow",
        )

        logger.info(f"[ALKAHEST]: Hash: {hash}")

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
        # logger.info("[DEMO] DEMO AKLAHEST")
        # await self._demo_alkahest()
        outcome = await execute_action(
            action=action,
            ctx=ctx,
            alkahest_client=self._alkahest_client,
        )
        # Capture outcomes for synchronous endpoints that need structured results.
        self._last_action_outcomes[domain_event.event_id] = outcome
        
        # [5] Experience recording
        try:
            action_type_str = action.action_type.value if hasattr(action.action_type, "value") else str(action.action_type)
            context_json = _serialize_context_for_storage(decision.context)
            await self._sqlite_client.save_decision(
                decision_id=decision.decision_id,
                event_id=domain_event.event_id,
                event_type=domain_event.event_type.value,
                agent_id=self.name,
                policy_used=decision.policy_used,
                action_type=action_type_str,
                timestamp=decision.timestamp.isoformat(),
                context_json=context_json,
            )
            
            await self._sqlite_client.save_decision_outcome(
                decision_id=decision.decision_id,
                outcome_json=_serialize_outcome_for_storage(outcome),
                timestamp=datetime.now().isoformat(),
            )
            logger.info(f"[PIPELINE] Recorded decision {decision.decision_id} with outcome")
        except Exception as e:
            logger.error(f"[PIPELINE] Failed to record decision: {e}")
        
        action_type_str = action.action_type.value if hasattr(action.action_type, "value") else str(action.action_type)
        action_mappings = {
            "accept_offer": "ACCEPT the offer.",
            "reject_offer": "REJECT the offer.",
            "counter_offer": "COUNTER the offer.",
            "make_offer": "MAKE OFFER. Create market order.",
            "resolve_internally": "RESOLVE INTERNALLY. Run rebalance_internal_resources utility.",
            "collect_escrow": "COLLECT ESCROW. Collect escrow for completed fulfillment.",
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

# Build agent card from config (shared with registration script)
from core.agent.app.utils.agent_card import build_agent_card_data
agent_card_data = build_agent_card_data(
    agent_name=CONFIG.agent_name,
    base_url=BASE_URL_OVERRIDE
)
public_agent_card = AgentCard(
    name=agent_card_data["name"],
    description=agent_card_data["description"],
    url=agent_card_data["url"],
    version=agent_card_data["version"],
    defaultInputModes=agent_card_data["defaultInputModes"],
    defaultOutputModes=agent_card_data["defaultOutputModes"],
    skills=agent_card_data["skills"],
    capabilities=AgentCapabilities(**agent_card_data["capabilities"]),
)

ALERTS_APP_NAME = "alerts"
ALERTS_USER_ID = "resource-monitor"


async def _run_alert_conversation(alert_request: ResourceAlertRequest) -> str:
    """Route alert details through the root agent so it can decide on next steps."""
    # Convert alert to ResourceImbalanceEvent
    resource_event = alert_request.to_resource_imbalance_event(
        event_id=f"alert_{uuid.uuid4()}",
        source=ALERTS_USER_ID,
    )
    
    # Validate and queue event if enabled
    if CONFIG.enable_event_queue:
        queue_event(resource_event.model_dump(mode='json'))
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

    # Convert ResourceImbalanceEvent to function response format
    alert_payload = {
        "event_type": EventType.RESOURCE_IMBALANCE.value,
        "event_id": resource_event.event_id,
        "source": resource_event.source,
        "data": resource_event.model_dump(mode='json'),
    }
    
    message = genai_types.Content(
        role="user",
        parts=[
            genai_types.Part.from_function_response(
                name="get_alert",
                response=alert_payload
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
    """Expose an endpoint that forwards resource alerts to the root agent.
    
    Validates alert structure using ResourceAlertRequest with strict validation.
    Returns 400 with detailed error messages if validation fails.
    """
    try:
        alert_data = await request.json()
    except Exception as e:
        return JSONResponse(
            {"error": "Invalid JSON in request body", "detail": str(e)},
            status_code=400
        )
    
    try:
        # Strict validation - all fields required, no defaults
        alert_request = ResourceAlertRequest.model_validate(alert_data)
    except ValidationError as e:
        # Convert validation errors to JSON-serializable format
        error_details = []
        for error in e.errors():
            # Convert error dict to JSON-serializable format
            serializable_error = {
                "type": error.get("type"),
                "loc": error.get("loc"),
                "msg": error.get("msg"),
                "input": error.get("input"),
            }
            # Handle ctx field which may contain non-serializable exceptions
            if "ctx" in error:
                ctx = error["ctx"]
                if isinstance(ctx, dict):
                    serializable_ctx = {}
                    for key, value in ctx.items():
                        if isinstance(value, Exception):
                            serializable_ctx[key] = str(value)
                        else:
                            serializable_ctx[key] = value
                    serializable_error["ctx"] = serializable_ctx
                else:
                    serializable_error["ctx"] = str(ctx) if ctx else None
            error_details.append(serializable_error)
        
        logger.error(f"[ALERT VALIDATION] Validation failed: {error_details}")
        return JSONResponse(
            {
                "error": "Alert validation failed",
                "details": error_details,
            },
            status_code=400
        )
    except Exception as e:
        logger.error(f"[ALERT VALIDATION] Unexpected error: {e}")
        return JSONResponse(
            {"error": "Failed to validate alert", "detail": str(e)},
            status_code=400
        )

    try:
        response_text = await _run_alert_conversation(alert_request)
        response = alert_request.model_dump(mode='json')
        response["root_agent_response"] = response_text
        return JSONResponse(response)
    except Exception as e:
        logger.error(f"[ALERT PROCESSING] Error processing alert: {e}")
        return JSONResponse(
            {"error": "Failed to process alert", "detail": str(e)},
            status_code=500
        )


# Create Starlette route for the alert endpoint
alert_route = Route("/alerts/resource", handle_resource_alert, methods=["POST"])

AGENT_REST_API_APP_NAME = "agent-rest-api"
AGENT_REST_API_USER_ID = "agent-rest-api"

async def _run_create_order_flow(request: Request) -> dict:
    """
    Internal helper to run the create order flow.

    Example offer (compute):
    {
      "gpu_model": "H200",
      "quantity": 1,
      "sla": 99.9,
      "region": "California, US"
    }

    Example demand (token):
    {
      "token": "MOCK",
      "amount": 9.0
    }
    """
    # Validate that request JSON is valid:
    # - Must have both offer and demand specified
    # - One must be a ComputeResource and the other a TokenResource
    try:
        order_data = await request.json()
    except Exception as e:
        raise ValueError(f"Invalid JSON in request body: {e}") from e

    offer_data = order_data.get("offer")
    demand_data = order_data.get("demand")
    duration_hours = order_data.get("duration_hours", 1)

    if offer_data is None or demand_data is None:
        raise ValueError("Request must include both 'offer' and 'demand'")

    def normalize_token_resource(resource_payload: dict) -> dict:
        if "token" not in resource_payload:
            return resource_payload

        token_value = resource_payload.get("token")
        if token_value is None:
            raise ValueError("Token must be a symbol or contract address")

        try:
            if isinstance(token_value, str):
                token_meta = TOKEN_REGISTRY.require(token_value)
            elif isinstance(token_value, dict):
                if all(key in token_value for key in ("symbol", "contract_address", "decimals")):
                    token_meta = token_value
                elif "symbol" in token_value:
                    token_meta = TOKEN_REGISTRY.require(token_value["symbol"])
                elif "contract_address" in token_value:
                    token_meta = TOKEN_REGISTRY.require(token_value["contract_address"])
                else:
                    raise ValueError("Token metadata must include symbol/contract_address/decimals")
            else:
                raise ValueError("Token must be a symbol or contract address")
        except Exception as exc:
            raise ValueError(f"Unknown token: {token_value}") from exc

        amount_value = resource_payload.get("amount")
        if amount_value is None:
            raise ValueError("Token resource must include amount")

        from decimal import Decimal
        if isinstance(token_meta, dict):
            decimals = int(token_meta["decimals"])
            token_dump = token_meta
        else:
            decimals = token_meta.decimals
            token_dump = token_meta.model_dump()

        raw = Decimal(str(amount_value)) * (Decimal(10) ** decimals)
        if raw != raw.to_integral_value():
            raise ValueError("Amount has too many decimal places for token")
        amount_int = int(raw)

        normalized = dict(resource_payload)
        normalized["token"] = token_dump
        normalized["amount"] = amount_int
        return normalized

    try:
        offer_resource = ComputeDomainResource.parse_from_dict(normalize_token_resource(offer_data))
        demand_resource = ComputeDomainResource.parse_from_dict(normalize_token_resource(demand_data))
    except Exception as e:
        raise ValueError(f"Invalid offer/demand resource: {e}") from e

    offer_is_compute = isinstance(offer_resource, ComputeResource)
    offer_is_token = isinstance(offer_resource, TokenResource)
    demand_is_compute = isinstance(demand_resource, ComputeResource)
    demand_is_token = isinstance(demand_resource, TokenResource)

    if not ((offer_is_compute and demand_is_token) or (offer_is_token and demand_is_compute)):
        raise ValueError("Offer and demand must be one compute and one token resource")

    event_id = f"order_create_{uuid.uuid4()}"
    order_create_event = OrderCreateEvent(
        event_id=event_id,
        source=BASE_URL_OVERRIDE,
        offer=offer_resource,
        demand=demand_resource,
        duration_hours=duration_hours,
        data={
            "offer": offer_resource.model_dump(mode="json"),
            "demand": demand_resource.model_dump(mode="json"),
            "duration_hours": duration_hours,
        },
    )

    if CONFIG.enable_event_queue:
        queue_event(order_create_event.model_dump(mode="json"))
        return {
            "status": "queued",
            "event_id": event_id,
            "order_request": order_create_event.model_dump(mode="json"),
        }

    session_service = InMemorySessionService()
    session = session_service.create_session_sync(
        app_name=AGENT_REST_API_APP_NAME,
        user_id=AGENT_REST_API_USER_ID,
    )
    runner = Runner(
        agent=root_agent,
        app_name=AGENT_REST_API_APP_NAME,
        session_service=session_service,
    )

    event_payload = order_create_event.model_dump(mode="json")

    message = genai_types.Content(
        role="user",
        parts=[
            genai_types.Part.from_function_response(
                name="create_order",
                response=event_payload
            )
        ],
    )

    final_response: str | None = None
    async for event in runner.run_async(
        user_id=AGENT_REST_API_USER_ID,
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
            detail="root_agent did not provide a response to the order creation request.",
        )

    outcome = root_agent._last_action_outcomes.pop(event_id, None)
    order_id = _extract_order_id(outcome)

    response_payload = {
        "status": "created",
        "event_id": event_id,
        "order_request": order_create_event.model_dump(mode="json"),
        "root_agent_response": final_response,
    }
    if order_id:
        response_payload["order_id"] = order_id
    return response_payload

async def _run_close_order_flow(request: Request) -> dict:
    """
    Internal helper to run the close order flow.

    Expected payload:
    {
      "order_id": "..."
    }
    """
    try:
        close_data = await request.json()
    except Exception as e:
        raise ValueError(f"Invalid JSON in request body: {e}") from e

    order_id = close_data.get("order_id")
    if not isinstance(order_id, str) or not order_id.strip():
        raise ValueError("Request must include non-empty 'order_id'")

    event_id = f"order_close_{uuid.uuid4()}"
    order_close_event = OrderCloseEvent(
        event_id=event_id,
        source=BASE_URL_OVERRIDE,
        order_id=order_id,
        data={"order_id": order_id},
    )

    if CONFIG.enable_event_queue:
        queue_event(order_close_event.model_dump(mode="json"))
        return {
            "status": "queued",
            "event_id": event_id,
            "order_request": order_close_event.model_dump(mode="json"),
        }

    session_service = InMemorySessionService()
    session = session_service.create_session_sync(
        app_name=AGENT_REST_API_APP_NAME,
        user_id=AGENT_REST_API_USER_ID,
    )
    runner = Runner(
        agent=root_agent,
        app_name=AGENT_REST_API_APP_NAME,
        session_service=session_service,
    )

    event_payload = order_close_event.model_dump(mode="json")

    message = genai_types.Content(
        role="user",
        parts=[
            genai_types.Part.from_function_response(
                name="close_order",
                response=event_payload
            )
        ],
    )

    final_response: str | None = None
    async for event in runner.run_async(
        user_id=AGENT_REST_API_USER_ID,
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
            detail="root_agent did not provide a response to the order close request.",
        )

    return {
        "status": "closed",
        "event_id": event_id,
        "order_request": order_close_event.model_dump(mode="json"),
        "root_agent_response": final_response,
    }

async def create_market_order_endpoint(request: Request) -> JSONResponse:
    """
    Expose an endpoint to create market orders via the root agent.
    """

    try:
        response = await _run_create_order_flow(request)
        return JSONResponse(response)
    except ValueError as e:
        logger.error(f"[ORDER CREATION] Validation error: {e}")
        return JSONResponse(
            {"error": "Order validation failed", "detail": str(e)},
            status_code=400
        )
    except ValidationError as e:
        logger.error(f"[ORDER CREATION] Validation error: {e}")
        return JSONResponse(
            {"error": "Order validation failed", "detail": str(e)},
            status_code=400
        )
    except Exception as e:
        logger.error(f"[ORDER CREATION] Error creating market order: {e}")
        return JSONResponse(
            {"error": "Failed to create market order", "detail": str(e)},
            status_code=500
        )

async def close_market_order_endpoint(request: Request) -> JSONResponse:
    """
    Expose an endpoint to close market orders via the root agent.
    """
    try:
        response = await _run_close_order_flow(request)
        return JSONResponse(response)
    except ValueError as e:
        logger.error(f"[ORDER CLOSE] Validation error: {e}")
        return JSONResponse(
            {"error": "Order close validation failed", "detail": str(e)},
            status_code=400
        )
    except ValidationError as e:
        logger.error(f"[ORDER CLOSE] Validation error: {e}")
        return JSONResponse(
            {"error": "Order close validation failed", "detail": str(e)},
            status_code=400
        )
    except Exception as e:
        logger.error(f"[ORDER CLOSE] Error closing market order: {e}")
        return JSONResponse(
            {"error": "Failed to close market order", "detail": str(e)},
            status_code=500
        )

agent_order_creation_route = Route("/orders/create", create_market_order_endpoint, methods=["POST"])
agent_order_close_route = Route("/orders/close", close_market_order_endpoint, methods=["POST"])

a2a_app = to_a2a(root_agent, port=PORT, agent_card=public_agent_card)

# Add the alert route to the A2A app
a2a_app.routes.append(alert_route)
# Add the order creation route to the A2A app
a2a_app.routes.append(agent_order_creation_route)
# Add the order close route to the A2A app
a2a_app.routes.append(agent_order_close_route)

# Add ERC-8004 registration file endpoint
# Per ERC-8004 spec: tokenURI MUST resolve to the agent registration file
from core.agent.app.utils.agent_card import build_erc8004_registration_file
from core.agent.app.utils.registry.blockchain_utils import (
    build_erc8004_canonical_id,
    rpc_url_for_http_provider,
)

async def serve_erc8004_registration_file(request: Request) -> JSONResponse:
    """
    Serve ERC-8004 registration file at /.well-known/erc-8004-registration.json
    
    Per ERC-8004 spec, this file contains:
    - type: "https://eips.ethereum.org/EIPS/eip-8004#registration-v1"
    - name, description, endpoints (with A2A endpoint pointing to agent card)
    - registrations: array with agentId and agentRegistry (if registered on-chain)
    - supportedTrust: array (optional)
    """
    # Get chain_id
    chain_id = 1337  # Default
    if CONFIG.chain_rpc_url:
        try:
            from web3 import Web3
            from web3.providers import HTTPProvider
            http_url = rpc_url_for_http_provider(CONFIG.chain_rpc_url)
            w3 = Web3(HTTPProvider(http_url, request_kwargs={'timeout': 5}))
            chain_id = w3.eth.chain_id
        except Exception:
            pass  # Use default
    
    # Get on-chain agent ID if available
    agent_id = None
    if CONFIG.onchain_agent_id:
        try:
            agent_id = int(CONFIG.onchain_agent_id)
        except ValueError:
            pass
    
    # Build registration file
    registration_file = build_erc8004_registration_file(
        agent_card_data=agent_card_data,
        agent_id=agent_id,
        chain_id=chain_id,
        identity_registry=CONFIG.identity_registry_address,
        supported_trust=[]
    )
    
    return JSONResponse(registration_file)

# Add registration file route
registration_file_route = Route("/.well-known/erc-8004-registration.json", serve_erc8004_registration_file, methods=["GET"])
a2a_app.routes.append(registration_file_route)


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


# Background task to start heartbeat after server is ready
async def _start_heartbeat():
    """Start heartbeat loop after server is ready."""
    from core.agent.app.utils.config import CONFIG
    from core.agent.app.agent_heartbeat import start_agent_heartbeat
    await start_agent_heartbeat(CONFIG)


# Initialize startup tasks
async def _startup_tasks():
    """Initialize background tasks."""
    from core.agent.app.utils.config import CONFIG

    # Start heartbeat after server is ready
    asyncio.create_task(_start_heartbeat())

    if CONFIG.enable_redis_ingest:
        await start_redis_subscriber()
        logger.info("[STARTUP] Redis subscriber started")

    if CONFIG.enable_event_queue:
        # Start queue processor in background
        task = asyncio.create_task(process_queued_events())
        logger.info("[STARTUP] Event queue processor started")
        return task

    return None


# Background tasks are now started via FastAPI startup event in server.py
# This ensures the event loop is running when tasks are created
