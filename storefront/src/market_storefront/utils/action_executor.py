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
    ComputeResource,
    Listing,
    TokenResource,
)
from market_storefront.resources import parse_resource_from_dict

from market_storefront.services.compute_listing_reconciler import (
    mark_derived_listings_closed,
    stale_open_listing_ids,
)
from market_storefront.utils.config import CHAINS, settings, AGENT_ID, BASE_URL_OVERRIDE
from service.clients.alkahest import encode_recipient_demand, get_recipient_arbiter
from market_storefront.utils.sqlite_client import get_sqlite_client
from client.provisioning_client import ProvisioningClient, ProvisioningError
from models.vm_request_model import CreateVmRequest, ScheduleVmExpiryRequest
from registry_client import RegistryClient, ListingRequest, UpdateListingRequest
from market_policy.negotiation_thread import get_thread_store
from .validation import determine_strategy_from_order

BASE_URL_OVERRIDE = BASE_URL_OVERRIDE
PORT = settings.port
AGENT_ID = AGENT_ID
SSH_PUBLIC_KEY = settings.wallet.ssh_public_key

logger = logging.getLogger(__name__)

def _is_http_url(value: str | None) -> bool:
    """Return True if value is a valid http(s) URL with hostname."""
    if not value or not isinstance(value, str):
        return False
    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)




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

    if not settings.enable_registry_discovery:
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
                private_key=settings.wallet.private_key,
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


async def close_stale_compute_listings_after_capacity_change(db_path: str) -> list[str]:
    """Close open derived compute listings whose GPU slice no longer fits."""
    closed_listing_ids: list[str] = []
    for listing_id in stale_open_listing_ids(db_path):
        result = await close_order({"listing_id": listing_id})
        if str(result.get("status", "?")) in ("closed", "skipped", "queued"):
            closed_listing_ids.append(listing_id)
            continue
        row = await get_sqlite_client().load_listing(listing_id=listing_id)
        if row and row.get("status") == "closed":
            closed_listing_ids.append(listing_id)
    mark_derived_listings_closed(db_path, closed_listing_ids)
    return closed_listing_ids


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
    client = ProvisioningClient(
        settings.provisioning.service_url,
        admin_key=settings.admin_api_key,
        timeout=float(settings.provisioning.timeout),
    )
    async with client:
        params: dict = {"vm_target": vm_target, "ssh_pubkey": ssh_public_key}
        if settings.provisioning.frp_server_addr:
            params["frp_server_addr"] = settings.provisioning.frp_server_addr
        if settings.provisioning.frp_domain:
            params["frp_domain"] = settings.provisioning.frp_domain
        if settings.provisioning.frp_dashboard_password:
            params["frp_dashboard_password"] = settings.provisioning.frp_dashboard_password
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
            timeout=float(settings.provisioning.timeout),
            poll_interval=float(settings.provisioning.poll_interval),
        )
        result = job.result or {}
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
    client = ProvisioningClient(
        settings.provisioning.service_url,
        admin_key=settings.admin_api_key,
        timeout=float(settings.provisioning.timeout),
    )
    async with client:
        submit = await client.schedule_expiry(
            vm_host, vm_target, ScheduleVmExpiryRequest(vm_expiry_at=lease_end_utc)
        )
        job = await client.poll_until_complete(
            submit.job_id,
            timeout=float(settings.provisioning.timeout),
            poll_interval=float(settings.provisioning.poll_interval),
        )
    return job.result or {}


def _canonical_agent_id(chain_name: str | None = None) -> str | None:
    """Return the storefront's identity for downstream services.

    Post-pluggable-identity (Phase 4): the storefront's identity is the
    EIP-191 wallet address (``settings.wallet.address``, lowercased).
    The ``chain_name`` argument is accepted for back-compat with callers
    that previously dispatched per-chain but no longer affects the
    returned value — identity is chain-agnostic.

    Returns ``None`` when no wallet is configured.
    """
    del chain_name  # back-compat shim; identity is chain-agnostic now
    address = (settings.wallet.address or "").strip().lower()
    return address or None


