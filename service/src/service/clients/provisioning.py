"""HTTP client for the async-provisioning-service (port 8085)."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import aiohttp
from service.clients.erc8004.blockchain import build_erc8004_canonical_id

logger = logging.getLogger(__name__)

_VM_CREATE_FIELDS = ("ssh_command", "ssh_port", "tenant_user", "vm_host_ip")
_CHAIN_IDS = {
    "anvil": 31337,
    "base_sepolia": 84532,
    "ethereum_sepolia": 11155111,
    "ethereum_mainnet": 1,
}


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


def _canonicalize_agent_id(agent_id: str | None) -> str | None:
    if not agent_id or agent_id.startswith("eip155:"):
        return agent_id

    identity_registry = os.getenv("IDENTITY_REGISTRY_ADDRESS")
    if not identity_registry:
        return agent_id

    try:
        numeric_id = int(agent_id)
    except ValueError:
        return agent_id

    chain_id: int | None = None
    chain_id_env = os.getenv("CHAIN_ID")
    if chain_id_env:
        try:
            chain_id = int(chain_id_env)
        except ValueError:
            chain_id = None
    if chain_id is None:
        chain_name = os.getenv("CHAIN_NAME", "").lower() or os.getenv("ALKAHEST_NETWORK", "").lower()
        chain_id = _CHAIN_IDS.get(chain_name)
    if chain_id is None:
        return agent_id

    return build_erc8004_canonical_id(chain_id, identity_registry, numeric_id)


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
    resolved_agent_id = _canonicalize_agent_id(agent_id)
    if resolved_agent_id:
        headers["X-Agent-ID"] = resolved_agent_id
    payload = dict(params)
    buyer_agent_id = payload.get("buyer_agent_id")
    if isinstance(buyer_agent_id, str):
        payload["buyer_agent_id"] = _canonicalize_agent_id(buyer_agent_id)
    url = f"{service_url.rstrip('/')}/api/v1/jobs"
    async with session.post(url, json=payload, headers=headers) as resp:
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
    resolved_agent_id = _canonicalize_agent_id(agent_id)
    if resolved_agent_id:
        headers["X-Agent-ID"] = resolved_agent_id
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
