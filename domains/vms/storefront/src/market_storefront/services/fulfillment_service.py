"""VM fulfillment orchestration for settled compute obligations."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from core_storefront.stage_log import stage_event

from alkahest_py import AlkahestClient

from compute_provisioning import (
    ComputeProvisioningClient,
    ComputeProvisioningJobError,
    ComputeProvisioningTimeoutError,
    FulfillmentRequestBody,
    FulfillmentScheduleRequest,
    LeaseRegistration,
)
from market_fulfillment import VersionedEnvelope
from market_storefront.services.vm_fulfillment_service import (
    fulfill_vm_obligation,
    persist_escrow_fields_with_retry,
)
from market_storefront.services.vm_job_spec_service import (
    build_provisioning_job_spec as _vm_build_provisioning_job_spec,
)

from market_storefront.utils.config import CHAINS, settings, BASE_URL_OVERRIDE
from market_storefront.services.capacity_client import (
    build_capacity_client,
    build_fulfillment_client,
)
from market_storefront.utils.sqlite_client import get_sqlite_client

logger = logging.getLogger(__name__)

# The VM domain's market identity for schedule_resource/begin_fulfillment
# calls -- matches the domains/vms package name; no other convention is
# documented anywhere in the fulfillment kit.
_VM_MARKET = "vms"



async def _do_provision(
    ssh_public_key: str,
    *,
    vm_host: str,
    vm_target: str,
    on_job_submitted: Callable[[str], Awaitable[None]] | None = None,
    capacity_reservation_id: str,
    escrow_uid: str,
) -> dict:
    """Schedule and begin durable fulfillment for this VM, then poll to completion.

    ``vm_host`` is accepted for call-site compatibility with the
    ``provision_vm`` seam ``fulfill_vm_obligation`` calls through.
    ``vm_host`` is not used to select a resource here: ``schedule_resource``
    re-confirms (or fairness-reassigns) the settlement resource from the
    reservation itself, independent of which host the reservation happened
    to bind at reserve time. The storefront escrow identity is used only for
    local progress persistence and does not enter the generic fulfillment request.

    ``on_job_submitted`` runs once ``begin_fulfillment`` returns a durable
    ``fulfillment_id`` but before polling starts, mirroring the legacy job-id
    hook this replaces.
    """
    fulfillment_client = build_fulfillment_client(
        build_capacity_client(lambda: get_sqlite_client())
    )

    scheduled = await fulfillment_client.schedule_resource(
        FulfillmentScheduleRequest(
            capacity_reservation_id=capacity_reservation_id,
            market=_VM_MARKET,
        )
    )
    if escrow_uid:
        await persist_escrow_fields_with_retry(
            get_sqlite_client,
            escrow_uid=escrow_uid,
            capacity_reservation_id=capacity_reservation_id,
            settlement_resource_id=scheduled.settlement_resource_id,
        )

    connectivity = _connectivity_settings_from_storefront_config()
    request_payload: dict[str, Any] = {"vm_target": vm_target, "ssh_pubkey": ssh_public_key}
    if connectivity:
        request_payload["connectivity"] = connectivity

    accepted = await fulfillment_client.begin_fulfillment(
        FulfillmentRequestBody(
            capacity_reservation_id=capacity_reservation_id,
            market=_VM_MARKET,
            fulfillment_request=VersionedEnvelope(
                kind="vm.fulfillment.request",
                schema_version=1,
                payload=request_payload,
            ),
        )
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
    )
    if status.state == "failed":
        raise ComputeProvisioningJobError(
            status.failure_message or f"fulfillment {accepted.fulfillment_id} failed"
        )

    envelope = await fulfillment_client.get_fulfillment_result(
        accepted.fulfillment_id, capacity_reservation_id=capacity_reservation_id,
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
    frp_dashboard_password = getattr(provisioning, "frp_dashboard_password", None) or None
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
            fulfillment_id, capacity_reservation_id=capacity_reservation_id,
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
    sqlite_client: Any | None = None,
) -> dict | None:
    db = sqlite_client or get_sqlite_client()
    return await _vm_build_provisioning_job_spec(
        order_dict=order_dict,
        ssh_public_key=ssh_public_key,
        duration_seconds=duration_seconds,
        capacity=build_capacity_client(lambda: db),
    )


async def _apply_fulfillment_failure_policy_adapter(
    *,
    capacity_reservation_id: str | None,
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
            capacity_reservation_id=capacity_reservation_id,
            escrow_uid=escrow_uid,
            listing_id=listing_id,
            resource_id=resource_id,
            reason=reason,
            message=message,
            source=source,
        ),
        # In remote-capacity mode the hold lives in the site ledger; the
        # policy's release_capacity action must go back through the client.
        capacity=build_capacity_client(lambda: get_sqlite_client()),
    )


async def _register_vm_lease_with_settings(
    *,
    resource_id: str,
    capacity_reservation_id: str | None,
    escrow_uid: str,
    vm_host: str,
    vm_target: str,
    lease_end_utc: str,
    lease_start_utc: str | None = None,
) -> None:
    lease_end_dt = datetime.strptime(lease_end_utc, "%Y-%m-%d %H:%M").replace(
        tzinfo=timezone.utc,
    )
    async with ComputeProvisioningClient(
        settings.provisioning.service_url,
        admin_key=settings.admin_api_key,
        timeout=10,
    ) as client:
        await client.register_lease(LeaseRegistration(
            capacity_reservation_id=capacity_reservation_id or resource_id,
            deal_ref={"escrow_uid": escrow_uid},
            executor_kind="vm",
            executor_target=vm_target,
            lease_start_utc=(
                datetime.fromisoformat(lease_start_utc.replace("Z", "+00:00"))
                if lease_start_utc
                else None
            ),
            lease_end_utc=lease_end_dt,
        ))


async def fulfill_compute_obligation(
    client: AlkahestClient | None,
    escrow_uid: str,
    ssh_public_key: str,
    order: str | dict | None = None,
    duration_seconds: int = 3600,
    start_utc: str | None = None,
    listing_id: str | None = None,
    seller_order_id: str | None = None,
    negotiation_id: str | None = None,
):
    """Provision compute and fulfill the obligation. Falls back to simulated flow if no client.

    ``duration_seconds`` is the buyer's negotiated lease window — passed
    through from `start_settlement_job`, which reads it off the
    negotiation thread's `agreed_duration_seconds`. Falls back to 1h
    only if the caller didn't provide one (recovery / legacy paths).

    When the negotiation's acceptance placed a TTL capacity hold
    (two-phase reserve), it is consumed here: fulfillment commits the
    held reservation instead of racing a fresh reserve.

    When fulfillment lands, pushes the fulfillment_uid to the registry's
    update endpoint.
    """
    held_reservation: dict | None = None
    if negotiation_id:
        db = get_sqlite_client()
        hold = await db.load_capacity_hold(negotiation_id=negotiation_id)
        if hold:
            held_reservation = dict(hold.get("payload") or {})
            held_reservation.setdefault("capacity_reservation_id", hold.get("capacity_reservation_id"))
            # Consume-once: whether the commit lands or falls back to a
            # fresh reserve, this hold row's job is done.
            await db.delete_capacity_hold(negotiation_id=negotiation_id)

    return await fulfill_vm_obligation(
        client=client,
        escrow_uid=escrow_uid,
        ssh_public_key=ssh_public_key,
        order=order,
        duration_seconds=duration_seconds,
        start_utc=start_utc,
        listing_id=listing_id,
        seller_order_id=seller_order_id,
        chain_configs=CHAINS,
        base_url=BASE_URL_OVERRIDE,
        get_sqlite_client=get_sqlite_client,
        # Late-bound factory: tests monkeypatch this module's
        # get_sqlite_client, and the capacity client must follow it.
        capacity=build_capacity_client(lambda: get_sqlite_client()),
        stage_event=stage_event,
        provision_vm=_do_provision,
        schedule_shutdown=_do_shutdown,
        register_lease=_register_vm_lease_with_settings,
        apply_failure_policy=_apply_fulfillment_failure_policy_adapter,
        held_reservation=held_reservation,
    )
