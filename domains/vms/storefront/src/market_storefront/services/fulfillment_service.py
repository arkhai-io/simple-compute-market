"""VM fulfillment orchestration for settled compute obligations."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from functools import partial
from typing import Any

from compute_provisioning_client import (
    ComputeProvisioningClient,
    ComputeProvisioningJobError,
    ComputeProvisioningTimeoutError,
)
from compute_provisioning_contracts import (
    ACCESS_DELIVERY_KIND,
    ACCESS_DELIVERY_SCHEMA_VERSION,
    AccessDelivery,
    FulfillmentRequestBody,
    FulfillmentScheduleRequest,
    LeaseTermination,
)
from arkhai_vms import VmConnectionDetails
from core_storefront.stage_log import stage_event
from market_core import SettlementEvidence, VersionedEnvelope

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
    ``fulfillment_id`` but before polling starts, so recovery can retain the
    accepted physical identity even if foreground polling is interrupted.
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
    if request.payload.get("ssh_pubkey") != ssh_public_key:
        raise ValueError("SSH key differs from immutable delivery request")

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
    return _fulfillment_result_to_connection(envelope)


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


def _fulfillment_result_to_connection(envelope: VersionedEnvelope) -> dict[str, Any]:
    """An active fulfillment's delivery, as the deal's connection details.

    The details are ``VmConnectionDetails``: the delivered SSH endpoint, when
    access became ready, and the provisioned resources. The credentials the
    delivery carries, by role and with only their delivered fields, ride along
    under ``authentication`` for the caller to store; they are never part of
    the connection details.
    """
    payload: dict[str, Any] = envelope.payload or {}
    domain = payload.get("domain_result") or {}
    if (
        domain.get("kind") != ACCESS_DELIVERY_KIND
        or domain.get("schema_version") != ACCESS_DELIVERY_SCHEMA_VERSION
    ):
        raise RuntimeError(
            f"physical fulfillment returned an unsupported delivery {domain.get('kind')!r}"
        )
    delivery = AccessDelivery.model_validate(domain.get("payload") or {})
    endpoint = next(
        (endpoint for endpoint in delivery.endpoints if endpoint.protocol == "ssh"), None
    )
    if endpoint is None:
        raise RuntimeError("physical fulfillment delivered no SSH endpoint")
    details: dict[str, Any] = VmConnectionDetails(
        host=endpoint.host,
        port=endpoint.port,
        user=endpoint.user,
        ready_at=delivery.ready_at,
        provisioned_resource_ids=tuple(
            str(resource.get("provisioned_resource_id"))
            for resource in payload.get("provisioned_resources", [])
        ),
    ).model_dump(mode="json", exclude_none=True)
    authentication = {
        credential.role: {"password": credential.password, "key_type": credential.key_type}
        for credential in delivery.credentials
        if credential.role in ("root", "tenant")
    }
    if authentication:
        details["authentication"] = authentication
    return details


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


def _recorded_utc(value: str) -> datetime:
    """A lease time as the site recorded it: ISO 8601, or minute precision."""
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        parsed = datetime.strptime(text, "%Y-%m-%d %H:%M")
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


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
        apply_failure_policy=failure_policy,
        held_reservation=held_reservation,
        site_id=site_id,
    )
