"""Action execution.

TODO(refactor): This module still contains compute-domain action logic.
Move domain-specific execution into the domain package as refactor continues.
"""

from __future__ import annotations

import asyncio
import functools
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import logging
from typing import Any
from urllib.parse import urlparse

from market_storefront.utils.stage_log import stage_event

from alkahest_py import AlkahestClient
import json

from market_storefront.schema.pydantic_models import (
    Action,
    ActionType,
    ComputeResource,
    Listing,
    TokenResource,
)
from market_storefront.resources import parse_resource_from_dict

from market_storefront.utils.config import CONFIG
from service.clients.alkahest import encode_recipient_demand, get_recipient_arbiter
from market_storefront.utils.sqlite_client import get_sqlite_client
from client.provisioning_client import ProvisioningClient, ProvisioningError
from registry_client import RegistryClient, RegistryClientError, ListingRequest, UpdateListingRequest
from market_storefront.utils.order_matching import match_orders
from market_policy.negotiation_thread import (
    get_thread_store,
    NegotiationThreadTransaction,
)
from .validation import determine_strategy_from_order

BASE_URL_OVERRIDE = CONFIG.base_url_override
PORT = CONFIG.port
AGENT_ID = CONFIG.agent_id
SSH_PUBLIC_KEY = CONFIG.ssh_public_key

logger = logging.getLogger(__name__)

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


