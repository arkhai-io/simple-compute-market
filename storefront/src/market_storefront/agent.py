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

from market_storefront.models.domain_models import (
    ActionType,
    EventType,
    DomainEvent,
    Listing,
    ReceiveComputeObligationFulfillmentEvent,
    FulfillmentFailedEvent,
    ArbitrationCompleteEvent,
    ResourceImbalanceEvent,
    ResourceAlertRequest,
    ComputeResource,
    TokenResource,
    ListingCreatedEvent,
    ListingClosedEvent,
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
from market_storefront.models.domain_models import DecisionContext, Action, Decision
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


# Limits to keep stored JSON blobs from exploding the SQLite size
MAX_CONTEXT_JSON_CHARS = 100_000
MAX_OUTCOME_JSON_CHARS = 100_000
MAX_PAST_EXPERIENCES = 5


def _extract_listing_id(outcome: dict | None) -> str | None:
    if not isinstance(outcome, dict):
        return None
    if outcome.get("listing_id"):
        return outcome["listing_id"]
    result = outcome.get("result")
    if isinstance(result, dict):
        return result.get("listing_id") or (result.get("listing") or {}).get("listing_id")
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
                raise ValueError("ListingCreatedEvent requires 'offer' and 'demand' dictionaries")

            max_duration_seconds = data.get(
                "max_duration_seconds",
                payload.get("max_duration_seconds"),
            )
            order_create_payload = {
                "event_id": payload.get("event_id") or f"order_create_{uuid.uuid4()}",
                "event_type": EventType.ORDER_CREATE.value,
                "source": payload.get("source") or BASE_URL_OVERRIDE,
                "offer": offer_data,
                "demand": demand_data,
                "max_duration_seconds": max_duration_seconds,
                "data": data,
            }
            return ListingCreatedEvent.model_validate(order_create_payload)

        elif event_type == EventType.ORDER_CLOSE:
            listing_id = data.get("listing_id", payload.get("listing_id"))
            if not isinstance(listing_id, str) or not listing_id.strip():
                raise ValueError("ListingClosedEvent requires 'listing_id'")
            order_close_payload = {
                "event_id": payload.get("event_id") or f"order_close_{uuid.uuid4()}",
                "event_type": EventType.ORDER_CLOSE.value,
                "source": payload.get("source") or BASE_URL_OVERRIDE,
                "listing_id": listing_id,
                "data": data,
            }
            return ListingClosedEvent.model_validate(order_close_payload)

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
                listing_id=data.get("listing_id"),
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


# ---------------------------------------------------------------------------
# Agent card metadata — built once at import time; accessed by identity_controller.
# TraderAgent is no longer instantiated at module level; StorefrontService
# owns that lifecycle, initialized during server.py lifespan startup.
# ---------------------------------------------------------------------------
from market_storefront.utils.agent_card import build_agent_card_data
agent_card_data = build_agent_card_data(
    agent_name=CONFIG.agent_name,
    base_url=BASE_URL_OVERRIDE,
    agent_wallet_address=CONFIG.agent_wallet_address,
)

ALERTS_USER_ID = "resource-monitor"

# ---------------------------------------------------------------------------
# root_agent shim — lazy accessor for the StorefrontService singleton.
#
# Legacy handler functions (_run_refund_flow, _run_claim_flow, etc.) still
# reference root_agent._sqlite_client and root_agent._alkahest_client.
# Rather than rewriting all those bodies now, we provide a thin shim that
# delegates attribute access to the resolved StorefrontService.
# This is removed once the legacy handlers are fully migrated to controllers.
# ---------------------------------------------------------------------------

class _RootAgentShim:
    """Forwards attribute access to the resolved StorefrontService singleton."""

    @property
    def _sqlite_client(self):
        import market_storefront.container as _c
        if _c.resolved_storefront_service is None:
            raise RuntimeError("StorefrontService not yet initialized (server not started?)")
        return _c.resolved_storefront_service._sqlite_client

    @property
    def _alkahest_client(self):
        import market_storefront.container as _c
        if _c.resolved_storefront_service is None:
            raise RuntimeError("StorefrontService not yet initialized (server not started?)")
        return _c.resolved_storefront_service._alkahest_client

    @property
    def _last_action_outcomes(self):
        import market_storefront.container as _c
        if _c.resolved_storefront_service is None:
            raise RuntimeError("StorefrontService not yet initialized")
        return _c.resolved_storefront_service._last_action_outcomes

    async def _process_event_with_pipeline(self, event, *, ctx=None):
        import market_storefront.container as _c
        if _c.resolved_storefront_service is None:
            raise RuntimeError("StorefrontService not yet initialized")
        return await _c.resolved_storefront_service.process_event_with_pipeline(event, ctx=ctx)


root_agent = _RootAgentShim()



# Runtime agent identity — set once by _ensure_agent_identity() during startup.
_AGENT_ID: int | None = None

async def _ensure_agent_identity() -> int:
    """Resolve the numeric on-chain agent ID, registering if necessary.

    Resolution order:
      1. CONFIG.onchain_agent_id (pinned in TOML / helm values) — fast path,
         no chain interaction.
      2. auto_register=True → call perform_registration() and hold the result
         in memory for this process lifetime.
      3. auto_register=False and no ID pinned → crash with a clear message.
         This protects operators who have already registered an agent and
         don't want a misconfigured deploy to silently mint a new one.

    Sets the module-level _AGENT_ID and returns it.
    """
    global _AGENT_ID

    if CONFIG.onchain_agent_id:
        try:
            _AGENT_ID = int(CONFIG.onchain_agent_id)
            logger.info(
                "[IDENTITY] Using pinned agent ID %d from config", _AGENT_ID
            )
        except ValueError:
            raise RuntimeError(
                f"[IDENTITY] seller.onchain_agent_id '{CONFIG.onchain_agent_id}' "
                "is not a valid integer."
            )

        # Validate that this wallet actually owns the pinned ID on-chain.
        # Skipped when chain config is absent (local dev without a node).
        if CONFIG.chain_rpc_url and CONFIG.identity_registry_address and CONFIG.agent_wallet_address:
            try:
                from service.clients.erc8004.blockchain import (
                    build_erc8004_canonical_id,
                    get_identity_registry_contract,
                )
                from web3 import Web3
                from web3.providers import WebsocketProviderV2, HTTPProvider

                rpc = CONFIG.chain_rpc_url
                if rpc.startswith("ws"):
                    # Use HTTP fallback for the ownership check — websocket is
                    # only needed for event subscriptions, not one-shot calls.
                    rpc_http = rpc.replace("ws://", "http://").replace("wss://", "https://")
                    w3 = Web3(HTTPProvider(rpc_http, request_kwargs={"timeout": 5}))
                else:
                    w3 = Web3(HTTPProvider(rpc, request_kwargs={"timeout": 5}))

                contract = get_identity_registry_contract(w3, CONFIG.identity_registry_address)
                owner = contract.functions.ownerOf(_AGENT_ID).call()
                expected = CONFIG.agent_wallet_address

                if owner.lower() != expected.lower():
                    raise RuntimeError(
                        f"[IDENTITY] Pinned onchain_agent_id={_AGENT_ID} is owned by "
                        f"{owner} on-chain, but [seller].wallet_address in config is "
                        f"{expected}. These must match.\n"
                        "Fix: either update [seller].onchain_agent_id to the correct "
                        "agent ID for this wallet, or correct [seller].wallet_address."
                    )
                logger.info(
                    "[IDENTITY] Ownership confirmed: agent %d owned by %s",
                    _AGENT_ID, owner,
                )
            except RuntimeError:
                raise
            except Exception as exc:
                # Chain unreachable / contract not deployed — log but don't block
                # startup.  This matches the existing behaviour for ZeroTier
                # environments where the chain may not be reachable until the
                # ZeroTier IP is assigned.
                logger.warning(
                    "[IDENTITY] Could not verify ownership of agent %d on-chain: %s. "
                    "Proceeding with pinned ID.",
                    _AGENT_ID, exc,
                )

        return _AGENT_ID

    if not CONFIG.auto_register:
        raise RuntimeError(
            "[IDENTITY] seller.onchain_agent_id is not set and "
            "seller.auto_register is false. "
            "Either pin [seller].onchain_agent_id in config.toml / helm values, "
            "or set seller.auto_register = true to allow automatic registration."
        )

    logger.info("[IDENTITY] No agent ID pinned — performing on-chain registration.")
    from market_storefront.commands.register import perform_registration
    _AGENT_ID = await perform_registration(chain_id=CONFIG.chain_id)
    logger.info("[IDENTITY] Registered with agent ID %d", _AGENT_ID)
    return _AGENT_ID


# Add ERC-8004 registration file endpoint
# Per ERC-8004 spec: tokenURI MUST resolve to the agent registration file
from market_storefront.utils.agent_card import build_erc8004_registration_file
from service.clients.erc8004.blockchain import (
    build_erc8004_canonical_id,
)

# Add registration file route


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
        "onchain_agent_id": str(_AGENT_ID) if _AGENT_ID is not None else None,
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


def _maybe_join_zerotier_network() -> None:
    """If a ZeroTier network is configured, ask the local zerotier-one
    daemon to join it. The daemon itself is brought up by the deploy
    layer (compose entrypoint, helm initContainer, or systemd unit) —
    we don't manage its lifecycle here, just talk to its CLI socket.

    Errors are logged and swallowed: a misconfigured ZeroTier setup
    should not block the agent from serving on its host network.
    """
    network = CONFIG.zerotier_network
    if not network:
        return
    import subprocess
    try:
        subprocess.run(
            ["sudo", "zerotier-cli", "join", network],
            check=True, capture_output=True, text=True, timeout=10,
        )
        logger.info("[STARTUP] Joined ZeroTier network %s", network)
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.warning(
            "[STARTUP] ZeroTier join failed for network=%s: %s. "
            "The agent will continue serving on its host network.",
            network, exc,
        )


# Initialize startup tasks
async def _startup_tasks():
    """Initialize background tasks."""
    from market_storefront.utils.config import CONFIG
    from market_storefront.resource_poller import resource_poller_loop

    _maybe_join_zerotier_network()

    # Resolve agent identity first — everything else (heartbeat, registration
    # file endpoint) depends on having a valid numeric agent ID.
    # Raises RuntimeError on hard failure (missing config + auto_register=False),
    # which crashes the startup and surfaces as a clear pod CrashLoopBackOff.
    await _ensure_agent_identity()

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