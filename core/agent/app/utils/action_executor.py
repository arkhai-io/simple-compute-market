"""Action execution.

TODO(refactor): This module still contains compute-domain action logic.
Move domain-specific execution into the domain package as refactor continues.
"""

from __future__ import annotations

import asyncio
import traceback
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import logging
from typing import Any
from urllib.parse import urlparse

from google.adk.agents import InvocationContext
from google.adk.events import Event
from google.adk.agents.remote_a2a_agent import (
    AGENT_CARD_WELL_KNOWN_PATH,
    RemoteA2aAgent,
)

from alkahest_py import (
    AlkahestClient,
    ArbitrationMode,
    TrustedOracleArbiterDemandData,
)
import json

from google.genai import types as genai_types

from core.agent.app.schema.pydantic_models import (
    Action,
    ActionType,
    ComputeResource,
    EventType,
    GPUModel,
    MarketOrder,
    Region,
    TokenResource,
)
from core.agent.app.resources import parse_resource_from_dict

from core.agent.app.utils.config import CONFIG
from service.clients.alkahest import get_trusted_oracle_arbiter
from service.clients.token import TOKEN_REGISTRY
from service.clients.indexer import get_registry_client
from core.agent.app.utils.sqlite_client import get_sqlite_client
from .provisioning import run_vm_provisioning_playbook, schedule_vm_shutdown
from core.agent.app.policy.negotiation_thread import (
    get_thread_store,
    NegotiationThreadTransaction,
)
from core.agent.app.policy.action_builders import CounterOfferParams
from .validation import determine_strategy_from_order

BASE_URL_OVERRIDE = CONFIG.base_url_override
PORT = CONFIG.port
AGENT_ID = CONFIG.agent_id
SSH_PUBLIC_KEY = CONFIG.ssh_public_key

logger = logging.getLogger(__name__)


def _serialize_decision(decision: Any) -> Any:
    """Return a minimal JSON-safe dict with decision and tx_hash."""
    if isinstance(decision, dict):
        return {
            "decision": decision.get("decision"),
            "tx_hash": decision.get("tx_hash") or decision.get("transaction_hash"),
        }

    decision_bool = getattr(decision, "decision", None)
    tx_hash = getattr(decision, "transaction_hash", None) or getattr(decision, "tx_hash", None)

    if decision_bool is None and isinstance(decision, bool):
        decision_bool = decision

    return {
        "decision": decision_bool,
        "tx_hash": tx_hash,
    }


def _serialize_decisions(decisions: Any) -> list[Any]:
    if decisions is None:
        return []
    if isinstance(decisions, list):
        return [_serialize_decision(d) for d in decisions]
    return [_serialize_decision(decisions)]



def _is_http_url(value: str | None) -> bool:
    """Return True if value is a valid http(s) URL with hostname."""
    if not value or not isinstance(value, str):
        return False
    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _normalize_agent_url(url: str | None) -> str:
    if not url:
        return ""
    return url.strip().rstrip("/").lower()


def _agent_urls_match(a: str | None, b: str | None) -> bool:
    na, nb = _normalize_agent_url(a), _normalize_agent_url(b)
    return bool(na and na == nb)


def _resource_is_compute(resource: Any) -> bool:
    """True when the resource represents compute (has gpu_model), not tokens.

    Works with both Pydantic model instances and serialized dicts. ComputeResource
    serializes with a 'gpu_model' key; TokenResource serializes with 'token'/'amount'.
    """
    if isinstance(resource, str):
        try:
            resource = json.loads(resource)
        except Exception:
            return False
    if isinstance(resource, dict):
        return "gpu_model" in resource
    return hasattr(resource, "gpu_model")


def _we_are_compute_buyer(order_dict: dict[str, Any]) -> bool:
    """True when we are the compute-buying (token-paying) side of this order.

    Two cases:
    - Seller-as-maker: maker offers compute, we are the taker → we buy compute.
    - Buyer-as-maker: maker offers tokens (us), we are the maker → we buy compute.
    """
    maker_offers_compute = _resource_is_compute(order_dict.get("offer_resource"))
    we_are_maker = _agent_urls_match(order_dict.get("order_maker"), BASE_URL_OVERRIDE)
    return (maker_offers_compute and not we_are_maker) or (not maker_offers_compute and we_are_maker)


def _resolve_counterparty_url_from_order(order_dict: dict[str, Any]) -> str | None:
    """Return the URL of the other party in the order (the one that is not us)."""
    maker = order_dict.get("order_maker")
    taker = order_dict.get("order_taker")
    if _agent_urls_match(maker, BASE_URL_OVERRIDE):
        return taker
    return maker


def _coerce_agent_reference_to_url(agent_ref: str | None) -> str | None:
    """Best-effort conversion from agent ref/alias to resolvable URL."""
    if not isinstance(agent_ref, str):
        return None
    ref = agent_ref.strip()
    if not ref:
        return None

    if _is_http_url(ref):
        return ref

    # Handle host[:port] strings without scheme.
    if "://" not in ref and (":" in ref or "." in ref):
        candidate = f"http://{ref}"
        if _is_http_url(candidate):
            return candidate
    return None