async def fetch_agent_wallet_address(agent_url: str, *, timeout: float = 5.0) -> str | None:
    """Fetch an agent's on-chain wallet via its /.well-known/agent-wallet.json.

    Returns the 0x-prefixed wallet or None on any failure. This is what the
    buyer calls before escrow creation to name the seller as the demanded
    recipient under RecipientArbiter.
    """
    import httpx

    url = agent_url.rstrip("/") + "/.well-known/agent-wallet.json"
    try:
        async with httpx.AsyncClient(timeout=timeout) as http:
            resp = await http.get(url)
            if resp.status_code != 200:
                logger.warning(
                    "[WALLET_LOOKUP] %s returned HTTP %d", url, resp.status_code
                )
                return None
            body = resp.json()
    except Exception as exc:
        logger.warning("[WALLET_LOOKUP] Failed to fetch %s: %s", url, exc)
        return None

    wallet = body.get("agent_wallet_address") if isinstance(body, dict) else None
    if not wallet or not isinstance(wallet, str):
        return None
    wallet = wallet.strip()
    if not (wallet.startswith("0x") and len(wallet) == 42):
        logger.warning(
            "[WALLET_LOOKUP] %s returned malformed wallet %r", url, wallet
        )
        return None
    return wallet


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
    ctx: Any | None = None,
) -> dict[str, Any]:
    """Execute a policy action and return the outcome.

    The surviving action types after the buyer-as-client / seller-as-
    request-response refactor are all local or registry-only:

        MAKE_OFFER        — create a local order + publish it to the
                            registry. No fan-out to counterparties;
                            buyers initiate negotiation themselves.
        CLOSE_ORDER       — mark an order closed locally + in the
                            registry.
        RESOLVE_INTERNALLY — agent rebalances its own pool (noop-ish).
        REJECT_OFFER      — no-op stub.
        NOOP              — explicit no-op.

    Negotiation, settlement, fulfillment, and claim used to be policy-
    dispatched actions too; they're now either closed functions called
    directly from HTTP handlers (/negotiate/*, /settle/*) or standalone
    recovery endpoints (/orders/claim, /orders/reclaim, /orders/refund,
    /orders/arbitrate).
    """
    action_type = action.action_type
    action_type_str = action_type if isinstance(action_type, str) else action_type.value
    parameters = action.parameters or {}

    logger.info(f"[ACTION] Executing {action_type_str} with params: {parameters}")

    outcome: dict[str, Any] = {
        "action_type": action_type_str,
        "status": "executed",
        "parameters": parameters,
    }

    match action_type_str:
        case ActionType.MAKE_OFFER.value:
            offer_param = parameters.get("offer")
            demand_param = parameters.get("demand")
            if offer_param is None or demand_param is None:
                raise ValueError("MAKE_OFFER requires explicit 'offer' and 'demand' parameters")

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

            order = create_order(
                offer_resource=offer_resource,
                demand_resource=demand_resource,
                duration_hours=parameters.get("duration_hours", 1),
            )
            created_order_id = order.get("order_id") if isinstance(order, dict) else None

            # Mirror the order in the local DB for the seller's own
            # bookkeeping (policies read from here, not from the registry).
            if isinstance(order, dict) and order.get("order_id"):
                try:
                    now_iso = datetime.now().isoformat()
                    sqlite_client = get_sqlite_client()
                    await sqlite_client.upsert_order(
                        listing_id=order.get("order_id"),
                        status="open",
                        created_at=now_iso,
                        updated_at=now_iso,
                        offer_resource=order.get("offer_resource"),
                        demand_resource=order.get("demand_resource"),
                        fulfillment_resource=None,
                        duration_hours=int(order.get("duration_hours", 1)),
                        seller=order.get("order_maker", BASE_URL_OVERRIDE),
                        buyer=order.get("order_taker"),
                        matched_offer_id=parameters.get("matched_offer_id"),
                        seller_attestation=order.get("maker_attestation"),
                        buyer_attestation=order.get("taker_attestation"),
                        oracle_address=order.get("oracle_address"),
                        escrow_uid=None,
                    )
                except Exception as exc:
                    logger.warning("[LOCAL DB] Failed to upsert order %s: %s", created_order_id, exc)

            publish_result = await publish_order_to_registry(order)
            outcome["result"] = publish_result
            outcome["message"] = publish_result.get(
                "message",
                f"Order {created_order_id or '?'} ({publish_result.get('status')})",
            )
            if created_order_id:
                outcome["order_id"] = created_order_id

        case ActionType.CLOSE_ORDER.value:
            result = await close_order(parameters)
            outcome["result"] = result
            outcome["message"] = result.get("message", "Order closed")

        case ActionType.RESOLVE_INTERNALLY.value:
            rebalance_internal_resources()
            outcome["result"] = {"rebalanced": True}
            outcome["message"] = "Resources rebalanced internally"

        case ActionType.REJECT_OFFER.value:
            reject_offer()
            outcome["result"] = {"rejected": True}
            outcome["message"] = "Offer rejected"

        case ActionType.NOOP.value:
            outcome["result"] = None
            outcome["message"] = "No operation"

        case _:
            logger.warning("[ACTION] Unhandled action type %s", action_type_str)
            outcome["result"] = None
            outcome["status"] = "unhandled"
            outcome["message"] = f"Action type not supported: {action_type_str}"

    return outcome



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
            listing_id=order_id,
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
        async with _make_registry_client() as registry_client:
            result = await registry_client.update_listing(
                order_id,
                UpdateListingRequest(
                    updates={"status": "closed"},
                    private_key=CONFIG.agent_priv_key,
                    agent_id=_canonical_agent_id(),
                ),
            )
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


async def _do_provision(ssh_public_key: str, *, vm_host: str, vm_target: str) -> dict:
    """Submit a create VM job to the provisioning service and return the result."""
    from models.vm_request_model import CreateVmRequest
    canonical_id = _canonical_agent_id()
    client = ProvisioningClient(
        CONFIG.provisioning_service_url,
        agent_id=canonical_id,
        timeout=float(CONFIG.provisioning_timeout),
    )
    async with client:
        params: dict = {"vm_target": vm_target, "ssh_pubkey": ssh_public_key}
        if CONFIG.frp_server_addr:
            params["frp_server_addr"] = CONFIG.frp_server_addr
        if CONFIG.frp_domain:
            params["frp_domain"] = CONFIG.frp_domain
        if CONFIG.frp_dashboard_password:
            params["frp_dashboard_password"] = CONFIG.frp_dashboard_password
        submit = await client.create_vm(vm_host, CreateVmRequest(**params))
        job = await client.poll_until_complete(
            submit.job_id,
            timeout=float(CONFIG.provisioning_timeout),
            poll_interval=float(CONFIG.provisioning_poll_interval),
        )
        result = job.result or {}
        if canonical_id:
            try:
                creds_resp = await client.get_job_credentials(submit.job_id)
                auth: dict = {}
                for c in creds_resp.credentials:
                    if c.role:
                        auth[c.role] = {
                            "password": c.password,
                            "ssh_commands": c.ssh_commands,
                            "ssh_key_path_host": c.ssh_key_path_host,
                            "key_type": c.key_type,
                        }
                if auth:
                    result["authentication"] = auth
            except Exception as exc:
                logger.warning(
                    "[PROVISIONING] Failed to fetch credentials for job %s: %s",
                    submit.job_id, exc,
                )
    return result


