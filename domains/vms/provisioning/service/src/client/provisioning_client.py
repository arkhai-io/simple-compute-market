"""HTTP clients for the provisioning service REST API.

Two clients with identical method signatures:

``ProvisioningClient``      — async, backed by ``httpx.AsyncClient``
``SyncProvisioningClient``  — sync,  backed by ``httpx.Client``

Both clients:
- Own their HTTP session internally — callers never create or pass a session
- Accept a ``transport=`` kwarg at construction for in-process test injection
- Send ``X-Admin-Key`` on every request when ``admin_key`` is set
- Send ``X-Agent-ID`` on every request when ``agent_id`` is set
- Raise ``ProvisioningError`` on non-2xx responses
- Return typed model objects from all methods

Usage (async)::

    client = ProvisioningClient("http://provisioning:8081", admin_key="…")
    async with client:
        submit = await client.create_vm("kvm1", CreateVmRequest(...))
        result = await client.poll_until_complete(submit.job_id)

Usage (sync, e.g. smoke tests)::

    client = SyncProvisioningClient("http://provisioning:8081")
    hosts = client.list_hosts()
    client.close()

Polling pattern
---------------
All job-creating methods return a ``JobSubmitResponse`` (job_id + status).
Use ``poll_until_complete`` / ``sync_poll_until_complete`` to block until the
job reaches a terminal state, or call ``get_job`` for custom polling logic.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Optional

import httpx

from models.host_model import (
    HostConnectivityResponse,
    HostCreate,
    HostListResponse,
    HostResponse,
    HostUpdate,
)
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
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ProvisioningError(Exception):
    """Base class for provisioning client errors."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ProvisioningJobError(ProvisioningError):
    """A provisioning job reached terminal ``failed`` status."""


class ProvisioningTimeoutError(ProvisioningError):
    """Polling a provisioning job exceeded the configured timeout."""


# ---------------------------------------------------------------------------
# Shared base
# ---------------------------------------------------------------------------


