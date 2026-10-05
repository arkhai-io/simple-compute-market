"""VM fulfillment orchestration for settled compute obligations."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from functools import partial
from typing import Any

from compute_provisioning import (
    ComputeProvisioningClient,
    ComputeProvisioningJobError,
    ComputeProvisioningTimeoutError,
    FulfillmentRequestBody,
    FulfillmentScheduleRequest,
    LeaseRegistration,
    LeaseTermination,
)
from core_storefront.stage_log import stage_event
from market_core import SettlementEvidence
from market_fulfillment import VersionedEnvelope

from market_storefront.services.capacity_client import (
    build_capacity_client,
    build_capacity_runtime,
    build_fulfillment_client,
)
from market_storefront.services.vm_fulfillment_planner import build_vm_fulfillment_plan
from market_storefront.services.vm_fulfillment_service import (
    fulfill_vm_obligation,
    persist_delivery_fields_with_retry,
)
from market_storefront.services.vm_job_spec_service import (
    build_provisioning_job_spec as _vm_build_provisioning_job_spec,
)
from market_storefront.utils.config import (
    BASE_URL_OVERRIDE,
    get_provisioning_authorities,
    settings,
)

logger = logging.getLogger(__name__)

# The VM domain's market identity for schedule_resource/begin_fulfillment
# calls -- matches the domains/vms package name; no other convention is
# documented anywhere in the fulfillment kit.
_VM_MARKET = "vms"


async def _do_provision(
    ssh_public_key: str,
    sqlite_client: Any,
    *,
    vm_host: str | None,
    vm_target: str,
    on_job_submitted: Callable[[str], Awaitable[None]] | None = None,
    capacity_reservation_id: str,
    negotiation_id: str,
) -> dict:
    """Schedule and begin durable fulfillment for this VM, then poll to completion.

    ``vm_host`` is accepted for call-site compatibility with the
    ``provision_vm`` seam ``fulfill_vm_obligation`` calls through, and may
    legitimately be ``None`` -- the opaque capacity-reservation boundary
    does not guarantee it. ``vm_host`` is not used to select a resource
    here: ``schedule_resource`` re-confirms (or fairness-reassigns) the
    settlement resource from the reservation itself, independent of which
    host the reservation happened to bind at reserve time. The storefront
    negotiation identity is used only for local progress persistence and does
    not enter the generic fulfillment request.

    ``on_job_submitted`` runs once ``begin_fulfillment`` returns a durable
    ``fulfillment_id`` but before polling starts, mirroring the legacy job-id
    hook this replaces.
    """
    delivery = await sqlite_client.load_vm_delivery(negotiation_id=negotiation_id)
    if delivery is None or not delivery.get("negotiation_id"):
        raise RuntimeError(
            f"negotiation {negotiation_id!r} has no accepted negotiation binding"
        )
    thread_binding = await sqlite_client.load_thread_binding(
        negotiation_id=str(delivery["negotiation_id"])
    )
    sqlite_client.domain_registry.resolve(thread_binding.binding)
    raw_context = delivery.get("fulfillment_context")
    if isinstance(raw_context, str):
        try:
            context = json.loads(raw_context)
        except json.JSONDecodeError as exc:
            raise RuntimeError("stored fulfillment context is malformed") from exc
    elif isinstance(raw_context, dict):
        context = dict(raw_context)
    elif raw_context is None:
        context = {}
    else:
        raise RuntimeError("stored fulfillment context must be an object")
    bound_context = sqlite_client.bind_fulfillment_context(
        context,
        thread_binding=thread_binding,
    )
    await sqlite_client.update_vm_delivery(
        negotiation_id=negotiation_id,
        fulfillment_context=json.dumps(
            bound_context,
            sort_keys=True,
            separators=(",", ":"),
        ),
    )
    site_id = thread_binding.site_id
    fulfillment_client = build_fulfillment_client(
        build_capacity_client(lambda: sqlite_client)
    )

    request_envelope = (bound_context.get("payload") or {}).get("fulfillment_request")
    if not isinstance(request_envelope, dict):
        raise RuntimeError("immutable VM fulfillment request is unavailable")
    request = VersionedEnvelope.model_validate(request_envelope)
    if (
        request.payload.get("vm_target") != vm_target
        or request.payload.get("ssh_pubkey") != ssh_public_key
    ):
        raise ValueError("VM target or key differs from immutable delivery request")

    scheduled = await fulfillment_client.schedule_resource(
        FulfillmentScheduleRequest(
            capacity_reservation_id=capacity_reservation_id,
            market=_VM_MARKET,
        ),
        site_id=site_id,
    )
    if negotiation_id:
        await persist_delivery_fields_with_retry(
            lambda: sqlite_client,
            negotiation_id=negotiation_id,
            capacity_reservation_id=capacity_reservation_id,
            settlement_resource_id=scheduled.settlement_resource_id,
        )

    accepted = await fulfillment_client.begin_fulfillment(
        FulfillmentRequestBody(
            capacity_reservation_id=capacity_reservation_id,
            market=_VM_MARKET,
            fulfillment_request=request,
        ),
        site_id=site_id,
    )

    if on_job_submitted is not None:
        try:
            await on_job_submitted(accepted.fulfillment_id)
        except Exception as exc:
            logger.warning(
                "[PROVISIONING] on_job_submitted callback failed for fulfillment %s: %s",
                accepted.fulfillment_id,
                exc,
            )

    timeout = float(settings.provisioning.timeout)
    poll_interval = float(settings.provisioning.poll_interval)
    status = await _poll_fulfillment_until_terminal(
        fulfillment_client,
        accepted.fulfillment_id,
        capacity_reservation_id=capacity_reservation_id,
        timeout=timeout,
        poll_interval=poll_interval,
        site_id=site_id,
    )
    if status.state == "failed":
        raise ComputeProvisioningJobError(
            status.failure_message or f"fulfillment {accepted.fulfillment_id} failed"
        )

    envelope = await fulfillment_client.get_fulfillment_result(
        accepted.fulfillment_id,
        capacity_reservation_id=capacity_reservation_id,
        site_id=site_id,
    )
    return _fulfillment_result_to_legacy_shape(envelope)


def _connectivity_settings_from_storefront_config() -> dict[str, Any] | None:
    """Storefront-operator-configured FRP settings, or None if unset.

    Currently the only source of connectivity terms; a buyer-specified,
    negotiated source populating this same request field is a plausible
    future addition, not yet implemented.
    """
    provisioning = settings.provisioning
    frp_server_addr = getattr(provisioning, "frp_server_addr", None) or None
    frp_domain = getattr(provisioning, "frp_domain", None) or None
    frp_dashboard_password = (
        getattr(provisioning, "frp_dashboard_password", None) or None
    )
    if not (frp_server_addr or frp_domain or frp_dashboard_password):
        return None
    return {
        "frp_server_addr": frp_server_addr,
        "frp_domain": frp_domain,
        "frp_dashboard_password": frp_dashboard_password,
    }


async def _poll_fulfillment_until_terminal(
    fulfillment_client: Any,
    fulfillment_id: str,
    *,
    capacity_reservation_id: str,
    timeout: float,
    poll_interval: float,
    site_id: str,
) -> Any:
    """Poll ``get_fulfillment_status`` until ``active``/``failed`` or timeout.

    Every other state (``assigned``, ``dispatch_pending``, ``dispatching``,
    and the teardown-side states, which cannot appear here) is still in
    progress.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        status = await fulfillment_client.get_fulfillment_status(
            fulfillment_id,
            capacity_reservation_id=capacity_reservation_id,
            site_id=site_id,
        )
        if status.state in ("active", "failed"):
            return status
        if loop.time() >= deadline:
            raise ComputeProvisioningTimeoutError(
                f"fulfillment {fulfillment_id} did not reach a terminal state "
                f"within {timeout}s (last state: {status.state})"
            )
        await asyncio.sleep(poll_interval)