async def _do_shutdown(lease_end_utc: str, *, vm_host: str, vm_target: str) -> dict:
    """Schedule VM expiry via the provisioning service."""
    from models.vm_request_model import ScheduleVmExpiryRequest
    canonical_id = _canonical_agent_id()
    client = ProvisioningClient(
        CONFIG.provisioning_service_url,
        agent_id=canonical_id,
        timeout=float(CONFIG.provisioning_timeout),
    )
    async with client:
        submit = await client.schedule_expiry(
            vm_host, vm_target, ScheduleVmExpiryRequest(vm_expiry_at=lease_end_utc)
        )
        job = await client.poll_until_complete(
            submit.job_id,
            timeout=float(CONFIG.provisioning_timeout),
            poll_interval=float(CONFIG.provisioning_poll_interval),
        )
    return job.result or {}


@functools.lru_cache(maxsize=1)
def _canonical_agent_id() -> str | None:
    """Return the full ERC-8004 canonical ID for this agent (eip155:<chain>:0x<contract>:<id>).

    The provisioning service's X-Agent-ID header requires the canonical form, not the raw
    numeric ONCHAIN_AGENT_ID.  If the ID is already canonical (starts with 'eip155:') it is
    returned as-is; otherwise it is built from IDENTITY_REGISTRY_ADDRESS + ONCHAIN_AGENT_ID.
    Returns None if the required config values are missing.
    """
    raw = CONFIG.onchain_agent_id
    if not raw:
        return None
    if isinstance(raw, str) and raw.startswith("eip155:"):
        return raw
    try:
        from service.clients.erc8004.blockchain import build_erc8004_canonical_id
        chain_id = 31337  # default for Anvil/local
        if CONFIG.chain_rpc_url:
            try:
                from web3 import Web3
                from web3.providers import HTTPProvider
                from service.clients.erc8004.blockchain import rpc_url_for_http_provider
                w3 = Web3(HTTPProvider(rpc_url_for_http_provider(CONFIG.chain_rpc_url), request_kwargs={"timeout": 5}))
                chain_id = w3.eth.chain_id
            except Exception:
                pass
        return build_erc8004_canonical_id(
            chain_id=chain_id,
            identity_registry=CONFIG.identity_registry_address,
            agent_id=int(raw),
        )
    except Exception as exc:
        logger.warning("[PROVISIONING] Could not build canonical agent ID from %r: %s", raw, exc)
        return str(raw)


def _make_registry_client() -> RegistryClient:
    """Construct a RegistryClient from environment/CONFIG.

    Each call returns a new client instance — callers should use it as a
    context manager or call close() when done.  Singletons are avoided here
    because the private_key and agent_id config values can theoretically
    change between calls during testing.
    """
    return RegistryClient(
        CONFIG.registry_url or CONFIG.indexer_url or "http://localhost:8080",
        private_key=CONFIG.agent_priv_key,
    )


def _sender_id() -> str:
    """Return the canonical ERC-8004 agent ID for use as negotiation message sender.

    Falls back to the local AGENT_ID (e.g. 'agent_8000') when the on-chain
    identity is not configured.
    """
    return _canonical_agent_id() or AGENT_ID


