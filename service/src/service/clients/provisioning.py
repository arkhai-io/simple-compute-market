"""HTTP client for the async-provisioning-service (port 8085)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

_VM_CREATE_FIELDS = ("ssh_command", "ssh_port", "tenant_user", "vm_host_ip")


def _normalize_vm_create_result(result: dict[str, Any]) -> dict[str, Any]:
    """Strip verbose ansible/frp/gpu fields from a VM create result.

    Returns a compact dict matching the ansible_provisioning shape:
      ssh_command, ssh_port, tenant_user, vm_host_ip [, authentication, status, vm_name]

    Falls back to the full dict if none of the expected connection fields are
    present — this covers check/lease_end results that have a different structure.
    """
    if not any(result.get(k) for k in _VM_CREATE_FIELDS):
        return result

    compact: dict[str, Any] = {k: result.get(k) for k in _VM_CREATE_FIELDS}

    # Prefer FRP hostname as vm_host_ip — public tunnel reachable by the buyer.
    frp = result.get("frp") or {}
    if isinstance(frp, dict) and frp.get("domain"):
        compact["vm_host_ip"] = frp["domain"]

    # authentication must survive so action_executor can pop it as credentials.
    if result.get("authentication") is not None:
        compact["authentication"] = result["authentication"]

    # Lightweight context fields.
    for key in ("status", "vm_name"):
        if result.get(key):
            compact[key] = result[key]

    return {k: v for k, v in compact.items() if v is not None}


class ProvisioningError(Exception):
    """Base class for provisioning errors."""


class ProvisioningJobError(ProvisioningError):
    """Raised when a provisioning job terminates in a failed state."""


class ProvisioningTimeoutError(ProvisioningError):
    """Raised when polling a provisioning job exceeds the timeout."""


async def _submit_job(
    session: aiohttp.ClientSession,
    service_url: str,
    params: dict[str, Any],
    agent_id: str | None,
) -> str:
    """POST /api/v1/jobs and return the job_id."""
    headers = {}
    if agent_id:
        headers["X-Agent-ID"] = agent_id
    url = f"{service_url.rstrip('/')}/api/v1/jobs"
    async with session.post(url, json=params, headers=headers) as resp:
        resp.raise_for_status()
        data = await resp.json()
        job_id = data.get("job_id") or data.get("id")
        if not job_id:
            raise ProvisioningError(f"No job_id in response: {data}")
        return str(job_id)


async def _poll_job(
    session: aiohttp.ClientSession,
    service_url: str,
    job_id: str,
    *,
    timeout: int,
    poll_interval: int,
    agent_id: str | None,
) -> dict[str, Any]:
    """Poll GET /api/v1/jobs/{job_id} until terminal state. Returns result dict."""
    headers = {}
    if agent_id:
        headers["X-Agent-ID"] = agent_id
    url = f"{service_url.rstrip('/')}/api/v1/jobs/{job_id}"
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        async with session.get(url, headers=headers) as resp:
            resp.raise_for_status()
            data = await resp.json()
        status = data.get("status", "")
        if status == "succeeded":
            return data.get("result") or data
        if status == "failed":
            reason = data.get("error") or data.get("message") or "unknown"
            raise ProvisioningJobError(f"Job {job_id} failed: {reason}")
        # queued / running — keep polling
        if asyncio.get_event_loop().time() >= deadline:
            raise ProvisioningTimeoutError(
                f"Job {job_id} did not complete within {timeout}s (status={status})"
            )
        await asyncio.sleep(poll_interval)


async def provision_machine_async(
    provisioning_service_url: str,
    params: dict[str, Any],
    *,
    timeout: int = 3600,
    poll_interval: int = 15,
    agent_id: str | None = None,
) -> dict[str, Any]:
    """POST /api/v1/jobs and poll until succeeded.

    Returns connection details dict with: ssh_command, ssh_port, tenant_user, vm_host_ip.
    Raises ProvisioningJobError on terminal failure, ProvisioningTimeoutError on timeout.
    """
    async with aiohttp.ClientSession() as session:
        job_id = await _submit_job(session, provisioning_service_url, params, agent_id)
        logger.info("[PROVISIONING] Submitted job %s to %s", job_id, provisioning_service_url)
        result = await _poll_job(
            session,
            provisioning_service_url,
            job_id,
            timeout=timeout,
            poll_interval=poll_interval,
            agent_id=agent_id,
        )
    logger.info("[PROVISIONING] Job %s completed successfully", job_id)
    return _normalize_vm_create_result(result)


async def schedule_vm_shutdown_async(
    provisioning_service_url: str,
    lease_end_utc: str,
    vm_host: str = "ww1",
    vm_target: str = "tenant-vm",
    *,
    timeout: int = 300,
    poll_interval: int = 5,
    agent_id: str | None = None,
) -> dict[str, Any]:
    """POST /api/v1/jobs with vm_action=lease_end and poll until succeeded."""
    params = {
        "vm_host": vm_host,
        "vm_target": vm_target,
        "vm_action": "lease_end",
        "vm_lease_end": lease_end_utc,
    }
    return await provision_machine_async(
        provisioning_service_url,
        params,
        timeout=timeout,
        poll_interval=poll_interval,
        agent_id=agent_id,
    )


async def get_vm_available_resources(
    provisioning_service_url: str,
    vm_host: str = "ww1",
    *,
    timeout: int = 120,
    poll_interval: int = 5,
    agent_id: str | None = None,
) -> dict[str, Any]:
    """POST /api/v1/jobs with vm_action=check and poll for inventory result.

    Normalises the nested Ansible check_data response to the flat shape that
    resource_poller._poll_once expects:
      - ``available`` (bool): True if any GPU slots are free
      - ``running_vms`` (int): number of allocated GPUs (proxy for active VMs)
    Additional keys (available_gpus, available_vcpus, available_ram_mb) are
    included for callers that want richer inventory data.
    """
    params = {
        "vm_host": vm_host,
        "vm_action": "check",
    }
    result = await provision_machine_async(
        provisioning_service_url,
        params,
        timeout=timeout,
        poll_interval=poll_interval,
        agent_id=agent_id,
    )
    available = result.get("available", {})
    allocated = result.get("allocated", {})
    if not isinstance(available, dict):
        # Already normalised (e.g. from a future API change or test stub)
        return result
    return {
        "available": available.get("gpus", 0) > 0,
        "running_vms": allocated.get("gpus", 0),
        "available_gpus": available.get("gpus", 0),
        "available_vcpus": available.get("vcpus", 0),
        "available_ram_mb": available.get("ram_mb", 0),
    }
