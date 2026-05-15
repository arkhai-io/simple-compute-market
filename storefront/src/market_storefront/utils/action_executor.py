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

import httpx

from market_storefront.utils.config import CONFIG, _resolve_chain_id
from service.clients.alkahest import encode_recipient_demand, get_recipient_arbiter
from service.clients.erc8004.blockchain import build_erc8004_canonical_id  # type: ignore[import-not-found]
from market_storefront.utils.sqlite_client import (
    get_sqlite_client,
    synthesize_accepted_escrows_from_demand,
)
from client.provisioning_client import ProvisioningClient, ProvisioningError
from models.vm_request_model import CreateVmRequest, ScheduleVmExpiryRequest
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


async def fetch_agent_wallet_address(agent_url: str, *, timeout: float = 5.0) -> str | None:
    """Fetch an agent's on-chain wallet via its /.well-known/agent-wallet.json.

    Returns the 0x-prefixed wallet or None on any failure. This is what the
    buyer calls before escrow creation to name the seller as the demanded
    recipient under RecipientArbiter.
    """
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
            accepted_escrows_param = parameters.get("accepted_escrows")
            if offer_param is None:
                raise ValueError("MAKE_OFFER requires an 'offer' parameter")
            if accepted_escrows_param is None and demand_param is None:
                raise ValueError(
                    "MAKE_OFFER requires either 'accepted_escrows' or "
                    "'demand' (legacy single-token shape, synthesized into "
                    "accepted_escrows at this boundary)"
                )

            try:
                offer_resource = parse_resource_from_dict(offer_param)
            except Exception as exc:
                raise ValueError(f"Invalid offer resource: {exc}") from exc

            if not isinstance(offer_resource, ComputeResource):
                # Only seller-side compute listings are supported. The
                # token-offer / compute-demand "buyer-as-maker" path was
                # deleted with the demand_resource cutover — buyers
                # propose escrows against seller listings, they don't
                # publish their own listings.
                raise ValueError(
                    "MAKE_OFFER offer must be a compute resource; "
                    f"got {type(offer_resource).__name__}"
                )

            if accepted_escrows_param is None:
                accepted_escrows_param = synthesize_accepted_escrows_from_demand(
                    demand_param
                )

            order = create_order(
                offer_resource=offer_resource,
                accepted_escrows=accepted_escrows_param,
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
                        accepted_escrows=order.get("accepted_escrows"),
                        fulfillment_resource=None,
                        max_duration_seconds=order.get("max_duration_seconds"),
                        seller=order.get("seller", BASE_URL_OVERRIDE),
                        oracle_address=order.get("oracle_address"),
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
            target_urls = await _registries_to_target(order_id, registry_client.urls)
            update_request = UpdateListingRequest(
                updates={"status": "closed"},
                private_key=CONFIG.agent_priv_key,
                agent_id=_canonical_agent_id(),
            )
            payloads = {url: update_request for url in target_urls}
            results = await registry_client.update_listing_per_registry(
                order_id, payloads,
            )
        await _record_publications(order_id, results)
        first_ok = next(
            (r["response"] for r in results if r["success"] and r["response"]),
            None,
        )
        if first_ok:
            return {
                "status": "closed",
                "message": f"Order {order_id} marked closed in registry",
                "listing_id": order_id,
                "registry_result": first_ok,
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


def _make_registry_client() -> "MultiRegistryClient":
    """Construct a multi-registry client wrapping every configured URL.

    Each call returns a fresh wrapper — callers use it as an async
    context manager (``async with _make_registry_client() as rc:``).
    The wrapper exposes the same surface as ``RegistryClient`` so call
    sites (and the test mocks that patch this function) don't change
    shape; reads fan in across every URL, writes fan out best-effort.
    """
    from .multi_registry_client import MultiRegistryClient
    urls = list(CONFIG.indexer_urls) if CONFIG.indexer_urls else ["http://localhost:8080"]
    return MultiRegistryClient(
        urls,
        timeout=CONFIG.discovery_timeout,
        auth=CONFIG.indexer_auth,
    )


def _sender_id() -> str:
    """Return the canonical ERC-8004 agent ID for use as negotiation message sender.

    Falls back to the local AGENT_ID (e.g. 'agent_8000') when the on-chain
    identity is not configured.
    """
    return _canonical_agent_id() or AGENT_ID


def extract_compute_from_order(order: dict) -> dict:
    """Return the compute dict from an order's ``offer_resource``.

    Listings only carry compute as the offered resource since the
    demand_resource cutover; the buyer-side token info comes from
    ``accepted_escrows[0]`` (see ``_listing_payment_token`` in
    ``sync_negotiation``).
    """
    offer_resource = order.get("offer_resource", {})
    if isinstance(offer_resource, str):
        offer_resource = json.loads(offer_resource)
    if not _resource_is_compute(offer_resource):
        raise ValueError(
            f"Order offer_resource is not compute: "
            f"listing_id={order.get('listing_id')}"
        )
    return offer_resource


def _extract_initial_price_from_order(order: Listing | dict) -> int:
    """Extract the initial negotiation floor from a listing's
    ``accepted_escrows[0].price_per_hour``.

    Tristate semantics on the advertised price:
      * ``> 0`` — public price; returned directly.
      * ``0``  — free / public-test offering; returned as 0. The seller's
        strategy accepts any non-negative offer.
      * ``None`` or missing entry — hidden reserve; falls back to
        ``[seller.pricing].default_min_price`` so the strategy has a real
        floor. If that's also unset, raises ``ValueError`` — the caller
        (sync_negotiation) translates that to a 409 refusal.
    """
    if isinstance(order, dict):
        order = Listing.model_validate(order)

    advertised: int | None = None
    if order.accepted_escrows:
        first = order.accepted_escrows[0]
        advertised = first.price_per_hour

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
        f"Listing {order.listing_id} has hidden reserve "
        "(accepted_escrows[0].price_per_hour=None) and "
        "[seller.pricing].default_min_price is not configured. The seller "
        "has no floor to negotiate against; refusing the negotiation."
    )



def create_order(
    publish_to_registry: bool = True,
    offer_resource: ComputeResource | TokenResource = None,
    accepted_escrows: list[dict[str, Any]] | None = None,
    max_duration_seconds: int | None = None,
) -> dict | None:
    """Create an order in the market.

    This only locally assembles the details of an order, without yet propagating it into the market,
    and so should be considered a helper function towards making the offer.

    Not to be confused with make_offer, which propagates the order to the market.

    Args:
        publish_to_registry: Whether to publish order to registry (default: True)
        offer_resource: Offer resource (required)
        accepted_escrows: List of accepted escrow shapes the seller will
            honour for this listing. May be ``None`` when the chain
            config can't resolve an escrow address (synthesis falls
            through); the listing still gets created but has no
            pricing/escrow advertisement until callers populate one.
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

    order = Listing(
        listing_id=str(uuid.uuid4()),
        seller=BASE_URL_OVERRIDE,
        offer_resource=offer_resource,
        accepted_escrows=accepted_escrows,
        max_duration_seconds=max_duration_seconds,
        oracle_address=None,
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

    if not CONFIG.enable_registry_discovery:
        return {"status": "disabled", "listing_id": order_id}

    # Registry still expects a single-token ``demand`` payload (its own
    # demand_resource cleanup is a separate milestone). Synthesize from
    # accepted_escrows[0] so the registry sees the same pricing
    # advertisement the storefront stores locally.
    demand_for_registry = _synthesize_demand_for_registry(
        order_dict.get("accepted_escrows")
    )

    try:
        agent_id_for_registry = _canonical_agent_id() or CONFIG.agent_id
        async with _make_registry_client() as registry_client:
            order_request = ListingRequest(
                listing_id=order_id,
                offer=order_dict.get("offer_resource", {}),
                demand=demand_for_registry,
                max_duration_seconds=order_dict.get("max_duration_seconds"),
            )
            payloads = {url: order_request for url in registry_client.urls}
            results = await registry_client.publish_listing_per_registry(
                agent_id_for_registry, payloads, private_key=CONFIG.agent_priv_key,
            )
        await _record_publications(order_id, results)
        any_ok = any(r["success"] for r in results)
        if any_ok:
            logger.info("[REGISTRY] Published order %s", order_id)
            stage_event(
                "discovery", "order_published",
                order_id=order_id,
                agent_url=BASE_URL_OVERRIDE,
                offer=order_dict.get("offer_resource"),
                demand=demand_for_registry,
                max_duration_seconds=order_dict.get("max_duration_seconds"),
            )
            return {"status": "published", "listing_id": order_id}
        # No registry accepted the publish — surface the first error.
        first_err = next((r["error"] for r in results if r["error"]), "unknown")
        logger.warning("[REGISTRY] Failed to publish order %s: %s", order_id, first_err)
        return {"status": "error", "listing_id": order_id, "message": first_err}
    except Exception as exc:
        logger.warning("[REGISTRY] Failed to publish order %s: %s", order_id, exc)
        return {"status": "error", "listing_id": order_id, "message": str(exc)}


async def _registries_to_target(
    listing_id: str, fallback_urls: list[str],
) -> list[str]:
    """Return the set of registry URLs to target for an update/delete on
    ``listing_id``.

    Consults the ``publications`` table — only registries that previously
    received this listing get the update. Falls back to ``fallback_urls``
    (typically ``registry_client.urls``) when no publications row exists
    yet, which keeps update-before-publish flows (e.g. close_order on a
    listing the storefront never published) functioning.

    'unpublished' rows are skipped so a previously deleted listing doesn't
    receive an update.
    """
    try:
        sqlite_client = get_sqlite_client()
        pubs = await sqlite_client.load_publications(listing_id=listing_id)
    except Exception:
        return list(fallback_urls)
    active = [p["registry_url"] for p in pubs if p.get("status") != "unpublished"]
    return active if active else list(fallback_urls)


async def _record_publications(
    listing_id: str, results: list[dict[str, Any]],
) -> None:
    """Persist one ``publications`` row per per-registry result.

    Called after every fan-out write (publish / update / delete). Logged
    rather than raised on persistence errors — the registry-side write
    has already happened (or failed); the local audit row is best-effort.
    """
    try:
        sqlite_client = get_sqlite_client()
    except Exception:
        return
    for r in results:
        payload = r.get("payload") or {}
        status = "published" if r.get("success") else "failed"
        try:
            await sqlite_client.upsert_publication(
                listing_id=listing_id,
                registry_url=r["registry_url"],
                payload=payload,
                status=status,
                registry_assigned_id=r.get("registry_assigned_id"),
                last_error=r.get("error"),
            )
        except Exception as exc:
            logger.warning(
                "[PUBLICATIONS] Failed to record publication for %s @ %s: %s",
                listing_id, r.get("registry_url"), exc,
            )


def _synthesize_demand_for_registry(
    accepted_escrows: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Build a legacy ``demand`` payload (``{token, amount}``) from
    ``accepted_escrows[0]`` for the registry's still-old API.

    Returns an empty dict when there's no usable entry — the registry
    will reject or absorb that, but at least we don't crash on a missing
    ``accepted_escrows``.
    """
    if not accepted_escrows:
        return {}
    entry = accepted_escrows[0]
    if not isinstance(entry, dict):
        return {}
    payment_token = (entry.get("fields") or {}).get("payment_token")
    if not isinstance(payment_token, str) or not payment_token:
        return {}
    try:
        from service.clients.token import TOKEN_REGISTRY
        meta = TOKEN_REGISTRY.get_by_address(payment_token)
    except Exception:
        meta = None
    if meta is not None:
        token_payload = {
            "symbol": meta.symbol,
            "contract_address": meta.contract_address,
            "decimals": meta.decimals,
        }
    else:
        token_payload = {"contract_address": payment_token}
    return {"token": token_payload, "amount": entry.get("price_per_hour")}


def _token_resource_from_accepted_escrow(
    accepted_escrow: dict[str, Any] | Any,
) -> TokenResource | None:
    """Build a ``TokenResource`` from an ``accepted_escrows[i]`` entry.

    Looks up ERC20 metadata by the entry's ``fields.payment_token``
    address in TOKEN_REGISTRY, falling back to address-only metadata
    when the registry doesn't recognise it. Returns ``None`` when the
    entry lacks a payment_token. The token amount is the entry's
    ``price_per_hour`` (per-hour rate in base units); ``None`` becomes 0.
    """
    if not isinstance(accepted_escrow, dict):
        return None
    fields = accepted_escrow.get("fields") or {}
    payment_token = fields.get("payment_token")
    if not isinstance(payment_token, str) or not payment_token:
        return None
    try:
        from service.clients.token import TOKEN_REGISTRY, ERC20TokenMetadata
    except Exception:
        return None
    meta = TOKEN_REGISTRY.get_by_address(payment_token)
    if meta is None:
        # Fall back to a minimal metadata object so the encoder has
        # something to serialise. Decimals=0 means amounts are rendered
        # as integers; better than failing the lease entirely.
        meta = ERC20TokenMetadata(
            symbol="UNKNOWN",
            contract_address=payment_token,
            decimals=0,
        )
    price_per_hour = accepted_escrow.get("price_per_hour")
    amount = int(price_per_hour) if isinstance(price_per_hour, (int, float)) else 0
    return TokenResource(token=meta, amount=amount)


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
        compute_resource = extract_compute_from_order(order_dict)
        if isinstance(compute_resource, dict):
            for key in ("resource_id", "region", "gpu_model"):
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

    When fulfillment lands, pushes the fulfillment_uid to the registry's
    update endpoint.
    """
    fulfillment_uid = None
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
        compute_resource = extract_compute_from_order(order_dict)
        if isinstance(compute_resource, dict):
            for key in ("resource_id", "region", "gpu_model"):
                if compute_resource.get(key) is not None:
                    required_attributes[key] = compute_resource.get(key)
        accepted_escrows = order_dict.get("accepted_escrows") or []
        first_escrow = accepted_escrows[0] if accepted_escrows else None
        token_resource = _token_resource_from_accepted_escrow(first_escrow)
        if token_resource is None:
            raise ValueError(
                f"Cannot encode compute lease for listing "
                f"{order_id!r}: no usable accepted_escrows[0].payment_token"
            )
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
            await get_sqlite_client().update_escrow(
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
    # Register the lease with the provisioning service so the LeaseWatchdog
    # can call back to patch this resource to 'available' when the lease expires.
    # storefront_url and storefront_admin_key are global settings on the
    # provisioning service — not passed per-lease.
    # Non-fatal: a failure here is logged but does not abort settlement.
    if reserved_resource_id and reserved_vm_host and vm_target and escrow_uid:
        try:
            from client.provisioning_client import ProvisioningClient
            from datetime import datetime as _dt
            lease_end_dt = _dt.strptime(lease_end_utc, "%Y-%m-%d %H:%M").replace(
                tzinfo=timezone.utc
            )
            async with ProvisioningClient(
                CONFIG.provisioning_service_url,
                agent_id=str(CONFIG.onchain_agent_id or ""),
                timeout=10,
            ) as prov_client:
                await prov_client.register_lease(
                    resource_id=reserved_resource_id,
                    escrow_uid=escrow_uid,
                    vm_host=reserved_vm_host,
                    vm_target=vm_target,
                    lease_end_utc=lease_end_dt,
                )
            logger.info(
                "[LEASE] Registered lease with provisioning service "
                "(resource=%s escrow=%s expires=%s)",
                reserved_resource_id, escrow_uid, lease_end_utc,
            )
        except Exception as lease_err:
            logger.warning(
                "[LEASE] Failed to register lease with provisioning service "
                "(resource=%s escrow=%s): %s — watchdog will not auto-release this resource",
                reserved_resource_id, escrow_uid, lease_err,
            )

    async def _schedule_shutdown_best_effort() -> None:
        try:
            await _do_shutdown(lease_end_utc, vm_host=reserved_vm_host, vm_target=vm_target)
        except Exception as shutdown_err:
            logger.warning(
                "[LEASE] Failed to schedule VM expiry with provisioning service "
                "(resource=%s escrow=%s vm=%s/%s): %s",
                reserved_resource_id,
                escrow_uid,
                reserved_vm_host,
                vm_target,
                shutdown_err,
            )

    asyncio.create_task(_schedule_shutdown_best_effort())

    if not client or not oracle_address:
        # Demo fallback: skip on-chain, return simulated fulfillment uid
        fulfillment_uid = f"fulfill_{uuid.uuid4()}"
        logger.info("[ALKAHEST] (Simulated) Fulfilled compute obligation without on-chain client.")
    else:
        try:
            fulfillment_uid = await client.string_obligation.do_obligation(
                connection_details,
                escrow_uid
            )
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

    # Update registry with fulfillment_uid when the seller fulfills.
    if order and fulfillment_uid and CONFIG.enable_registry_discovery and order_id:
        try:
            async with _make_registry_client() as registry_client:
                target_urls = await _registries_to_target(
                    order_id, registry_client.urls,
                )
                update_request = UpdateListingRequest(
                    updates={"seller_attestation": fulfillment_uid},
                    private_key=CONFIG.agent_priv_key,
                    agent_id=_canonical_agent_id(),
                )
                payloads = {url: update_request for url in target_urls}
                results = await registry_client.update_listing_per_registry(
                    order_id, payloads,
                )
            await _record_publications(order_id, results)
            if any(r["success"] for r in results):
                logger.info(f"[REGISTRY] Updated order {order_id} with fulfillment_uid: {fulfillment_uid}")
            else:
                logger.warning(f"[REGISTRY] Failed to update order {order_id} with fulfillment_uid")
        except Exception as e:
            logger.warning(f"[REGISTRY] Error updating order {order_id} with fulfillment_uid: {e}")

    if order_id:
        try:
            sqlite_client = get_sqlite_client()
            await sqlite_client.update_listing(
                listing_id=order_id,
                fulfillment_resource=connection_details,
            )
        except Exception as exc:
            logger.warning("[LOCAL DB] Failed to update fulfillment for order %s: %s", order_id, exc)
        if fulfillment_uid:
            try:
                await get_sqlite_client().update_escrow(
                    escrow_uid=escrow_uid,
                    fulfillment_uid=fulfillment_uid,
                )
            except Exception as exc:
                logger.warning(
                    "[LOCAL DB] Failed to record fulfillment_uid on escrow %s: %s",
                    escrow_uid, exc,
                )

    tenant_auth = (authentication or {}).get("tenant", {}) or {}
    stage_event("provision", "fulfilled",
        listing_id=order_id,
        escrow_uid=escrow_uid,
        fulfillment_uid=fulfillment_uid,
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