def extract_compute_and_token_from_order_dict(order: dict) -> tuple[dict, dict]:
    """Given an order, take the demand and offer and extract which is compute and which is tokens."""
    offer_resource = order.get("offer_resource", {})
    demand_resource = order.get("demand_resource", {})

    offer_is_compute = _resource_is_compute(offer_resource)
    demand_is_compute = _resource_is_compute(demand_resource)

    if offer_is_compute:
        compute_resource = offer_resource
        token_resource = demand_resource
    elif demand_is_compute:
        compute_resource = demand_resource
        token_resource = offer_resource
    else:
        raise ValueError("Neither offer nor demand resource is compute in the provided order.")

    return compute_resource, token_resource


def _extract_initial_price_from_order(order: Listing | dict) -> int:
    """Extract the initial price from an order's token resource.

    The token amount represents:
    - For surplus (offering compute): The floor price (minimum willing to accept)
    - For deficit (demanding compute): The ceiling price (maximum willing to pay)
    """
    if isinstance(order, dict):
        order = Listing.model_validate(order)

    if isinstance(order.offer_resource, TokenResource):
        return order.offer_resource.amount
    if isinstance(order.demand_resource, TokenResource):
        return order.demand_resource.amount

    raise ValueError(f"Order has no token resource: {order.order_id}")



