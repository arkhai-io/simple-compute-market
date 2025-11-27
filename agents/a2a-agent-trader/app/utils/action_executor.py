"""Action execution simulation (logging only for now)."""

from __future__ import annotations

import uuid
from decimal import Decimal
import logging
from typing import Any

from google.adk.agents import InvocationContext
from google.adk.events import Event
from google.adk.agents.remote_a2a_agent import (
    AGENT_CARD_WELL_KNOWN_PATH,
    RemoteA2aAgent,
)

from alkahest_py import (
    AlkahestClient,
    ArbitrateOptions,
    TrustedOracleArbiterDemandData
)
import json

from google.genai import types as genai_types

from app.schema.pydantic_models import (
    Action,
    ActionType,
    ComputeResource,
    DomainEvent,
    EventType,
    GPUModel,
    MarketOrder,
    MakeOfferEvent,
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
SSH_PUBLIC_KEY = CONFIG.ssh_public_key

TRUSTED_ORACLE_ARBITER = "0xa51c1fc2f0d1a1b8494ed1fe312d7c3a78ed91c0"
DEMO_ORACLE_ADDRESS = "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC"

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


def _resolve_oracle_address(oracle_address: str | None) -> str:
    """Return the oracle signer address."""
    return oracle_address or DEMO_ORACLE_ADDRESS


async def execute_action(
    action: Action,
    alkahest_client: Any,
    ctx: InvocationContext | None = None,
    domain_event: DomainEvent | None = None,
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
                domain_event=domain_event,
                parameters=parameters,
            )
            outcome["result"] = result
            outcome["message"] = result.get("message", "Offer accepted")
            
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

        case ActionType.FULFILL_COMPUTE_OBLIGATION.value:
            logger.info(f"[ACTION] [SIMULATED] Fulfilling compute obligation with params: {parameters}")
            result = await fulfill_compute_obligation(
                client=alkahest_client,
                escrow_uid=parameters.get("escrow_uid"),
                oracle_address=parameters.get("oracle_address") or DEMO_ORACLE_ADDRESS,
                ssh_public_key=parameters.get("ssh_public_key"),
            )
            # Include event_type for downstream parsing and propagate to remote agent.
            result["event_type"] = EventType.RECEIVE_COMPUTE_OBLIGATION_FULFILLMENT.value
            if ctx:
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
                    await send_to_remote_agent(ctx, event)
                except Exception as send_err:
                    logger.warning("[ACTION] Failed to send fulfillment to remote agent: %s", send_err)
            outcome["result"] = result
            outcome["message"] = result.get("message", "Compute obligation fulfilled (simulated)")

        case ActionType.TRUST_COMPUTE_OBLIGATION_FULFILLMENT.value:
            logger.info(f"[ACTION] Trusting compute fulfillment with params: {parameters}")
            result = await arbitrate_compute_fulfillment(
                client=alkahest_client,
                fulfillment_uid=parameters.get("fulfillment_uid"),
                oracle_address=parameters.get("oracle_address", DEMO_ORACLE_ADDRESS),
                escrow_uid=parameters.get("escrow_uid"),
            )
            result["escrow_uid"] = result.get("escrow_uid") or parameters.get("escrow_uid")
            decisions = result.get("decisions")
            logger.info("[ACTION] Arbitration decisions: %s", decisions)
            if ctx:
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
                    await send_to_remote_agent(ctx, event)
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
                await collect_escrow(
                    client=alkahest_client,
                    escrow_uid=escrow_uid,
                    fulfillment_uid=fulfillment_uid,
                )
                outcome["result"] = {
                    "status": "collected",
                    "message": "Escrow collected successfully",
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


async def mock_provision_machine(ssh_public_key: str | None = None) -> str:
    """Mock stand-in for provisioning a machine.

    Return:
        String with connection details.
    """
    if ssh_public_key:
        logger.info("[TOOL] (Simulated) Machine provisioned with SSH key.")
    else:
        logger.info("[TOOL] (Simulated) Machine provisioned without SSH key.")
    return "demo-user@node-01.example.net"


async def accept_offer(
    *,
    alkahest_client: Any | None,
    ctx: InvocationContext | None,
    domain_event: DomainEvent | None,
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Accept a received offer and send acceptance to the counterparty via A2A."""
    parameters = parameters or {}

    # Prefer explicit order payload; fallback to the triggering MakeOfferEvent.
    order_payload = parameters.get("order") or parameters.get("offer")
    if order_payload is None and isinstance(domain_event, MakeOfferEvent):
        order_payload = domain_event.order

    if isinstance(order_payload, MarketOrder):
        order_dict = order_payload.model_dump(mode="json")
    elif isinstance(order_payload, dict):
        order_dict = order_payload
    else:
        logger.warning("[TOOL] Cannot accept offer: no order payload provided.")
        return {"status": "error", "message": "Missing order payload for accept_offer"}

    escrow_uid = None
    escrow_receipt = None

    # If alkahest_client provided, attempt on-chain buy to escrow tokens.
    if alkahest_client:
        try:
            logger.info("[ALKAHEST]: Putting tokens in escrow.")
            compute_resource = order_dict.get("offer_resource", {})
            token_resource = order_dict.get("demand_resource", {})
            escrow_receipt = await buy_compute_with_erc20(
                compute_resource=compute_resource,
                token_resource=token_resource,
                oracle_address=DEMO_ORACLE_ADDRESS,
                client=alkahest_client,
            )
            escrow_uid = escrow_receipt.get("log", {}).get("uid")
            logger.info("[ALKAHEST] Created escrow via buy_with_erc20; uid=%s", escrow_uid)
        except Exception as e:
            logger.warning("[ALKAHEST] Failed to create escrow via buy_with_erc20: %s", e)
    else:
        logger.info("[ALKAHEST] No AlkahestClient, falling back to simulated escrow_uid.")
        escrow_uid = f"escrow_{uuid.uuid4()}"

    if not escrow_uid and isinstance(escrow_receipt, dict):
        escrow_uid = escrow_receipt.get("log", {}).get("uid")
        logger.info(f"[ALKAHEST] Got escrow_uid: {escrow_uid}")

    # Stamp taker metadata onto the order.
    order_dict["order_taker"] = BASE_URL_OVERRIDE
    order_dict["taker_attestation"] = escrow_uid

    event_payload = {
        "event_type": EventType.ACCEPT_OFFER.value,
        "offer": order_dict,
        "escrow_uid": escrow_uid,
        "ssh_public_key": SSH_PUBLIC_KEY,
    }

    if ctx is None:
        logger.warning("[TOOL] No invocation context; acceptance not sent.")
        return {
            **event_payload,
            "status": "pending",
            "message": "No invocation context available to send acceptance",
        }

    event = Event(
        author=AGENT_ID,
        content=genai_types.Content(
            role="model",
            parts=[
                genai_types.Part.from_function_response(
                    name="accept_offer",
                    response=event_payload,
                )
            ],
        ),
        invocation_id=ctx.invocation_id,
        branch=ctx.branch,
    )

    logger.info("[TOOL] Accepting offer and notifying counterparty: %s", event_payload)

    try:
        result = await send_to_remote_agent(ctx, event)
        return {
            "status": "sent",
            "message": "Offer accepted and forwarded to counterparty",
            "escrow_uid": escrow_uid,
            "offer": order_dict,
            "remote_response": getattr(result, "content", None),
        }
    except Exception as e:
        logger.error("[TOOL] Failed to send acceptance: %s", e)
        return {
            "status": "error",
            "message": f"Failed to send acceptance: {e}",
            "escrow_uid": escrow_uid,
            "offer": order_dict,
        }


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
    settlement_token = TOKEN_REGISTRY.require("MOCK")
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
            token=settlement_token,
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


def encode_compute_lease(
    compute_resource: ComputeResource | dict[str, Any],
    token_resource: TokenResource | dict[str, Any],
    duration_days: int = 1,
) -> bytes:
    """Encode a compute-for-token trade as JSON bytes for use as Alkahest demand payload.

    Args:
        compute_resource: ComputeResource (or dict payload) describing the offered compute.
        token_resource: TokenResource (or dict) describing the payment token and amount (base units).
        duration_days: Lease duration in days (defaults to 1, must be >=1).
    """
    compute = compute_resource
    if isinstance(compute_resource, dict):
        compute = ComputeResource.model_validate(compute_resource)
    if not isinstance(compute, ComputeResource):
        raise ValueError("encode_compute_lease expects a ComputeResource")

    payment = token_resource
    if isinstance(token_resource, dict):
        payment = TokenResource.model_validate(token_resource)
    if not isinstance(payment, TokenResource):
        raise ValueError("encode_compute_lease expects a TokenResource")

    if duration_days < 1:
        raise ValueError("duration_days must be >= 1")

    token_meta = payment.token
    human_total_price = Decimal(payment.amount) / Decimal(10**token_meta.decimals)
    human_price_per_day = human_total_price / Decimal(duration_days)

    lease_terms = {
        "gpu_model": compute.gpu_model.value if hasattr(compute.gpu_model, "value") else str(compute.gpu_model),
        "region": compute.region.value if hasattr(compute.region, "value") else str(compute.region),
        "quantity": compute.quantity,
        "sla": compute.sla,
        "duration_days": duration_days,
        "token_symbol": token_meta.symbol,
        "token_address": token_meta.contract_address,
        "price_per_day": float(human_price_per_day),
        "total_price": float(human_total_price),
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
    escrow_approval = await alkahest_client.erc20.approve(price_data, "escrow")
    logger.info(f"[ALKAHEST]: Escrow approved: f{escrow_approval}")
    return escrow_approval


async def buy_compute_with_erc20(
    compute_resource: ComputeResource | dict[str, Any],
    token_resource: TokenResource | dict[str, Any],
    *,
    oracle_address: str,
    client: AlkahestClient,
) -> Any:
    """Create an ERC20 escrow for a compute lease using Alkahest.

    This is from the point of view of someone with a TokenResource who
    wishes to trade it for a ComputeResource.

    Encodes the compute lease as a JSON demand payload, approves the ERC20 amount,
    and purchases via buy_with_erc20. Expiration is set to 0 (non-expiring) for now.
    """
    # POV: Compute-buyer
    if not client:
        raise RuntimeError("buy_with_erc20 requires an AlkahestClient instance")

    logger.info(f"[ALKAHEST]: Buying compute with Client {client}")

    arbiter_address = TRUSTED_ORACLE_ARBITER

    # 1) Encode lease terms into demand bytes
    demand_data = TrustedOracleArbiterDemandData(
        oracle_address,
        encode_compute_lease(
            compute_resource=compute_resource,
            token_resource=token_resource,
            duration_days=1,
        )
    )

    demand_bytes = demand_data.encode_self()

    # 2) Build price data from token resource
    if isinstance(token_resource, TokenResource):
        payment = token_resource
    else:
        payment = TokenResource.model_validate(token_resource)

    price_data = {"address": payment.token.contract_address, "value": payment.amount}

    # 3) Approve escrow spend
    await approve_token_escrow(payment, alkahest_client=client)

    # 4) Buy with ERC20, tying demand to arbiter data
    arbiter_data = {"arbiter": arbiter_address, "demand": demand_bytes}
    expiration = 0  # non-expiring escrow for now; may become time-limited later

    logger.info(
        "[ALKAHEST] buy_with_erc20 price_data=%s arbiter=%s expiration=%s",
        price_data,
        arbiter_address,
        expiration,
    )

    try:
        escrow_receipt =  await client.erc20.buy_with_erc20(price_data, arbiter_data, expiration)
        logger.info(f"[ALKAHEST]: {escrow_receipt}")
    except Exception as buy_with_erc20_err:
        logger.warning("[ALKAHEST] Failed to buy_with_erc20: %s", buy_with_erc20_err)

    return escrow_receipt

async def fulfill_compute_obligation(
    client: AlkahestClient | None,
    escrow_uid: str,
    oracle_address: str | None = None,
    ssh_public_key: str | None = None,
):
    """Provision compute and fulfill the obligation. Falls back to simulated flow if no client."""
    # POV: Compute-seller
    oracle_address = _resolve_oracle_address(oracle_address)
    connection_details = await mock_provision_machine(ssh_public_key)
    if not client or not oracle_address:
        # Demo fallback: skip on-chain, return simulated fulfillment uid
        fulfillment_uid = f"fulfill_{uuid.uuid4()}"
        logger.info("[ALKAHEST] (Simulated) Fulfilled compute obligation without on-chain client.")
        return {
            "status": "fulfilled",
            "message": "Compute obligation fulfilled (simulated)",
            "escrow_uid": escrow_uid,
            "fulfillment_uid": fulfillment_uid,
            "connection_details": connection_details,
            "ssh_public_key": ssh_public_key,
        }

    fulfillment_uid = await client.string_obligation.do_obligation(
        connection_details,
        escrow_uid
    )
    logger.info("[ALKAHEST] Fulfilled compute obligation with on-chain client; simulated machine provisioned.")
    request_arbitration_result = await client.oracle.request_arbitration(fulfillment_uid, oracle_address)
    logger.info(f"[ALKAHEST] Arbitration requested: {request_arbitration_result}")
    return {
        "status": "fulfilled",
        "message": "Compute obligation fulfilled",
        "escrow_uid": escrow_uid,
        "fulfillment_uid": fulfillment_uid,
        "connection_details": connection_details,
        "ssh_public_key": ssh_public_key,
    }

async def arbitrate_compute_fulfillment(
    client: AlkahestClient | None,
    fulfillment_uid: str,
    oracle_address: str | None,
    escrow_uid: str | None = None,
):
    # POV: Compute-buyer.
    oracle_address = _resolve_oracle_address(oracle_address)
    
    async def decision_function (attestation):
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

    options = ArbitrateOptions(skip_arbitrated=False, only_new=False)

    result = await client.oracle.listen_and_arbitrate_no_spawn(
        decision_function,
        callback,
        options,
        timeout_seconds=2.0
    )

    decisions = getattr(result, "decisions", None) or getattr(result, "decision", None) or []
    logger.info("[ALKAHEST] Arbitration decisions: %s", decisions)
    serialized_decisions = _serialize_decisions(decisions)

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
    # POV: Compute-seller.
    
    if client:
        result = await client.erc20.collect_escrow(escrow_uid, fulfillment_uid)
        logger.info(f"[ALKAHEST]: Escrow collected: {result}")
    else:
        logger.info("[ALKAHEST] (Simulated) Escrow collected")
    return