async def execute_action(
    action: Action,
    alkahest_client: Any,
    ctx: InvocationContext | None = None,
) -> dict[str, Any]:
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
            result = await accept_offer(
                alkahest_client=alkahest_client,
                ctx=ctx,
                parameters=parameters,
            )
            outcome["result"] = result
            outcome["message"] = result.get("message", "Offer accepted")
            
        case ActionType.REJECT_OFFER.value:
            result = reject_offer()
            logger.info(f"[ACTION] [SIMULATED] Rejecting offer with params: {parameters}")
            outcome["result"] = result
            outcome["message"] = "Offer rejected (simulated)"

        case ActionType.CLOSE_ORDER.value:
            logger.info(f"[ACTION] Closing order with params: {parameters}")
            result = await close_order(parameters)
            outcome["result"] = result
            outcome["message"] = result.get("message", "Order closed")

        case ActionType.MAKE_OFFER.value:
            offer_param = parameters.get("offer")
            demand_param = parameters.get("demand")
            created_order_id: str | None = None
            if offer_param is not None and demand_param is not None:
                try:
                    offer_resource = parse_resource_from_dict(offer_param)
                    demand_resource = parse_resource_from_dict(demand_param)
                except Exception as exc:
                    raise ValueError(f"Invalid offer/demand resource: {exc}") from exc

                offer_is_compute = isinstance(offer_resource, ComputeResource)
                offer_is_token = isinstance(offer_resource, TokenResource)
                demand_is_compute = isinstance(demand_resource, ComputeResource)
                demand_is_token = isinstance(demand_resource, TokenResource)

                if not ((offer_is_compute and demand_is_token) or (offer_is_token and demand_is_compute)):
                    raise ValueError("Offer and demand must be one compute and one token resource")

                logger.info("[ACTION] Creating order from explicit offer/demand payload")
                order = create_order(
                    offer_resource=offer_resource,
                    demand_resource=demand_resource,
                    duration_hours=parameters.get("duration_hours", 1),
                )
                if isinstance(order, dict):
                    created_order_id = order.get("order_id")
                gpu_model = getattr(offer_resource, "gpu_model", None) or getattr(demand_resource, "gpu_model", "unknown")
            else:
                gpu_model = parameters.get("gpu_model", "unknown")
                imbalance_type = parameters.get("imbalance_type", "surplus")
                logger.info(f"[ACTION] Creating order for {gpu_model} with params: {parameters}")
                order = create_order(
                    gpu_model_str=parameters.get("gpu_model"),
                    sla=parameters.get("sla"),
                    region_str=parameters.get("region"),
                    imbalance_type=imbalance_type,
                    duration_hours=parameters.get("duration_hours", 1),
                )
                if isinstance(order, dict):
                    created_order_id = order.get("order_id")
            if created_order_id:
                outcome["order_id"] = created_order_id
            if isinstance(order, dict) and order.get("order_id"):
                try:
                    now_iso = datetime.now().isoformat()
                    sqlite_client = get_sqlite_client()
                    await sqlite_client.upsert_order(
                        order_id=order.get("order_id", created_order_id or ""),
                        status="open",
                        created_at=now_iso,
                        updated_at=now_iso,
                        offer_resource=order.get("offer_resource"),
                        demand_resource=order.get("demand_resource"),
                        fulfillment_resource=None,
                        duration_hours=int(order.get("duration_hours", 1)),
                        order_maker=order.get("order_maker", BASE_URL_OVERRIDE),
                        order_taker=order.get("order_taker"),
                        matched_offer_id=parameters.get("matched_offer_id"),
                        maker_attestation=order.get("maker_attestation"),
                        taker_attestation=order.get("taker_attestation"),
                        oracle_address=order.get("oracle_address"),
                        escrow_uid=None,
                    )
                except Exception as exc:
                    logger.warning("[LOCAL DB] Failed to upsert order %s: %s", created_order_id, exc)
            outcome["result"] = {"order_id": f"sim_{action.timestamp.isoformat()}"}
            outcome["message"] = f"Order created for {gpu_model}"
            # Then, call make_offer to propagate to the network.
            make_offer_result = await make_offer(ctx=ctx, order=order, alkahest_client=alkahest_client)
            # make_offer returns a dict, not an Event object
            if isinstance(make_offer_result, dict):
                outcome["result"] = make_offer_result
                outcome["message"] = make_offer_result.get("message", f"Order created for {gpu_model}")
                logger.info(f"[ACTION] Make offer result: {make_offer_result}")
            else:
                # Fallback for Event objects (shouldn't happen but handle gracefully)
                content = getattr(make_offer_result, "content", None)
                if content:
                    # Content object has .parts attribute, not .get() method
                    parts = getattr(content, "parts", [])
                    for part in parts:
                        text = getattr(part, "text", "")
                        if text:
                            logger.info(f"[ACTION] Received response: {text}")
                            outcome["message"] = text
                            break
            
        case ActionType.RESOLVE_INTERNALLY.value:
            result = rebalance_internal_resources()
            logger.info(f"[ACTION] [SIMULATED] Resolving resource imbalance internally with params: {parameters}")
            outcome["result"] = result
            outcome["message"] = "Resources rebalanced internally (simulated)"

        case ActionType.FULFILL_COMPUTE_OBLIGATION.value:
            logger.info(f"[ACTION] Fulfilling compute obligation with params: {parameters}")
            escrow_uid = parameters.get("escrow_uid")
            ssh_public_key = parameters.get("ssh_public_key")
            order = parameters.get("order")
            order_dict = order if isinstance(order, dict) else {}
            oracle_address = parameters.get("oracle_address") or order_dict.get("oracle_address")
            matched_order_id = parameters.get("matched_order_id")

            if not escrow_uid:
                raise ValueError("escrow_uid is required for fulfill_compute_obligation")
            if not ssh_public_key:
                raise ValueError("ssh_public_key is required for fulfill_compute_obligation")

            # Update our own local order if matched_order_id was threaded through the event.
            # This handles the seller-as-taker case where order_id in the order dict is the
            # buyer's order_id (not present in the seller's local DB).
            if matched_order_id:
                try:
                    sqlite_client = get_sqlite_client()
                    await sqlite_client.update_order(
                        order_id=matched_order_id,
                        status="accepted",
                        escrow_uid=escrow_uid,
                    )
                except Exception as exc:
                    logger.warning("[LOCAL DB] Failed to update matched_order_id %s at fulfillment: %s", matched_order_id, exc)

            result = await fulfill_compute_obligation(
                client=alkahest_client,
                escrow_uid=escrow_uid,
                oracle_address=parameters.get("oracle_address") or (order if isinstance(order, dict) else {}).get("oracle_address"),
                ssh_public_key=ssh_public_key,
                order=order,
            )
            if result.get("status") == "fulfilled":
                # Include event_type for downstream parsing and propagate to remote agent.
                result["event_type"] = EventType.RECEIVE_COMPUTE_OBLIGATION_FULFILLMENT.value
                if ctx:
                    # Counterparty to notify is the order taker (we are the maker fulfilling for them).
                    order_obj = parameters.get("order")
                    if isinstance(order_obj, dict):
                        order_dict = order_obj
                    elif hasattr(order_obj, "model_dump"):
                        order_dict = order_obj.model_dump(mode="json") if order_obj else {}
                    else:
                        order_dict = {}
                    counterparty_ref = parameters.get("counterparty_url") or _resolve_counterparty_url_from_order(order_dict)
                    counterparty_url = _coerce_agent_reference_to_url(counterparty_ref)
                    if not counterparty_url:
                        raise ValueError(
                            f"fulfill_compute_obligation: cannot notify buyer — "
                            f"unresolved counterparty={counterparty_ref!r}"
                        )
                    try:
                        event = Event(
                            author=AGENT_ID,
                            content=genai_types.Content(
                                role="model",
                                parts=[
                                    genai_types.Part.from_function_response(
                                        name=EventType.RECEIVE_COMPUTE_OBLIGATION_FULFILLMENT.value,
                                        response=result,
                                    )
                                ],
                            ),
                            invocation_id=ctx.invocation_id,
                            branch=ctx.branch,
                        )
                        await send_to_remote_agent(ctx, event, agent_url=counterparty_url)
                    except Exception as send_err:
                        logger.warning("[ACTION] Failed to send fulfillment to remote agent: %s", send_err)
            else:
                logger.warning(
                    "[ACTION] Skipping fulfillment event; status=%s",
                    result.get("status"),
                )
            outcome["result"] = result
            outcome["message"] = result.get("message")

        case ActionType.TRUST_COMPUTE_OBLIGATION_FULFILLMENT.value:
            logger.info(f"[ACTION] Trusting compute fulfillment with params: {parameters}")
            # The agent trusting a fulfillment is always the oracle (token buyer).
            oracle_address = parameters.get("oracle_address") or CONFIG.agent_wallet_address
            result = await arbitrate_compute_fulfillment(
                client=alkahest_client,
                fulfillment_uid=parameters.get("fulfillment_uid"),
                oracle_address=oracle_address,
                escrow_uid=parameters.get("escrow_uid"),
            )
            logger.info(f"[ALKAHEST]: {result}")
            result["escrow_uid"] = result.get("escrow_uid") or parameters.get("escrow_uid")
            decisions = result.get("decisions")
            logger.info("[ACTION] Arbitration decisions: %s", decisions)
            try:
                escrow_uid = parameters.get("escrow_uid")
                connection_details = parameters.get("connection_details")
                if escrow_uid and connection_details:
                    sqlite_client = get_sqlite_client()
                    await sqlite_client.update_order_by_escrow_uid(
                        escrow_uid=escrow_uid,
                        status="accepted",
                        fulfillment_resource=connection_details,
                    )
            except Exception as exc:
                logger.warning("[LOCAL DB] Failed to store fulfillment details for escrow %s: %s", parameters.get("escrow_uid"), exc)
            if ctx:
                # Counterparty to notify is whoever sent the fulfillment (source of the trust action).
                counterparty_ref = parameters.get("counterparty_url") or parameters.get("agent_url")
                counterparty_url = _coerce_agent_reference_to_url(counterparty_ref)
                if not counterparty_url:
                    raise ValueError(
                        f"trust_compute_obligation_fulfillment: cannot send arbitration result — "
                        f"unresolved counterparty reference={counterparty_ref!r}"
                    )
                try:
                    event = Event(
                        author=AGENT_ID,
                        content=genai_types.Content(
                            role="model",
                            parts=[
                                genai_types.Part.from_function_response(
                                    name=EventType.ARBITRATION_COMPLETE.value,
                                    response={
                                        "event_type": EventType.ARBITRATION_COMPLETE.value,
                                        "decisions": decisions,
                                        "fulfillment_uid": result.get("fulfillment_uid"),
                                        "oracle_address": result.get("oracle_address"),
                                        "escrow_uid": result.get("escrow_uid"),
                                        "status": result.get("status"),
                                    },
                                )
                            ],
                        ),
                        invocation_id=ctx.invocation_id,
                        branch=ctx.branch,
                    )
                    await send_to_remote_agent(ctx, event, agent_url=counterparty_url)
                except Exception as send_err:
                    logger.warning("[ACTION] Failed to send arbitration result to remote agent: %s", send_err)
            outcome["result"] = result
            outcome["message"] = "Fulfillment trusted; arbitration completed"

        case ActionType.COLLECT_ESCROW.value:
            logger.info(f"[ACTION] Collecting escrow with params: {parameters}")
            escrow_uid = parameters.get("escrow_uid")
            fulfillment_uid = parameters.get("fulfillment_uid")

            if not escrow_uid or not fulfillment_uid:
                outcome["result"] = {
                    "status": "error",
                    "message": "Missing escrow_uid or fulfillment_uid for collect_escrow",
                    "escrow_uid": escrow_uid,
                    "fulfillment_uid": fulfillment_uid,
                }
                outcome["message"] = outcome["result"]["message"]
                return outcome

            try:
                result = await collect_escrow(
                    client=alkahest_client,
                    escrow_uid=escrow_uid,
                    fulfillment_uid=fulfillment_uid,
                )
                logger.info(f"[ACTION] Escrow collection result: {result}")
                if result:
                    outcome["result"] = {
                        "status": "collected",
                        "message": "Escrow collected successfully",
                        "escrow_uid": escrow_uid,
                        "escrow_collection_uid": result,
                        "fulfillment_uid": fulfillment_uid,
                    }
                else:
                    outcome["result"] = {
                        "status": "collected",
                        "message": "Failed to collect escrow",
                        "escrow_uid": escrow_uid,
                        "fulfillment_uid": fulfillment_uid,
                    }
                outcome["message"] = outcome["result"]["message"]
            except Exception as err:
                logger.warning("[ACTION] Failed to collect escrow: %s", err)
                outcome["result"] = {
                    "status": "error",
                    "message": f"Failed to collect escrow: {err}",
                    "escrow_uid": escrow_uid,
                    "fulfillment_uid": fulfillment_uid,
                }
                outcome["message"] = outcome["result"]["message"]
            
        case ActionType.COUNTER_OFFER.value:
            logger.info(f"[ACTION] Countering offer with params: {parameters}")
            # Execute counter offer: create negotiation thread and send negotiation event
            result = await counter_offer(
                ctx=ctx,
                parameters=parameters,
            )
            outcome["result"] = result
            outcome["message"] = result.get("message", "Counter offer sent")
            
        case ActionType.NOOP.value:
            logger.info(f"[ACTION] [SIMULATED] No operation required")
            outcome["result"] = None
            outcome["message"] = "No operation"
            
        case _:
            logger.warning(f"[ACTION] [SIMULATED] Unknown action type: {action_type_str}")
            outcome["result"] = None
            outcome["message"] = f"Unknown action type (simulated): {action_type_str}"
    
    return outcome


