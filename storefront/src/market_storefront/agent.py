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
from alkahest_py import AlkahestClient
from typing import Any, Dict, Optional, Tuple
from enum import Enum


from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from pydantic import ValidationError
import logging

# Import config first
from market_storefront.utils.config import CONFIG

# Setup file-based logging early, before any other imports that might log
from market_storefront.utils.logging_config import setup_file_logging
setup_file_logging(CONFIG.log_file_path, CONFIG.log_level)

logger = logging.getLogger(__name__)

BASE_URL_OVERRIDE = CONFIG.base_url_override
MCP_SERVER_URL = CONFIG.mcp_server_url
PORT = CONFIG.port
AGENT_DB_PATH = CONFIG.agent_db_path
AGENT_PRIV_KEY = CONFIG.agent_priv_key
CHAIN_RPC_URL = CONFIG.chain_rpc_url

from market_storefront.schema.pydantic_models import (
    ActionType,
    EventType,
    DomainEvent,
    MarketOrder,
    ReceiveComputeObligationFulfillmentEvent,
    FulfillmentFailedEvent,
    ArbitrationCompleteEvent,
    ResourceImbalanceEvent,
    ResourceAlertRequest,
    ComputeResource,
    TokenResource,
    OrderCreateEvent,
    OrderCloseEvent,
)
from market_storefront.resources import (
    adapt_db_resource_to_domain_resource,
    get_supported_resource_types,
    parse_resource_from_dict,
)
from market_policy.store import PolicyStore
from market_policy.manager import PolicyManager
from market_policy.negotiation_thread import get_thread_store
from market_policy.identity import Identity
from market_storefront.policy.seeding import ComputePolicySeeder
from market_storefront.utils.sqlite_client import SQLiteClient
from market_storefront.schema.pydantic_models import DecisionContext, Action, Decision
from market_storefront.utils.action_executor import _sender_id as _get_sender_id
from market_storefront.utils.event_ingestion import (
    configure_default_ingestion,
    queue_event,
    pop_event,
    has_queued_events,
    is_event_queue_enabled,
    start_redis_subscriber,
    stop_redis_subscriber,
)

from market_storefront.utils.action_executor import execute_action
from service.clients.alkahest import (
    get_alkahest_network,
    prewarm_alkahest_address_config_cache,
    resolve_alkahest_address_config,
)
from market_storefront.utils.serializer import json_serializer
from service.clients.token import TOKEN_REGISTRY, init_token_registry
from market_storefront.utils.zerotier import get_zerotier_ip

# Re-bind TOKEN_REGISTRY to the path resolved from our typed config.
# (The module-level singleton is otherwise loaded from a bundled default
# at import time.)
init_token_registry(CONFIG.token_registry_path)


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

ALKAHEST_NETWORK = get_alkahest_network(CONFIG.chain_name)


# Wire the typed RegistryClient config into the service-layer singleton
# so callers (action_executor, etc.) can use `get_registry_client()` with
# no args. The canonical eip155:... agent_id is resolved from CONFIG —
# no env vars.
from service.clients.indexer import (
    CanonicalAgentIdInputs,
    RegistryClientConfig,
    configure_registry_client,
    resolve_canonical_agent_id,
)

configure_registry_client(RegistryClientConfig(
    base_url=CONFIG.indexer_url,
    timeout=CONFIG.registry_order_timeout,
    private_key=CONFIG.agent_priv_key,
    agent_id=resolve_canonical_agent_id(CanonicalAgentIdInputs(
        onchain_agent_id=CONFIG.onchain_agent_id,
        agent_id=CONFIG.agent_id,
        identity_registry_address=CONFIG.identity_registry_address,
        chain_rpc_url=CONFIG.chain_rpc_url,
        alkahest_network=ALKAHEST_NETWORK,
    )),
))

# Limits to keep stored JSON blobs from exploding the SQLite size
MAX_CONTEXT_JSON_CHARS = 100_000
MAX_OUTCOME_JSON_CHARS = 100_000
MAX_PAST_EXPERIENCES = 5


