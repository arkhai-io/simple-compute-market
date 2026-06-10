"""VM fulfillment orchestration."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from domains.vms.provisioning.fulfillment_plan import build_vm_fulfillment_plan
from domains.vms.settlement import submit_compute_fulfillment

logger = logging.getLogger(__name__)

StageEventFn = Callable[..., Any]
SQLiteClientFactory = Callable[[], Any]
# Site-authority capacity client (core_storefront.capacity.CapacityClient
# shape); duck-typed so this concept module needs no core import.
CapacityClientLike = Any
ProvisionVmFn = Callable[..., Awaitable[Any]]
ScheduleShutdownFn = Callable[..., Awaitable[Any]]
CloseStaleListingsFn = Callable[[str], Awaitable[list[str]]]
RegisterLeaseFn = Callable[..., Awaitable[Any]]
ApplyFailurePolicyFn = Callable[..., Awaitable[None]]


async def fulfill_vm_obligation(
    *,
    client: Any | None,
    escrow_uid: str,
    ssh_public_key: str,
    oracle_address: str | None = None,
    order: str | dict[str, Any] | None = None,
    duration_seconds: int = 3600,
    listing_id: str | None = None,
    seller_order_id: str | None = None,
    chain_configs: dict[str, Any] | None = None,
    base_url: str | None = None,
    get_sqlite_client: SQLiteClientFactory,
    capacity: CapacityClientLike,
    stage_event: StageEventFn,
    close_stale_listings_after_capacity_change: CloseStaleListingsFn,
    provision_vm: ProvisionVmFn,
    schedule_shutdown: ScheduleShutdownFn,
    register_lease: RegisterLeaseFn,
    apply_failure_policy: ApplyFailurePolicyFn | None = None,
) -> dict[str, Any]:
    """Provision VM capacity and submit settlement fulfillment."""
    fulfillment_uid = None
    connection_details: str | None = None
    reserved_allocation_id: str | None = None
    reserved_resource_id: str | None = None
    reserved_vm_host: str | None = None
    vm_target = f"tenant-{uuid.uuid4().hex[:4]}"

    logger.info("[ALKAHEST] Order for fulfillment: %s", order)
    plan = build_vm_fulfillment_plan(
        order=order,
        duration_seconds=duration_seconds,
        chain_configs=chain_configs,
    )
    order_id = plan.order_id
    order_bytes = plan.order_bytes
    required_attributes = plan.required_attributes

    try:
        sqlite_client = get_sqlite_client()
        reserved = await capacity.reserve(
            claim=required_attributes or None,
            deal_ref={
                "listing_id": listing_id or order_id,
                "escrow_uid": escrow_uid,
            },
        )
        if not reserved:
            raise RuntimeError("No available compute VM matched required attributes")
        reserved_allocation_id = (
            str(reserved.get("allocation_id")) if reserved.get("allocation_id") else None
        )
        reserved_resource_id = str(reserved.get("resource_id"))
        reserved_vm_host = reserved.get("vm_host")
        if not reserved_vm_host:
            raise RuntimeError("Reserved resource missing vm_host")
        stage_event(
            "provision", "resource_reserved",
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
            closed_listing_ids = await close_stale_listings_after_capacity_change(
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
            stage_event(
                "provision", "job_submitted",
                listing_id=order_id,
                escrow_uid=escrow_uid,
                resource_id=reserved_resource_id,
                vm_host=reserved_vm_host,
                provisioning_job_id=job_id,
            )

        provision_result = await provision_vm(
            ssh_public_key,
            vm_host=reserved_vm_host,
            vm_target=vm_target,
            on_job_submitted=_record_job_id,
        )
        authentication: dict[str, Any] | None = None
        if isinstance(provision_result, dict):
            authentication = provision_result.pop("authentication", None)
            connection_details = json.dumps(provision_result)
        else:
            connection_details = provision_result
    except Exception as error:
        if apply_failure_policy is not None:
            try:
                await apply_failure_policy(
                    allocation_id=reserved_allocation_id,
                    escrow_uid=escrow_uid,
                    listing_id=listing_id or order_id,
                    resource_id=reserved_resource_id,
                    reason="provisioning_failed",
                    message=str(error),
                    source="settlement_provisioning",
                )
            except Exception as policy_err:
                logger.warning(
                    "[FULFILLMENT_POLICY] Failed to apply provisioning failure "
                    "policy for escrow %s: %s",
                    escrow_uid,
                    policy_err,
                )
        logger.error(
            "[ALKAHEST] Provisioning failed, skipping obligation fulfillment: %s",
            error,
        )
        stage_event(
            "provision", "failed",
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

    lease_end_utc = (
        datetime.now(timezone.utc) + timedelta(seconds=duration_seconds)
    ).strftime("%Y-%m-%d %H:%M")

    if reserved_resource_id:
        try:
            await capacity.commit(
                resource_id=reserved_resource_id,
                allocation_id=reserved_allocation_id,
                lease_end_utc=lease_end_utc,
                idempotency_ref=escrow_uid,
            )
        except Exception as lease_err:
            logger.warning(
                "[LOCAL DB] Failed to mark resource %s as leased after provisioning: %s",
                reserved_resource_id,
                lease_err,
            )

    cred_order_id = seller_order_id or order_id
    if authentication and cred_order_id:
        try:
            cred_client = get_sqlite_client()
            root_data = authentication.get("root", {}) or {}
            tenant_data = authentication.get("tenant", {}) or {}
            if root_data:
                await cred_client.store_credential(
                    listing_id=cred_order_id,
                    role="root",
                    granted_to="self",
                    password=root_data.get("password"),
                    ssh_commands=(
                        json.dumps(root_data.get("ssh_commands"))
                        if root_data.get("ssh_commands") else None
                    ),
                    ssh_key_path_host=root_data.get("ssh_key_path_host"),
                )
            if tenant_data:
                await cred_client.store_credential(
                    listing_id=cred_order_id,
                    role="tenant",
                    granted_to="self",
                    password=tenant_data.get("password"),
                    ssh_commands=(
                        json.dumps(tenant_data.get("ssh_commands"))
                        if tenant_data.get("ssh_commands") else None
                    ),
                    key_type=tenant_data.get("key_type"),
                )
        except Exception as cred_err:
            logger.warning(
                "[LOCAL DB] Failed to store credentials for order %s: %s",
                cred_order_id,
                cred_err,
            )

    if reserved_resource_id and reserved_vm_host and vm_target and escrow_uid:
        try:
            await register_lease(
                resource_id=reserved_resource_id,
                allocation_id=reserved_allocation_id,
                escrow_uid=escrow_uid,
                vm_host=reserved_vm_host,
                vm_target=vm_target,
                lease_end_utc=lease_end_utc,
            )
            logger.info(
                "[LEASE] Registered lease with provisioning service "
                "(resource=%s escrow=%s expires=%s)",
                reserved_resource_id, escrow_uid, lease_end_utc,
            )
        except Exception as lease_err:
            logger.warning(
                "[LEASE] Failed to register lease with provisioning service "
                "(resource=%s escrow=%s): %s - watchdog will not auto-release "
                "this resource",
                reserved_resource_id,
                escrow_uid,
                lease_err,
            )

    async def _schedule_shutdown_best_effort() -> None:
        try:
            await schedule_shutdown(
                lease_end_utc,
                vm_host=reserved_vm_host,
                vm_target=vm_target,
            )
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

    try:
        fulfillment_uid = await submit_compute_fulfillment(
            client=client,
            escrow_uid=escrow_uid,
            connection_details=connection_details,
            oracle_address=oracle_address,
            demand_bytes=order_bytes,
        )
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
        stage_event(
            "settlement", "failed_after_provisioning",
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
            logger.warning(
                "[LOCAL DB] Failed to update fulfillment for order %s: %s",
                order_id,
                exc,
            )
        if fulfillment_uid:
            try:
                await get_sqlite_client().update_escrow(
                    escrow_uid=escrow_uid,
                    fulfillment_uid=fulfillment_uid,
                )
            except Exception as exc:
                logger.warning(
                    "[LOCAL DB] Failed to record fulfillment_uid on escrow %s: %s",
                    escrow_uid,
                    exc,
                )

    tenant_auth = (authentication or {}).get("tenant", {}) or {}
    stage_event(
        "provision", "fulfilled",
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
        "fulfilling_party_url": base_url,
        "tenant_credentials": {
            "password": tenant_auth.get("password"),
            "key_type": tenant_auth.get("key_type"),
        },
    }
