"""VM fulfillment orchestration for settled compute obligations."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any, Awaitable, Callable

from core_storefront.stage_log import stage_event

from alkahest_py import AlkahestClient

from domains.vms.provisioning import (
    build_provisioning_job_spec as _vm_build_provisioning_job_spec,
    fulfill_vm_obligation,
    provision_vm_and_wait,
    register_vm_lease,
    schedule_vm_expiry_and_wait,
)

from market_storefront.utils.config import CHAINS, settings, AGENT_ID, BASE_URL_OVERRIDE
from market_storefront.services.publication_service import (
    close_stale_compute_listings_after_capacity_change,
)
from market_storefront.utils.sqlite_client import get_sqlite_client

BASE_URL_OVERRIDE = BASE_URL_OVERRIDE
AGENT_ID = AGENT_ID

logger = logging.getLogger(__name__)


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
