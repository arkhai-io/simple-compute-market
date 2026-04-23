"""HTTP client for the provisioning service.

Importable as::

    from provisioning_service.client.provisioning_client import (
        ProvisioningClient,
        ProvisioningError,
        ProvisioningJobError,
        ProvisioningTimeoutError,
    )

This client is the canonical contract between the provisioning service and its
consumers.  The provisioning service integration tests import it directly, so
any drift between the client and the actual REST API is caught immediately.

Design principles
-----------------
* **Lightweight**: only ``aiohttp`` and ``pydantic`` — no server-side imports.
* **Mirror the REST API exactly**: one method per endpoint, URL structure
  matches ``/api/v1/hosts/{host}/vms/...``.
* **Typed**: request bodies use the same Pydantic models defined in
  ``models/vm_request_model.py`` and ``models/jobs_model.py``.  Consumers
  can build requests with autocomplete and validation before sending.

Polling pattern
---------------
All job-creating methods return a ``JobSubmitResponse`` (job_id + "queued").
Use ``poll_until_complete`` to block until the job reaches a terminal state,
or call ``get_job`` yourself for custom polling logic.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

import aiohttp

from models.jobs_model import (
    CredentialListResponse,
    JobListResponse,
    JobLogsResponse,
    JobStatusResponse,
    JobSubmitResponse,
)
from models.vm_request_model import (
    CreateVmRequest,
    ScheduleVmExpiryRequest,
    VmActionRequest,
    build_simple_params,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ProvisioningError(Exception):
    """Base class for provisioning client errors."""


class ProvisioningJobError(ProvisioningError):
    """A provisioning job reached terminal ``failed`` status."""


class ProvisioningTimeoutError(ProvisioningError):
    """Polling a provisioning job exceeded the configured timeout."""


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class ProvisioningClient:
    """Async HTTP client for the provisioning service REST API.

    Instantiate with the base URL of the service and an optional agent ID
    that is sent as ``X-Agent-ID`` on every mutating request::

        client = ProvisioningClient("http://provisioning:8081", agent_id="eip155:1:0x…:42")
        async with aiohttp.ClientSession() as session:
            response = await client.create_vm(session, "ww1", CreateVmRequest(...))
            result = await client.poll_until_complete(session, response.job_id)

    All methods accept an ``aiohttp.ClientSession`` rather than creating one
    internally so that the caller controls connection pooling and lifecycle.
    """

    def __init__(self, base_url: str, agent_id: Optional[str] = None) -> None:
        self._base = base_url.rstrip("/")
        self._agent_id = agent_id

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _headers(self, require_agent_id: bool = False) -> dict[str, str]:
        h: dict[str, str] = {}
        if self._agent_id:
            h["X-Agent-ID"] = self._agent_id
        elif require_agent_id:
            raise ProvisioningError(
                "X-Agent-ID is required for this endpoint but agent_id was not set"
            )
        return h

    async def _post(
        self,
        session: aiohttp.ClientSession,
        path: str,
        body: Any,
        *,
        require_agent_id: bool = False,
    ) -> dict:
        url = f"{self._base}{path}"
        payload = body.model_dump() if hasattr(body, "model_dump") else (body or {})
        async with session.post(url, json=payload, headers=self._headers(require_agent_id)) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def _delete(
        self,
        session: aiohttp.ClientSession,
        path: str,
        body: Any = None,
    ) -> dict:
        url = f"{self._base}{path}"
        payload = body.model_dump() if hasattr(body, "model_dump") else {}
        async with session.delete(url, json=payload, headers=self._headers()) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def _get(
        self,
        session: aiohttp.ClientSession,
        path: str,
        *,
        params: Optional[dict] = None,
        require_agent_id: bool = False,
    ) -> dict:
        url = f"{self._base}{path}"
        async with session.get(
            url, params=params, headers=self._headers(require_agent_id)
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    def _submit_response(self, data: dict) -> JobSubmitResponse:
        return JobSubmitResponse(**data)

    # ------------------------------------------------------------------
    # VM lifecycle
    # ------------------------------------------------------------------

    async def create_vm(
        self,
        session: aiohttp.ClientSession,
        host: str,
        body: CreateVmRequest,
    ) -> JobSubmitResponse:
        """``POST /api/v1/hosts/{host}/vms/``"""
        data = await self._post(session, f"/api/v1/hosts/{host}/vms/", body)
        return self._submit_response(data)

    async def list_vms(
        self,
        session: aiohttp.ClientSession,
        host: str,
        body: Optional[VmActionRequest] = None,
    ) -> JobSubmitResponse:
        """``GET /api/v1/hosts/{host}/vms/``"""
        data = await self._post(session, f"/api/v1/hosts/{host}/vms/", body or VmActionRequest())
        return self._submit_response(data)

    async def start_vm(
        self,
        session: aiohttp.ClientSession,
        host: str,
        vm_name: str,
        body: Optional[VmActionRequest] = None,
    ) -> JobSubmitResponse:
        """``POST /api/v1/hosts/{host}/vms/{vm_name}/start``"""
        data = await self._post(session, f"/api/v1/hosts/{host}/vms/{vm_name}/start", body or VmActionRequest())
        return self._submit_response(data)

    async def shutdown_vm(
        self,
        session: aiohttp.ClientSession,
        host: str,
        vm_name: str,
        body: Optional[VmActionRequest] = None,
    ) -> JobSubmitResponse:
        """``POST /api/v1/hosts/{host}/vms/{vm_name}/shutdown``"""
        data = await self._post(session, f"/api/v1/hosts/{host}/vms/{vm_name}/shutdown", body or VmActionRequest())
        return self._submit_response(data)

    async def reboot_vm(
        self,
        session: aiohttp.ClientSession,
        host: str,
        vm_name: str,
        body: Optional[VmActionRequest] = None,
    ) -> JobSubmitResponse:
        """``POST /api/v1/hosts/{host}/vms/{vm_name}/reboot``"""
        data = await self._post(session, f"/api/v1/hosts/{host}/vms/{vm_name}/reboot", body or VmActionRequest())
        return self._submit_response(data)

    async def destroy_vm(
        self,
        session: aiohttp.ClientSession,
        host: str,
        vm_name: str,
        body: Optional[VmActionRequest] = None,
    ) -> JobSubmitResponse:
        """``POST /api/v1/hosts/{host}/vms/{vm_name}/destroy``"""
        data = await self._post(session, f"/api/v1/hosts/{host}/vms/{vm_name}/destroy", body or VmActionRequest())
        return self._submit_response(data)

    async def undefine_vm(
        self,
        session: aiohttp.ClientSession,
        host: str,
        vm_name: str,
        body: Optional[VmActionRequest] = None,
    ) -> JobSubmitResponse:
        """``POST /api/v1/hosts/{host}/vms/{vm_name}/undefine``"""
        data = await self._post(session, f"/api/v1/hosts/{host}/vms/{vm_name}/undefine", body or VmActionRequest())
        return self._submit_response(data)

    async def monitor_vm(
        self,
        session: aiohttp.ClientSession,
        host: str,
        vm_name: str,
    ) -> JobSubmitResponse:
        """``GET /api/v1/hosts/{host}/vms/{vm_name}/monitor``"""
        data = await self._get(session, f"/api/v1/hosts/{host}/vms/{vm_name}/monitor")
        return self._submit_response(data)

    async def reset_password(
        self,
        session: aiohttp.ClientSession,
        host: str,
        vm_name: str,
        body: Optional[VmActionRequest] = None,
    ) -> JobSubmitResponse:
        """``POST /api/v1/hosts/{host}/vms/{vm_name}/reset-password``"""
        data = await self._post(session, f"/api/v1/hosts/{host}/vms/{vm_name}/reset-password", body or VmActionRequest())
        return self._submit_response(data)

    async def schedule_expiry(
        self,
        session: aiohttp.ClientSession,
        host: str,
        vm_name: str,
        body: ScheduleVmExpiryRequest,
    ) -> JobSubmitResponse:
        """``POST /api/v1/hosts/{host}/vms/{vm_name}/expiry``"""
        data = await self._post(session, f"/api/v1/hosts/{host}/vms/{vm_name}/expiry", body)
        return self._submit_response(data)

    async def cancel_expiry(
        self,
        session: aiohttp.ClientSession,
        host: str,
        vm_name: str,
        body: Optional[VmActionRequest] = None,
    ) -> JobSubmitResponse:
        """``DELETE /api/v1/hosts/{host}/vms/{vm_name}/expiry``"""
        data = await self._delete(session, f"/api/v1/hosts/{host}/vms/{vm_name}/expiry", body or VmActionRequest())
        return self._submit_response(data)

    # ------------------------------------------------------------------
    # Host operations
    # ------------------------------------------------------------------

    async def check_capacity(
        self,
        session: aiohttp.ClientSession,
        host: str,
    ) -> JobSubmitResponse:
        """``GET /api/v1/hosts/{host}/capacity``"""
        data = await self._get(session, f"/api/v1/hosts/{host}/capacity")
        return self._submit_response(data)

    # ------------------------------------------------------------------
    # Job operations
    # ------------------------------------------------------------------

    async def get_job(
        self,
        session: aiohttp.ClientSession,
        job_id: str,
    ) -> JobStatusResponse:
        """``GET /api/v1/jobs/{job_id}``"""
        data = await self._get(session, f"/api/v1/jobs/{job_id}")
        return JobStatusResponse(**data)

    async def get_job_credentials(
        self,
        session: aiohttp.ClientSession,
        job_id: str,
    ) -> CredentialListResponse:
        """``GET /api/v1/jobs/{job_id}/credentials``

        Requires ``agent_id`` to be set on the client.
        """
        data = await self._get(
            session, f"/api/v1/jobs/{job_id}/credentials", require_agent_id=True
        )
        return CredentialListResponse(**data)

    async def get_job_logs(
        self,
        session: aiohttp.ClientSession,
        job_id: str,
    ) -> JobLogsResponse:
        """``GET /api/v1/jobs/{job_id}/logs``"""
        data = await self._get(session, f"/api/v1/jobs/{job_id}/logs")
        return JobLogsResponse(**data)

    async def cancel_job(
        self,
        session: aiohttp.ClientSession,
        job_id: str,
    ) -> dict:
        """``POST /api/v1/jobs/{job_id}/cancel``"""
        return await self._post(session, f"/api/v1/jobs/{job_id}/cancel", {})

    async def list_jobs(
        self,
        session: aiohttp.ClientSession,
        *,
        status: Optional[str] = None,
        offset: int = 0,
        limit: int = 20,
    ) -> JobListResponse:
        """``GET /api/v1/jobs/``"""
        params: dict[str, Any] = {"offset": offset, "limit": limit}
        if status:
            params["status"] = status
        data = await self._get(session, "/api/v1/jobs/", params=params)
        return JobListResponse(**data)

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    async def poll_until_complete(
        self,
        session: aiohttp.ClientSession,
        job_id: str,
        *,
        timeout: float = 3600.0,
        poll_interval: float = 5.0,
    ) -> JobStatusResponse:
        """Poll ``GET /api/v1/jobs/{job_id}`` until the job reaches a terminal state.

        Returns the final ``JobStatusResponse`` on ``succeeded``.
        Raises ``ProvisioningJobError`` on ``failed``.
        Raises ``ProvisioningTimeoutError`` if ``timeout`` seconds elapse
        before a terminal state is reached.
        """
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            job = await self.get_job(session, job_id)
            if job.status == "succeeded":
                return job
            if job.status == "failed":
                raise ProvisioningJobError(
                    f"Job {job_id} failed: {job.error or 'unknown error'}"
                )
            if job.status == "cancelled":
                raise ProvisioningJobError(f"Job {job_id} was cancelled")
            if asyncio.get_event_loop().time() >= deadline:
                raise ProvisioningTimeoutError(
                    f"Job {job_id} did not complete within {timeout}s "
                    f"(current status: {job.status})"
                )
            await asyncio.sleep(poll_interval)


# ---------------------------------------------------------------------------
# Module-level convenience wrappers
#
# These preserve the calling convention of the old service.clients.provisioning
# module so agent-side call sites need only change their import path, not
# their call sites.  Each wrapper creates a single-use aiohttp.ClientSession
# internally, mirroring the old behaviour.
#
# TODO(action_executor_refactor): Replace these wrappers with direct use of
# ProvisioningClient in core/agent/app/utils/action_executor.py.  The class
# interface is cleaner: caller controls session lifecycle, and the typed
# create_vm / schedule_expiry methods replace the raw params dict.
# ---------------------------------------------------------------------------


async def provision_machine_async(
    provisioning_service_url: str,
    params: dict[str, Any],
    *,
    timeout: int = 3600,
    poll_interval: int = 15,
    agent_id: Optional[str] = None,
) -> dict[str, Any]:
    """Submit a create VM job and poll until succeeded.

    Returns the job result dict on success.
    Raises ``ProvisioningJobError`` on failure, ``ProvisioningTimeoutError`` on timeout.
    """
    from models.vm_request_model import CreateVmRequest
    host = params.get("vm_host", "ww1")
    body = CreateVmRequest(**{k: v for k, v in params.items() if k != "vm_host"})
    client = ProvisioningClient(provisioning_service_url, agent_id=agent_id)
    async with aiohttp.ClientSession() as session:
        submit = await client.create_vm(session, host, body)
        job = await client.poll_until_complete(
            session, submit.job_id,
            timeout=float(timeout), poll_interval=float(poll_interval),
        )
    return job.result or {}


async def provision_machine_async_with_id(
    provisioning_service_url: str,
    params: dict[str, Any],
    *,
    timeout: int = 3600,
    poll_interval: int = 15,
    agent_id: Optional[str] = None,
) -> tuple[str, dict[str, Any]]:
    """Submit a create VM job and poll until succeeded.  Returns (job_id, result)."""
    from models.vm_request_model import CreateVmRequest
    host = params.get("vm_host", "ww1")
    body = CreateVmRequest(**{k: v for k, v in params.items() if k != "vm_host"})
    client = ProvisioningClient(provisioning_service_url, agent_id=agent_id)
    async with aiohttp.ClientSession() as session:
        submit = await client.create_vm(session, host, body)
        job = await client.poll_until_complete(
            session, submit.job_id,
            timeout=float(timeout), poll_interval=float(poll_interval),
        )
    return submit.job_id, job.result or {}


async def schedule_vm_expiry_async(
    provisioning_service_url: str,
    vm_expiry_at: str,
    vm_host: str = "ww1",
    vm_target: str = "tenant-vm",
    *,
    timeout: int = 300,
    poll_interval: int = 5,
    agent_id: Optional[str] = None,
) -> dict[str, Any]:
    """Schedule VM expiry via ``POST /api/v1/hosts/{host}/vms/{vm}/expiry``."""
    from models.vm_request_model import ScheduleVmExpiryRequest
    body = ScheduleVmExpiryRequest(vm_expiry_at=vm_expiry_at)
    client = ProvisioningClient(provisioning_service_url, agent_id=agent_id)
    async with aiohttp.ClientSession() as session:
        submit = await client.schedule_expiry(session, vm_host, vm_target, body)
        job = await client.poll_until_complete(
            session, submit.job_id,
            timeout=float(timeout), poll_interval=float(poll_interval),
        )
    return job.result or {}


# Backward-compat alias — callers using the old name still work.
schedule_vm_shutdown_async = schedule_vm_expiry_async


async def get_vm_available_resources(
    provisioning_service_url: str,
    vm_host: str = "ww1",
    *,
    timeout: int = 120,
    poll_interval: int = 5,
    agent_id: Optional[str] = None,
) -> dict[str, Any]:
    """Check host capacity via ``GET /api/v1/hosts/{host}/capacity``."""
    client = ProvisioningClient(provisioning_service_url, agent_id=agent_id)
    async with aiohttp.ClientSession() as session:
        submit = await client.check_capacity(session, vm_host)
        job = await client.poll_until_complete(
            session, submit.job_id,
            timeout=float(timeout), poll_interval=float(poll_interval),
        )
    result = job.result or {}
    available = result.get("available", {})
    allocated = result.get("allocated", {})
    if not isinstance(available, dict):
        return result
    return {
        "available": available.get("gpus", 0) > 0,
        "running_vms": allocated.get("gpus", 0),
        "available_gpus": available.get("gpus", 0),
        "available_vcpus": available.get("vcpus", 0),
        "available_ram_mb": available.get("ram_mb", 0),
    }


async def get_job_credentials_async(
    service_url: str,
    job_id: str,
    agent_id: str,
) -> dict | None:
    """Fetch credentials for a completed job."""
    client = ProvisioningClient(service_url, agent_id=agent_id)
    async with aiohttp.ClientSession() as session:
        try:
            creds_resp = await client.get_job_credentials(session, job_id)
        except Exception as exc:
            logger.warning("[PROVISIONING] Failed to fetch credentials for job %s: %s", job_id, exc)
            return None
    auth: dict[str, dict] = {}
    for c in creds_resp.credentials:
        if c.role:
            auth[c.role] = {
                "password": c.password,
                "ssh_commands": c.ssh_commands,
                "ssh_key_path_host": c.ssh_key_path_host,
                "key_type": c.key_type,
            }
    return auth or None