class _ProvisioningClientBase:
    def __init__(
        self,
        base_url: str,
        admin_key: Optional[str],
        timeout: float,
        agent_id: Optional[str] = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._admin_key = admin_key
        self._agent_id = agent_id
        self._timeout = timeout

    def _url(self, path: str) -> str:
        return f"{self._base}{path}"

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {}
        if self._admin_key:
            h["X-Admin-Key"] = self._admin_key
        if self._agent_id:
            h["X-Agent-ID"] = self._agent_id
        return h

    @staticmethod
    def _raise_for_status(method: str, url: str, status: int, text: str) -> None:
        if status not in range(200, 300):
            raise ProvisioningError(
                f"{method} {url} → HTTP {status}\n{text[:500]}", status_code=status
            )

    @staticmethod
    def _submit(data: dict) -> JobSubmitResponse:
        return JobSubmitResponse(**data)


# ---------------------------------------------------------------------------
# Async client
# ---------------------------------------------------------------------------


class ProvisioningClient(_ProvisioningClientBase):
    """Async HTTP client for the provisioning service REST API.

    Parameters
    ----------
    base_url:
        Base URL of the provisioning service.
    admin_key:
        Shared operator admin key sent as ``X-Admin-Key`` on every request
        (the storefront's ``admin_api_key``). ``None`` for local dev where
        the service runs with no key configured.
    agent_id:
        Operator-assigned agent identifier sent as ``X-Agent-ID`` when provisioning
        auth is enabled.
    timeout:
        HTTP timeout in seconds.
    transport:
        Optional ``httpx.AsyncBaseTransport`` for in-process test injection.
    """

    def __init__(
        self,
        base_url: str,
        admin_key: Optional[str] = None,
        agent_id: Optional[str] = None,
        *,
        timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(base_url, admin_key, timeout, agent_id)
        self._client = httpx.AsyncClient(
            base_url=self._base,
            timeout=timeout,
            transport=transport,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "ProvisioningClient":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    async def _get(self, path: str, *, params: dict | None = None) -> dict:
        url = self._url(path)
        resp = await self._client.get(
            path, params=params, headers=self._headers()
        )
        self._raise_for_status("GET", url, resp.status_code, resp.text)
        return resp.json()

    async def _post(self, path: str, body: Any) -> dict:
        url = self._url(path)
        payload = body.model_dump(exclude_none=True) if hasattr(body, "model_dump") else (body or {})
        resp = await self._client.post(
            path, json=payload, headers=self._headers()
        )
        self._raise_for_status("POST", url, resp.status_code, resp.text)
        return resp.json()

    async def _put(self, path: str, body: Any) -> dict:
        url = self._url(path)
        payload = body.model_dump(exclude_none=True) if hasattr(body, "model_dump") else (body or {})
        resp = await self._client.put(path, json=payload, headers=self._headers())
        self._raise_for_status("PUT", url, resp.status_code, resp.text)
        return resp.json()

    async def _delete(self, path: str, body: Any = None) -> dict:
        url = self._url(path)
        import json as _json
        payload = body.model_dump(exclude_none=True) if hasattr(body, "model_dump") else {}
        resp = await self._client.request(
            "DELETE", path,
            content=_json.dumps(payload).encode() if payload else None,
            headers={**self._headers(), "Content-Type": "application/json"},
        )
        self._raise_for_status("DELETE", url, resp.status_code, resp.text)
        return resp.json()

    async def _patch(self, path: str, body: Any) -> dict:
        url = self._url(path)
        payload = body.model_dump(exclude_none=True) if hasattr(body, "model_dump") else (body or {})
        resp = await self._client.patch(path, json=payload, headers=self._headers())
        self._raise_for_status("PATCH", url, resp.status_code, resp.text)
        return resp.json()

    async def _post_multipart(self, path: str, files: dict, data: dict) -> dict:
        url = self._url(path)
        resp = await self._client.post(
            path, files=files, data=data, headers=self._headers()
        )
        self._raise_for_status("POST", url, resp.status_code, resp.text)
        return resp.json()

    # ------------------------------------------------------------------
    # VM lifecycle
    # ------------------------------------------------------------------

    async def create_vm(self, host: str, body: CreateVmRequest) -> JobSubmitResponse:
        """POST /api/v1/hosts/{host}/vms/"""
        return self._submit(await self._post(f"/api/v1/hosts/{host}/vms/", body))

    async def list_vms(self, host: str, body: Optional[VmActionRequest] = None) -> JobSubmitResponse:
        """POST /api/v1/hosts/{host}/vms/ (list action)"""
        return self._submit(await self._post(f"/api/v1/hosts/{host}/vms/", body or VmActionRequest()))

    async def start_vm(self, host: str, vm_name: str, body: Optional[VmActionRequest] = None) -> JobSubmitResponse:
        """POST /api/v1/hosts/{host}/vms/{vm_name}/start"""
        return self._submit(await self._post(f"/api/v1/hosts/{host}/vms/{vm_name}/start", body or VmActionRequest()))

    async def shutdown_vm(self, host: str, vm_name: str, body: Optional[VmActionRequest] = None) -> JobSubmitResponse:
        """POST /api/v1/hosts/{host}/vms/{vm_name}/shutdown"""
        return self._submit(await self._post(f"/api/v1/hosts/{host}/vms/{vm_name}/shutdown", body or VmActionRequest()))

    async def reboot_vm(self, host: str, vm_name: str, body: Optional[VmActionRequest] = None) -> JobSubmitResponse:
        """POST /api/v1/hosts/{host}/vms/{vm_name}/reboot"""
        return self._submit(await self._post(f"/api/v1/hosts/{host}/vms/{vm_name}/reboot", body or VmActionRequest()))

    async def destroy_vm(self, host: str, vm_name: str, body: Optional[VmActionRequest] = None) -> JobSubmitResponse:
        """POST /api/v1/hosts/{host}/vms/{vm_name}/destroy"""
        return self._submit(await self._post(f"/api/v1/hosts/{host}/vms/{vm_name}/destroy", body or VmActionRequest()))

    async def undefine_vm(self, host: str, vm_name: str, body: Optional[VmActionRequest] = None) -> JobSubmitResponse:
        """POST /api/v1/hosts/{host}/vms/{vm_name}/undefine"""
        return self._submit(await self._post(f"/api/v1/hosts/{host}/vms/{vm_name}/undefine", body or VmActionRequest()))

    async def monitor_vm(self, host: str, vm_name: str) -> JobSubmitResponse:
        """GET /api/v1/hosts/{host}/vms/{vm_name}/monitor"""
        return self._submit(await self._get(f"/api/v1/hosts/{host}/vms/{vm_name}/monitor"))

    async def reset_password(self, host: str, vm_name: str, body: Optional[VmActionRequest] = None) -> JobSubmitResponse:
        """POST /api/v1/hosts/{host}/vms/{vm_name}/reset-password"""
        return self._submit(await self._post(f"/api/v1/hosts/{host}/vms/{vm_name}/reset-password", body or VmActionRequest()))

    async def schedule_expiry(self, host: str, vm_name: str, body: ScheduleVmExpiryRequest) -> JobSubmitResponse:
        """POST /api/v1/hosts/{host}/vms/{vm_name}/expiry"""
        return self._submit(await self._post(f"/api/v1/hosts/{host}/vms/{vm_name}/expiry", body))

    async def cancel_expiry(self, host: str, vm_name: str, body: Optional[VmActionRequest] = None) -> JobSubmitResponse:
        """DELETE /api/v1/hosts/{host}/vms/{vm_name}/expiry"""
        return self._submit(await self._delete(f"/api/v1/hosts/{host}/vms/{vm_name}/expiry", body or VmActionRequest()))

    async def check_capacity(self, host: str) -> JobSubmitResponse:
        """GET /api/v1/hosts/{host}/capacity"""
        return self._submit(await self._get(f"/api/v1/hosts/{host}/capacity"))

    # ------------------------------------------------------------------
    # Host operations
    # ------------------------------------------------------------------

    async def list_hosts(self, *, search: Optional[str] = None,
                         include_disabled: bool = False) -> HostListResponse:
        """GET /api/v1/hosts/"""
        params: dict[str, Any] = {}
        if search:
            params["search"] = search
        if include_disabled:
            params["include_disabled"] = "true"
        return HostListResponse(**(await self._get("/api/v1/hosts/", params=params or None)))

    async def get_host(self, name: str) -> HostResponse:
        """GET /api/v1/hosts/{name}"""
        return HostResponse(**(await self._get(f"/api/v1/hosts/{name}")))

    async def register_host(self, body: HostCreate) -> HostResponse:
        """POST /api/v1/hosts/"""
        return HostResponse(**(await self._post("/api/v1/hosts/", body)))

    async def update_host(self, name: str, body: HostUpdate) -> HostResponse:
        """PUT /api/v1/hosts/{name}"""
        return HostResponse(**(await self._put(f"/api/v1/hosts/{name}", body)))

    async def enable_host(self, name: str) -> HostResponse:
        """POST /api/v1/hosts/{name}/enable"""
        return HostResponse(**(await self._post(f"/api/v1/hosts/{name}/enable", {})))

    async def disable_host(self, name: str) -> HostResponse:
        """POST /api/v1/hosts/{name}/disable"""
        return HostResponse(**(await self._post(f"/api/v1/hosts/{name}/disable", {})))

    async def check_connectivity(self, host: str) -> HostConnectivityResponse:
        """GET /api/v1/hosts/{host}/connectivity — run ansible -m ping.

        Always returns 200 with ``reachable=True/False`` — only raises on
        404 (host not registered) or unexpected server errors.
        """
        data = await self._get(f"/api/v1/hosts/{host}/connectivity")
        return HostConnectivityResponse.model_validate(data)

    async def import_hosts_from_path(self, path: Path, ssh_key_type: str = "path") -> HostListResponse:
        """POST /api/v1/hosts/import — upload an INI file from disk."""
        with open(path, "rb") as f:
            content = f.read()
        return HostListResponse(**(await self._post_multipart(
            "/api/v1/hosts/import",
            files={"file": (path.name, content, "text/plain")},
            data={"ssh_key_type": ssh_key_type},
        )))

    async def import_hosts_from_text(self, ini_text: str, ssh_key_type: str = "path",
                                     filename: str = "hosts") -> HostListResponse:
        """POST /api/v1/hosts/import — upload INI content from a string."""
        return HostListResponse(**(await self._post_multipart(
            "/api/v1/hosts/import",
            files={"file": (filename, ini_text.encode("utf-8"), "text/plain")},
            data={"ssh_key_type": ssh_key_type},
        )))

    # ------------------------------------------------------------------
    # System / readiness
    # ------------------------------------------------------------------

    async def get_health(self) -> dict:
        """GET /health — fast liveness probe (local checks only, no outbound HTTP).

        Returns ``{"status": "ok"|"degraded", "checks": {...}}``.
        """
        return await self._get("/health")

    async def get_system_status(self) -> dict:
        """GET /api/v1/system/status — full diagnostic status.

        Includes outbound HTTP probes against the storefront and lease watchdog
        state. Returns ``{"status": "ok"|"degraded", "checks": {...}}``.

        Accepts both 200 (all checks ok) and 503 (some checks degraded) as valid
        responses — 503 indicates a degraded but reachable service, not an error.
        """
        url = self._url("/api/v1/system/status")
        resp = await self._client.get("/api/v1/system/status", headers=self._headers())
        if resp.status_code not in (200, 503):
            self._raise_for_status("GET", url, resp.status_code, resp.text)
        return resp.json()

    async def get_ansible_readiness(self) -> dict:
        """GET /api/v1/system/ansible/readiness — Ansible config readiness check.

        Returns a dict with fields:
          - ansible_version: str | None
          - inventory: {source, path, exists, host_count}
          - playbook: {path, exists}
          - ssh_keys: list of SSH key diagnostic dicts

        Always returns 200 regardless of readiness state — check
        ``response["playbook"]["exists"]`` to confirm the provisioning
        service is correctly configured for the deal flow.
        """
        return await self._get("/api/v1/system/ansible/readiness")

    # ------------------------------------------------------------------
    # Job operations
    # ------------------------------------------------------------------

    async def get_job(self, job_id: str) -> JobStatusResponse:
        """GET /api/v1/jobs/{job_id}"""
        return JobStatusResponse(**(await self._get(f"/api/v1/jobs/{job_id}")))

    async def get_job_credentials(self, job_id: str) -> CredentialListResponse:
        """GET /api/v1/jobs/{job_id}/credentials — returns all job credentials."""
        return CredentialListResponse(**(await self._get(
            f"/api/v1/jobs/{job_id}/credentials"
        )))

    async def get_job_logs(self, job_id: str) -> JobLogsResponse:
        """GET /api/v1/jobs/{job_id}/logs"""
        return JobLogsResponse(**(await self._get(f"/api/v1/jobs/{job_id}/logs")))

    async def cancel_job(self, job_id: str) -> dict:
        """POST /api/v1/jobs/{job_id}/cancel"""
        return await self._post(f"/api/v1/jobs/{job_id}/cancel", {})

    async def list_jobs(self, *, status: Optional[str] = None,
                        offset: int = 0, limit: int = 20,
                        escrow_uid: Optional[str] = None) -> JobListResponse:
        """GET /api/v1/jobs/"""
        params: dict[str, Any] = {"offset": offset, "limit": limit}
        if status:
            params["status"] = status
        if escrow_uid:
            params["escrow_uid"] = escrow_uid
        return JobListResponse(**(await self._get("/api/v1/jobs/", params=params)))

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    async def poll_until_complete(
        self,
        job_id: str,
        *,
        timeout: float = 3600.0,
        poll_interval: float = 5.0,
    ) -> JobStatusResponse:
        """Poll GET /api/v1/jobs/{job_id} until terminal state.

        Returns the final ``JobStatusResponse`` on ``succeeded``.
        Raises ``ProvisioningJobError`` on ``failed`` or ``cancelled``.
        Raises ``ProvisioningTimeoutError`` if ``timeout`` seconds elapse.
        """
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            job = await self.get_job(job_id)
            if job.status == "succeeded":
                return job
            if job.status in ("failed", "cancelled"):
                raise ProvisioningJobError(
                    f"Job {job_id} {job.status}: {job.error or 'unknown error'}"
                )
            if asyncio.get_event_loop().time() >= deadline:
                raise ProvisioningTimeoutError(
                    f"Job {job_id} did not complete within {timeout}s "
                    f"(current status: {job.status})"
                )
            await asyncio.sleep(poll_interval)

    # ------------------------------------------------------------------
    # Leases
    # ------------------------------------------------------------------

    async def register_lease(
        self,
        *,
        resource_id: str,
        escrow_uid: str,
        vm_host: str,
        vm_target: str,
        lease_end_utc,
        lease_start_utc=None,
        create_job_id: Optional[str] = None,
        allocation_id: Optional[str] = None,
    ) -> dict:
        """POST /api/v1/leases — register a new VM lease."""
        body: dict = {
            "resource_id": resource_id,
            "escrow_uid": escrow_uid,
            "vm_host": vm_host,
            "vm_target": vm_target,
            "lease_end_utc": lease_end_utc.isoformat() if hasattr(lease_end_utc, "isoformat") else str(lease_end_utc),
        }
        if allocation_id is not None:
            body["allocation_id"] = allocation_id
        if lease_start_utc is not None:
            body["lease_start_utc"] = lease_start_utc.isoformat() if hasattr(lease_start_utc, "isoformat") else str(lease_start_utc)
        if create_job_id is not None:
            body["create_job_id"] = create_job_id
        return await self._post("/api/v1/leases/", body)

    async def list_leases(
        self,
        *,
        status: Optional[str] = None,
        vm_host: Optional[str] = None,
        escrow_uid: Optional[str] = None,
    ) -> dict:
        """GET /api/v1/leases — list leases with optional filters."""
        params: dict = {}
        if status is not None:
            params["status"] = status
        if vm_host is not None:
            params["vm_host"] = vm_host
        if escrow_uid is not None:
            params["escrow_uid"] = escrow_uid
        return await self._get("/api/v1/leases/", params=params)

    async def get_lease(self, lease_id: str) -> dict:
        """GET /api/v1/leases/{lease_id} — fetch one lease by internal ID."""
        return await self._get(f"/api/v1/leases/{lease_id}")

    async def get_lease_by_escrow(self, escrow_uid: str) -> dict:
        """GET /api/v1/leases/by-escrow/{escrow_uid} — fetch lease by escrow UID."""
        return await self._get(f"/api/v1/leases/by-escrow/{escrow_uid}")

    async def update_lease(self, lease_id: str, **kwargs) -> dict:
        """PATCH /api/v1/leases/{lease_id} — partial update."""
        return await self._patch(f"/api/v1/leases/{lease_id}", kwargs)

    async def cancel_lease(self, lease_id: str) -> dict:
        """DELETE /api/v1/leases/{lease_id}/cancel — cancel before expiry."""
        return await self._delete(f"/api/v1/leases/{lease_id}/cancel")


class SyncProvisioningClient(_ProvisioningClientBase):
    """Synchronous HTTP client for the provisioning service REST API.

    Identical method signatures to ``ProvisioningClient`` but blocking.
    Suitable for synchronous smoke tests and scripts.

    Parameters
    ----------
    base_url:
        Base URL of the provisioning service.
    admin_key:
        Shared operator admin key sent as ``X-Admin-Key`` on every request
        (the storefront's ``admin_api_key``). ``None`` for local dev.
    agent_id:
        Operator-assigned agent identifier sent as ``X-Agent-ID`` when provisioning
        auth is enabled.
    timeout:
        HTTP timeout in seconds.
    transport:
        Optional ``httpx.BaseTransport`` for in-process test injection.
    """

    def __init__(
        self,
        base_url: str,
        admin_key: Optional[str] = None,
        agent_id: Optional[str] = None,
        *,
        timeout: float = 60.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        super().__init__(base_url, admin_key, timeout, agent_id)
        self._client = httpx.Client(
            base_url=self._base,
            timeout=timeout,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "SyncProvisioningClient":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def _get(self, path: str, *, params: dict | None = None) -> dict:
        url = self._url(path)
        resp = self._client.get(path, params=params, headers=self._headers())
        self._raise_for_status("GET", url, resp.status_code, resp.text)
        return resp.json()

    def _post(self, path: str, body: Any) -> dict:
        url = self._url(path)
        payload = body.model_dump(exclude_none=True) if hasattr(body, "model_dump") else (body or {})
        resp = self._client.post(path, json=payload, headers=self._headers())
        self._raise_for_status("POST", url, resp.status_code, resp.text)
        return resp.json()

    def _put(self, path: str, body: Any) -> dict:
        url = self._url(path)
        payload = body.model_dump(exclude_none=True) if hasattr(body, "model_dump") else (body or {})
        resp = self._client.put(path, json=payload, headers=self._headers())
        self._raise_for_status("PUT", url, resp.status_code, resp.text)
        return resp.json()

    def _delete(self, path: str, body: Any = None) -> dict:
        url = self._url(path)
        payload = body.model_dump(exclude_none=True) if hasattr(body, "model_dump") else {}
        resp = self._client.delete(path, json=payload, headers=self._headers())
        self._raise_for_status("DELETE", url, resp.status_code, resp.text)
        return resp.json()

    def _patch(self, path: str, body: Any) -> dict:
        url = self._url(path)
        payload = body.model_dump(exclude_none=True) if hasattr(body, "model_dump") else (body or {})
        resp = self._client.patch(path, json=payload, headers=self._headers())
        self._raise_for_status("PATCH", url, resp.status_code, resp.text)
        return resp.json()

    def _post_multipart(self, path: str, files: dict, data: dict) -> dict:
        url = self._url(path)
        resp = self._client.post(path, files=files, data=data, headers=self._headers())
        self._raise_for_status("POST", url, resp.status_code, resp.text)
        return resp.json()

    # VM lifecycle (sync mirrors)
    def create_vm(self, host: str, body: CreateVmRequest) -> JobSubmitResponse:
        return self._submit(self._post(f"/api/v1/hosts/{host}/vms/", body))

    def start_vm(self, host: str, vm_name: str, body: Optional[VmActionRequest] = None) -> JobSubmitResponse:
        return self._submit(self._post(f"/api/v1/hosts/{host}/vms/{vm_name}/start", body or VmActionRequest()))

    def shutdown_vm(self, host: str, vm_name: str, body: Optional[VmActionRequest] = None) -> JobSubmitResponse:
        return self._submit(self._post(f"/api/v1/hosts/{host}/vms/{vm_name}/shutdown", body or VmActionRequest()))

    def destroy_vm(self, host: str, vm_name: str, body: Optional[VmActionRequest] = None) -> JobSubmitResponse:
        return self._submit(self._post(f"/api/v1/hosts/{host}/vms/{vm_name}/destroy", body or VmActionRequest()))

    def schedule_expiry(self, host: str, vm_name: str, body: ScheduleVmExpiryRequest) -> JobSubmitResponse:
        return self._submit(self._post(f"/api/v1/hosts/{host}/vms/{vm_name}/expiry", body))

    def cancel_expiry(self, host: str, vm_name: str, body: Optional[VmActionRequest] = None) -> JobSubmitResponse:
        return self._submit(self._delete(f"/api/v1/hosts/{host}/vms/{vm_name}/expiry", body or VmActionRequest()))

    def check_capacity(self, host: str) -> JobSubmitResponse:
        return self._submit(self._get(f"/api/v1/hosts/{host}/capacity"))

    # Host operations (sync mirrors)
    def list_hosts(self, *, search: Optional[str] = None,
                   include_disabled: bool = False) -> HostListResponse:
        params: dict[str, Any] = {}
        if search:
            params["search"] = search
        if include_disabled:
            params["include_disabled"] = "true"
        return HostListResponse(**(self._get("/api/v1/hosts/", params=params or None)))

    def get_host(self, name: str) -> HostResponse:
        return HostResponse(**(self._get(f"/api/v1/hosts/{name}")))

    def register_host(self, body: HostCreate) -> HostResponse:
        return HostResponse(**(self._post("/api/v1/hosts/", body)))

    def update_host(self, name: str, body: HostUpdate) -> HostResponse:
        return HostResponse(**(self._put(f"/api/v1/hosts/{name}", body)))

    def enable_host(self, name: str) -> HostResponse:
        return HostResponse(**(self._post(f"/api/v1/hosts/{name}/enable", {})))

    def disable_host(self, name: str) -> HostResponse:
        return HostResponse(**(self._post(f"/api/v1/hosts/{name}/disable", {})))

    def check_connectivity(self, host: str) -> HostConnectivityResponse:
        """GET /api/v1/hosts/{host}/connectivity — run ansible -m ping."""
        return HostConnectivityResponse.model_validate(self._get(f"/api/v1/hosts/{host}/connectivity"))

    def import_hosts_from_text(self, ini_text: str, ssh_key_type: str = "path",
                                filename: str = "hosts") -> HostListResponse:
        return HostListResponse(**(self._post_multipart(
            "/api/v1/hosts/import",
            files={"file": (filename, ini_text.encode("utf-8"), "text/plain")},
            data={"ssh_key_type": ssh_key_type},
        )))

    def import_hosts_from_path(self, path: Path, ssh_key_type: str = "path") -> HostListResponse:
        with open(path, "rb") as f:
            content = f.read()
        return HostListResponse(**(self._post_multipart(
            "/api/v1/hosts/import",
            files={"file": (path.name, content, "text/plain")},
            data={"ssh_key_type": ssh_key_type},
        )))

    # System / readiness (sync mirrors)
    def get_health(self) -> dict:
        """GET /health — fast liveness probe (local checks only, no outbound HTTP).

        Returns ``{"status": "ok"|"degraded", "checks": {...}}``.
        Use ``get_system_status()`` for the full diagnostic status including
        storefront connectivity and watchdog state.
        """
        return self._get("/health")

    def get_system_status(self) -> dict:
        """GET /api/v1/system/status — full diagnostic status.

        Includes outbound HTTP probes against the storefront (storefront,
        storefront_auth checks) and lease watchdog state. Suitable for
        operator diagnostics and e2e pre-flight checks.

        Accepts both 200 (all checks ok) and 503 (some checks degraded) as valid
        responses — 503 indicates a degraded but reachable service, not an error.

        Returns ``{"status": "ok"|"degraded", "checks": {...}}``.
        """
        url = self._url("/api/v1/system/status")
        resp = self._client.get("/api/v1/system/status", headers=self._headers())
        if resp.status_code not in (200, 503):
            self._raise_for_status("GET", url, resp.status_code, resp.text)
        return resp.json()

    def get_ansible_readiness(self) -> dict:
        """GET /api/v1/system/ansible/readiness — Ansible config readiness check.

        Returns a dict with fields:
          - ansible_version: str | None
          - inventory: {source, path, exists, host_count}
          - playbook: {path, exists}
          - ssh_keys: list of SSH key diagnostic dicts

        Always returns 200 regardless of readiness state — check
        ``response["playbook"]["exists"]`` to confirm the provisioning
        service is correctly configured for the deal flow.
        """
        return self._get("/api/v1/system/ansible/readiness")

    # Job operations (sync mirrors)
    def get_job(self, job_id: str) -> JobStatusResponse:
        return JobStatusResponse(**(self._get(f"/api/v1/jobs/{job_id}")))

    def get_job_credentials(self, job_id: str) -> CredentialListResponse:
        return CredentialListResponse(**(self._get(
            f"/api/v1/jobs/{job_id}/credentials"
        )))

    def get_job_logs(self, job_id: str) -> JobLogsResponse:
        return JobLogsResponse(**(self._get(f"/api/v1/jobs/{job_id}/logs")))

    def list_jobs(self, *, status: Optional[str] = None,
                  offset: int = 0, limit: int = 20,
                  escrow_uid: Optional[str] = None) -> JobListResponse:
        params: dict[str, Any] = {"offset": offset, "limit": limit}
        if status:
            params["status"] = status
        if escrow_uid:
            params["escrow_uid"] = escrow_uid
        return JobListResponse(**(self._get("/api/v1/jobs/", params=params)))

    def sync_poll_until_complete(
        self,
        job_id: str,
        *,
        timeout: float = 3600.0,
        poll_interval: float = 5.0,
    ) -> JobStatusResponse:
        """Poll GET /api/v1/jobs/{job_id} until terminal state (blocking)."""
        deadline = time.monotonic() + timeout
        while True:
            job = self.get_job(job_id)
            if job.status == "succeeded":
                return job
            if job.status in ("failed", "cancelled"):
                raise ProvisioningJobError(
                    f"Job {job_id} {job.status}: {job.error or 'unknown error'}"
                )
            if time.monotonic() >= deadline:
                raise ProvisioningTimeoutError(
                    f"Job {job_id} did not complete within {timeout}s "
                    f"(current status: {job.status})"
                )
            time.sleep(poll_interval)

    # ------------------------------------------------------------------
    # Leases
    # ------------------------------------------------------------------

    def register_lease(
        self,
        *,
        resource_id: str,
        escrow_uid: str,
        vm_host: str,
        vm_target: str,
        lease_end_utc,
        lease_start_utc=None,
        create_job_id: Optional[str] = None,
        allocation_id: Optional[str] = None,
    ) -> dict:
        """POST /api/v1/leases — register a new VM lease."""
        body: dict = {
            "resource_id": resource_id,
            "escrow_uid": escrow_uid,
            "vm_host": vm_host,
            "vm_target": vm_target,
            "lease_end_utc": lease_end_utc.isoformat() if hasattr(lease_end_utc, "isoformat") else str(lease_end_utc),
        }
        if allocation_id is not None:
            body["allocation_id"] = allocation_id
        if lease_start_utc is not None:
            body["lease_start_utc"] = lease_start_utc.isoformat() if hasattr(lease_start_utc, "isoformat") else str(lease_start_utc)
        if create_job_id is not None:
            body["create_job_id"] = create_job_id
        return self._post("/api/v1/leases/", body)

    def list_leases(
        self,
        *,
        status: Optional[str] = None,
        vm_host: Optional[str] = None,
        escrow_uid: Optional[str] = None,
    ) -> dict:
        """GET /api/v1/leases — list leases with optional filters."""
        params: dict = {}
        if status is not None:
            params["status"] = status
        if vm_host is not None:
            params["vm_host"] = vm_host
        if escrow_uid is not None:
            params["escrow_uid"] = escrow_uid
        return self._get("/api/v1/leases/", params=params)

    def get_lease(self, lease_id: str) -> dict:
        """GET /api/v1/leases/{lease_id} — fetch one lease by internal ID."""
        return self._get(f"/api/v1/leases/{lease_id}")

    def get_lease_by_escrow(self, escrow_uid: str) -> dict:
        """GET /api/v1/leases/by-escrow/{escrow_uid} — fetch lease by escrow UID."""
        return self._get(f"/api/v1/leases/by-escrow/{escrow_uid}")

    def update_lease(self, lease_id: str, **kwargs) -> dict:
        """PATCH /api/v1/leases/{lease_id} — partial update."""
        return self._patch(f"/api/v1/leases/{lease_id}", kwargs)

    def cancel_lease(self, lease_id: str) -> dict:
        """DELETE /api/v1/leases/{lease_id}/cancel — cancel before expiry."""
        return self._delete(f"/api/v1/leases/{lease_id}/cancel")

    # ------------------------------------------------------------------
    # Lease watchdog control
    # ------------------------------------------------------------------

    def check_leases(self) -> dict:
        """POST /api/v1/system/check-leases — run one lifecycle cycle immediately.

        Bypasses the watchdog pause flag. Returns summary dict with
        activated, checked, released, forced, skipped counts.
        """
        return self._post("/api/v1/system/check-leases", {})

    def pause_lease_watchdog(self) -> dict:
        """POST /api/v1/system/lease-watchdog/pause — pause timer-driven cycles."""
        return self._post("/api/v1/system/lease-watchdog/pause", {})

    def resume_lease_watchdog(self) -> dict:
        """POST /api/v1/system/lease-watchdog/resume — resume timer-driven cycles."""
        return self._post("/api/v1/system/lease-watchdog/resume", {})
