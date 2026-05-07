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
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

from market_storefront.utils.stage_log import stage_event

from alkahest_py import AlkahestClient
import json

from market_storefront.models.domain_models import (
    Action,
    ActionType,
    ComputeResource,
    Listing,
    TokenResource,
)
from market_storefront.resources import parse_resource_from_dict

from market_storefront.utils.config import CONFIG, _resolve_chain_id
from service.clients.alkahest import encode_recipient_demand, get_recipient_arbiter
from service.clients.erc8004.blockchain import build_erc8004_canonical_id  # type: ignore[import-not-found]
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
    we_are_maker = _agent_urls_match(order_dict.get("seller"), BASE_URL_OVERRIDE)
    return (maker_offers_compute and not we_are_maker) or (not maker_offers_compute and we_are_maker)


def _resolve_counterparty_url_from_order(order_dict: dict[str, Any]) -> str | None:
    """Return the URL of the other party in the order (the one that is not us)."""
    maker = order_dict.get("seller")
    taker = order_dict.get("buyer")
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
                max_duration_seconds=parameters.get("max_duration_seconds"),
            )
            created_listing_id = order.get("listing_id") if isinstance(order, dict) else None

            # paused=True: write order locally with paused=1, skip registry publish.
            # Operator unblocks via POST /api/v1/listings/{listing_id}/resume which clears
            # the flag and calls publish_order_to_registry.
            create_paused = bool(parameters.get("paused", False))

            # Mirror the order in the local DB for the seller's own
            # bookkeeping (policies read from here, not from the registry).
            if isinstance(order, dict) and order.get("listing_id"):
                try:
                    now_iso = datetime.now().isoformat()
                    sqlite_client = get_sqlite_client()
                    await sqlite_client.upsert_listing(
                        listing_id=order.get("listing_id"),
                        status="open",
                        created_at=now_iso,
                        updated_at=now_iso,
                        offer_resource=order.get("offer_resource"),
                        demand_resource=order.get("demand_resource"),
                        fulfillment_resource=None,
                        max_duration_seconds=order.get("max_duration_seconds"),
                        seller=order.get("seller", BASE_URL_OVERRIDE),
                        buyer=order.get("buyer"),
                        matched_offer_id=parameters.get("matched_offer_id"),
                        seller_attestation=order.get("seller_attestation"),
                        buyer_attestation=order.get("buyer_attestation"),
                        oracle_address=order.get("oracle_address"),
                        escrow_uid=None,
                        paused=create_paused,
                    )
                except Exception as exc:
                    logger.warning("[LOCAL DB] Failed to upsert order %s: %s", created_listing_id, exc)

            if create_paused:
                logger.info(
                    "[MAKE_OFFER] Order %s created locally with paused=True; skipping registry publish",
                    created_listing_id,
                )
                publish_result = {"status": "paused", "order_id": created_listing_id}
            else:
                publish_result = await publish_order_to_registry(order)
            outcome["result"] = publish_result
            outcome["message"] = publish_result.get(
                "message",
                f"Order {created_listing_id or '?'} ({publish_result.get('status')})",
            )
            if created_listing_id:
                outcome["listing_id"] = created_listing_id

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
    order_id = parameters.get("listing_id")
    if not isinstance(order_id, str) or not order_id.strip():
        return {"status": "error", "message": "Missing listing_id for close_listing"}

    try:
        sqlite_client = get_sqlite_client()
        await sqlite_client.update_listing(
            listing_id=order_id,
            status="closed",
        )
    except Exception as exc:
        logger.warning("[LOCAL DB] Failed to update order %s as closed: %s", order_id, exc)

    if not CONFIG.enable_registry_discovery:
        return {
            "status": "skipped",
            "message": "Registry discovery is disabled; order not updated in registry",
            "listing_id": order_id,
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
                "listing_id": order_id,
                "registry_result": result,
            }
        return {
            "status": "error",
            "message": f"Failed to update order {order_id} in registry",
            "listing_id": order_id,
        }
    except Exception as exc:
        logger.warning("[REGISTRY] Failed to close order %s in registry: %s", order_id, exc)
        return {
            "status": "error",
            "message": f"Registry update failed for order {order_id}: {exc}",
            "listing_id": order_id,
        }