def _extract_order_id(outcome: dict | None) -> str | None:
    if not isinstance(outcome, dict):
        return None
    if outcome.get("order_id"):
        return outcome["order_id"]
    result = outcome.get("result")
    if isinstance(result, dict):
        return result.get("order_id") or (result.get("order") or {}).get("order_id")
    return None


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
    
    # Tool names that carry the real event_type inside payload["data"] — not EventType values.
    _TOOL_NAME_ALIASES = {"counter_offer", "exit_negotiation", "make_offer", "accept_offer"}

    try:
        event_type = EventType(event_type_str)
    except ValueError:
        # Unknown event type — check if the actual domain event is nested inside payload["data"].
        nested = payload.get("data")
        if isinstance(nested, dict) and nested.get("event_type") and nested.get("event_type") != event_type_str:
            if event_type_str not in _TOOL_NAME_ALIASES:
                logger.warning(f"[PARSE DOMAIN EVENT] Unknown event_type '{event_type_str}', retrying with nested data event_type '{nested.get('event_type')}'")
            return _parse_domain_event(nested)
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

        elif event_type == EventType.FULFILLMENT_FAILED:
            return FulfillmentFailedEvent(
                event_id=payload.get("event_id", f"ff_{uuid.uuid4()}"),
                source=payload.get("source", "unknown"),
                escrow_uid=data.get("escrow_uid", ""),
                reason=data.get("reason"),
                seller_order_id=data.get("seller_order_id"),
                negotiation_id=data.get("negotiation_id"),
                data=data,
            )

        elif event_type == EventType.ARBITRATION_COMPLETE:
            arb_payload = {**data, "source": payload.get("source") or data.get("source", "unknown")}
            return ArbitrationCompleteEvent.from_payload(arb_payload)

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
class TraderAgent:
    """Reactive policy-driven trader for compute resources.

    Inbound endpoints construct a DomainEvent and call
    `_process_event_with_pipeline` directly.
    """

    def __init__(self, name: str):
        logger.info("Starting TraderAgent.")
        self.name = name
        self.resource_portfolio: dict = {}
        self._last_action_outcomes: dict[str, dict] = {}

        # Log ZeroTier IP if available for the configured network.
        zerotier_network = CONFIG.zerotier_network
        if zerotier_network:
            zerotier_ip = get_zerotier_ip(zerotier_network)
            if zerotier_ip:
                logger.info("ZeroTier IP (%s): %s", zerotier_network, zerotier_ip)
            else:
                logger.info(
                    "ZeroTier IP not assigned yet for network %s. Ensure the member is authorized.",
                    zerotier_network,
                )

        # Initialize SQLite client (shared for policies and decisions)
        self._sqlite_client = SQLiteClient(db_path=AGENT_DB_PATH)

        # Initialize negotiation thread store with our local identity.
        # The engine is identity-agnostic; we hand it the storefront's
        # url + agent id at boot.
        get_thread_store(
            sqlite_client=self._sqlite_client,
            identity=Identity(agent_url=BASE_URL_OVERRIDE, agent_id=self.name),
        )
        
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
        supported_resource_types = get_supported_resource_types()
        db_resources = await self._sqlite_client.list_resources()
        resources: list[dict[str, Any]] = []

        for db_resource in db_resources:
            resource_type = db_resource.get("resource_type")
            if resource_type not in supported_resource_types:
                continue

            try:
                resource = adapt_db_resource_to_domain_resource(db_resource)
            except Exception as exc:
                logger.warning(
                    "[RESOURCE PORTFOLIO] Skipping malformed supported resource %s (%s): %s",
                    db_resource.get("resource_id"),
                    resource_type,
                    exc,
                )
                continue

            if hasattr(resource, "model_dump"):
                resources.append(resource.model_dump(mode="json"))

        return {"resources": resources}

    async def _build_domain_context(self, event: DomainEvent) -> tuple[DomainEvent, dict]:
        """Enrich a DomainEvent with agent state, past experiences, market conditions."""
        if not isinstance(event, DomainEvent):
            raise TypeError(
                f"_build_domain_context expects a DomainEvent, got {type(event).__name__}"
            )
        domain_event = event
        
        # Get resource portfolio
        resource_portfolio = await self.get_resource_portfolio()
        
        market_state: dict = {}
        
        # Load past experiences (recent decisions for same event type)
        past_experiences = await self._sqlite_client.load_recent_decisions(
            agent_id=self.name,
            limit=10,
            event_type=domain_event.event_type.value,
        )
        
        # The legacy NegotiationEvent path used to load thread_info +
        # negotiation_history here. Negotiation now goes through the
        # sync /negotiate/* endpoints, which talk to the thread store
        # directly; the event-pipeline path no longer sees negotiation
        # events.
        market_state_with_thread = {**market_state, "thread_info": {}}
        negotiation_history: list = []
        
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
            agent_id=_get_sender_id(),
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

    async def _process_event_with_pipeline(self, domain_event: DomainEvent, *, ctx: Any | None = None) -> str:
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
                agent_id=_get_sender_id(),
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


root_agent = TraderAgent(
    name=CONFIG.agent_id,
)

# Agent card metadata (served read-only at /.well-known/erc-8004-registration.json).
# No longer wrapped in an a2a.types.AgentCard — this agent does not speak A2A.
from market_storefront.utils.agent_card import build_agent_card_data
agent_card_data = build_agent_card_data(
    agent_name=CONFIG.agent_name,
    base_url=BASE_URL_OVERRIDE,
    agent_wallet_address=CONFIG.agent_wallet_address,
)

ALERTS_USER_ID = "resource-monitor"


async def _run_alert_conversation(alert_request: ResourceAlertRequest) -> str:
    """Route a resource-imbalance alert through the reactive pipeline."""
    resource_event = alert_request.to_resource_imbalance_event(
        event_id=f"alert_{uuid.uuid4()}",
        source=ALERTS_USER_ID,
    )

    if is_event_queue_enabled():
        queue_event(resource_event.model_dump(mode="json"))
        return "Alert processing queued."

    message = await root_agent._process_event_with_pipeline(resource_event, ctx=None)
    return message or "Alert processed."


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

_MAX_TIMESTAMP_SKEW = 300  # seconds


def _check_agent_request_auth(request: Request, operation: str, resource_id: str) -> JSONResponse | None:
    """Verify X-Signature / X-Timestamp headers against the agent's own wallet address.

    Returns a JSONResponse (403) if auth fails, or None to allow the request through.
    If AGENT_WALLET_ADDRESS is not configured the check is skipped (backward compat).
    """
    owner = CONFIG.agent_wallet_address
    if not owner:
        return None

    from service.clients.erc8004.signing import verify_eip191

    sig = request.headers.get("X-Signature")
    ts_raw = request.headers.get("X-Timestamp")

    if not sig or not ts_raw:
        logger.warning("[AUTH] Missing X-Signature or X-Timestamp on %s request", operation)
        return JSONResponse({"error": "Missing auth headers"}, status_code=403)

    try:
        ts = int(ts_raw)
    except ValueError:
        return JSONResponse({"error": "Invalid X-Timestamp"}, status_code=403)

    import time as _time
    if abs(_time.time() - ts) > _MAX_TIMESTAMP_SKEW:
        logger.warning("[AUTH] Timestamp too old/future for %s", operation)
        return JSONResponse({"error": "Timestamp out of range"}, status_code=403)

    message = f"{operation}:{resource_id}:{ts}"
    if not verify_eip191(message, sig, owner):
        logger.warning("[AUTH] Invalid signature for %s resource=%s", operation, resource_id)
        return JSONResponse({"error": "Invalid signature"}, status_code=403)

    return None


