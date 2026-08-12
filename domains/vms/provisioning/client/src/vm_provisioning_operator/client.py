"""HTTP clients for the provisioning service REST API.

Two clients with identical method signatures:

``ProvisioningClient``      — async, backed by ``httpx.AsyncClient``
``SyncProvisioningClient``  — sync,  backed by ``httpx.Client``

Both clients own their HTTP session, authenticate every non-health request with
the caller's marketplace signer, pin and verify the provisioning authority on
every response, raise ``ProvisioningError`` on non-2xx responses, and return
typed model objects.

Polling pattern
---------------
All job-creating methods return a ``JobSubmitResponse`` (job_id + status).
Use ``poll_until_complete`` to block until the job reaches a terminal state,
or call ``get_job`` for custom polling logic.
"""

from __future__ import annotations

import hashlib
import asyncio
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Optional

import httpx

from compute_provisioning import (
    PoolCreate,
    PoolImportRequest,
    PoolImportResponse,
    PoolListResponse,
    PoolReplace,
    PoolResponse,
    PoolUpdate,
    PoolValidateResponse,
)
from compute_provisioning.client import (
    ComputeProvisioningAuthenticationError,
    ComputeProvisioningClient,
    canonical_provisioning_request_body,
    resolve_provisioning_route,
)
from market_identity import EMPTY_BODY, Signer, TrustedIdentitySet
from vm_provisioning_operator.models import (
    AnsibleReadinessResponse,
    CreateVmRequest,
    CredentialListResponse,
    HealthResponse,
    HostConnectivityResponse,
    HostCreate,
    HostListResponse,
    HostResponse,
    HostUpdate,
    JobListResponse,
    JobLogsResponse,
    JobStatusResponse,
    JobSubmitResponse,
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
        signer: Signer,
        expected_authorities: TrustedIdentitySet,
        timeout: float,
    ) -> None:
        if not isinstance(signer, Signer):
            raise TypeError("signer must implement market_identity.Signer")
        if not isinstance(expected_authorities, TrustedIdentitySet):
            raise TypeError(
                "expected_authorities must be a market_identity.TrustedIdentitySet"
            )
        self._base = base_url.rstrip("/")
        self._signer = signer
        self._caller_role = "admin"
        self._expected_authorities = expected_authorities
        self._max_timestamp_skew = 300
        self._request_contexts: dict[
            str, tuple[str, str, str, str]
        ] = {}
        self._timeout = timeout

    def _url(self, path: str) -> str:
        return f"{self._base}{path}"

    def _authentication(
        self,
        method: str,
        path: str,
        body: Any = EMPTY_BODY,
        *,
        query: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> tuple[dict[str, str], str, str, str]:
        authenticated_body = canonical_provisioning_request_body(
            method, path, body, query=query
        )
        operation, resource = resolve_provisioning_route(
            method, path, authenticated_body
        )
        resolved_request_id = request_id or uuid.uuid4().hex
        headers = ComputeProvisioningClient._request_headers(
            self,
            method=method,
            operation=operation,
            resource=resource,
            body=authenticated_body,
            request_id=resolved_request_id,
        )
        return headers, operation, resource, resolved_request_id

    def _verified_body(
        self,
        response: httpx.Response,
        *,
        method: str,
        operation: str,
        resource: str,
        request_id: str,
        accepted_statuses: frozenset[int] | None = None,
    ) -> Any:
        if response.content:
            try:
                body: Any = response.json()
            except ValueError:
                body = response.text
        else:
            body = EMPTY_BODY
        try:
            ComputeProvisioningClient._verify_response(
                self,
                response,
                method=method,
                operation=operation,
                resource=resource,
                request_id=request_id,
                body=body,
            )
        except ComputeProvisioningAuthenticationError as exc:
            raise ProvisioningError(
                str(exc), status_code=exc.status_code
            ) from exc
        if accepted_statuses is None or response.status_code not in accepted_statuses:
            self._raise_for_status(
                method,
                str(response.request.url),
                response.status_code,
                response.text,
            )
        return body

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
    """Authenticated asynchronous operator client for the provisioning service."""

    def __init__(
        self,
        base_url: str,
        signer: Signer,
        expected_authorities: TrustedIdentitySet,
        *,
        timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(base_url, signer, expected_authorities, timeout)
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
        wire_params = {
            key: (
                str(value).lower() if isinstance(value, bool) else str(value)
            )
            for key, value in (params or {}).items()
            if value is not None
        }
        headers, operation, resource, request_id = self._authentication(
            "GET", path, query=wire_params
        )
        response = await self._client.get(
            path, params=wire_params or None, headers=headers
        )
        return self._verified_body(
            response,
            method="GET",
            operation=operation,
            resource=resource,
            request_id=request_id,
        )

    async def _json_request(self, method: str, path: str, body: Any) -> dict:
        payload = (
            body.model_dump(mode="json", exclude_none=True)
            if hasattr(body, "model_dump")
            else (body or {})
        )
        headers, operation, resource, request_id = self._authentication(
            method, path, payload
        )
        response = await self._client.request(
            method, path, json=payload, headers=headers
        )
        return self._verified_body(
            response,
            method=method,
            operation=operation,
            resource=resource,
            request_id=request_id,
        )

    async def _post(self, path: str, body: Any) -> dict:
        return await self._json_request("POST", path, body)

    async def _put(self, path: str, body: Any) -> dict:
        return await self._json_request("PUT", path, body)

    async def _patch(self, path: str, body: Any) -> dict:
        return await self._json_request("PATCH", path, body)

    async def _delete(self, path: str) -> dict:
        return await self._json_request("DELETE", path, {})

    async def _post_multipart(self, path: str, files: dict, data: dict) -> dict:
        request = self._client.build_request("POST", path, files=files, data=data)
        content = await request.aread()
        content_type = request.headers["content-type"].split(";", 1)[0].lower()
        descriptor = {
            "content_type": content_type,
            "sha256": hashlib.sha256(content).hexdigest(),
        }
        headers, operation, resource, request_id = self._authentication(
            "POST", path, descriptor
        )
        request.headers.update(headers)
        response = await self._client.send(request)
        return self._verified_body(
            response,
            method="POST",
            operation=operation,
            resource=resource,
            request_id=request_id,
        )

    # ------------------------------------------------------------------
    # VM lifecycle
    # ------------------------------------------------------------------

    async def create_vm(self, host: str, body: CreateVmRequest) -> JobSubmitResponse:
        """POST /api/v1/hosts/{host}/vms/"""
        return self._submit(await self._post(f"/api/v1/hosts/{host}/vms/", body))

    async def list_vms(self, host: str, body: Optional[VmActionRequest] = None) -> JobSubmitResponse:
        """GET /api/v1/hosts/{host}/vms/"""
        params = (body or VmActionRequest()).model_dump(exclude_none=True)
        return self._submit(await self._get(f"/api/v1/hosts/{host}/vms/", params=params or None))

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
    # Resource pools (admin)
    # ------------------------------------------------------------------

    async def list_pools(self) -> PoolListResponse:
        """GET /api/v1/pools"""
        return PoolListResponse(**(await self._get("/api/v1/pools/")))

    async def get_pool(self, pool_id: str) -> PoolResponse:
        """GET /api/v1/pools/{pool_id}"""
        return PoolResponse(**(await self._get(f"/api/v1/pools/{pool_id}")))

    async def export_pools_yaml(self) -> str:
        """GET /api/v1/pools/export — canonical authoritative YAML."""
        return await self._get("/api/v1/pools/export")

    async def create_pool(self, body: PoolCreate) -> PoolResponse:
        """POST /api/v1/pools"""
        return PoolResponse(**(await self._post("/api/v1/pools/", body)))

    async def replace_pool(self, pool_id: str, body: PoolReplace) -> PoolResponse:
        """PUT /api/v1/pools/{pool_id}"""
        return PoolResponse(**(await self._put(f"/api/v1/pools/{pool_id}", body)))

    async def patch_pool(self, pool_id: str, body: PoolUpdate) -> PoolResponse:
        """PATCH /api/v1/pools/{pool_id}"""
        return PoolResponse(**(await self._patch(f"/api/v1/pools/{pool_id}", body)))

    async def delete_pool(self, pool_id: str) -> PoolResponse:
        """DELETE /api/v1/pools/{pool_id} — disables, does not hard-delete."""
        return PoolResponse(**(await self._delete(f"/api/v1/pools/{pool_id}")))

    async def import_pools(self, yaml_text: str) -> PoolImportResponse:
        """POST /api/v1/pools/import"""
        return PoolImportResponse(**(await self._post(
            "/api/v1/pools/import", PoolImportRequest(yaml_text=yaml_text)
        )))

    async def validate_pools(self, yaml_text: str) -> PoolValidateResponse:
        """POST /api/v1/pools/validate"""
        return PoolValidateResponse(**(await self._post(
            "/api/v1/pools/validate", PoolImportRequest(yaml_text=yaml_text)
        )))

    # ------------------------------------------------------------------
    # System / readiness
    # ------------------------------------------------------------------

    async def get_health(self) -> dict:
        """GET /health — public local liveness without outbound dependencies."""
        response = await self._client.get("/health")
        self._raise_for_status(
            "GET", self._url("/health"), response.status_code, response.text
        )
        return response.json()

    async def get_system_status(self) -> dict:
        """Return the authenticated full diagnostic status, accepting degraded 503."""
        path = "/api/v1/system/status"
        headers, operation, resource, request_id = self._authentication("GET", path)
        response = await self._client.get(path, headers=headers)
        return self._verified_body(
            response,
            method="GET",
            operation=operation,
            resource=resource,
            request_id=request_id,
            accepted_statuses=frozenset({200, 503}),
        )

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
        capacity_reservation_id: Optional[str] = None,
    ) -> dict:
        """POST /api/v1/leases — register a VM lease on a live reservation."""
        body: dict = {
            "resource_id": resource_id,
            "escrow_uid": escrow_uid,
            "vm_host": vm_host,
            "vm_target": vm_target,
            "lease_end_utc": lease_end_utc.isoformat() if hasattr(lease_end_utc, "isoformat") else str(lease_end_utc),
        }
        if capacity_reservation_id is not None:
            body["capacity_reservation_id"] = capacity_reservation_id
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
        """PATCH /api/v1/leases/{lease_id} — partial update of any lease fields."""
        return await self._patch(f"/api/v1/leases/{lease_id}", kwargs)

    async def terminate_lease(self, lease_id: str, **kwargs) -> dict:
        """POST /api/v1/leases/{lease_id}/terminate — submit executor release."""
        return await self._post(f"/api/v1/leases/{lease_id}/terminate", kwargs)

    async def release_lease_oversight(self, lease_id: str, *, reason: str) -> dict:
        """POST /api/v1/leases/{lease_id}/release-oversight — mark unmanaged."""
        return await self._post(
            f"/api/v1/leases/{lease_id}/release-oversight", {"reason": reason},
        )

    async def retry_lease_release(
        self, lease_id: str, *, reason: Optional[str] = None, max_retries: Optional[int] = None,
    ) -> dict:
        """POST /api/v1/admin/leases/{lease_id}/retry-release."""
        body: dict = {}
        if reason is not None:
            body["reason"] = reason
        if max_retries is not None:
            body["max_retries"] = max_retries
        return await self._post(f"/api/v1/admin/leases/{lease_id}/retry-release", body)

    async def force_release_lease(
        self, lease_id: str, *, reason: str, evidence: Optional[str] = None,
    ) -> dict:
        """POST /api/v1/admin/leases/{lease_id}/force-release."""
        body = {"reason": reason}
        if evidence is not None:
            body["evidence"] = evidence
        return await self._post(f"/api/v1/admin/leases/{lease_id}/force-release", body)

    # ------------------------------------------------------------------
    # Site-authority capacity ledger
    # ------------------------------------------------------------------

    async def check_leases(self) -> dict:
        """POST /api/v1/system/check-leases — run one lifecycle cycle now."""
        return await self._post("/api/v1/system/check-leases", {})

    async def get_fulfillment_status(self, fulfillment_id: str) -> dict:
        """GET the durable fulfillment lifecycle state."""
        return await self._get(f"/api/v1/fulfillment/{fulfillment_id}/status")

    async def run_fulfillment_convergence_cycle(self) -> dict:
        """POST /api/v1/system/fulfillment-convergence/run-cycle."""
        return await self._post(
            "/api/v1/system/fulfillment-convergence/run-cycle", {}
        )

    async def pause_lease_watchdog(self) -> dict:
        """POST /api/v1/system/lease-watchdog/pause — pause timer-driven cycles."""
        return await self._post("/api/v1/system/lease-watchdog/pause", {})

    async def resume_lease_watchdog(self) -> dict:
        """POST /api/v1/system/lease-watchdog/resume — resume timer-driven cycles."""
        return await self._post("/api/v1/system/lease-watchdog/resume", {})

    async def capacity_snapshot(self) -> list[dict]:
        """GET /api/v1/capacity/snapshot — advisory availability view."""
        return (await self._get("/api/v1/capacity/snapshot")).get("resources") or []

    async def list_capacity_reservations(
        self,
        state: Optional[str] = None,
        escrow_uid: Optional[str] = None,
    ) -> dict:
        """GET /api/v1/capacity/reservations — ledger reservations."""
        params: dict = {}
        if state is not None:
            params["state"] = state
        if escrow_uid is not None:
            params["escrow_uid"] = escrow_uid
        return await self._get("/api/v1/capacity/reservations", params=params)

    async def get_capacity_reservation(self, capacity_reservation_id: str) -> dict:
        """GET /api/v1/capacity/reservations/{id} — one ledger reservation."""
        return (await self._get(
            f"/api/v1/capacity/reservations/{capacity_reservation_id}"
        )).get("reservation") or {}

    async def truncate_capacity_lease(
        self, capacity_reservation_id: str, lease_end_utc: str,
    ) -> dict:
        """POST /api/v1/capacity/reservations/{id}/truncate-lease."""
        return (await self._post(
            f"/api/v1/capacity/reservations/{capacity_reservation_id}/truncate-lease",
            {"lease_end_utc": lease_end_utc},
        )).get("reservation") or {}


# ---------------------------------------------------------------------------
# Sync client
# ---------------------------------------------------------------------------


class SyncProvisioningClient(_ProvisioningClientBase):
    """Authenticated synchronous operator client for the provisioning service."""

    def __init__(
        self,
        base_url: str,
        signer: Signer,
        expected_authorities: TrustedIdentitySet,
        *,
        timeout: float = 60.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        super().__init__(base_url, signer, expected_authorities, timeout)
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
        wire_params = {
            key: (
                str(value).lower() if isinstance(value, bool) else str(value)
            )
            for key, value in (params or {}).items()
            if value is not None
        }
        headers, operation, resource, request_id = self._authentication(
            "GET", path, query=wire_params
        )
        response = self._client.get(
            path, params=wire_params or None, headers=headers
        )
        return self._verified_body(
            response,
            method="GET",
            operation=operation,
            resource=resource,
            request_id=request_id,
        )

    def _json_request(self, method: str, path: str, body: Any) -> dict:
        payload = (
            body.model_dump(mode="json", exclude_none=True)
            if hasattr(body, "model_dump")
            else (body or {})
        )
        headers, operation, resource, request_id = self._authentication(
            method, path, payload
        )
        response = self._client.request(
            method, path, json=payload, headers=headers
        )
        return self._verified_body(
            response,
            method=method,
            operation=operation,
            resource=resource,
            request_id=request_id,
        )

    def _post(self, path: str, body: Any) -> dict:
        return self._json_request("POST", path, body)

    def _put(self, path: str, body: Any) -> dict:
        return self._json_request("PUT", path, body)

    def _patch(self, path: str, body: Any) -> dict:
        return self._json_request("PATCH", path, body)

    def _delete(self, path: str) -> dict:
        return self._json_request("DELETE", path, {})

    def _post_multipart(self, path: str, files: dict, data: dict) -> dict:
        request = self._client.build_request("POST", path, files=files, data=data)
        content = request.read()
        content_type = request.headers["content-type"].split(";", 1)[0].lower()
        descriptor = {
            "content_type": content_type,
            "sha256": hashlib.sha256(content).hexdigest(),
        }
        headers, operation, resource, request_id = self._authentication(
            "POST", path, descriptor
        )
        request.headers.update(headers)
        response = self._client.send(request)
        return self._verified_body(
            response,
            method="POST",
            operation=operation,
            resource=resource,
            request_id=request_id,
        )

    # VM lifecycle (sync mirrors)
    def create_vm(self, host: str, body: CreateVmRequest) -> JobSubmitResponse:
        return self._submit(self._post(f"/api/v1/hosts/{host}/vms/", body))

    def list_vms(self, host: str, body: Optional[VmActionRequest] = None) -> JobSubmitResponse:
        params = (body or VmActionRequest()).model_dump(exclude_none=True)
        return self._submit(self._get(f"/api/v1/hosts/{host}/vms/", params=params or None))

    def start_vm(self, host: str, vm_name: str, body: Optional[VmActionRequest] = None) -> JobSubmitResponse:
        return self._submit(self._post(f"/api/v1/hosts/{host}/vms/{vm_name}/start", body or VmActionRequest()))

    def shutdown_vm(self, host: str, vm_name: str, body: Optional[VmActionRequest] = None) -> JobSubmitResponse:
        return self._submit(self._post(f"/api/v1/hosts/{host}/vms/{vm_name}/shutdown", body or VmActionRequest()))

    def reboot_vm(self, host: str, vm_name: str, body: Optional[VmActionRequest] = None) -> JobSubmitResponse:
        return self._submit(self._post(f"/api/v1/hosts/{host}/vms/{vm_name}/reboot", body or VmActionRequest()))

    def destroy_vm(self, host: str, vm_name: str, body: Optional[VmActionRequest] = None) -> JobSubmitResponse:
        return self._submit(self._post(f"/api/v1/hosts/{host}/vms/{vm_name}/destroy", body or VmActionRequest()))

    def undefine_vm(self, host: str, vm_name: str, body: Optional[VmActionRequest] = None) -> JobSubmitResponse:
        return self._submit(self._post(f"/api/v1/hosts/{host}/vms/{vm_name}/undefine", body or VmActionRequest()))

    def monitor_vm(self, host: str, vm_name: str) -> JobSubmitResponse:
        return self._submit(self._get(f"/api/v1/hosts/{host}/vms/{vm_name}/monitor"))

    def reset_password(self, host: str, vm_name: str, body: Optional[VmActionRequest] = None) -> JobSubmitResponse:
        return self._submit(self._post(f"/api/v1/hosts/{host}/vms/{vm_name}/reset-password", body or VmActionRequest()))

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

    # Resource pools (admin, sync mirrors)
    def list_pools(self) -> PoolListResponse:
        return PoolListResponse(**(self._get("/api/v1/pools/")))

    def get_pool(self, pool_id: str) -> PoolResponse:
        return PoolResponse(**(self._get(f"/api/v1/pools/{pool_id}")))

    def export_pools_yaml(self) -> str:
        return self._get("/api/v1/pools/export")

    def create_pool(self, body: PoolCreate) -> PoolResponse:
        return PoolResponse(**(self._post("/api/v1/pools/", body)))

    def replace_pool(self, pool_id: str, body: PoolReplace) -> PoolResponse:
        return PoolResponse(**(self._put(f"/api/v1/pools/{pool_id}", body)))

    def patch_pool(self, pool_id: str, body: PoolUpdate) -> PoolResponse:
        return PoolResponse(**(self._patch(f"/api/v1/pools/{pool_id}", body)))

    def delete_pool(self, pool_id: str) -> PoolResponse:
        return PoolResponse(**(self._delete(f"/api/v1/pools/{pool_id}")))

    def import_pools(self, yaml_text: str) -> PoolImportResponse:
        return PoolImportResponse(**(self._post(
            "/api/v1/pools/import", PoolImportRequest(yaml_text=yaml_text)
        )))

    def validate_pools(self, yaml_text: str) -> PoolValidateResponse:
        return PoolValidateResponse(**(self._post(
            "/api/v1/pools/validate", PoolImportRequest(yaml_text=yaml_text)
        )))

    # System / readiness (sync mirrors)
    def get_health(self) -> dict:
        response = self._client.get("/health")
        self._raise_for_status(
            "GET", self._url("/health"), response.status_code, response.text
        )
        return response.json()

    def get_system_status(self) -> dict:
        path = "/api/v1/system/status"
        headers, operation, resource, request_id = self._authentication("GET", path)
        response = self._client.get(path, headers=headers)
        return self._verified_body(
            response,
            method="GET",
            operation=operation,
            resource=resource,
            request_id=request_id,
            accepted_statuses=frozenset({200, 503}),
        )

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

    def cancel_job(self, job_id: str) -> dict:
        return self._post(f"/api/v1/jobs/{job_id}/cancel", {})

    def list_jobs(self, *, status: Optional[str] = None,
                  offset: int = 0, limit: int = 20,
                  escrow_uid: Optional[str] = None) -> JobListResponse:
        params: dict[str, Any] = {"offset": offset, "limit": limit}
        if status:
            params["status"] = status
        if escrow_uid:
            params["escrow_uid"] = escrow_uid
        return JobListResponse(**(self._get("/api/v1/jobs/", params=params)))

    def poll_until_complete(
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
        capacity_reservation_id: Optional[str] = None,
    ) -> dict:
        """POST /api/v1/leases — register a VM lease on a live reservation."""
        body: dict = {
            "resource_id": resource_id,
            "escrow_uid": escrow_uid,
            "vm_host": vm_host,
            "vm_target": vm_target,
            "lease_end_utc": lease_end_utc.isoformat() if hasattr(lease_end_utc, "isoformat") else str(lease_end_utc),
        }
        if capacity_reservation_id is not None:
            body["capacity_reservation_id"] = capacity_reservation_id
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
        """PATCH /api/v1/leases/{lease_id} — partial update of any lease fields."""
        return self._patch(f"/api/v1/leases/{lease_id}", kwargs)

    def terminate_lease(self, lease_id: str, **kwargs) -> dict:
        """POST /api/v1/leases/{lease_id}/terminate — submit executor release."""
        return self._post(f"/api/v1/leases/{lease_id}/terminate", kwargs)

    def release_lease_oversight(self, lease_id: str, *, reason: str) -> dict:
        """POST /api/v1/leases/{lease_id}/release-oversight — mark unmanaged."""
        return self._post(
            f"/api/v1/leases/{lease_id}/release-oversight", {"reason": reason},
        )

    def retry_lease_release(
        self, lease_id: str, *, reason: Optional[str] = None, max_retries: Optional[int] = None,
    ) -> dict:
        """POST /api/v1/admin/leases/{lease_id}/retry-release."""
        body: dict = {}
        if reason is not None:
            body["reason"] = reason
        if max_retries is not None:
            body["max_retries"] = max_retries
        return self._post(f"/api/v1/admin/leases/{lease_id}/retry-release", body)

    def force_release_lease(
        self, lease_id: str, *, reason: str, evidence: Optional[str] = None,
    ) -> dict:
        """POST /api/v1/admin/leases/{lease_id}/force-release."""
        body = {"reason": reason}
        if evidence is not None:
            body["evidence"] = evidence
        return self._post(f"/api/v1/admin/leases/{lease_id}/force-release", body)

    # ------------------------------------------------------------------
    # Site-authority capacity ledger
    # ------------------------------------------------------------------

    def capacity_snapshot(self) -> list[dict]:
        """GET /api/v1/capacity/snapshot — advisory availability view."""
        return self._get("/api/v1/capacity/snapshot").get("resources") or []

    def list_capacity_reservations(
        self,
        state: Optional[str] = None,
        escrow_uid: Optional[str] = None,
    ) -> dict:
        """GET /api/v1/capacity/reservations — ledger reservations."""
        params: dict = {}
        if state is not None:
            params["state"] = state
        if escrow_uid is not None:
            params["escrow_uid"] = escrow_uid
        return self._get("/api/v1/capacity/reservations", params=params)

    def get_capacity_reservation(self, capacity_reservation_id: str) -> dict:
        """GET /api/v1/capacity/reservations/{id} — one ledger reservation."""
        return self._get(
            f"/api/v1/capacity/reservations/{capacity_reservation_id}"
        ).get("reservation") or {}

    def truncate_capacity_lease(
        self, capacity_reservation_id: str, lease_end_utc: str,
    ) -> dict:
        """POST /api/v1/capacity/reservations/{id}/truncate-lease."""
        return self._post(
            f"/api/v1/capacity/reservations/{capacity_reservation_id}/truncate-lease",
            {"lease_end_utc": lease_end_utc},
        ).get("reservation") or {}

    # ------------------------------------------------------------------
    # Lease watchdog control
    # ------------------------------------------------------------------

    def check_leases(self) -> dict:
        """POST /api/v1/system/check-leases — run one lifecycle cycle immediately.

        Bypasses the watchdog pause flag. Returns summary dict with
        checked, released, release_failed, skipped counts.
        """
        return self._post("/api/v1/system/check-leases", {})

    def get_fulfillment_status(self, fulfillment_id: str) -> dict:
        """GET the durable fulfillment lifecycle state."""
        return self._get(f"/api/v1/fulfillment/{fulfillment_id}/status")

    def run_fulfillment_convergence_cycle(self) -> dict:
        """POST /api/v1/system/fulfillment-convergence/run-cycle."""
        return self._post("/api/v1/system/fulfillment-convergence/run-cycle", {})

    def pause_lease_watchdog(self) -> dict:
        """POST /api/v1/system/lease-watchdog/pause — pause timer-driven cycles."""
        return self._post("/api/v1/system/lease-watchdog/pause", {})

    def resume_lease_watchdog(self) -> dict:
        """POST /api/v1/system/lease-watchdog/resume — resume timer-driven cycles."""
        return self._post("/api/v1/system/lease-watchdog/resume", {})
