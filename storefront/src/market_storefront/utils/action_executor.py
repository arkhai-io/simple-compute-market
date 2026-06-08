"""Action execution.

TODO(refactor): This module still contains compute-domain action logic.
Move domain-specific execution into the domain package as refactor continues.
"""

from __future__ import annotations

import functools
from datetime import datetime, timezone
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
    build_provisioning_job_spec as _vm_build_provisioning_job_spec,
    fulfill_vm_obligation,
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

from domains.vms.listings.reconciler import (
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
    db = sqlite_client or get_sqlite_client()
    return await _vm_build_provisioning_job_spec(
        order_dict=order_dict,
        ssh_public_key=ssh_public_key,
        duration_seconds=duration_seconds,
        sqlite_client=db,
    )


async def _apply_fulfillment_failure_policy_adapter(
    *,
    allocation_id: str | None,
    escrow_uid: str,
    listing_id: str | None,
    resource_id: str | None,
    reason: str,
    message: str,
    source: str,
) -> None:
    from market_storefront.utils.failure_policy import (
        FulfillmentFailureContext,
        apply_fulfillment_failure_policy,
    )

    await apply_fulfillment_failure_policy(
        get_sqlite_client(),
        FulfillmentFailureContext(
            allocation_id=allocation_id,
            escrow_uid=escrow_uid,
            listing_id=listing_id,
            resource_id=resource_id,
            reason=reason,
            message=message,
            source=source,
        ),
    )


async def _register_vm_lease_with_settings(
    *,
    resource_id: str,
    allocation_id: str | None,
    escrow_uid: str,
    vm_host: str,
    vm_target: str,
    lease_end_utc: str,
) -> None:
    lease_end_dt = datetime.strptime(lease_end_utc, "%Y-%m-%d %H:%M").replace(
        tzinfo=timezone.utc,
    )
    await register_vm_lease(
        service_url=settings.provisioning.service_url,
        admin_key=settings.admin_api_key,
        timeout=10,
        resource_id=resource_id,
        allocation_id=allocation_id,
        escrow_uid=escrow_uid,
        vm_host=vm_host,
        vm_target=vm_target,
        lease_end_utc=lease_end_dt,
    )


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
    return await fulfill_vm_obligation(
        client=client,
        escrow_uid=escrow_uid,
        ssh_public_key=ssh_public_key,
        oracle_address=oracle_address,
        order=order,
        duration_seconds=duration_seconds,
        listing_id=listing_id,
        seller_order_id=seller_order_id,
        chain_configs=CHAINS,
        base_url=BASE_URL_OVERRIDE,
        get_sqlite_client=get_sqlite_client,
        stage_event=stage_event,
        close_stale_listings_after_capacity_change=(
            close_stale_compute_listings_after_capacity_change
        ),
        provision_vm=_do_provision,
        schedule_shutdown=_do_shutdown,
        register_lease=_register_vm_lease_with_settings,
        apply_failure_policy=_apply_fulfillment_failure_policy_adapter,
    )