def _check_buyer_signature(
    request: Request, operation: str, resource_id: str, claimed_address: str,
) -> JSONResponse | None:
    """Verify X-Signature / X-Timestamp headers against a buyer-supplied address.

    Sibling to `_check_agent_request_auth`, which checks against *our*
    wallet. This one checks against the address the buyer claims in the
    request body — proving they control the corresponding private key
    without requiring the seller to know buyer wallets in advance.

    Returns a JSONResponse (403) on failure, or None to allow through.
    """
    from service.clients.erc8004.signing import verify_eip191

    if not claimed_address or not claimed_address.startswith("0x") or len(claimed_address) != 42:
        return JSONResponse({"error": "Missing or malformed buyer_address"}, status_code=400)

    sig = request.headers.get("X-Signature")
    ts_raw = request.headers.get("X-Timestamp")
    if not sig or not ts_raw:
        return JSONResponse({"error": "Missing auth headers"}, status_code=403)

    try:
        ts = int(ts_raw)
    except ValueError:
        return JSONResponse({"error": "Invalid X-Timestamp"}, status_code=403)

    import time as _time
    if abs(_time.time() - ts) > _MAX_TIMESTAMP_SKEW:
        return JSONResponse({"error": "Timestamp out of range"}, status_code=403)

    message = f"{operation}:{resource_id}:{ts}"
    if not verify_eip191(message, sig, claimed_address):
        logger.warning(
            "[AUTH] Buyer signature invalid for %s resource=%s claimed=%s",
            operation, resource_id, claimed_address,
        )
        return JSONResponse({"error": "Invalid signature for claimed buyer_address"},
                            status_code=403)
    return None


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
        offer_resource = parse_resource_from_dict(normalize_token_resource(offer_data))
        demand_resource = parse_resource_from_dict(normalize_token_resource(demand_data))
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

    if is_event_queue_enabled():
        queue_event(order_create_event.model_dump(mode="json"))
        return {
            "status": "queued",
            "event_id": event_id,
            "order_request": order_create_event.model_dump(mode="json"),
        }

    final_response = await root_agent._process_event_with_pipeline(
        order_create_event, ctx=None,
    )

    outcome = root_agent._last_action_outcomes.pop(event_id, None)
    order_id = _extract_order_id(outcome)

    response_payload = {
        "status": "created" if order_id else "no_action",
        "event_id": event_id,
        "order_request": order_create_event.model_dump(mode="json"),
        "root_agent_response": final_response or "",
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

    if is_event_queue_enabled():
        queue_event(order_close_event.model_dump(mode="json"))
        return {
            "status": "queued",
            "event_id": event_id,
            "order_request": order_close_event.model_dump(mode="json"),
        }

    final_response = await root_agent._process_event_with_pipeline(
        order_close_event, ctx=None,
    )

    return {
        "status": "closed",
        "event_id": event_id,
        "order_request": order_close_event.model_dump(mode="json"),
        "root_agent_response": final_response or "",
    }

async def create_market_order_endpoint(request: Request) -> JSONResponse:
    """
    Expose an endpoint to create market orders via the root agent.
    """
    auth_error = _check_agent_request_auth(request, "create_order", CONFIG.agent_wallet_address)
    if auth_error:
        return auth_error

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
        body = await request.json()
        order_id = body.get("order_id", "")
    except Exception:
        order_id = ""
    auth_error = _check_agent_request_auth(request, "close_order", order_id)
    if auth_error:
        return auth_error

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


async def _run_refund_flow(request: Request) -> tuple[int, dict]:
    """Provider-initiated direct token-transfer refund.

    Body:
      {
        "order_id":      "<required>",
        "buyer_address": "0x...  (required; the provider explicitly names the recipient)",
        "amount":        "<optional decimal; defaults to order.demand_resource.amount * duration_hours>",
        "token":         "<optional symbol; defaults to order.demand_resource.token>"
      }

    Does NOT touch the escrow contract. This is a side-channel make-whole
    transfer out of the provider's own wallet, for cases where the deal
    cannot be settled through the normal escrow release path (provisioning
    failed, hardware went down, buyer abandoned but escrow remains, etc.).

    Returns (status_code, body_dict).
    """
    try:
        payload = await request.json()
    except Exception as exc:
        raise ValueError(f"Invalid JSON in request body: {exc}") from exc

    if not AGENT_PRIV_KEY or not AGENT_PRIV_KEY.strip():
        return 500, {"error": "AGENT_PRIV_KEY not configured on agent"}
    if not CHAIN_RPC_URL or not CHAIN_RPC_URL.strip():
        return 500, {"error": "CHAIN_RPC_URL not configured on agent"}

    order_id_peek = payload.get("order_id") if isinstance(payload, dict) else None
    order = None
    if isinstance(order_id_peek, str) and order_id_peek.strip():
        order = await root_agent._sqlite_client.load_order(order_id=order_id_peek.strip())

    def _resolve_token(ident: str) -> dict:
        try:
            meta = TOKEN_REGISTRY.require(ident)
        except Exception as exc:
            raise ValueError(f"Unknown token: {ident}") from exc
        return meta.model_dump() if hasattr(meta, "model_dump") else dict(meta)

    from market_storefront.utils.refund import derive_refund_params
    outcome = derive_refund_params(order=order, payload=payload, resolve_token=_resolve_token)
    if outcome[0] == "error":
        _, status, body = outcome
        return status, body
    params = outcome[1]

    from market_storefront.utils.token_transfer import transfer_erc20
    try:
        result = await transfer_erc20(
            private_key=AGENT_PRIV_KEY,
            rpc_url=CHAIN_RPC_URL,
            token_address=params["token_address"],
            to_address=params["buyer_address"],
            amount_raw=params["amount_raw"],
        )
    except RuntimeError as exc:
        logger.error("[REFUND] Transfer failed for order %s: %s", params["order_id"], exc)
        return 502, {"error": "Token transfer failed", "detail": str(exc)}

    updated_at = datetime.now().isoformat()
    await root_agent._sqlite_client.update_order(
        order_id=params["order_id"],
        status="refunded",
        updated_at=updated_at,
    )

    from market_storefront.utils.stage_log import stage_event
    stage_event(
        "post_settlement",
        "refund_transferred",
        order_id=params["order_id"],
        escrow_uid=params.get("escrow_uid"),
        tx_hash=result["tx_hash"],
        token_symbol=params["token_meta"].get("symbol"),
        token_address=params["token_meta"].get("contract_address"),
        to_address=result["to_address"],
        amount_raw=params["amount_raw"],
    )

    return 200, {
        "status": "refunded",
        "order_id": params["order_id"],
        "tx_hash": result["tx_hash"],
        "from_address": result["from_address"],
        "to_address": result["to_address"],
        "token": {
            "symbol": params["token_meta"].get("symbol"),
            "contract_address": params["token_meta"].get("contract_address"),
            "decimals": params["decimals"],
        },
        "amount_raw": params["amount_raw"],
        "block_number": result["block_number"],
    }


async def refund_market_order_endpoint(request: Request) -> JSONResponse:
    """Expose an endpoint for providers to refund a deal via direct token transfer."""
    try:
        body = await request.json()
        order_id = body.get("order_id", "")
    except Exception:
        order_id = ""
    auth_error = _check_agent_request_auth(request, "refund_order", order_id)
    if auth_error:
        return auth_error

    try:
        status_code, body_out = await _run_refund_flow(request)
        return JSONResponse(body_out, status_code=status_code)
    except ValueError as exc:
        logger.error(f"[REFUND] Validation error: {exc}")
        return JSONResponse(
            {"error": "Refund request invalid", "detail": str(exc)},
            status_code=400,
        )
    except Exception as exc:
        logger.error(f"[REFUND] Unexpected error: {exc}")
        return JSONResponse(
            {"error": "Failed to process refund", "detail": str(exc)},
            status_code=500,
        )


# ---------------------------------------------------------------------------
# Escrow recovery endpoints: claim / reclaim / arbitrate
# ---------------------------------------------------------------------------


def _require_alkahest_client() -> tuple[int, dict] | None:
    """Return an error tuple if the alkahest client is not configured, else None."""
    if root_agent._alkahest_client is None:
        return 500, {
            "error": "Alkahest client not configured",
            "detail": "AGENT_PRIV_KEY and CHAIN_RPC_URL must both be set",
        }
    return None


async def _run_claim_flow(request: Request) -> tuple[int, dict]:
    """Seller collects an escrow on-chain after fulfillment."""
    try:
        payload = await request.json()
    except Exception as exc:
        raise ValueError(f"Invalid JSON in request body: {exc}") from exc

    cfg_err = _require_alkahest_client()
    if cfg_err:
        return cfg_err

    order_id_peek = payload.get("order_id") if isinstance(payload, dict) else None
    order = None
    if isinstance(order_id_peek, str) and order_id_peek.strip():
        order = await root_agent._sqlite_client.load_order(order_id=order_id_peek.strip())

    from market_storefront.utils.recovery import derive_claim_params
    outcome = derive_claim_params(order=order, payload=payload)
    if outcome[0] == "error":
        _, status, body = outcome
        return status, body
    params = outcome[1]

    try:
        collect_result = await root_agent._alkahest_client.erc20.escrow.non_tierable.collect(
            params["escrow_uid"],
            params["fulfillment_uid"],
        )
    except Exception as exc:
        logger.error("[CLAIM] collect failed for order %s: %s", params["order_id"], exc)
        return 502, {
            "error": "Escrow collect failed on-chain",
            "detail": str(exc),
            "order_id": params["order_id"],
            "escrow_uid": params["escrow_uid"],
        }

    await root_agent._sqlite_client.update_order(
        order_id=params["order_id"],
        status="closed",
        updated_at=datetime.now().isoformat(),
    )
    from market_storefront.utils.stage_log import stage_event
    stage_event(
        "post_settlement",
        "escrow_claimed",
        order_id=params["order_id"],
        escrow_uid=params["escrow_uid"],
        fulfillment_uid=params["fulfillment_uid"],
        collect_result=str(collect_result),
    )

    return 200, {
        "status": "claimed",
        "order_id": params["order_id"],
        "escrow_uid": params["escrow_uid"],
        "fulfillment_uid": params["fulfillment_uid"],
        "collect_result": str(collect_result),
    }


async def claim_market_order_endpoint(request: Request) -> JSONResponse:
    """POST /orders/claim — seller-side escrow collect."""
    try:
        body = await request.json()
        order_id = body.get("order_id", "")
    except Exception:
        order_id = ""
    auth_error = _check_agent_request_auth(request, "claim_order", order_id)
    if auth_error:
        return auth_error

    try:
        status, body_out = await _run_claim_flow(request)
        return JSONResponse(body_out, status_code=status)
    except ValueError as exc:
        logger.error(f"[CLAIM] Validation error: {exc}")
        return JSONResponse(
            {"error": "Claim request invalid", "detail": str(exc)},
            status_code=400,
        )
    except Exception as exc:
        logger.error(f"[CLAIM] Unexpected error: {exc}")
        return JSONResponse(
            {"error": "Failed to process claim", "detail": str(exc)},
            status_code=500,
        )


async def _run_reclaim_flow(request: Request) -> tuple[int, dict]:
    """Buyer reclaims an expired escrow on-chain."""
    try:
        payload = await request.json()
    except Exception as exc:
        raise ValueError(f"Invalid JSON in request body: {exc}") from exc

    cfg_err = _require_alkahest_client()
    if cfg_err:
        return cfg_err

    order_id_peek = payload.get("order_id") if isinstance(payload, dict) else None
    order = None
    if isinstance(order_id_peek, str) and order_id_peek.strip():
        order = await root_agent._sqlite_client.load_order(order_id=order_id_peek.strip())

    from market_storefront.utils.recovery import derive_reclaim_params
    outcome = derive_reclaim_params(order=order, payload=payload)
    if outcome[0] == "error":
        _, status, body = outcome
        return status, body
    params = outcome[1]

    try:
        reclaim_result = await root_agent._alkahest_client.erc20.escrow.non_tierable.reclaim_expired(
            params["escrow_uid"],
        )
    except Exception as exc:
        logger.error("[RECLAIM] reclaim_expired failed for order %s: %s", params["order_id"], exc)
        # Most common cause: expiration hasn't passed yet. Surface the
        # on-chain error verbatim; the CLI displays it to the operator.
        return 502, {
            "error": "Escrow reclaim failed on-chain",
            "detail": str(exc),
            "order_id": params["order_id"],
            "escrow_uid": params["escrow_uid"],
        }

    await root_agent._sqlite_client.update_order(
        order_id=params["order_id"],
        status="reclaimed",
        updated_at=datetime.now().isoformat(),
    )
    from market_storefront.utils.stage_log import stage_event
    stage_event(
        "post_settlement",
        "escrow_reclaimed",
        order_id=params["order_id"],
        escrow_uid=params["escrow_uid"],
        reclaim_result=str(reclaim_result),
    )

    return 200, {
        "status": "reclaimed",
        "order_id": params["order_id"],
        "escrow_uid": params["escrow_uid"],
        "reclaim_result": str(reclaim_result),
    }


async def reclaim_market_order_endpoint(request: Request) -> JSONResponse:
    """POST /orders/reclaim — buyer-side reclaim of an expired escrow."""
    try:
        body = await request.json()
        order_id = body.get("order_id", "")
    except Exception:
        order_id = ""
    auth_error = _check_agent_request_auth(request, "reclaim_order", order_id)
    if auth_error:
        return auth_error

    try:
        status, body_out = await _run_reclaim_flow(request)
        return JSONResponse(body_out, status_code=status)
    except ValueError as exc:
        logger.error(f"[RECLAIM] Validation error: {exc}")
        return JSONResponse(
            {"error": "Reclaim request invalid", "detail": str(exc)},
            status_code=400,
        )
    except Exception as exc:
        logger.error(f"[RECLAIM] Unexpected error: {exc}")
        return JSONResponse(
            {"error": "Failed to process reclaim", "detail": str(exc)},
            status_code=500,
        )


async def _run_arbitrate_flow(request: Request) -> tuple[int, dict]:
    """Buyer-as-oracle records an arbitration decision for a fulfillment.

    Under the current RecipientArbiter-based escrow this has NO effect on
    collection — escrow release is gated purely on the fulfillment
    attestation's recipient matching the demanded seller address. Kept
    for debugging and for the day we reintroduce oracle-gated arbiters.
    """
    try:
        payload = await request.json()
    except Exception as exc:
        raise ValueError(f"Invalid JSON in request body: {exc}") from exc

    cfg_err = _require_alkahest_client()
    if cfg_err:
        return cfg_err

    order_id_peek = payload.get("order_id") if isinstance(payload, dict) else None
    order = None
    if isinstance(order_id_peek, str) and order_id_peek.strip():
        order = await root_agent._sqlite_client.load_order(order_id=order_id_peek.strip())

    from market_storefront.utils.recovery import derive_arbitrate_params
    outcome = derive_arbitrate_params(order=order, payload=payload)
    if outcome[0] == "error":
        _, status, body = outcome
        return status, body
    params = outcome[1]

    # Drive one arbitration pass using a fixed decision. This matches the
    # simulation mode in `arbitrate_compute_fulfillment`: approve=True.
    try:
        from alkahest_py import ArbitrationMode
        decision_value = bool(params["decision"])

        async def decision_function(_attestation, _demand):
            return decision_value

        def callback(_decision):
            pass

        decisions = await root_agent._alkahest_client.oracle.arbitrate_many(
            decision_function,
            callback,
            ArbitrationMode.PastUnarbitrated,
            timeout_seconds=5.0,
        )
    except Exception as exc:
        logger.error(
            "[ARBITRATE] arbitrate_many failed for order %s: %s",
            params["order_id"], exc,
        )
        return 502, {
            "error": "Oracle arbitration failed on-chain",
            "detail": str(exc),
            "order_id": params["order_id"],
        }

    from market_storefront.utils.stage_log import stage_event
    stage_event(
        "post_settlement",
        "oracle_arbitrated",
        order_id=params["order_id"],
        fulfillment_uid=params["fulfillment_uid"],
        escrow_uid=params["escrow_uid"],
        decision=params["decision"],
        decisions_count=len(decisions or []) if decisions is not None else 0,
    )

    return 200, {
        "status": "arbitrated",
        "order_id": params["order_id"],
        "fulfillment_uid": params["fulfillment_uid"],
        "decision": params["decision"],
        "decisions_count": len(decisions or []) if decisions is not None else 0,
        "note": (
            "Under RecipientArbiter this decision does not gate escrow collection; "
            "use /orders/claim to release funds."
        ),
    }


async def arbitrate_market_order_endpoint(request: Request) -> JSONResponse:
    """POST /orders/arbitrate — buyer-as-oracle records a decision (no-op under RecipientArbiter)."""
    try:
        body = await request.json()
        order_id = body.get("order_id", "")
    except Exception:
        order_id = ""
    auth_error = _check_agent_request_auth(request, "arbitrate_order", order_id)
    if auth_error:
        return auth_error

    try:
        status, body_out = await _run_arbitrate_flow(request)
        return JSONResponse(body_out, status_code=status)
    except ValueError as exc:
        logger.error(f"[ARBITRATE] Validation error: {exc}")
        return JSONResponse(
            {"error": "Arbitrate request invalid", "detail": str(exc)},
            status_code=400,
        )
    except Exception as exc:
        logger.error(f"[ARBITRATE] Unexpected error: {exc}")
        return JSONResponse(
            {"error": "Failed to process arbitration", "detail": str(exc)},
            status_code=500,
        )


async def _run_discover_flow(request: Request) -> tuple[int, dict]:
    """List registry orders that match a given local order.

    Body: {"order_id": "...", "include_active": bool?}

    Pure query: no thread writes, no outbound sends. The orchestrator
    uses this as the first step of a sequential buy/sell flow, then
    decides which matches to start negotiations with.
    """
    try:
        payload = await request.json()
    except Exception as exc:
        raise ValueError(f"Invalid JSON in request body: {exc}") from exc

    order_id = payload.get("order_id")
    if not isinstance(order_id, str) or not order_id.strip():
        raise ValueError("Request must include non-empty 'order_id'")
    order_id = order_id.strip()

    include_active = bool(payload.get("include_active", False))

    from market_storefront.utils.action_executor import discover
    try:
        matches = await discover(
            order_id=order_id,
            include_active_negotiations=include_active,
        )
    except ValueError as exc:
        return 400, {"error": "Discover request invalid",
                     "detail": str(exc),
                     "order_id": order_id}
    except RuntimeError as exc:
        return 500, {"error": "Discovery unavailable",
                     "detail": str(exc),
                     "order_id": order_id}

    return 200, {
        "order_id": order_id,
        "match_count": len(matches),
        "matches": matches,
    }


async def discover_market_orders_endpoint(request: Request) -> JSONResponse:
    """POST /orders/discover — pure registry-query step."""
    try:
        body = await request.json()
        order_id = body.get("order_id", "")
    except Exception:
        order_id = ""
    auth_error = _check_agent_request_auth(request, "discover_orders", order_id)
    if auth_error:
        return auth_error

    try:
        status, body_out = await _run_discover_flow(request)
        return JSONResponse(body_out, status_code=status)
    except ValueError as exc:
        logger.error(f"[DISCOVER] Validation error: {exc}")
        return JSONResponse(
            {"error": "Discover request invalid", "detail": str(exc)},
            status_code=400,
        )
    except Exception as exc:
        logger.error(f"[DISCOVER] Unexpected error: {exc}")
        return JSONResponse(
            {"error": "Failed to process discover", "detail": str(exc)},
            status_code=500,
        )


agent_order_creation_route = Route("/orders/create", create_market_order_endpoint, methods=["POST"])
agent_order_close_route = Route("/orders/close", close_market_order_endpoint, methods=["POST"])
agent_order_refund_route = Route("/orders/refund", refund_market_order_endpoint, methods=["POST"])
agent_order_claim_route = Route("/orders/claim", claim_market_order_endpoint, methods=["POST"])
agent_order_reclaim_route = Route("/orders/reclaim", reclaim_market_order_endpoint, methods=["POST"])
agent_order_arbitrate_route = Route("/orders/arbitrate", arbitrate_market_order_endpoint, methods=["POST"])
agent_order_discover_route = Route("/orders/discover", discover_market_orders_endpoint, methods=["POST"])


# ---------------------------------------------------------------------------
# Synchronous negotiation endpoints (buyer drives, seller responds in-line)
# ---------------------------------------------------------------------------


async def negotiate_new_endpoint(request: Request) -> JSONResponse:
    """POST /negotiate/new — start a new negotiation, return first seller decision.

    Body:
      {
        "seller_order_id": "...",
        "buyer_address":   "0x...",
        "initial_price":   <int, raw token units>
      }

    Signed by buyer_address via X-Signature over
    "negotiate_new:{seller_order_id}:{timestamp}".

    Returns:
      {"negotiation_id": "...",       # server-assigned, used in subsequent /negotiate/{id} calls
       "action": "counter"|"accept"|"exit"|"reject",
       "price"?: int,
       "reason"?: str}
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    seller_order_id = body.get("seller_order_id")
    buyer_address = body.get("buyer_address")
    initial_price_raw = body.get("initial_price")

    for name, val in (("seller_order_id", seller_order_id),
                      ("buyer_address", buyer_address)):
        if not isinstance(val, str) or not val.strip():
            return JSONResponse({"error": f"Missing or empty '{name}'"}, status_code=400)
    try:
        initial_price = int(initial_price_raw)
    except (TypeError, ValueError):
        return JSONResponse({"error": "initial_price must be an integer"}, status_code=400)

    auth_error = _check_buyer_signature(
        request, operation="negotiate_new",
        resource_id=seller_order_id, claimed_address=buyer_address,
    )
    if auth_error:
        return auth_error

    buyer_agent_url = body.get("buyer_agent_url", "")  # informational

    from market_storefront.utils.sync_negotiation import start_sync_negotiation
    try:
        result = await start_sync_negotiation(
            sqlite_client=root_agent._sqlite_client,
            our_order_id=seller_order_id,
            buyer_address=buyer_address,
            their_proposed_price=initial_price,
            our_base_url=BASE_URL_OVERRIDE or "",
            their_agent_url=buyer_agent_url or buyer_address,
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except Exception as exc:
        logger.error("[NEGOTIATE/new] Unexpected error: %s", exc, exc_info=True)
        return JSONResponse({"error": "Negotiation start failed", "detail": str(exc)},
                            status_code=500)
    return JSONResponse(result)


async def negotiate_continue_endpoint(request: Request) -> JSONResponse:
    """POST /negotiate/{neg_id} — one further round against an existing thread.

    Body:
      {
        "action":        "counter"|"accept"|"exit",
        "price"?:        <int for counter/accept>,
        "reason"?:       <str for exit>,
        "buyer_address": "0x..."
      }

    Signed by buyer_address via X-Signature over
    "negotiate_continue:{neg_id}:{timestamp}".

    Returns the seller's decision for this round:
      {"action": "counter"|"accept"|"exit"|"reject",
       "price"?: int, "reason"?: str}
    """
    neg_id = request.path_params.get("neg_id", "")
    if not neg_id:
        return JSONResponse({"error": "Missing negotiation id in path"}, status_code=400)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    buyer_action = body.get("action")
    if buyer_action not in ("counter", "accept", "exit"):
        return JSONResponse({"error": "action must be 'counter'|'accept'|'exit'"},
                            status_code=400)

    buyer_address = body.get("buyer_address")
    if not isinstance(buyer_address, str) or not buyer_address.strip():
        return JSONResponse({"error": "Missing or empty 'buyer_address'"}, status_code=400)

    buyer_price_raw = body.get("price")
    buyer_price: int | None = None
    if buyer_action == "counter":
        try:
            buyer_price = int(buyer_price_raw)
        except (TypeError, ValueError):
            return JSONResponse({"error": "'price' required as int for counter"},
                                status_code=400)

    auth_error = _check_buyer_signature(
        request, operation="negotiate_continue",
        resource_id=neg_id, claimed_address=buyer_address,
    )
    if auth_error:
        return auth_error

    from market_storefront.utils.sync_negotiation import continue_sync_negotiation
    try:
        result = await continue_sync_negotiation(
            sqlite_client=root_agent._sqlite_client,
            neg_id=neg_id,
            buyer_action=buyer_action,
            buyer_price=buyer_price,
            buyer_reason=body.get("reason"),
            buyer_address=buyer_address,
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except Exception as exc:
        logger.error("[NEGOTIATE/{id}] Unexpected error: %s", exc, exc_info=True)
        return JSONResponse({"error": "Negotiation continue failed", "detail": str(exc)},
                            status_code=500)
    return JSONResponse(result)


agent_negotiate_new_route = Route("/negotiate/new", negotiate_new_endpoint, methods=["POST"])
agent_negotiate_continue_route = Route(
    "/negotiate/{neg_id}", negotiate_continue_endpoint, methods=["POST"],
)


# ---------------------------------------------------------------------------
# Seller-side polling settle: POST to kick off, GET to poll status
# ---------------------------------------------------------------------------


async def settle_escrow_endpoint(request: Request) -> JSONResponse:
    """POST /settle/{escrow_uid} — kick off provisioning for this escrow.

    Body:
      {"negotiation_id": "...", "ssh_public_key": "...",
       "buyer_address": "0x..."}

    Signed by buyer_address via X-Signature over
    "settle_escrow:{escrow_uid}:{timestamp}". The seller verifies the
    signature matches the claimed address; on-chain escrow validation
    is the alkahest client's job during fulfillment.

    Returns the current job state. 202 on first kick-off; 200 if a job
    already exists for this escrow (idempotent).
    """
    escrow_uid = request.path_params.get("escrow_uid", "")
    if not escrow_uid:
        return JSONResponse({"error": "Missing escrow_uid in path"}, status_code=400)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    negotiation_id = body.get("negotiation_id")
    ssh_public_key = body.get("ssh_public_key")
    buyer_address = body.get("buyer_address")

    for name, val in (("negotiation_id", negotiation_id),
                      ("ssh_public_key", ssh_public_key),
                      ("buyer_address", buyer_address)):
        if not isinstance(val, str) or not val.strip():
            return JSONResponse({"error": f"Missing or empty '{name}'"}, status_code=400)

    auth_error = _check_buyer_signature(
        request, operation="settle_escrow",
        resource_id=escrow_uid, claimed_address=buyer_address,
    )
    if auth_error:
        return auth_error

    if root_agent._alkahest_client is None:
        return JSONResponse(
            {"error": "Alkahest client not configured",
             "detail": "AGENT_PRIV_KEY and CHAIN_RPC_URL must be set"},
            status_code=500,
        )

    from market_storefront.utils.settlement_jobs import start_settlement_job, serialize_settlement_job
    try:
        result = await start_settlement_job(
            escrow_uid=escrow_uid,
            negotiation_id=negotiation_id,
            ssh_public_key=ssh_public_key,
            sqlite_client=root_agent._sqlite_client,
            alkahest_client=root_agent._alkahest_client,
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except Exception as exc:
        logger.error("[SETTLE] start_settlement_job failed: %s", exc, exc_info=True)
        return JSONResponse(
            {"error": "Settlement start failed", "detail": str(exc)},
            status_code=500,
        )

    # If this was the first call, the row has no extra fields yet — 202.
    # If idempotent (row already existed), return 200 with the current state.
    status_code = 200 if result.get("status") in ("ready", "failed") else 202
    return JSONResponse(
        serialize_settlement_job(result) if "created_at" in result else result,
        status_code=status_code,
    )


async def settle_status_endpoint(request: Request) -> JSONResponse:
    """GET /settle/{escrow_uid}/status — poll provisioning status.

    Query params: none. Requires X-Signature/X-Timestamp headers from
    buyer_address (passed as `buyer_address` query param, since GET has
    no body). Prevents random third parties from reading provisioning
    details (connection_details, tenant_credentials).

    Returns the serialized settlement_jobs row. 404 if no job for this
    escrow_uid.
    """
    escrow_uid = request.path_params.get("escrow_uid", "")
    if not escrow_uid:
        return JSONResponse({"error": "Missing escrow_uid in path"}, status_code=400)

    buyer_address = request.query_params.get("buyer_address", "")
    if not buyer_address:
        return JSONResponse(
            {"error": "Missing 'buyer_address' query param for signed poll"},
            status_code=400,
        )

    auth_error = _check_buyer_signature(
        request, operation="settle_status",
        resource_id=escrow_uid, claimed_address=buyer_address,
    )
    if auth_error:
        return auth_error

    from market_storefront.utils.settlement_jobs import serialize_settlement_job
    job = await root_agent._sqlite_client.load_settlement_job(escrow_uid=escrow_uid)
    if not job:
        return JSONResponse(
            {"error": f"No settlement job for escrow {escrow_uid}",
             "escrow_uid": escrow_uid},
            status_code=404,
        )
    return JSONResponse(serialize_settlement_job(job))


agent_settle_escrow_route = Route(
    "/settle/{escrow_uid}", settle_escrow_endpoint, methods=["POST"],
)
agent_settle_status_route = Route(
    "/settle/{escrow_uid}/status", settle_status_endpoint, methods=["GET"],
)

# Plain Starlette ASGI app. Named `a2a_app` historically — kept for
# import compatibility with server.py. There is no A2A protocol running
# underneath anymore; every endpoint is a regular HTTP handler.
from starlette.applications import Starlette

a2a_app = Starlette(routes=[
    alert_route,
    agent_order_creation_route,
    agent_order_close_route,
    agent_order_refund_route,
    agent_order_claim_route,
    agent_order_reclaim_route,
    agent_order_arbitrate_route,
    agent_order_discover_route,
    agent_negotiate_new_route,
    agent_negotiate_continue_route,
    agent_settle_escrow_route,
    agent_settle_status_route,
])

# Add ERC-8004 registration file endpoint
# Per ERC-8004 spec: tokenURI MUST resolve to the agent registration file
from market_storefront.utils.agent_card import build_erc8004_registration_file
from service.clients.erc8004.blockchain import (
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


async def serve_agent_wallet(request: Request) -> JSONResponse:
    """Serve the agent's on-chain wallet address.

    Published so counterparties can resolve this agent's wallet without a
    full ERC-8004 identity-registry lookup. The buyer reads this before
    creating an escrow so it can demand `RecipientArbiter(recipient=seller_wallet)`.
    Empty `agent_wallet_address` indicates this agent is not configured
    for on-chain action — callers should refuse the deal.
    """
    return JSONResponse({"agent_wallet_address": CONFIG.agent_wallet_address or ""})


agent_wallet_route = Route("/.well-known/agent-wallet.json", serve_agent_wallet, methods=["GET"])
a2a_app.routes.append(agent_wallet_route)


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
    from market_storefront.utils.config import CONFIG
    from service.clients.erc8004.heartbeat import start_agent_heartbeat
    await start_agent_heartbeat({
        "indexer_url": CONFIG.indexer_url,
        "identity_registry_address": CONFIG.identity_registry_address,
        "agent_wallet_address": CONFIG.agent_wallet_address,
        "onchain_agent_id": CONFIG.onchain_agent_id,
        "chain_rpc_url": CONFIG.chain_rpc_url,
        "agent_priv_key": CONFIG.agent_priv_key,
    })


async def _preflight_provisioning() -> None:
    """Ping the provisioning service and log a loud warning if it's down.

    Runs once, ~10s after startup (to let compose dependencies settle).
    Does not hard-fail — provisioning may come up later, and we want the
    agent to keep serving unrelated endpoints.
    """
    import httpx
    from market_storefront.utils.config import CONFIG

    await asyncio.sleep(10)
    url = CONFIG.provisioning_service_url.rstrip("/") + "/health"
    try:
        async with httpx.AsyncClient(timeout=5) as http:
            resp = await http.get(url)
            if resp.status_code == 200:
                logger.info("[STARTUP] Provisioning service reachable at %s",
                            CONFIG.provisioning_service_url)
                return
            logger.warning(
                "[STARTUP] Provisioning service at %s returned HTTP %d — "
                "fulfillment will fail until this is resolved",
                CONFIG.provisioning_service_url, resp.status_code,
            )
    except Exception as exc:
        logger.warning(
            "A working PROVISIONING_SERVICE_URL is required; "
            "fulfillment will fail until this is resolved. "
            "For e2e tests without hardware, set ACTIVE_PROFILES=mock on the "
            "provisioning-service container.",
            CONFIG.provisioning_service_url, type(exc).__name__, exc,
        )


# Initialize startup tasks
async def _startup_tasks():
    """Initialize background tasks."""
    from market_storefront.utils.config import CONFIG
    from market_storefront.resource_poller import resource_poller_loop

    # Start heartbeat after server is ready
    asyncio.create_task(_start_heartbeat())

    # Start resource availability poller
    asyncio.create_task(resource_poller_loop())
    logger.info("[STARTUP] Resource poller started (interval=%ds)",
            CONFIG.resource_check_interval)

    # Start negotiation watchdog (marks stale threads as abandoned)
    from market_storefront.negotiation_watchdog import watchdog_loop as _neg_watchdog_loop
    asyncio.create_task(_neg_watchdog_loop())
    logger.info(
        "[STARTUP] Negotiation watchdog started (interval=%ds, timeout=%ds)",
        CONFIG.negotiation_watchdog_interval,
        CONFIG.negotiation_timeout_seconds,
    )

    # Preflight: warn loudly if the provisioning service is unreachable.
    asyncio.create_task(_preflight_provisioning())

    if CONFIG.enable_redis_ingest:
        await start_redis_subscriber()
        logger.info("[STARTUP] Redis subscriber started")

    if is_event_queue_enabled():
        # Start queue processor in background
        task = asyncio.create_task(process_queued_events())
        logger.info("[STARTUP] Event queue processor started")
        return task

    return None


# Background tasks are now started via FastAPI startup event in server.py
# This ensures the event loop is running when tasks are created