def connect_to_remote_agent(agent_url: str | None = None):
    """Connect to a remote agent by URL."""
    if agent_url is None:
        raise ValueError("[A2A] send_to_remote_agent called with no agent_url")
    resolved_agent_url = _coerce_agent_reference_to_url(agent_url)
    if not resolved_agent_url or not _is_http_url(resolved_agent_url):
        raise ValueError(f"Unable to resolve valid remote agent URL from reference '{agent_url}'")
    agent_url = resolved_agent_url
    agent_card_url = f"{agent_url.rstrip('/')}{AGENT_CARD_WELL_KNOWN_PATH}"
    
    # Sanitize URL to create valid identifier (remove protocol, slashes, colons)
    # e.g., "http://localhost:8000/" -> "localhost_8000"
    sanitized_name = agent_url.replace("http://", "").replace("https://", "").replace("/", "_").replace(":", "_").replace(".", "_")
    # Remove trailing underscores and ensure it starts with letter/underscore
    sanitized_name = sanitized_name.rstrip("_")
    if sanitized_name and sanitized_name[0].isdigit():
        sanitized_name = f"agent_{sanitized_name}"
    if not sanitized_name:
        sanitized_name = "remote_agent"
    
    remote_agent = RemoteA2aAgent(
        name=sanitized_name,
        description="A helpful AI assistant trading compute resources with others.",
        agent_card=agent_card_url,
    )
    return remote_agent

async def send_to_remote_agent(
    ctx: InvocationContext,
    event: Event,
    remote_agent: RemoteA2aAgent = None,
    agent_url: str | None = None
):
    """Takes an event and sends it to a specified remote agent via A2A.

    Args:
        ctx: Invocation context
        event: Event to send
        remote_agent: Pre-constructed RemoteA2aAgent (optional)
        agent_url: Agent URL to connect to (optional, used if remote_agent is None)

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
        remote_agent = connect_to_remote_agent(agent_url)

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


async def close_order(parameters: dict[str, Any] | None = None) -> dict[str, Any]:
    """Close an order locally and in the registry (if enabled)."""
    parameters = parameters or {}
    order_id = parameters.get("order_id")
    if not isinstance(order_id, str) or not order_id.strip():
        return {"status": "error", "message": "Missing order_id for close_order"}

    try:
        sqlite_client = get_sqlite_client()
        await sqlite_client.update_order(
            order_id=order_id,
            status="closed",
        )
    except Exception as exc:
        logger.warning("[LOCAL DB] Failed to update order %s as closed: %s", order_id, exc)

    if not CONFIG.enable_registry_discovery:
        return {
            "status": "skipped",
            "message": "Registry discovery is disabled; order not updated in registry",
            "order_id": order_id,
        }

    try:
        registry_client = get_registry_client()
        result = await registry_client.update_order(order_id, {"status": "closed"})
        if result:
            return {
                "status": "closed",
                "message": f"Order {order_id} marked closed in registry",
                "order_id": order_id,
                "registry_result": result,
            }
        return {
            "status": "error",
            "message": f"Failed to update order {order_id} in registry",
            "order_id": order_id,
        }
    except Exception as exc:
        logger.warning("[REGISTRY] Failed to close order %s in registry: %s", order_id, exc)
        return {
            "status": "error",
            "message": f"Registry update failed for order {order_id}: {exc}",
            "order_id": order_id,
        }


async def mock_provision_machine(ssh_public_key: str) -> str:
    """Mock stand-in for provisioning a machine.

    Return:
        String with connection details.
    """
    logger.info(f"[TOOL] (Simulated) Machine provisioned with SSH key for pubkey: {ssh_public_key}.")
    return "ssh -i <your_private_key> -p 7021 demo-user@node-01.example.net | password: demo-password"


def mock_schedule_vm_shutdown(lease_end_utc: str) -> None:
    """Mock stand-in for scheduling VM shutdown."""
    logger.info("[TOOL] (Simulated) Scheduled VM shutdown at %s UTC.", lease_end_utc)


async def provision_machine(
    ssh_public_key: str,
    *,
    vm_host: str = "vm1",
    vm_target: str = "tenant-vm",
) -> str:
    """Provision a machine using the provided SSH public key.

    Args:
        ssh_public_key: SSH public key to install on the provisioned machine.

    Returns:
        String with connection details.
    """
    logger.info(f"[TOOL] Provisioning machine with provided SSH public key.")
    try:
        connection_info = run_vm_provisioning_playbook(
            ssh_public_key,
            vm_host=vm_host,
            vm_target=vm_target,
        )
        if connection_info:
            logger.info(f"[TOOL] Machine provisioned: {connection_info}")
            return connection_info
        logger.warning("[TOOL] Provisioning completed but connection info was not available.")
        raise RuntimeError("Provisioning completed, but SSH connection info unavailable.")
    except Exception as exc:
        logger.error("[TOOL] Provisioning failed: %s", exc)
        raise RuntimeError(f"Provisioning failed: {exc}") from exc

def extract_compute_and_token_from_order_dict(order: dict) -> tuple[dict, dict]:
    """Given an order, take the demand and offer and extract which is compute and which is tokens."""
    offer_resource = order.get("offer_resource", {})
    demand_resource = order.get("demand_resource", {})

    offer_is_compute = "gpu_model" in offer_resource
    demand_is_compute = "gpu_model" in demand_resource

    if offer_is_compute:
        compute_resource = offer_resource
        token_resource = demand_resource
    elif demand_is_compute:
        compute_resource = demand_resource
        token_resource = offer_resource
    else:
        raise ValueError("Neither offer nor demand resource is compute in the provided order.")

    return compute_resource, token_resource


def _extract_initial_price_from_order(order: MarketOrder | dict) -> int:
    """Extract the initial price from an order's token resource.

    The token amount represents:
    - For surplus (offering compute): The floor price (minimum willing to accept)
    - For deficit (demanding compute): The ceiling price (maximum willing to pay)
    """
    if isinstance(order, dict):
        order = MarketOrder.model_validate(order)

    if isinstance(order.offer_resource, TokenResource):
        return order.offer_resource.amount
    if isinstance(order.demand_resource, TokenResource):
        return order.demand_resource.amount

    raise ValueError(f"Order has no token resource: {order.order_id}")


async def counter_offer(
    *,
    ctx: InvocationContext | None,
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Send a counter offer in a negotiation."""
    parameters = parameters or {}

    # Use type-safe parameter extraction
    params = CounterOfferParams.from_dict(parameters)
    if not params:
        return {
            "status": "error",
            "message": "Missing required counter_offer parameters (negotiation_id, order_id, proposed_price, our_price, their_price)",
        }

    if ctx is None:
        return {
            "status": "error",
            "message": "No invocation context available for counter_offer",
        }

    # Get order details to find the counterparty
    try:
        registry_client = get_registry_client()
        order = await registry_client.get_order(params.order_id)
        if not order:
            return {
                "status": "error",
                "message": f"Order {params.order_id} not found in registry",
            }

        their_agent_id = order.get("order_maker")

        # Validate that we have a valid agent URL for the counterparty
        if not their_agent_id:
            logger.warning(f"[ACTION] Order {params.order_id} missing 'order_maker' field.")
        elif not their_agent_id.startswith(("http://", "https://")):
            logger.warning(
                f"[ACTION] Order {params.order_id} has invalid 'order_maker' URL: {their_agent_id}"
            )

        # Determine our strategy by looking up our order (for internal policy use)
        strategy = None
        if params.our_order_id:
            try:
                our_order = await registry_client.get_order(params.our_order_id)
                if our_order:
                    market_order = MarketOrder.model_validate(our_order)
                    strategy = determine_strategy_from_order(market_order)
                    logger.info(f"[ACTION] Determined strategy '{strategy}' from our order {params.our_order_id}")
            except Exception as e:
                logger.warning(f"[ACTION] Failed to determine strategy from order {params.our_order_id}: {e}")

        # Use transaction context manager for thread operations
        async with NegotiationThreadTransaction("COUNTER_OFFER") as txn:
            await txn.ensure_thread(
                negotiation_id=params.negotiation_id,
                our_order_id=params.our_order_id or "",
                their_order_id=params.order_id,
                our_agent_id=AGENT_ID,
                their_agent_id=their_agent_id or "",
                our_initial_price=params.our_price,  # Store locally for future rounds
                our_strategy=strategy,  # Store locally, never transmitted
            )
            await txn.add_message(
                negotiation_id=params.negotiation_id,
                sender=AGENT_ID,
                our_price=params.our_price,
                their_price=params.their_price,
                proposed_price=params.proposed_price,
                action_taken=ActionType.COUNTER_OFFER.value,
                message_type="counter_proposal",
            )

        event_payload = {
            "event_type": EventType.NEGOTIATION.value,
            "negotiation_id": params.negotiation_id,
            "message_type": "counter_proposal",
            "sender": AGENT_ID,
            "data": {
                "proposed_price": params.proposed_price,
            },
        }

        event = Event(
            author=AGENT_ID,
            content=genai_types.Content(
                role="model",
                parts=[
                    genai_types.Part.from_function_response(
                        name="counter_offer",
                        response=event_payload,
                    )
                ],
            ),
            invocation_id=ctx.invocation_id,
            branch=ctx.branch,
        )

        # Send to counterparty
        result = await send_to_remote_agent(ctx, event, agent_url=their_agent_id)

        return {
            "status": "sent",
            "message": "Counter offer sent",
            "negotiation_id": params.negotiation_id,
            "proposed_price": params.proposed_price,
            "remote_response": getattr(result, "content", None),
        }
    except Exception as e:
        logger.error(f"[ACTION] Failed to send counter offer: {e}")
        return {
            "status": "error",
            "message": f"Failed to send counter offer: {e}",
        }