def create_order(
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
        publish_to_registry: Whether to publish order to registry (default: True)
        offer_resource: Offer resource (required)
        demand_resource: Demand resource (required)
        duration_hours: Duration of the order in hours (default: 1); 1 if seller (rate), else total if buyer

    Returns:
        The created order as a dictionary if the order was successfully created, or None otherwise.
        This creates a UUID identifying the new order, and the details should match the provided arguments.
    """
    logger.info("[TOOL] Creating order.")

    if not offer_resource:
        logger.error("[TOOL] offer_resource is required")
        return None
    if not demand_resource:
        logger.error("[TOOL] demand_resource is required")
        return None
    
    # The token-offering side is always the oracle/buyer.
    offering_tokens = isinstance(offer_resource, TokenResource) or (
        isinstance(offer_resource, dict) and "token" in offer_resource
    )
    oracle_address = CONFIG.agent_wallet_address if offering_tokens else None

    order = Listing(
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


async def discover(
    *,
    order_id: str,
    include_active_negotiations: bool = False,
) -> list[dict[str, Any]]:
    """Query the registry for orders matching `order_id` and return them.

    Pure query — no thread writes, no outbound sends. Intended as the
    first closed-function step of a sequential buy/sell flow.

    Returns a list of match records:
        {"their_listing_id": str,
         "their_agent_url": str,
         "their_order": dict}

    Filters applied:
      - only `status='open'` rows from the registry
      - bidirectional resource compatibility (via registry_client.match_orders)
      - our own orders removed
      - orders already in active negotiations with us removed, unless
        `include_active_negotiations=True` (useful for debugging / forced
        re-propose flows)

    Callers that also want to *initiate* negotiations against the result
    should pair this with `start_negotiations(order_id, matches)`.
    """
    if not CONFIG.enable_registry_discovery:
        raise RuntimeError("Registry discovery is disabled (CONFIG.enable_registry_discovery=False)")

    async with _make_registry_client() as registry_client:
        try:
            our_order = await registry_client.get_listing(order_id)
        except RegistryClientError as exc:
            if exc.status_code == 404:
                raise ValueError(f"Order {order_id} not found in registry") from exc
            raise

        candidates_resp = await registry_client.list_listings(
            status="open",
            limit=CONFIG.max_discovery_agents,
        )
        matching_orders = match_orders(our_order, candidates_resp.listings, bidirectional=True)
    # Drop our own orders.
    matching_orders = [
        m for m in matching_orders
        if str(m.id) != order_id
        and not _agent_urls_match(m.maker_agent_id, BASE_URL_OVERRIDE)
    ]

    if not include_active_negotiations:
        async with NegotiationThreadTransaction("DISCOVER") as txn:
            active_order_ids = await txn.filter_active(order_id)
            if active_order_ids:
                matching_orders = [
                    m for m in matching_orders
                    if str(m.id) not in active_order_ids
                ]
                logger.info(
                    "[DISCOVER] Filtered out %d orders already in active negotiations",
                    len(active_order_ids),
                )

    matches: list[dict[str, Any]] = []
    for m in matching_orders[:CONFIG.max_discovery_agents]:
        their_listing_id = str(m.id)
        their_agent_url = m.maker_agent_id
        if not their_listing_id or not their_agent_url:
            continue
        matches.append({
            "their_listing_id": their_listing_id,
            "their_agent_url": their_agent_url,
            "their_order": m,
        })

    stage_event(
        "discovery", "matches_found",
        our_order_id=order_id,
        match_count=len(matches),
        matched_order_ids=[m["their_listing_id"] for m in matches],
        counterparty_urls=[m["their_agent_url"] for m in matches],
    )
    return matches


async def publish_order_to_registry(order: Listing | dict) -> dict[str, Any]:
    """Publish a new order to the registry so discoverers can find it.

    Called by the MAKE_OFFER action path when /orders/create runs. No
    fan-out to counterparties here — the buyer's orchestrator queries
    the registry directly and initiates negotiations from there.

    Returns a small status dict. Never raises for missing config or
    registry errors; logs them. Callers interpret `status` to decide
    whether to bubble up.
    """
    if isinstance(order, Listing):
        order_dict = order.model_dump(mode="json")
        order_id = order.order_id
    else:
        order_dict = order
        order_id = order_dict.get("order_id", "unknown")

    if order_dict.get("maker_attestation"):
        logger.warning(
            "[REGISTRY] Order %s has maker_attestation set but should be None for open orders",
            order_id,
        )

    if not CONFIG.enable_registry_discovery:
        return {"status": "disabled", "order_id": order_id}

    try:
        agent_id_for_registry = _canonical_agent_id() or CONFIG.agent_id
        async with _make_registry_client() as registry_client:
            order_request = ListingRequest(
                listing_id=order_id,
                offer=order_dict.get("offer_resource", {}),
                demand=order_dict.get("demand_resource", {}),
                duration_hours=float(order_dict.get("duration_hours", 1.0)),
            )
            await registry_client.publish_listing(
                agent_id_for_registry, order_request, private_key=CONFIG.agent_priv_key
            )
        logger.info("[REGISTRY] Published order %s", order_id)
        stage_event(
            "discovery", "order_published",
            order_id=order_id,
            agent_url=BASE_URL_OVERRIDE,
            offer=order_dict.get("offer_resource"),
            demand=order_dict.get("demand_resource"),
            duration_hours=order_dict.get("duration_hours"),
        )
        return {"status": "published", "order_id": order_id}
    except Exception as exc:
        logger.warning("[REGISTRY] Failed to publish order %s: %s", order_id, exc)
        return {"status": "error", "order_id": order_id, "message": str(exc)}


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


async def fulfill_compute_obligation(
    client: AlkahestClient | None,
    escrow_uid: str,
    ssh_public_key: str,
    oracle_address: str | None = None,
    order: str | dict | None = None,
    seller_order_id: str | None = None,
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
                    listing_id=order_id,
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
        stage_event("provision", "resource_reserved",
            escrow_uid=escrow_uid,
            resource_id=reserved_resource_id,
            vm_host=reserved_vm_host,
            required_attributes=required_attributes,
        )

        provision_result = await _do_provision(
            ssh_public_key,
            vm_host=reserved_vm_host,
            vm_target=vm_target,
        )
        # Split credentials out before serialising — passwords must never touch on-chain data.
        authentication: dict | None = None
        if isinstance(provision_result, dict):
            authentication = provision_result.pop("authentication", None)
            connection_details = json.dumps(provision_result)
        else:
            connection_details = provision_result
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
        stage_event("provision", "failed",
            escrow_uid=escrow_uid,
            resource_id=reserved_resource_id,
            error=str(error),
        )
        return {
            "status": "error",
            "message": f"Provisioning failed: {error}",
            "escrow_uid": escrow_uid,
            "connection_details": None,
            "ssh_public_key": ssh_public_key,
        }

    lease_end_utc = (datetime.now(timezone.utc) + timedelta(hours=duration_hours)).strftime("%Y-%m-%d %H:%M")

    if reserved_resource_id:
        try:
            await get_sqlite_client().apply_resource_set_transition(
                resource_id=reserved_resource_id,
                event_type="lease_started_after_provisioning",
                idempotency_key=f"lease:{escrow_uid}:{reserved_resource_id}",
                set_state="leased",
                set_attribute={"$.lease_end_utc": lease_end_utc},
            )
        except Exception as lease_err:
            logger.warning(
                "[LOCAL DB] Failed to mark resource %s as leased after provisioning: %s",
                reserved_resource_id,
                lease_err,
            )

    # Persist seller-side credentials (root + tenant) — off-chain only.
    # Use seller_order_id if provided (the seller's own order); fall back to order_id
    # (the buyer's order from the offer dict) only when seller_order_id is absent.
    cred_order_id = seller_order_id or order_id
    if authentication and cred_order_id:
        try:
            _cred_client = get_sqlite_client()
            root_data = authentication.get("root", {}) or {}
            tenant_data = authentication.get("tenant", {}) or {}
            if root_data:
                await _cred_client.store_credential(
                    listing_id=cred_order_id,
                    role="root",
                    granted_to="self",
                    password=root_data.get("password"),
                    ssh_commands=json.dumps(root_data.get("ssh_commands")) if root_data.get("ssh_commands") else None,
                    ssh_key_path_host=root_data.get("ssh_key_path_host"),
                )
            if tenant_data:
                await _cred_client.store_credential(
                    listing_id=cred_order_id,
                    role="tenant",
                    granted_to="self",
                    password=tenant_data.get("password"),
                    ssh_commands=json.dumps(tenant_data.get("ssh_commands")) if tenant_data.get("ssh_commands") else None,
                    key_type=tenant_data.get("key_type"),
                )
        except Exception as cred_err:
            logger.warning("[LOCAL DB] Failed to store credentials for order %s: %s", cred_order_id, cred_err)
    await _do_shutdown(lease_end_utc, vm_host=reserved_vm_host, vm_target=vm_target)

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
            async with _make_registry_client() as registry_client:
                result = await registry_client.update_listing(
                    order_id,
                    UpdateListingRequest(
                        updates={"seller_attestation": maker_attestation},
                        private_key=CONFIG.agent_priv_key,
                        agent_id=_canonical_agent_id(),
                    ),
                )
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
                listing_id=order_id,
                seller_attestation=maker_attestation,
                fulfillment_resource=connection_details,
                escrow_uid=escrow_uid,
            )
        except Exception as exc:
            logger.warning("[LOCAL DB] Failed to update fulfillment for order %s: %s", order_id, exc)

    tenant_auth = (authentication or {}).get("tenant", {}) or {}
    stage_event("provision", "fulfilled",
        escrow_uid=escrow_uid,
        fulfillment_uid=fulfillment_uid,
        maker_attestation=maker_attestation,
        resource_id=reserved_resource_id,
        vm_host=reserved_vm_host,
        lease_end_utc=lease_end_utc,
        seller_order_id=seller_order_id,
        order_id=order_id,
    )
    return {
        "status": "fulfilled",
        "message": "Compute obligation fulfilled",
        "escrow_uid": escrow_uid,
        "fulfillment_uid": fulfillment_uid,
        "connection_details": connection_details,
        "ssh_public_key": ssh_public_key,
        "fulfilling_party_url": BASE_URL_OVERRIDE,
        "tenant_credentials": {
            "password": tenant_auth.get("password"),
            "key_type": tenant_auth.get("key_type"),
        },
    }