async def _do_provision(
    ssh_public_key: str,
    *,
    vm_host: str,
    vm_target: str,
    on_job_submitted: Callable[[str], Awaitable[None]] | None = None,
) -> dict:
    """Submit a create VM job to the provisioning service and return the result.

    ``on_job_submitted`` runs after the create_vm call returns the job_id but
    before we start polling — gives the caller a hook to record the job_id
    in the settlement_jobs row so the buyer's GET /settle/{uid}/status can
    surface it while the job is still queued/running.
    """
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
        if on_job_submitted is not None:
            try:
                await on_job_submitted(submit.job_id)
            except Exception as exc:
                logger.warning(
                    "[PROVISIONING] on_job_submitted callback failed for job %s: %s",
                    submit.job_id, exc,
                )
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

    Resolution order:
      1. CONFIG.onchain_agent_id — explicit pin in config.toml (highest priority)
      2. agent._AGENT_ID — set at startup by perform_registration when no pin is present
      3. None — falls back to CONFIG.agent_id in callers (last resort)

    Returns None if no agent ID is available.
    """
    raw = CONFIG.onchain_agent_id
    if not raw:
        # Fall back to the in-memory ID set by perform_registration at startup.
        # This covers the case where onchain_agent_id is not pinned in config.toml
        # but the agent successfully registered and stored the result in agent._AGENT_ID.
        try:
            from market_storefront.agent import _AGENT_ID as _runtime_id
            if _runtime_id is not None:
                raw = str(_runtime_id)
        except Exception:
            pass
    if not raw:
        return None
    if isinstance(raw, str) and raw.startswith("eip155:"):
        return raw
    try:
        chain_id = _resolve_chain_id()
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
        CONFIG.indexer_url or "http://localhost:8080",
    )


def _sender_id() -> str:
    """Return the canonical ERC-8004 agent ID for use as negotiation message sender.

    Falls back to the local AGENT_ID (e.g. 'agent_8000') when the on-chain
    identity is not configured.
    """
    return _canonical_agent_id() or AGENT_ID


def extract_compute_and_token_from_order_dict(order: dict) -> tuple[dict, dict]:
    """Given an order, take the demand and offer and extract which is compute and which is tokens.

    SQLite stores offer/demand_resource as JSON strings; downstream encoders
    (encode_compute_lease, ComputeResource.model_validate) expect dicts, so
    json-decode here rather than push that responsibility to every caller.
    """
    offer_resource = order.get("offer_resource", {})
    demand_resource = order.get("demand_resource", {})
    if isinstance(offer_resource, str):
        offer_resource = json.loads(offer_resource)
    if isinstance(demand_resource, str):
        demand_resource = json.loads(demand_resource)

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
    """Extract the initial negotiation floor from an order's token resource.

    Tristate semantics on ``demand.amount``:
      * ``> 0`` — public price; returned directly (current behavior).
      * ``0``  — free / public-test offering; returned as 0. The seller's
        strategy accepts any non-negative offer.
      * ``None`` — hidden reserve; falls back to
        ``[seller.pricing].default_min_price`` so the strategy has a real
        floor. If that's also unset, raises ``ValueError`` — the caller
        (sync_negotiation) translates that to a 409 refusal.
    """
    if isinstance(order, dict):
        order = Listing.model_validate(order)

    advertised: int | None
    if isinstance(order.offer_resource, TokenResource):
        advertised = order.offer_resource.amount
    elif isinstance(order.demand_resource, TokenResource):
        advertised = order.demand_resource.amount
    else:
        raise ValueError(f"Order has no token resource: {order.listing_id}")

    # 0 is a meaningful value (free); only None falls through to the fallback.
    if advertised is not None:
        return int(advertised)

    # Hidden reserve: fall back to the seller's config default.
    from market_storefront.utils.config import CONFIG
    fallback = CONFIG.default_min_price
    if fallback is not None and str(fallback).strip():
        try:
            parsed = int(fallback)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"[seller.pricing].default_min_price={fallback!r} is not a "
                f"valid integer; hidden-reserve listing {order.listing_id} has "
                "no usable floor."
            ) from exc
        if parsed > 0:
            return parsed

    raise ValueError(
        f"Listing {order.listing_id} has hidden reserve (demand.amount=None) "
        "and [seller.pricing].default_min_price is not configured. The seller "
        "has no floor to negotiate against; refusing the negotiation."
    )



def create_order(
    publish_to_registry: bool = True,
    offer_resource: ComputeResource | TokenResource = None,
    demand_resource: ComputeResource | TokenResource = None,
    max_duration_seconds: int | None = None,
) -> dict | None:
    """Create an order in the market.

    This only locally assembles the details of an order, without yet propagating it into the market,
    and so should be considered a helper function towards making the offer.

    Not to be confused with make_offer, which propagates the order to the market.

    Args:
        publish_to_registry: Whether to publish order to registry (default: True)
        offer_resource: Offer resource (required)
        demand_resource: Demand resource (required)
        max_duration_seconds: Optional ceiling on lease duration in seconds.
            None = unlimited. Buyer specifies the actual duration at
            negotiation init time.

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
        listing_id=str(uuid.uuid4()),
        seller=BASE_URL_OVERRIDE,
        buyer=None,
        offer_resource=offer_resource,
        demand_resource=demand_resource,
        max_duration_seconds=max_duration_seconds,
        seller_attestation=None,
        buyer_attestation=None,
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
        our_listing_id=order_id,
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
        order_id = order.listing_id
    else:
        order_dict = order
        order_id = order_dict.get("listing_id", "unknown")

    if order_dict.get("maker_attestation"):
        logger.warning(
            "[REGISTRY] Order %s has maker_attestation set but should be None for open orders",
            order_id,
        )

    if not CONFIG.enable_registry_discovery:
        return {"status": "disabled", "listing_id": order_id}

    try:
        agent_id_for_registry = _canonical_agent_id() or CONFIG.agent_id
        async with _make_registry_client() as registry_client:
            order_request = ListingRequest(
                listing_id=order_id,
                offer=order_dict.get("offer_resource", {}),
                demand=order_dict.get("demand_resource", {}),
                max_duration_seconds=order_dict.get("max_duration_seconds"),
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
            max_duration_seconds=order_dict.get("max_duration_seconds"),
        )
        return {"status": "published", "listing_id": order_id}
    except Exception as exc:
        logger.warning("[REGISTRY] Failed to publish order %s: %s", order_id, exc)
        return {"status": "error", "listing_id": order_id, "message": str(exc)}