def _make_registry_client() -> "MultiRegistryClient":
    """Construct a multi-registry client wrapping every configured URL.

    Each call returns a fresh wrapper — callers use it as an async
    context manager (``async with _make_registry_client() as rc:``).
    The wrapper exposes the same surface as ``RegistryClient`` so call
    sites (and the test mocks that patch this function) don't change
    shape; reads fan in across every URL, writes fan out best-effort.
    """
    from .multi_registry_client import MultiRegistryClient
    urls = list(settings.registry.urls) if settings.registry.urls else ["http://localhost:8080"]
    return MultiRegistryClient(
        urls,
        timeout=settings.registry.discovery_timeout,
        auth=settings.registry.auth,
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
    ``accepted_escrows[0]`` (see ``_listing_token`` in
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


def _extract_initial_price_from_order(order: Listing | dict) -> int | float:
    """Extract the initial negotiation floor from a listing's primary rate.

    Tristate semantics on the advertised price:
      * ``> 0`` — public price; returned directly.
      * ``0``  — free / public-test offering; returned as 0. The seller's
        strategy accepts any non-negative offer.
      * ``None`` or missing entry — hidden reserve; falls back to
        ``[seller.pricing].default_min_price`` so the strategy has a real
        floor. If that's also unset, raises ``ValueError`` — the caller
        (sync_negotiation) translates that to a 409 refusal.
    """
    from service.schemas import primary_rate_value

    if isinstance(order, dict):
        order = Listing.model_validate(order)

    advertised: int | None = None
    if order.accepted_escrows:
        advertised = primary_rate_value(order.accepted_escrows[0])

    # 0 is a meaningful value (free); only None falls through to the fallback.
    if advertised is not None:
        return advertised

    # Hidden reserve: fall back to the seller's config default.
    from market_storefront.utils.config import settings, AGENT_ID, BASE_URL_OVERRIDE
    fallback = settings.pricing.default_min_price
    if fallback is not None and str(fallback).strip():
        try:
            parsed = float(fallback)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"[seller.pricing].default_min_price={fallback!r} is not a "
                f"valid number; hidden-reserve listing {order.listing_id} has "
                "no usable floor."
            ) from exc
        if parsed > 0:
            return parsed

    raise ValueError(
        f"Listing {order.listing_id} has hidden reserve "
        "(accepted_escrows[0].rates is empty) and "
        "[seller.pricing].default_min_price is not configured. The seller "
        "has no floor to negotiate against; refusing the negotiation."
    )



def _ensure_json_obj(value: Any, default: Any) -> Any:
    """Coerce a maybe-stringified JSON blob into a Python object.

    offer_resource / accepted_escrows live in SQLite TEXT columns; some
    load paths hand them back already parsed, others as the raw JSON
    string. The registry stores them in JSON columns and runs JSONPath
    discovery filters over them, so forwarding a string round-trips
    double-encoded and silently breaks every offer_resource.* / token
    filter — a buyer's ``market buy --gpu-model`` then matches nothing.
    """
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return default
    return default if value is None else value


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

    if not settings.enable_registry_discovery:
        return {"status": "disabled", "listing_id": order_id}

    offer_resource = _ensure_json_obj(order_dict.get("offer_resource"), {})
    accepted_escrows = _ensure_json_obj(order_dict.get("accepted_escrows"), [])
    demands = _ensure_json_obj(order_dict.get("demands"), [])

    try:
        async with _make_registry_client() as registry_client:
            order_request = ListingRequest(
                listing_id=order_id,
                offer=offer_resource,
                accepted_escrows=accepted_escrows,
                demands=demands,
                max_duration_seconds=order_dict.get("max_duration_seconds"),
                storefront_url=order_dict.get("seller") or BASE_URL_OVERRIDE,
            )
            payloads = {url: order_request for url in registry_client.urls}
            results = await registry_client.publish_listing_per_registry(
                payloads, private_key=settings.wallet.private_key,
            )
        await _record_publications(order_id, results)
        any_ok = any(r["success"] for r in results)
        if any_ok:
            logger.info("[REGISTRY] Published order %s", order_id)
            stage_event(
                "discovery", "order_published",
                order_id=order_id,
                agent_url=BASE_URL_OVERRIDE,
                offer=offer_resource,
                accepted_escrows=accepted_escrows,
                demands=demands,
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


def _token_resource_from_accepted_escrow(
    accepted_escrow: dict[str, Any] | Any,
) -> TokenResource | None:
    """Build a ``TokenResource`` from an ``accepted_escrows[i]`` entry.

    Looks up ERC20 metadata by the entry's ``literal_fields.token``
    address in the chain-resolved cache, falling back to address-only
    metadata when the cache doesn't yet know it. Returns ``None`` when
    the entry lacks a token. The token amount is the entry's primary
    rate value (per-hour rate in base units); ``None`` becomes 0.
    """
    from service.schemas import accepted_token_address

    if not isinstance(accepted_escrow, dict):
        return None
    token = accepted_token_address(accepted_escrow)
    if not isinstance(token, str) or not token:
        return None
    try:
        from service.clients.token import resolve_token_cached, ERC20TokenMetadata
    except Exception:
        return None
    meta = resolve_token_cached(token)
    if meta is None:
        # Fall back to a minimal metadata object so the encoder has
        # something to serialise. Decimals=0 means amounts are rendered
        # as integers; better than failing the lease entirely.
        meta = ERC20TokenMetadata(
            symbol="UNKNOWN",
            contract_address=token,
            decimals=0,
        )
    from service.schemas import primary_rate_value

    amount = primary_rate_value(accepted_escrow) or 0
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
            for key in ("pool_id", "resource_id", "region", "gpu_model", "gpu_count"):
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
    reserved_allocation_id: str | None = None
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
            for key in ("pool_id", "resource_id", "region", "gpu_model", "gpu_count"):
                if compute_resource.get(key) is not None:
                    required_attributes[key] = compute_resource.get(key)
        accepted_escrows = order_dict.get("accepted_escrows") or []
        first_escrow = accepted_escrows[0] if accepted_escrows else None
        token_resource = _token_resource_from_accepted_escrow(first_escrow)
        if token_resource is None:
            raise ValueError(
                f"Cannot encode compute lease for listing "
                f"{order_id!r}: no usable accepted_escrows[0].token"
            )
        order_bytes = encode_compute_lease(
            compute_resource=compute_resource,
            token_resource=token_resource,
            duration_seconds=duration_seconds,
        )

    try:
        sqlite_client = get_sqlite_client()
        reserved = await sqlite_client.reserve_available_compute_vm(
            required_attributes=required_attributes or None,
            listing_id=listing_id or order_id,
            escrow_uid=escrow_uid,
        )
        if not reserved:
            raise RuntimeError("No available compute VM matched required attributes")
        reserved_allocation_id = str(reserved.get("allocation_id")) if reserved.get("allocation_id") else None
        reserved_resource_id = str(reserved.get("resource_id"))
        reserved_vm_host = reserved.get("vm_host")
        if not reserved_vm_host:
            raise RuntimeError("Reserved resource missing vm_host")
        stage_event("provision", "resource_reserved",
            listing_id=order_id,
            escrow_uid=escrow_uid,
            pool_id=reserved.get("pool_id"),
            member_id=reserved.get("member_id"),
            resource_id=reserved_resource_id,
            vm_host=reserved_vm_host,
            required_attributes=required_attributes,
            allocation_id=reserved_allocation_id,
            allocated_gpu_count=reserved.get("allocated_gpu_count"),
        )
        try:
            closed_listing_ids = await close_stale_compute_listings_after_capacity_change(
                sqlite_client.db_path,
            )
            if closed_listing_ids:
                stage_event(
                    "provision", "stale_compute_listings_closed",
                    listing_id=order_id,
                    escrow_uid=escrow_uid,
                    resource_id=reserved_resource_id,
                    allocation_id=reserved_allocation_id,
                    closed_listing_ids=closed_listing_ids,
                )
        except Exception as close_err:
            logger.warning(
                "[LISTINGS] Failed to close stale compute listings after reservation: %s",
                close_err,
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
        if reserved_allocation_id:
            try:
                await get_sqlite_client().update_compute_allocation_state(
                    allocation_id=reserved_allocation_id,
                    state="released",
                )
            except Exception as release_err:
                logger.warning(
                    "[LOCAL DB] Failed to release compute allocation %s after provisioning failure: %s",
                    reserved_allocation_id,
                    release_err,
                )
        elif reserved_resource_id:
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
            if reserved_allocation_id:
                await get_sqlite_client().update_compute_allocation_state(
                    allocation_id=reserved_allocation_id,
                    state="leased",
                )
                await get_sqlite_client().apply_resource_set_transition(
                    resource_id=reserved_resource_id,
                    event_type="lease_started_after_provisioning",
                    idempotency_key=f"lease-attrs:{escrow_uid}:{reserved_resource_id}",
                    set_attribute={"$.lease_end_utc": lease_end_utc},
                )
            else:
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
                settings.provisioning.service_url,
                admin_key=settings.admin_api_key,
                timeout=10,
            ) as prov_client:
                await prov_client.register_lease(
                    resource_id=reserved_resource_id,
                    allocation_id=reserved_allocation_id,
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
            logger.error(
                "[ALKAHEST] EVENT=settlement_failed_after_provisioning "
                "escrow_uid=%s listing_id=%s resource_id=%s allocation_id=%s "
                "vm_host=%s error=%s",
                escrow_uid,
                order_id,
                reserved_resource_id,
                reserved_allocation_id,
                reserved_vm_host,
                error,
            )
            stage_event("settlement", "failed_after_provisioning",
                listing_id=order_id,
                escrow_uid=escrow_uid,
                resource_id=reserved_resource_id,
                allocation_id=reserved_allocation_id,
                vm_host=reserved_vm_host,
                error=str(error),
            )
            return {
                "status": "error",
                "message": f"On-chain fulfillment failed after provisioning: {error}",
                "escrow_uid": escrow_uid,
                "connection_details": None,
                "ssh_public_key": ssh_public_key,
            }

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
        allocation_id=reserved_allocation_id,
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