async def accept_offer(
    *,
    alkahest_client: Any | None,
    ctx: InvocationContext | None,
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Accept a received offer and send acceptance to the counterparty via A2A."""
    parameters = parameters or {}

    order_payload = parameters.get("order") or parameters.get("offer")

    if isinstance(order_payload, MarketOrder):
        order_dict = order_payload.model_dump(mode="json")
    elif isinstance(order_payload, dict):
        order_dict = order_payload
    else:
        logger.warning("[TOOL] Cannot accept offer: no order payload provided.")
        return {"status": "error", "message": "Missing order payload for accept_offer"}

    order_id = order_dict.get("order_id")
    our_order_id = parameters.get("our_order_id")
    their_order_id = parameters.get("their_order_id") or order_id
    negotiation_id = parameters.get("negotiation_id")

    async with NegotiationThreadTransaction("ACCEPT_OFFER") as txn:
        await txn.cancel_competing(order_id, their_order_id, negotiation_id)
        if negotiation_id:
            await txn.mark_terminal(negotiation_id, "success")

    if not our_order_id:
        try:
            sqlite_client = get_sqlite_client()
            inferred = await sqlite_client.find_symmetric_open_order(
                offer_resource=order_dict.get("offer_resource"),
                demand_resource=order_dict.get("demand_resource"),
                order_maker=BASE_URL_OVERRIDE,
            )
            if inferred:
                our_order_id = inferred.get("order_id")
        except Exception as exc:
            logger.warning("[LOCAL DB] Failed to infer our_order_id: %s", exc)

    if _we_are_compute_buyer(order_dict):
        return await _accept_as_buyer(
            alkahest_client=alkahest_client,
            ctx=ctx,
            parameters=parameters,
            order_dict=order_dict,
            our_order_id=our_order_id,
            their_order_id=their_order_id,
        )
    else:
        return await _accept_as_seller(
            ctx=ctx,
            parameters=parameters,
            order_dict=order_dict,
            our_order_id=our_order_id,
            their_order_id=their_order_id,
        )


async def _accept_as_buyer(
    *,
    alkahest_client: Any | None,
    ctx: InvocationContext | None,
    parameters: dict[str, Any],
    order_dict: dict[str, Any],
    our_order_id: str | None,
    their_order_id: str | None,
) -> dict[str, Any]:
    """Buyer path: create on-chain escrow and send AcceptOfferEvent with escrow_uid."""
    oracle_address = CONFIG.agent_wallet_address
    if not oracle_address:
        raise ValueError("Agent wallet address is required for buyer accept_offer but not configured")

    escrow_uid = None
    escrow_receipt = None

    if alkahest_client:
        compute_resource, token_resource = extract_compute_and_token_from_order_dict(order_dict)
        max_retries = 3
        base_delay = 1.0
        for attempt in range(max_retries):
            try:
                logger.info("[ALKAHEST] Attempting to put tokens in escrow (attempt %d/%d)", attempt + 1, max_retries)
                escrow_receipt = await buy_compute_with_erc20(
                    compute_resource=compute_resource,
                    token_resource=token_resource,
                    duration_hours=order_dict.get("duration_hours", 1),
                    oracle_address=oracle_address,
                    client=alkahest_client,
                )
                escrow_uid = escrow_receipt.get("log", {}).get("uid")
                if escrow_uid:
                    logger.info("[ALKAHEST] Created escrow; uid=%s", escrow_uid)
                    break
                logger.warning("[ALKAHEST] Escrow receipt missing uid on attempt %d", attempt + 1)
            except Exception as e:
                logger.warning("[ALKAHEST] Failed to create escrow on attempt %d/%d: %s", attempt + 1, max_retries, e)
                if attempt < max_retries - 1:
                    await asyncio.sleep(base_delay * (2 ** attempt))
                else:
                    raise RuntimeError(f"Failed to create escrow after {max_retries} attempts: {e}") from e

        if not escrow_uid:
            if isinstance(escrow_receipt, dict):
                escrow_uid = escrow_receipt.get("log", {}).get("uid")
            if not escrow_uid:
                raise RuntimeError("Failed to obtain escrow_uid from Alkahest response")
    else:
        raise RuntimeError("AlkahestClient is required for accept_offer. Cannot proceed without on-chain escrow.")

    order_dict["order_taker"] = BASE_URL_OVERRIDE
    order_dict["taker_attestation"] = escrow_uid
    order_dict["oracle_address"] = oracle_address

    # Echo the seller's order_id back so they can update their local DB without a lookup.
    matched_order_id = parameters.get("matched_order_id")

    event_payload = {
        "event_type": EventType.ACCEPT_OFFER.value,
        "source": BASE_URL_OVERRIDE,
        "offer": order_dict,
        "escrow_uid": escrow_uid,
        "ssh_public_key": SSH_PUBLIC_KEY,
        "matched_order_id": matched_order_id,
    }

    try:
        sqlite_client = get_sqlite_client()
        if our_order_id:
            await sqlite_client.update_order(
                order_id=our_order_id,
                status="accepted",
                order_taker=BASE_URL_OVERRIDE,
                taker_attestation=escrow_uid,
                escrow_uid=escrow_uid,
                matched_offer_id=their_order_id,
                oracle_address=oracle_address,
            )
    except Exception as exc:
        logger.warning("[LOCAL DB] Failed to update order %s as accepted: %s", our_order_id, exc)

    if CONFIG.enable_registry_discovery:
        try:
            registry_client = get_registry_client()
            their_id = order_dict.get("order_id")
            if their_id:
                updates = {"status": "accepted", "order_taker": BASE_URL_OVERRIDE, "taker_attestation": escrow_uid}
                result = await registry_client.update_order(their_id, updates)
                if result:
                    logger.info("[REGISTRY] Updated maker's order %s to accepted", their_id)
                else:
                    logger.warning("[REGISTRY] Failed to update maker's order %s", their_id)
        except Exception as e:
            logger.warning("[REGISTRY] Failed to update order in registry: %s", e)

    counterparty_ref = parameters.get("counterparty_url") or order_dict.get("order_maker")
    counterparty_url = _coerce_agent_reference_to_url(counterparty_ref)
    if not counterparty_url:
        raise ValueError(f"accept_offer (buyer): cannot send acceptance — unresolved counterparty={counterparty_ref!r}")

    if ctx is None:
        logger.warning("[TOOL] No invocation context; acceptance not sent.")
        return {**event_payload, "status": "pending", "message": "No invocation context available"}

    event = Event(
        author=AGENT_ID,
        content=genai_types.Content(
            role="model",
            parts=[genai_types.Part.from_function_response(name="accept_offer", response=event_payload)],
        ),
        invocation_id=ctx.invocation_id,
        branch=ctx.branch,
    )
    logger.info("[TOOL] Buyer accepting offer, notifying seller: %s", counterparty_url)
    try:
        result = await send_to_remote_agent(ctx, event, agent_url=counterparty_url)
        return {
            "status": "sent",
            "message": "Offer matched.",
            "escrow_uid": escrow_uid,
            "offer": order_dict,
            "remote_response": getattr(result, "content", None),
        }
    except Exception as e:
        logger.error("[TOOL] Failed to send acceptance: %s", e)
        return {"status": "error", "message": f"Failed to send acceptance: {e}", "escrow_uid": escrow_uid, "offer": order_dict}


async def _accept_as_seller(
    *,
    ctx: InvocationContext | None,
    parameters: dict[str, Any],
    order_dict: dict[str, Any],
    our_order_id: str | None,
    their_order_id: str | None,
) -> dict[str, Any]:
    """Seller path: signal acceptance to the buyer without creating an escrow.

    The buyer will receive this and create the escrow on their side, then send
    back an AcceptOfferEvent with escrow_uid for the seller to fulfill.
    """
    # Include our order_id so the buyer can echo it back, letting us update our
    # local DB directly when we receive the second AcceptOfferEvent.
    event_payload = {
        "event_type": EventType.ACCEPT_OFFER.value,
        "source": BASE_URL_OVERRIDE,
        "offer": order_dict,
        "escrow_uid": None,
        "ssh_public_key": None,
        "matched_order_id": our_order_id,
    }

    try:
        sqlite_client = get_sqlite_client()
        if our_order_id:
            await sqlite_client.update_order(
                order_id=our_order_id,
                status="matched",
                matched_offer_id=their_order_id,
            )
    except Exception as exc:
        logger.warning("[LOCAL DB] Failed to update order %s as matched: %s", our_order_id, exc)

    counterparty_ref = parameters.get("counterparty_url") or order_dict.get("order_maker")
    counterparty_url = _coerce_agent_reference_to_url(counterparty_ref)
    if not counterparty_url:
        raise ValueError(f"accept_offer (seller): cannot notify buyer — unresolved counterparty={counterparty_ref!r}")

    if ctx is None:
        logger.warning("[TOOL] No invocation context; seller acceptance not sent.")
        return {**event_payload, "status": "pending", "message": "No invocation context available"}

    event = Event(
        author=AGENT_ID,
        content=genai_types.Content(
            role="model",
            parts=[genai_types.Part.from_function_response(name="accept_offer", response=event_payload)],
        ),
        invocation_id=ctx.invocation_id,
        branch=ctx.branch,
    )
    logger.info("[TOOL] Seller signalling acceptance to buyer (no escrow yet): %s", counterparty_url)
    try:
        result = await send_to_remote_agent(ctx, event, agent_url=counterparty_url)
        return {
            "status": "sent",
            "message": "Order matched.",
            "offer": order_dict,
            "remote_response": getattr(result, "content", None),
        }
    except Exception as e:
        logger.error("[TOOL] Failed to send seller acceptance: %s", e)
        return {"status": "error", "message": f"Failed to send seller acceptance: {e}", "offer": order_dict}


def create_order(
    gpu_model_str: str = None,
    sla: float = None,
    region_str: str = None,
    imbalance_type: str = "surplus",
    publish_to_registry: bool = True,
    offer_resource: ComputeResource | TokenResource = None,
    demand_resource: ComputeResource | TokenResource = None,
    duration_hours: int = 1,
) -> dict | None:
    """Create an order in the market.

    This only locally assembles the details of an order, without yet propagating it into the market,
    and so should be considered a helper function towards making the offer.

    Not to be confused with make_offer, which propagates the order to the market.

    Args:
        gpu_model_str: The GPU model, one of: {"H200", "Tesla V100", "RTX 5080"} (required for surplus)
        sla: SLA required for the order (required for surplus)
        region_str: Geographic region, one of: {"California, US", "New York, US, "Tokyo, JP"} (required for surplus)
        imbalance_type: "surplus" (offer compute, demand tokens) or "deficit" (offer tokens, demand compute)
        publish_to_registry: Whether to publish order to registry (default: True)
        offer_resource: Pre-constructed offer resource (optional, overrides gpu_model_str/sla/region_str)
        demand_resource: Pre-constructed demand resource (optional)
        duration_hours: Duration of the order in hours (default: 1); 1 if seller (rate), else total if buyer

    Returns:
        The created order as a dictionary if the order was successfully created, or None otherwise.
        This creates a UUID identifying the new order, and the details should match the provided arguments.
    """
    settlement_token = TOKEN_REGISTRY.require("MOCK")
    logger.info(f"[TOOL] Creating order for resource (imbalance_type: {imbalance_type}).")
    
    # Determine order direction based on imbalance_type
    if imbalance_type == "deficit":
        # Deficit: Offer tokens, demand compute
        if not offer_resource:
            offer_resource = TokenResource(
                token=settlement_token,
                amount=9 * 10**settlement_token.decimals,
            )
        if not demand_resource:
            if not gpu_model_str or sla is None or not region_str:
                logger.error("[TOOL] gpu_model_str, sla, and region_str required for deficit orders")
                return None
            demand_resource = ComputeResource(
                gpu_model=GPUModel(gpu_model_str),
                quantity=1,
                sla=sla,
                region=Region(region_str),
            )
    else:
        # Surplus: Offer compute, demand tokens (default/current behavior)
        if not offer_resource:
            if not gpu_model_str or sla is None or not region_str:
                logger.error("[TOOL] gpu_model_str, sla, and region_str required for surplus orders")
                return None
            offer_resource = ComputeResource(
                gpu_model=GPUModel(gpu_model_str),
                quantity=1,
                sla=sla,
                region=Region(region_str),
            )
        if not demand_resource:
            demand_resource = TokenResource(
                token=settlement_token,
                amount=9 * 10**settlement_token.decimals,
            )
    
    # The token-offering side is always the oracle/buyer.
    offering_tokens = isinstance(offer_resource, TokenResource) or (
        isinstance(offer_resource, dict) and "token" in offer_resource
    )
    oracle_address = CONFIG.agent_wallet_address if offering_tokens else None

    order = MarketOrder(
        order_id=str(uuid.uuid4()),
        order_maker=BASE_URL_OVERRIDE,
        order_taker=None,
        offer_resource=offer_resource,
        demand_resource=demand_resource,
        duration_hours=duration_hours,
        maker_attestation=None,
        taker_attestation=None,
        oracle_address=oracle_address,
    )

    order_dict = order.model_dump(mode='json')
    
    # Note: Order publishing to registry happens in make_offer() to ensure
    # it's done in an async context. This keeps create_order() synchronous
    # for compatibility with existing callers.
    
    return order_dict


async def _find_and_send_matching_offers(
    order_dict: dict,
    ctx: InvocationContext | None = None,
    event: Event | None = None,
) -> dict:
    """Helper function to find matching orders and send offers.
    
    This function is used by both make_offer() and the retry mechanism.
    
    Args:
        order_dict: Order dictionary to match against
        ctx: Invocation context (optional, for retries)
        event: Event object (optional, will be created if not provided)
    
    Returns:
        Result dictionary with status and details
    """
    if not CONFIG.enable_registry_discovery:
        return {
            "status": "disabled",
            "message": "Registry discovery is disabled",
        }
    
    try:
        registry_client = get_registry_client()
        
        # Determine resource types for filtering
        offer_res = order_dict.get("offer_resource", {})
        demand_res = order_dict.get("demand_resource", {})
        
        # Determine resource types
        offer_type = "compute" if "gpu_model" in offer_res else ("token" if "token" in offer_res else "unknown")
        demand_type = "compute" if "gpu_model" in demand_res else ("token" if "token" in demand_res else "unknown")
        
        # Query registry for matching orders (bidirectional)
        filters = {
            "status": "open",
        }
        
        matching_orders = await registry_client.query_orders(
            filters=filters,
            bidirectional=True,
            limit=CONFIG.max_discovery_agents
        )
        
        # Use match_orders helper to filter more precisely
        matching_orders = registry_client.match_orders(
            order_dict,
            matching_orders,
            bidirectional=True
        )
        
        # Filter out our own orders (don't match with ourselves)
        order_id = order_dict.get("order_id")
        matching_orders = [m for m in matching_orders if m.get("order_id") != order_id]

        # Filter out orders that are already in active negotiations with us
        async with NegotiationThreadTransaction("MAKE_OFFER") as txn:
            active_order_ids = await txn.filter_active(order_id)
            if active_order_ids:
                matching_orders = [
                    m for m in matching_orders
                    if m.get("order_id") not in active_order_ids
                ]
                logger.info(f"[REGISTRY] Filtered out {len(active_order_ids)} orders already in active negotiations")
        
        if not matching_orders:
            return {
                "status": "no_match",
                "message": "No matching market orders found in registry",
                "order": order_dict,
            }
        
        logger.info(f"[REGISTRY] Found {len(matching_orders)} matching orders, sending offers")
        
        # Extract agent URLs from matching orders
        agent_urls = []
        matched_order_ids = []
        for match_order in matching_orders[:CONFIG.max_discovery_agents]:
            maker_url = match_order.get("order_maker")
            matched_order_id = match_order.get("order_id")
            if maker_url and maker_url not in agent_urls:
                agent_urls.append(maker_url)
            if matched_order_id:
                matched_order_ids.append(matched_order_id)
        
        # Send offers only if we have a context (for initial make_offer calls)
        # For retries without context, we just log matches - actual offers will be sent
        # when other agents query the registry and find our orders
        results = []
        if ctx and event:
            # Create event if not provided
            if event is None:
                event = Event(
                    author=AGENT_ID,
                    content=genai_types.Content(
                        role="model",
                        parts=[
                            genai_types.Part.from_function_response(
                                name="make_offer",
                                response={
                                    "event_type": EventType.MAKE_OFFER.value,
                                    "offer": order_dict
                                })
                        ],
                    ),
                    invocation_id=ctx.invocation_id,
                    branch=ctx.branch,
                )
            
            # Send offer to each matching agent
            for idx, agent_url in enumerate(agent_urls):
                try:
                    matched_order = matching_orders[idx] if idx < len(matching_orders) else None
                    matched_order_id = matched_order.get("order_id") if matched_order else None
                    
                    # Check for duplicate negotiation before sending
                    negotiation_id = None
                    if matched_order_id:
                        async with NegotiationThreadTransaction("MAKE_OFFER") as txn:
                            if await txn.check_duplicate(order_id, matched_order_id):
                                logger.info(
                                    f"[REGISTRY] Skipping duplicate negotiation with order {matched_order_id}"
                                )
                                continue

                            # Create thread BEFORE sending offer to track in-flight negotiations
                            negotiation_id = f"{order_id}_{matched_order_id}_{AGENT_ID[:8]}"

                            # Get our order to determine strategy and initial price
                            our_order_dict = await registry_client.get_order(order_id)
                            if not our_order_dict:
                                raise ValueError(f"Order {order_id} not found in registry")
                            our_order = MarketOrder.model_validate(our_order_dict)
                            strategy = determine_strategy_from_order(our_order)
                            our_initial_price = _extract_initial_price_from_order(our_order)

                            await txn.ensure_thread(
                                negotiation_id=negotiation_id,
                                our_order_id=order_id,
                                their_order_id=matched_order_id,
                                our_agent_id=AGENT_ID,
                                their_agent_id=agent_url,
                                our_initial_price=our_initial_price,
                                our_strategy=strategy,
                            )
                            logger.debug(f"[REGISTRY] Created negotiation thread {negotiation_id} for offer to {agent_url}")

                    logger.info(f"[REGISTRY] Sending offer to agent at {agent_url}")
                    result = await send_to_remote_agent(ctx, event, agent_url=agent_url)
                    if result:
                        results.append({"agent_url": agent_url, "result": result})
                except Exception as e:
                    logger.warning(f"[REGISTRY] Failed to send offer to {agent_url}: {e}")
        elif agent_urls:
            # For retries without context, just log that matches were found
            # The bidirectional matching means other agents will discover our order
            logger.info(f"[REGISTRY] Found {len(agent_urls)} matching agents for order {order_id} (retry mode - matches logged)")
            return {
                "status": "matches_found",
                "message": f"Found {len(agent_urls)} matching orders (retry mode - offers will be sent when other agents query)",
                "order": order_dict,
                "targets": agent_urls,
                "matched_order_ids": matched_order_ids,
            }
        
        if results:
            logger.info(f"[REGISTRY] Successfully sent offers to {len(results)} agents")
            return {
                "status": "success",
                "message": f"Sent offers to {len(results)} agents",
                "results": results,
            }
        elif agent_urls:
            return {
                "status": "no_delivery",
                "message": "Matching orders found but no offers could be delivered",
                "order": order_dict,
                "targets": agent_urls,
            }
        else:
            return {
                "status": "no_match",
                "message": "No matching market orders found in registry",
                "order": order_dict,
            }
    except Exception as e:
        logger.error(f"[REGISTRY] Error finding/sending matching offers: {e}")
        return {
            "status": "error",
            "message": f"Error during matching: {e}",
            "order": order_dict,
        }


async def make_offer(ctx: InvocationContext, order: MarketOrder | dict, alkahest_client: Any | None = None):
    """Propagate an offer to the network using registry discovery.
    
    Queries the registry for matching orders and sends offers to discovered agents.
    
    Args:
        ctx: Invocation context
        order: MarketOrder object or order dictionary
        alkahest_client: Alkahest client for creating escrows (optional)
    """
    # Convert order to dict if needed
    if isinstance(order, MarketOrder):
        order_dict = order.model_dump(mode='json')
        order_id = order.order_id
    else:
        order_dict = order
        order_id = order_dict.get("order_id", "unknown")
    
    # Open orders should NOT have maker_attestation set
    # maker_attestation is only set when the maker fulfills their obligation via Alkahest
    # Ensure it's None for open orders
    if order_dict.get("maker_attestation"):
        logger.warning(f"[REGISTRY] Order {order_id} has maker_attestation set but should be None for open orders")
        # Don't remove it if it's already set (might be from a previous state)
    
    # Ensure order is published to registry first
    if CONFIG.enable_registry_discovery:
        try:
            registry_client = get_registry_client()
            
            # Get canonical agent ID for registry (required format)
            # Use ONCHAIN_AGENT_ID from .env directly
            agent_id_for_registry = CONFIG.agent_id  # fallback
            
            onchain_agent_id = CONFIG.onchain_agent_id
            # Debug: Log what we're reading
            logger.debug(f"[REGISTRY] CONFIG.onchain_agent_id={onchain_agent_id}, CONFIG.agent_id={CONFIG.agent_id}, CONFIG.port={CONFIG.port}")
            if not onchain_agent_id:
                logger.warning(f"[REGISTRY] ONCHAIN_AGENT_ID not set in .env, using CONFIG.agent_id={CONFIG.agent_id} (order publish may fail)")
            else:
                # Check if onchain_agent_id is already a canonical ID (starts with eip155:)
                if isinstance(onchain_agent_id, str) and onchain_agent_id.startswith("eip155:"):
                    # Already a canonical ID, use it directly
                    agent_id_for_registry = onchain_agent_id
                    logger.info(f"[REGISTRY] Using canonical ID from ONCHAIN_AGENT_ID: {agent_id_for_registry}")
                elif CONFIG.identity_registry_address:
                    # Build canonical ID from numeric agent ID
                    try:
                        numeric_agent_id = int(onchain_agent_id) if isinstance(onchain_agent_id, str) else onchain_agent_id
                        from service.clients.erc8004.blockchain import (
                            build_erc8004_canonical_id,
                        )
                        # Get chain_id - try from RPC or use default
                        chain_id = 31337  # Default for Anvil/local
                        if CONFIG.chain_rpc_url:
                            try:
                                from web3 import Web3
                                from web3.providers import HTTPProvider
                                from service.clients.erc8004.blockchain import (
                                    rpc_url_for_http_provider,
                                )
                                http_url = rpc_url_for_http_provider(CONFIG.chain_rpc_url)
                                w3 = Web3(HTTPProvider(http_url, request_kwargs={'timeout': 5}))
                                chain_id = w3.eth.chain_id
                            except Exception:
                                pass  # Use default
                        
                        agent_id_for_registry = build_erc8004_canonical_id(
                            chain_id=chain_id,
                            identity_registry=CONFIG.identity_registry_address,
                            agent_id=numeric_agent_id
                        )
                        logger.info(f"[REGISTRY] Built canonical ID from ONCHAIN_AGENT_ID={numeric_agent_id}: {agent_id_for_registry}")
                    except (ValueError, TypeError) as e:
                        logger.warning(f"[REGISTRY] Invalid ONCHAIN_AGENT_ID={onchain_agent_id}, must be numeric or canonical ID format. Using CONFIG.agent_id={CONFIG.agent_id}: {e}")
                    except Exception as e:
                        logger.warning(f"[REGISTRY] Failed to build canonical ID from ONCHAIN_AGENT_ID={onchain_agent_id}: {e}")
                else:
                    logger.warning(f"[REGISTRY] IDENTITY_REGISTRY_ADDRESS not set, cannot build canonical ID. Using CONFIG.agent_id={CONFIG.agent_id}")
            
            result = await registry_client.publish_order(agent_id_for_registry, order_dict)
            if result:
                logger.info(f"[REGISTRY] Published order {order_id} to registry before making offer")
            else:
                logger.warning(f"[REGISTRY] Order publish returned None - agent may not be registered in registry")
        except Exception as e:
            logger.warning(f"[REGISTRY] Failed to publish order to registry: {e}")
    
    # Create the event
    event = Event(
        author=AGENT_ID,
        content=genai_types.Content(
            role="model",
            parts=[
                genai_types.Part.from_function_response(
                    name="make_offer",
                    response={
                        "event_type": EventType.MAKE_OFFER.value,
                        "offer": order_dict
                    })
            ],
        ),
        invocation_id=ctx.invocation_id,
        branch=ctx.branch,
    )
    
    # Try registry discovery if enabled
    if CONFIG.enable_registry_discovery:
        result = await _find_and_send_matching_offers(order_dict, ctx, event)
        
        # Return appropriate result based on status
        if result.get("status") == "success":
            results = result.get("results", [])
            return results[0]["result"] if len(results) == 1 else {"results": results}
        elif result.get("status") == "no_match":
            # No matches found - order will remain open for retry
            return result
        elif result.get("status") == "no_delivery":
            return result
        elif result.get("status") == "error":
            raise RuntimeError(f"Registry discovery failed: {result.get('message')}")
        else:
            raise RuntimeError(f"Registry discovery returned unexpected status: {result.get('status')}")


def encode_compute_lease(
    compute_resource: ComputeResource | dict[str, Any],
    token_resource: TokenResource | dict[str, Any],
    duration_hours: int,
) -> bytes:
    """Encode a compute-for-token trade as JSON bytes for use as Alkahest demand payload.

    Args:
        compute_resource: ComputeResource (or dict payload) describing the offered compute.
        token_resource: TokenResource (or dict) describing the payment token and amount (base units) for the hourly rate.
        duration_hours: Lease duration in hours (defaults to 1, must be >=1).
    """
    compute = compute_resource
    if isinstance(compute_resource, dict):
        compute = ComputeResource.model_validate(compute_resource)
    if not isinstance(compute, ComputeResource):
        raise ValueError("encode_compute_lease expects a ComputeResource")

    hourly_rate = token_resource
    if isinstance(token_resource, dict):
        hourly_rate = TokenResource.model_validate(token_resource)
    if not isinstance(hourly_rate, TokenResource):
        raise ValueError("encode_compute_lease expects a TokenResource")

    if duration_hours < 1:
        raise ValueError("duration_hours must be >= 1")

    token_meta = hourly_rate.token
    total_price = hourly_rate.amount * duration_hours
    total_payment_resource = TokenResource(token=token_meta, amount=total_price)
    
    # Human-readable prices
    human_total_payment = Decimal(total_payment_resource.amount) / Decimal(10**token_meta.decimals)
    human_price_per_hour = Decimal(hourly_rate.amount) / (10**token_meta.decimals)

    lease_terms = {
        "gpu_model": compute.gpu_model.value if hasattr(compute.gpu_model, "value") else str(compute.gpu_model),
        "region": compute.region.value if hasattr(compute.region, "value") else str(compute.region),
        "quantity": compute.quantity,
        "sla": compute.sla,
        "duration_hours": duration_hours,
        "token_symbol": token_meta.symbol,
        "token_address": token_meta.contract_address,
        "price_per_hour_decimal": float(human_price_per_hour),
        "total_price_decimal": float(human_total_payment),
        "total_price_int": total_payment_resource.amount,
    }

    logger.info("[ALKAHEST] Encoding compute lease terms: %s", lease_terms)

    return json.dumps(lease_terms).encode("utf-8")


async def approve_token_escrow(
    token_resource: TokenResource | dict[str, Any],
    *,
    alkahest_client: AlkahestClient | None = None,
) -> str:
    """Approve an ERC20 escrow for the provided token resource."""
    if isinstance(token_resource, TokenResource):
        payment = token_resource
    elif isinstance(token_resource, dict):
        payment = TokenResource.model_validate(token_resource)
    else:
        raise ValueError("approve_token_escrow expects a TokenResource or compatible dict")
    token_meta = payment.token
    if alkahest_client is None:
        raise RuntimeError("approve_token_escrow requires an AlkahestClient")

    price_data = {"address": token_meta.contract_address, "value": payment.amount}
    logger.info(
        "[ALKAHEST] Approving escrow for %s %s (%s decimal places) -> %s",
        payment.amount,
        token_meta.symbol,
        token_meta.decimals,
        price_data,
    )
    try:
        escrow_approval = await alkahest_client.erc20.util.approve(price_data, "escrow")
        logger.info(f"[ALKAHEST]: Escrow approved: {escrow_approval}")
    except Exception as error:
        logger.info(f"[ALKAHEST] Escrow approval error: {error}")
        raise RuntimeError("Escrow approval failed") from error
    return escrow_approval


async def buy_compute_with_erc20(
    compute_resource: ComputeResource | dict[str, Any],
    token_resource: TokenResource | dict[str, Any],
    duration_hours: int,
    oracle_address: str,
    client: AlkahestClient,
) -> Any:
    """Create an ERC20 escrow for a compute lease using Alkahest.

    This is from the point of view of someone with a TokenResource who
    wishes to trade it for a ComputeResource.

    Encodes the compute lease as a JSON demand payload, approves the ERC20 amount,
    and creates escrow via the non-tierable escrow client. Expiration is set to 0
    (non-expiring) for now.
    """
    if not client:
        raise RuntimeError("buy_with_erc20 requires an AlkahestClient instance")

    logger.info(f"[ALKAHEST]: Buying compute with Client {client}")

    trusted_oracle_arbiter = get_trusted_oracle_arbiter()
    arbiter_address = trusted_oracle_arbiter

    # 1) Encode lease terms into demand bytes
    demand_data = TrustedOracleArbiterDemandData(
        oracle_address,
        encode_compute_lease(
            compute_resource=compute_resource,
            token_resource=token_resource,
            duration_hours=duration_hours,
        )
    )

    demand_bytes = demand_data.encode_self()

    # 2) Build price data from token resource, computing duration * rate
    if isinstance(token_resource, TokenResource):
        hourly_rate = token_resource
    else:
        hourly_rate = TokenResource.model_validate(token_resource)

    total_payment = TokenResource(
        token=hourly_rate.token,
        amount=hourly_rate.amount * duration_hours,
    )

    price_data = {"address": total_payment.token.contract_address, "value": total_payment.amount}

    # 3) Approve escrow spend
    await approve_token_escrow(total_payment, alkahest_client=client)

    # 4) Buy with ERC20, tying demand to arbiter data
    arbiter_data = {"arbiter": arbiter_address, "demand": demand_bytes}
    expiration = 0  # non-expiring escrow for now; may become time-limited later

    logger.info(
        "[ALKAHEST] escrow.create price_data=%s arbiter=%s expiration=%s",
        price_data,
        arbiter_address,
        expiration,
    )

    escrow_receipt = None

    try:
        escrow_receipt = await client.erc20.escrow.non_tierable.create(
            price_data,
            arbiter_data,
            expiration,
        )
        logger.info(f"[ALKAHEST]: {escrow_receipt}")
    except Exception as buy_with_erc20_err:
        logger.error("[ALKAHEST] Failed to create escrow: %s", buy_with_erc20_err)
        raise RuntimeError("Escrow creation failed") from buy_with_erc20_err

    return escrow_receipt

async def fulfill_compute_obligation(
    client: AlkahestClient | None,
    escrow_uid: str,
    ssh_public_key: str,
    oracle_address: str | None = None,
    order: str | dict | None = None,
):
    """Provision compute and fulfill the obligation. Falls back to simulated flow if no client.
    
    When the maker fulfills, this sets maker_attestation in the registry.
    """
    fulfillment_uid = None
    maker_attestation = None
    duration_hours = 1
    connection_details: str | None = None
    reserved_resource_id: str | None = None
    reserved_vm_host: str | None = None
    vm_target = f"tenant-{uuid.uuid4().hex[:4]}"

    logger.info(f"[ALKAHEST] Order for fulfillment: {order}")
    order_dict = None
    order_id = None
    order_bytes = b""
    required_attributes: dict[str, Any] = {}

    if order:
        if isinstance(order, str):
            try:
                order_dict = json.loads(order)
            except json.JSONDecodeError:
                order_dict = None
            order_bytes = order.encode("utf-8")
        elif isinstance(order, dict):
            order_dict = order

    if order_dict:
        order_id = order_dict.get("order_id")
        duration_hours = order_dict.get("duration_hours", 1)
        compute_resource, token_resource = extract_compute_and_token_from_order_dict(order_dict)
        if isinstance(compute_resource, dict):
            for key in ("region", "gpu_model"):
                if compute_resource.get(key) is not None:
                    required_attributes[key] = compute_resource.get(key)
        order_bytes = encode_compute_lease(
            compute_resource=compute_resource,
            token_resource=token_resource,
            duration_hours=duration_hours,
        )
        if order_id:
            try:
                sqlite_client = get_sqlite_client()
                await sqlite_client.update_order(
                    order_id=order_id,
                    status="accepted",
                    escrow_uid=escrow_uid,
                )
            except Exception as exc:
                logger.warning("[LOCAL DB] Failed to mark order %s accepted at fulfillment start: %s", order_id, exc)

    try:
        sqlite_client = get_sqlite_client()
        reserved = await sqlite_client.reserve_available_compute_vm(
            required_attributes=required_attributes or None
        )
        if not reserved:
            raise RuntimeError("No available compute VM matched required attributes")
        reserved_resource_id = str(reserved.get("resource_id"))
        reserved_vm_host = reserved.get("vm_host")
        if not reserved_vm_host:
            raise RuntimeError("Reserved resource missing vm_host")

        if CONFIG.use_mock_provisioning:
            connection_details = await mock_provision_machine(ssh_public_key)
        else:
            connection_details = await provision_machine(
                ssh_public_key,
                vm_host=reserved_vm_host,
                vm_target=vm_target,
            )
    except Exception as error:
        if reserved_resource_id:
            try:
                await get_sqlite_client().apply_resource_set_transition(
                    resource_id=reserved_resource_id,
                    event_type="reservation_released_after_provisioning_failure",
                    idempotency_key=f"release:{escrow_uid}:{reserved_resource_id}",
                    set_state="available",
                )
            except Exception as release_err:
                logger.warning(
                    "[LOCAL DB] Failed to release reserved resource %s after provisioning failure: %s",
                    reserved_resource_id,
                    release_err,
                )
        logger.error("[ALKAHEST] Provisioning failed, skipping obligation fulfillment: %s", error)
        return {
            "status": "error",
            "message": f"Provisioning failed: {error}",
            "escrow_uid": escrow_uid,
            "connection_details": None,
            "ssh_public_key": ssh_public_key,
        }

    if reserved_resource_id:
        try:
            await get_sqlite_client().apply_resource_set_transition(
                resource_id=reserved_resource_id,
                event_type="lease_started_after_provisioning",
                idempotency_key=f"lease:{escrow_uid}:{reserved_resource_id}",
                set_state="leased",
            )
        except Exception as lease_err:
            logger.warning(
                "[LOCAL DB] Failed to mark resource %s as leased after provisioning: %s",
                reserved_resource_id,
                lease_err,
            )

    lease_end_utc = (datetime.now(timezone.utc) + timedelta(hours=duration_hours)).strftime("%Y-%m-%d %H:%M")
    if CONFIG.use_mock_provisioning:
        mock_schedule_vm_shutdown(lease_end_utc)
    else:
        schedule_vm_shutdown(
            lease_end_utc,
            vm_host=reserved_vm_host or "vm1",
            vm_target=vm_target,
        )

    if not client or not oracle_address:
        # Demo fallback: skip on-chain, return simulated fulfillment uid
        fulfillment_uid = f"fulfill_{uuid.uuid4()}"
        maker_attestation = fulfillment_uid  # Use fulfillment_uid as maker_attestation
        logger.info("[ALKAHEST] (Simulated) Fulfilled compute obligation without on-chain client.")
    else:
        try:
            fulfillment_uid = await client.string_obligation.do_obligation(
                connection_details,
                escrow_uid
            )
            maker_attestation = fulfillment_uid  # Use fulfillment_uid as maker_attestation
            logger.info("[ALKAHEST] Fulfilled compute obligation with on-chain client; machine provisioned.")
            demand_bytes = order_bytes
            request_arbitration_result = await client.oracle.request_arbitration(
                fulfillment_uid,
                oracle_address,
                demand_bytes,
            )
            logger.info(f"[ALKAHEST] Arbitration requested: {request_arbitration_result}")
        except Exception as error:
            logger.error(f"[ALKAHEST] Fulfillment error: {error}")
    
    # Update registry with maker_attestation when maker fulfills
    if order and maker_attestation and CONFIG.enable_registry_discovery and order_id:
        try:
            registry_client = get_registry_client()
            updates = {
                "maker_attestation": maker_attestation,
            }
            result = await registry_client.update_order(order_id, updates)
            if result:
                logger.info(f"[REGISTRY] Updated order {order_id} with maker_attestation: {maker_attestation}")
            else:
                logger.warning(f"[REGISTRY] Failed to update order {order_id} with maker_attestation")
        except Exception as e:
            logger.warning(f"[REGISTRY] Error updating order {order_id} with maker_attestation: {e}")

    if order_id:
        try:
            sqlite_client = get_sqlite_client()
            await sqlite_client.update_order(
                order_id=order_id,
                maker_attestation=maker_attestation,
                fulfillment_resource=connection_details,
                escrow_uid=escrow_uid,
            )
        except Exception as exc:
            logger.warning("[LOCAL DB] Failed to update fulfillment for order %s: %s", order_id, exc)

    return {
        "status": "fulfilled",
        "message": "Compute obligation fulfilled",
        "escrow_uid": escrow_uid,
        "fulfillment_uid": fulfillment_uid,
        "connection_details": connection_details,
        "ssh_public_key": ssh_public_key,
        "fulfilling_party_url": BASE_URL_OVERRIDE,
    }

async def arbitrate_compute_fulfillment(
    client: AlkahestClient | None,
    fulfillment_uid: str,
    oracle_address: str | None,
    escrow_uid: str | None = None,
):
    logger.info(f"[ALKAHEST] Oracle address: {oracle_address}")
    
    async def decision_function(attestation, demand):
        logger.info(f"[ALKAHEST] Attestation: {attestation}")

        # Parse the demand directly from callback argument (no need to fetch from escrow!)
        try:
            demand_json = json.loads(bytes(demand).decode('utf-8'))
            logger.info(f"[ALKAHEST] Parsed demand data: {demand_json}")
        except Exception as e:
            logger.error(f"Failed to parse demand: {e}")

        return True

    def callback(decision):
        pass

    # Demo path: no client/chain
    if not client:
        decisions = [True]
        logger.info("[ALKAHEST] Arbitration decisions (simulated): %s", decisions)
        return {
            "status": "trusted",
            "message": "Arbitration skipped (auto-approve)",
            "fulfillment_uid": fulfillment_uid,
            "oracle_address": oracle_address,
            "escrow_uid": escrow_uid,
            "decisions": decisions,
        }

    mode = ArbitrationMode.PastUnarbitrated

    try:
        decisions = await client.oracle.arbitrate_many(
            decision_function,
            callback,
            mode,
            timeout_seconds=2.0
        )

        logger.info(f"[ALKAHEST] Arbitration result: {decisions}")
        if not decisions:
            logger.warning("[ALKAHEST] Warning: No fulfillments were arbitrated.")
        logger.info("[ALKAHEST] Arbitration decisions: %s", decisions)
        serialized_decisions = _serialize_decisions(decisions)
    except Exception as error:
        logger.info(f"[ALKAHEST] Arbitration Error: {error}")
        return {
            "status": "trusted",
            "message": "Arbitration failed",
            "fulfillment_uid": fulfillment_uid,
            "escrow_uid": escrow_uid,
            "oracle_address": oracle_address,
        }

    return {
        "status": "trusted",
        "message": "Arbitration completed",
        "fulfillment_uid": fulfillment_uid,
        "escrow_uid": escrow_uid,
        "oracle_address": oracle_address,
        "decisions": serialized_decisions,
    }

async def collect_escrow(
    client: AlkahestClient | None,
    escrow_uid: str,
    fulfillment_uid: str
):
    result = None
    if client is None:
        result = f"escrow_collected_{uuid.uuid4()}"
        logger.info("[ALKAHEST] (Simulated) Escrow collected {result}")
    else:
        try:
            logger.info(f"[ALKAHEST] Collecting escrow: escrow_uid={escrow_uid}, fulfillment_uid={fulfillment_uid}")
            result = await client.erc20.escrow.non_tierable.collect(
                escrow_uid,
                fulfillment_uid,
            )
            logger.info(f"[ALKAHEST]: Escrow collected: {result}")
        except Exception as error:
            logger.error(f"[ALKAHEST] Escrow collection error: {error}")
    return result