def encode_compute_lease(
    compute_resource: ComputeResource | dict[str, Any],
    token_resource: TokenResource | dict[str, Any],
    duration_seconds: int,
) -> bytes:
    """Encode a compute-for-token trade as JSON bytes for use as Alkahest demand payload.

    Args:
        compute_resource: ComputeResource (or dict payload) describing the offered compute.
        token_resource: TokenResource (or dict) describing the payment token and amount (base units) for the per-hour rate.
        duration_seconds: Lease duration in seconds (must be > 0).
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

    if duration_seconds < 1:
        raise ValueError("duration_seconds must be >= 1")

    token_meta = hourly_rate.token
    # Total payment = per-hour rate × seconds / 3600. Integer division keeps
    # the result in whole base units; fractional sub-units are not representable.
    total_price = hourly_rate.amount * duration_seconds // 3600
    total_payment_resource = TokenResource(token=token_meta, amount=total_price)

    # Human-readable prices
    human_total_payment = Decimal(total_payment_resource.amount) / Decimal(10**token_meta.decimals)
    human_price_per_hour = Decimal(hourly_rate.amount) / (10**token_meta.decimals)

    lease_terms = {
        "gpu_model": compute.gpu_model.value if hasattr(compute.gpu_model, "value") else str(compute.gpu_model),
        "region": compute.region.value if hasattr(compute.region, "value") else str(compute.region),
        "gpu_count": compute.gpu_count,
        "sla": compute.sla,
        "duration_seconds": duration_seconds,
        "token_symbol": token_meta.symbol,
        "token_address": token_meta.contract_address,
        "price_per_hour_decimal": float(human_price_per_hour),
        "total_price_decimal": float(human_total_payment),
        "total_price_int": total_payment_resource.amount,
    }

    logger.info("[ALKAHEST] Encoding compute lease terms: %s", lease_terms)

    return json.dumps(lease_terms).encode("utf-8")


async def _build_provisioning_job_spec(
    *,
    order_dict: dict | None,
    ssh_public_key: str,
    duration_seconds: int,
    sqlite_client: Any | None = None,
) -> dict | None:
    """Pure compute: select a host from inventory and build the provisioning job spec.

    Performs a **read-only** inventory lookup (``select_available_compute_vm``
    — no state change, no reservation). Use this for dry-run / evaluate paths.
    The real flow (``fulfill_compute_obligation``) continues to call
    ``reserve_available_compute_vm`` directly so it can atomically reserve.

    Returns a dict with keys:
        resource_id, vm_host, vm_target, required_attributes, ssh_public_key,
        duration_seconds

    Returns None if no resource matches required_attributes.

    This function is the ``doWork`` seam for the settlement pipeline:
        POST /api/v1/settle/{uid}
          ├── getRecordFromChain  (verify_escrow_for_settlement)
          ├── doWork              (_build_provisioning_job_spec)  ← this function
          └── submitJob           (_do_provision → asyncio.create_task)
    """
    required_attributes: dict[str, Any] = {}
    if order_dict:
        compute_resource, _token = extract_compute_and_token_from_order_dict(order_dict)
        if isinstance(compute_resource, dict):
            for key in ("region", "gpu_model"):
                if compute_resource.get(key) is not None:
                    required_attributes[key] = compute_resource[key]

    db = sqlite_client or get_sqlite_client()
    selected = await db.select_available_compute_vm(
        required_attributes=required_attributes or None,
    )
    if not selected:
        return None

    vm_target = f"tenant-{uuid.uuid4().hex[:4]}"
    return {
        "resource_id": str(selected["resource_id"]),
        "vm_host": selected["vm_host"],
        "vm_target": vm_target,
        "required_attributes": required_attributes,
        "ssh_public_key": ssh_public_key,
        "duration_seconds": duration_seconds,
    }


async def fulfill_compute_obligation(
    client: AlkahestClient | None,
    escrow_uid: str,
    ssh_public_key: str,
    oracle_address: str | None = None,
    order: str | dict | None = None,
    duration_seconds: int = 3600,
    listing_id: str | None = None,
    seller_order_id: str | None = None,
):
    """Provision compute and fulfill the obligation. Falls back to simulated flow if no client.

    ``duration_seconds`` is the buyer's negotiated lease window — passed
    through from `start_settlement_job`, which reads it off the
    negotiation thread's `agreed_duration_seconds`. Falls back to 1h
    only if the caller didn't provide one (recovery / legacy paths).

    When the maker fulfills, this sets maker_attestation in the registry.
    """
    fulfillment_uid = None
    maker_attestation = None
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
        # Storefront listings are keyed by listing_id; legacy callers may
        # still pass order_id. Prefer listing_id since that's what the rest
        # of the system (sqlite, stage events, registry) keys off of.
        order_id = order_dict.get("listing_id") or order_dict.get("order_id")
        compute_resource, token_resource = extract_compute_and_token_from_order_dict(order_dict)
        if isinstance(compute_resource, dict):
            for key in ("region", "gpu_model"):
                if compute_resource.get(key) is not None:
                    required_attributes[key] = compute_resource.get(key)
        order_bytes = encode_compute_lease(
            compute_resource=compute_resource,
            token_resource=token_resource,
            duration_seconds=duration_seconds,
        )
        if order_id:
            try:
                sqlite_client = get_sqlite_client()
                await sqlite_client.update_listing(
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
            listing_id=order_id,
            escrow_uid=escrow_uid,
            resource_id=reserved_resource_id,
            vm_host=reserved_vm_host,
            required_attributes=required_attributes,
        )

        async def _record_job_id(job_id: str) -> None:
            await get_sqlite_client().update_settlement_job(
                escrow_uid=escrow_uid,
                provisioning_job_id=job_id,
            )
            # Emitted after the DB write so a consumer waking on this event
            # is guaranteed to see provisioning_job_id populated.
            stage_event(
                "provision", "job_submitted",
                listing_id=order_id,
                escrow_uid=escrow_uid,
                resource_id=reserved_resource_id,
                vm_host=reserved_vm_host,
                provisioning_job_id=job_id,
            )

        provision_result = await _do_provision(
            ssh_public_key,
            vm_host=reserved_vm_host,
            vm_target=vm_target,
            on_job_submitted=_record_job_id,
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

    lease_end_utc = (datetime.now(timezone.utc) + timedelta(seconds=duration_seconds)).strftime("%Y-%m-%d %H:%M")

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
            await sqlite_client.update_listing(
                listing_id=order_id,
                seller_attestation=maker_attestation,
                fulfillment_resource=connection_details,
                escrow_uid=escrow_uid,
            )
        except Exception as exc:
            logger.warning("[LOCAL DB] Failed to update fulfillment for order %s: %s", order_id, exc)

    tenant_auth = (authentication or {}).get("tenant", {}) or {}
    stage_event("provision", "fulfilled",
        listing_id=order_id,
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
