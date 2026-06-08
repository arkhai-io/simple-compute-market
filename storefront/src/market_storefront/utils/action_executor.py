"""Action execution.

TODO(refactor): This module still contains compute-domain action logic.
Move domain-specific execution into the domain package as refactor continues.
"""

from __future__ import annotations

import asyncio
import functools
import uuid
from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

from market_storefront.utils.stage_log import stage_event

from alkahest_py import AlkahestClient
import json

from domains.vms.listings import (
    extract_compute_from_order as _vm_extract_compute_from_order,
    extract_initial_price_from_order as _vm_extract_initial_price_from_order,
    resource_is_compute as _vm_resource_is_compute,
)
from domains.vms.provisioning import (
    provision_vm_and_wait,
    register_vm_lease,
    schedule_vm_expiry_and_wait,
)
from domains.vms.settlement import (
    encode_compute_lease as _vm_encode_compute_lease,
    token_resource_from_accepted_escrow as _vm_token_resource_from_accepted_escrow,
)
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
from registry_client import RegistryClient, ListingRequest, UpdateListingRequest
from market_policy.negotiation_thread import get_thread_store

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
    """Compatibility wrapper for VM-domain compute resource detection."""
    return _vm_resource_is_compute(resource)


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
    return await provision_vm_and_wait(
        service_url=settings.provisioning.service_url,
        admin_key=settings.admin_api_key,
        timeout=float(settings.provisioning.timeout),
        poll_interval=float(settings.provisioning.poll_interval),
        ssh_public_key=ssh_public_key,
        vm_host=vm_host,
        vm_target=vm_target,
        frp_server_addr=settings.provisioning.frp_server_addr,
        frp_domain=settings.provisioning.frp_domain,
        frp_dashboard_password=settings.provisioning.frp_dashboard_password,
        on_job_submitted=on_job_submitted,
    )


async def _do_shutdown(lease_end_utc: str, *, vm_host: str, vm_target: str) -> dict:
    """Schedule VM expiry via the provisioning service."""
    return await schedule_vm_expiry_and_wait(
        service_url=settings.provisioning.service_url,
        admin_key=settings.admin_api_key,
        timeout=float(settings.provisioning.timeout),
        poll_interval=float(settings.provisioning.poll_interval),
        lease_end_utc=lease_end_utc,
        vm_host=vm_host,
        vm_target=vm_target,
    )


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
    """Compatibility wrapper for VM-domain compute extraction."""
    return _vm_extract_compute_from_order(order)


def _extract_initial_price_from_order(order: Listing | dict) -> int | float:
    """Compatibility wrapper for VM-domain price-floor extraction."""
    return _vm_extract_initial_price_from_order(
        order,
        default_min_price=settings.pricing.default_min_price,
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
    """Compatibility wrapper for VM-domain token materialization."""
    return _vm_token_resource_from_accepted_escrow(
        accepted_escrow,
        chain_configs=CHAINS,
    )


def encode_compute_lease(
    compute_resource: ComputeResource | dict[str, Any],
    token_resource: TokenResource | dict[str, Any],
    duration_seconds: int,
) -> bytes:
    """Compatibility wrapper for VM-domain compute lease encoding."""
    return _vm_encode_compute_lease(
        compute_resource=compute_resource,
        token_resource=token_resource,
        duration_seconds=duration_seconds,
    )


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
                f"Cannot encode compute lease for listing {order_id!r}: "
                "accepted_escrows[0] is neither token-backed nor native-token"
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
        try:
            from market_storefront.utils.failure_policy import (
                FulfillmentFailureContext,
                apply_fulfillment_failure_policy,
            )

            await apply_fulfillment_failure_policy(
                get_sqlite_client(),
                FulfillmentFailureContext(
                    allocation_id=reserved_allocation_id,
                    escrow_uid=escrow_uid,
                    listing_id=listing_id or order_id,
                    resource_id=reserved_resource_id,
                    reason="provisioning_failed",
                    message=str(error),
                    source="settlement_provisioning",
                ),
            )
        except Exception as policy_err:
            logger.warning(
                "[FULFILLMENT_POLICY] Failed to apply provisioning failure policy "
                "for escrow %s: %s",
                escrow_uid,
                policy_err,
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
            from datetime import datetime as _dt
            lease_end_dt = _dt.strptime(lease_end_utc, "%Y-%m-%d %H:%M").replace(
                tzinfo=timezone.utc
            )
            await register_vm_lease(
                service_url=settings.provisioning.service_url,
                admin_key=settings.admin_api_key,
                timeout=10,
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
