"""VM provisioning-service client helpers."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)


async def provision_vm_and_wait(
    *,
    service_url: str,
    admin_key: str | None,
    timeout: float,
    poll_interval: float,
    ssh_public_key: str,
    vm_host: str,
    vm_target: str,
    frp_server_addr: str | None = None,
    frp_domain: str | None = None,
    frp_dashboard_password: str | None = None,
    on_job_submitted: Callable[[str], Awaitable[None]] | None = None,
) -> dict[str, Any]:
    """Submit a create-VM job, wait for completion, and fetch credentials."""
    from client.provisioning_client import ProvisioningClient
    from models.vm_request_model import CreateVmRequest

    client = ProvisioningClient(
        service_url,
        admin_key=admin_key,
        timeout=timeout,
    )
    async with client:
        params: dict[str, Any] = {
            "vm_target": vm_target,
            "ssh_pubkey": ssh_public_key,
        }
        if frp_server_addr:
            params["frp_server_addr"] = frp_server_addr
        if frp_domain:
            params["frp_domain"] = frp_domain
        if frp_dashboard_password:
            params["frp_dashboard_password"] = frp_dashboard_password

        submit = await client.create_vm(vm_host, CreateVmRequest(**params))
        if on_job_submitted is not None:
            try:
                await on_job_submitted(submit.job_id)
            except Exception as exc:
                logger.warning(
                    "[PROVISIONING] on_job_submitted callback failed for job %s: %s",
                    submit.job_id,
                    exc,
                )

        job = await client.poll_until_complete(
            submit.job_id,
            timeout=timeout,
            poll_interval=poll_interval,
        )
        result = job.result or {}
        try:
            creds_resp = await client.get_job_credentials(submit.job_id)
            auth: dict[str, Any] = {}
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
                submit.job_id,
                exc,
            )
    return result


async def schedule_vm_expiry_and_wait(
    *,
    service_url: str,
    admin_key: str | None,
    timeout: float,
    poll_interval: float,
    lease_end_utc: str,
    vm_host: str,
    vm_target: str,
) -> dict[str, Any]:
    """Schedule VM expiry and wait for the provisioning job to finish."""
    from client.provisioning_client import ProvisioningClient
    from models.vm_request_model import ScheduleVmExpiryRequest

    client = ProvisioningClient(
        service_url,
        admin_key=admin_key,
        timeout=timeout,
    )
    async with client:
        submit = await client.schedule_expiry(
            vm_host,
            vm_target,
            ScheduleVmExpiryRequest(vm_expiry_at=lease_end_utc),
        )
        job = await client.poll_until_complete(
            submit.job_id,
            timeout=timeout,
            poll_interval=poll_interval,
        )
    return job.result or {}


async def register_vm_lease(
    *,
    service_url: str,
    admin_key: str | None,
    timeout: float,
    resource_id: str,
    allocation_id: str | None,
    escrow_uid: str,
    vm_host: str,
    vm_target: str,
    lease_end_utc: datetime,
) -> Any:
    """Register a VM lease with the provisioning service watchdog."""
    from client.provisioning_client import ProvisioningClient

    async with ProvisioningClient(
        service_url,
        admin_key=admin_key,
        timeout=timeout,
    ) as prov_client:
        return await prov_client.register_lease(
            resource_id=resource_id,
            allocation_id=allocation_id,
            escrow_uid=escrow_uid,
            vm_host=vm_host,
            vm_target=vm_target,
            lease_end_utc=lease_end_utc,
        )