def _fulfillment_result_to_legacy_shape(envelope: VersionedEnvelope) -> dict[str, Any]:
    """Map a fulfillment result envelope into the shape callers of
    ``provision_vm`` expect: a dict with an optional ``authentication`` key
    (``{"root": {...}, "tenant": {...}}``, popped out by the caller) plus
    other connection-detail fields serialized as ``connection_details``.
    """
    payload: dict[str, Any] = envelope.payload or {}
    domain_result = payload.get("domain_result") or {}
    domain_payload: dict[str, Any] = domain_result.get("payload") or {}
    credentials = domain_payload.get("credentials") or []

    authentication: dict[str, Any] = {}
    for credential in credentials:
        role = credential.get("role")
        if role not in ("root", "tenant"):
            continue
        entry: dict[str, Any] = {
            "password": credential.get("password"),
            "ssh_commands": credential.get("ssh_commands"),
        }
        if role == "root":
            entry["ssh_key_path_host"] = credential.get("ssh_key_path_host")
        else:
            entry["key_type"] = credential.get("key_type")
        authentication[role] = entry

    # `connection_info` is VmConnectionInfo's field set (vm_name, host,
    # timestamp, tenant_user, vm_ip_internal, ssh_port), dumped as a plain
    # dict on the wire -- spread directly rather than naming each field
    # again here.
    connection_info: dict[str, Any] = domain_payload.get("connection_info") or {}
    result: dict[str, Any] = {
        **connection_info,
        "provisioned_resource_ids": [
            resource.get("provisioned_resource_id")
            for resource in payload.get("provisioned_resources", [])
        ],
    }
    if authentication:
        result["authentication"] = authentication
    return result


async def _do_shutdown(lease_end_utc: str, *, vm_host: str, vm_target: str) -> dict:
    """Schedule VM expiry via the provisioning service.

    NOTE: The provisioning service has no ``schedule_expiry`` endpoint — this
    hook was wired but the underlying API was never implemented.
    Lease teardown is managed by the LeaseWatchdog; call
    ``POST /api/v1/system/check-leases`` or wait for the next watchdog cycle.

    Raises ``NotImplementedError`` if called so callers discover the gap
    immediately rather than silently failing on a missing import.
    """
    raise NotImplementedError(
        "_do_shutdown is not implemented: the provisioning service has no "
        "schedule_expiry endpoint. Lease teardown is handled by the "
        "LeaseWatchdog. Submit POST /api/v1/system/check-leases to trigger "
        "an immediate teardown cycle."
    )


async def _build_provisioning_job_spec(
    *,
    order_dict: dict | None,
    ssh_public_key: str,
    duration_seconds: int,
    sqlite_client: Any,
) -> dict | None:
    db = sqlite_client
    return await _vm_build_provisioning_job_spec(
        order_dict=order_dict,
        ssh_public_key=ssh_public_key,
        duration_seconds=duration_seconds,
        capacity=build_capacity_client(lambda: db),
    )


def _provisioning_client(*, timeout: float) -> ComputeProvisioningClient:
    from market_storefront import container

    signer = container.resolved_marketplace_signer
    if signer is None:
        raise RuntimeError("storefront marketplace signer is unavailable")
    return ComputeProvisioningClient(
        settings.provisioning.service_url,
        signer=signer,
        caller_role="seller",
        expected_authorities=get_provisioning_authorities(),
        timeout=timeout,
    )


async def _register_vm_lease_with_settings(
    *,
    resource_id: str | None = None,
    capacity_reservation_id: str | None,
    negotiation_id: str,
    vm_host: str | None = None,
    vm_target: str,
    lease_end_utc: str,
    lease_start_utc: str | None = None,
) -> None:
    # resource_id/vm_host are accepted for call-site compatibility with
    # fulfill_vm_obligation's opaque reservation result, but LeaseRegistration
    # never reads either: the reservation's executor_ref/vm_host is already
    # written independently at capacity-commit/rebind time and self-heals
    # from that value when not explicitly supplied. Requiring a caller to
    # have a physical resource identity in hand before it can register a
    # lease at all would reintroduce physical-node pinning into what is
    # meant to be a pool-scoped capacity negotiation.
    lease_end_dt = datetime.fromisoformat(lease_end_utc.replace("Z", "+00:00")).replace(
        tzinfo=timezone.utc
    )
    async with _provisioning_client(timeout=10) as client:
        await client.register_lease(
            LeaseRegistration(
                capacity_reservation_id=capacity_reservation_id or resource_id,
                deal_ref={"negotiation_id": negotiation_id},
                executor_kind="vm",
                executor_target=vm_target,
                lease_start_utc=(
                    datetime.fromisoformat(lease_start_utc.replace("Z", "+00:00"))
                    if lease_start_utc
                    else None
                ),
                lease_end_utc=lease_end_dt,
            )
        )


async def terminate_vm_lease(
    *,
    capacity_reservation_id: str,
    reason: str | None = None,
) -> None:
    """Ask the provisioning service to begin tearing down a leased VM early.

    Submits the same executor-dispatched release operation the lease
    watchdog's own expiry sweep submits (`POST
    /api/v1/contract/leases/{capacity_reservation_id}/terminate`) but
    immediately, without waiting for a sweep cycle. Capacity is held until
    the provisioning service confirms teardown; this call only requests
    that teardown begin, it does not wait for it to finish.

    No caller exists yet in this codebase — this function exists so a
    future buyer-initiated early-termination flow has something to call
    rather than needing to add provisioning-service surface area for it
    later. See `openspec/specs/vm-storefront-fulfillment/spec.md`.
    """
    async with _provisioning_client(timeout=10) as client:
        await client.terminate_lease(
            capacity_reservation_id,
            LeaseTermination(reason=reason),
        )


async def fulfill_compute_obligation(
    sqlite_client: Any,
    evidence: SettlementEvidence,
    *,
    site_id: str,
    failure_policy: Any = None,
):
    """Provision the verified VM delivery at its accepted site."""
    build_vm_fulfillment_plan(evidence=evidence)
    negotiation_id = evidence.negotiation_id
    held_reservation = None
    hold = await sqlite_client.load_capacity_hold(negotiation_id=negotiation_id)
    if hold:
        held_reservation = dict(hold.get("payload") or {})
        held_reservation.setdefault(
            "capacity_reservation_id", hold.get("capacity_reservation_id")
        )
        await sqlite_client.delete_capacity_hold(negotiation_id=negotiation_id)
    return await fulfill_vm_obligation(
        evidence=evidence,
        base_url=BASE_URL_OVERRIDE,
        get_sqlite_client=lambda: sqlite_client,
        capacity=build_capacity_runtime(lambda: sqlite_client),
        stage_event=stage_event,
        provision_vm=partial(_do_provision, sqlite_client=sqlite_client),
        schedule_shutdown=_do_shutdown,
        register_lease=_register_vm_lease_with_settings,
        apply_failure_policy=failure_policy,
        held_reservation=held_reservation,
        site_id=site_id,
    )
