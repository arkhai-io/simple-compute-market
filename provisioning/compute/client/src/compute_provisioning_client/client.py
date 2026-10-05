"""Typed clients for the compute provisioning family's routes.

``ComputeProvisioningClient`` is async and ``SyncComputeProvisioningClient`` is
sync. Both describe each operation once, as a call spec, and differ only in
sending it, so their public methods are identical. Each covers the routes the
compute family owns, and the provisioning service's own system and identity
routes, and nothing else: a domain, an implementation, or another capability
served by the same service wraps ``authenticated_request`` in its own typed
client and names its route declaration there.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx
from compute_provisioning_contracts import (
    ConnectivityResult,
    FulfillmentAcceptanceResponse,
    FulfillmentRequestBody,
    FulfillmentScheduleRequest,
    FulfillmentScheduleResponse,
    FulfillmentStatusResponse,
    FulfillmentValidationResponse,
    HostCreate,
    HostListResponse,
    HostResponse,
    HostUpdate,
    JobCredentialsResponse,
    JobListResponse,
    JobListSort,
    JobLogsResponse,
    JobStatusResponse,
    LeaseForceRelease,
    LeaseRegistration,
    LeaseRetryRelease,
    LeaseTermination,
    LeaseView,
    ProvisioningRouteContract,
    VersionResponse,
)
from market_core import VersionedEnvelope
from market_identity import EMPTY_BODY, RotationRequest, Signer, TrustedIdentitySet

from .base import SigningBase, multipart_descriptor, wire_query
from .errors import (
    ComputeProvisioningError,
    ComputeProvisioningJobError,
    ComputeProvisioningTimeoutError,
)

Route = ProvisioningRouteContract | Mapping[str, Any]


def _same(value: Any) -> Any:
    return value


@dataclass(frozen=True)
class _Call:
    method: str
    path: str
    body: Any = EMPTY_BODY
    query: Mapping[str, Any] | None = None
    parse: Callable[[Any], Any] = _same
    accepted_statuses: Collection[int] = field(default_factory=tuple)


def _model(model: type) -> Callable[[Any], Any]:
    return model.model_validate


def _object(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ComputeProvisioningError("expected a JSON object response")
    return payload


# Fulfillment.


def _schedule(request: FulfillmentScheduleRequest) -> _Call:
    return _Call("POST", "/api/v1/fulfillment/schedule", request, parse=_model(FulfillmentScheduleResponse))


def _validate(body: FulfillmentRequestBody) -> _Call:
    return _Call("POST", "/api/v1/fulfillment/validate", body, parse=_model(FulfillmentValidationResponse))


def _begin(body: FulfillmentRequestBody) -> _Call:
    return _Call("POST", "/api/v1/fulfillment/begin", body, parse=_model(FulfillmentAcceptanceResponse))


def _teardown(fulfillment_id: str) -> _Call:
    return _Call(
        "POST",
        f"/api/v1/fulfillment/{fulfillment_id}/begin-teardown",
        {},
        parse=_model(FulfillmentAcceptanceResponse),
    )


def _status(fulfillment_id: str) -> _Call:
    return _Call("GET", f"/api/v1/fulfillment/{fulfillment_id}/status", parse=_model(FulfillmentStatusResponse))


def _result(fulfillment_id: str) -> _Call:
    return _Call(
        "GET",
        f"/api/v1/fulfillment/{fulfillment_id}/result",
        parse=VersionedEnvelope[dict[str, Any]].model_validate,
    )


# Leases.


def _register_lease(registration: LeaseRegistration) -> _Call:
    return _Call("POST", "/api/v1/contract/leases", registration, parse=_model(LeaseView))


def _get_lease(capacity_reservation_id: str) -> _Call:
    return _Call("GET", f"/api/v1/contract/leases/{capacity_reservation_id}", parse=_model(LeaseView))


def _lease_action(capacity_reservation_id: str, action: str, body: Any) -> _Call:
    return _Call(
        "POST",
        f"/api/v1/contract/leases/{capacity_reservation_id}/{action}",
        body,
        parse=_model(LeaseView),
    )


# Jobs.


def _list_jobs(
    status: str | None, offset: int, limit: int, escrow_uid: str | None, sort: str
) -> _Call:
    return _Call(
        "GET",
        "/api/v1/jobs/",
        query={
            "offset": offset,
            "limit": limit,
            "status": status,
            "escrow_uid": escrow_uid,
            "sort": sort,
        },
        parse=_model(JobListResponse),
    )


def _get_job(job_id: str) -> _Call:
    return _Call("GET", f"/api/v1/jobs/{job_id}", parse=_model(JobStatusResponse))


def _job_credentials(job_id: str) -> _Call:
    return _Call("GET", f"/api/v1/jobs/{job_id}/credentials", parse=_model(JobCredentialsResponse))


def _job_logs(job_id: str) -> _Call:
    return _Call("GET", f"/api/v1/jobs/{job_id}/logs", parse=_model(JobLogsResponse))


def _cancel_job(job_id: str) -> _Call:
    return _Call("POST", f"/api/v1/jobs/{job_id}/cancel", {}, parse=_object)


# Hosts.


def _list_hosts(search: str | None, include_disabled: bool) -> _Call:
    return _Call(
        "GET",
        "/api/v1/hosts/",
        query={"search": search or None, "include_disabled": True if include_disabled else None},
        parse=_model(HostListResponse),
    )


def _get_host(host_id: str) -> _Call:
    return _Call("GET", f"/api/v1/hosts/{host_id}", parse=_model(HostResponse))


def _register_host(body: HostCreate) -> _Call:
    return _Call("POST", "/api/v1/hosts/", body, parse=_model(HostResponse))


def _update_host(host_id: str, body: HostUpdate) -> _Call:
    return _Call("PUT", f"/api/v1/hosts/{host_id}", body, parse=_model(HostResponse))


def _set_host_enabled(host_id: str, enabled: bool) -> _Call:
    action = "enable" if enabled else "disable"
    return _Call("POST", f"/api/v1/hosts/{host_id}/{action}", {}, parse=_model(HostResponse))


def _connectivity(host_id: str) -> _Call:
    return _Call("GET", f"/api/v1/hosts/{host_id}/connectivity", parse=_model(ConnectivityResult))


# The service's system and identity routes.


def _system_get(path: str, *, accepted_statuses: Collection[int] = ()) -> _Call:
    return _Call("GET", path, parse=_object, accepted_statuses=accepted_statuses)


def _system_post(path: str) -> _Call:
    return _Call("POST", path, {}, parse=_object)


def _version() -> _Call:
    return _Call("GET", "/api/v1/system/version", parse=_model(VersionResponse))


def _rotate(role: str, rotation: RotationRequest) -> _Call:
    if role not in {"admin", "seller"}:
        raise ValueError("role must be 'admin' or 'seller'")
    return _Call("POST", f"/api/v1/identity/rotations/{role}", rotation, parse=_object)


_CONVERGENCE = "/api/v1/system/fulfillment-convergence"
_LEASE_WATCHDOG = "/api/v1/system/lease-watchdog"
_TERMINAL_FAILURES = frozenset({"failed", "cancelled"})


def _job_outcome(job: JobStatusResponse, job_id: str) -> bool:
    """True once the job succeeded; raises once it failed or was cancelled."""
    if job.status == "succeeded":
        return True
    if job.status in _TERMINAL_FAILURES:
        raise ComputeProvisioningJobError(
            f"job {job_id} {job.status}: {job.error or 'no error recorded'}"
        )
    return False


class ComputeProvisioningClientProtocol(Protocol):
    """What a storefront calls on the family client."""

    async def register_lease(self, registration: LeaseRegistration, *, request_id: str | None = None) -> LeaseView: ...
    async def get_lease(self, capacity_reservation_id: str, *, request_id: str | None = None) -> LeaseView: ...
    async def terminate_lease(
        self, capacity_reservation_id: str, request: LeaseTermination, *, request_id: str | None = None
    ) -> LeaseView: ...
    async def retry_lease_release(
        self, capacity_reservation_id: str, request: LeaseRetryRelease, *, request_id: str | None = None
    ) -> LeaseView: ...
    async def force_release_lease(
        self, capacity_reservation_id: str, request: LeaseForceRelease, *, request_id: str | None = None
    ) -> LeaseView: ...
    async def rotate_trusted_principal(
        self, role: str, rotation: RotationRequest, *, request_id: str | None = None
    ) -> dict[str, Any]: ...
    async def schedule_resource(
        self, request: FulfillmentScheduleRequest, *, request_id: str | None = None
    ) -> FulfillmentScheduleResponse: ...
    async def validate_fulfillment(
        self, body: FulfillmentRequestBody, *, request_id: str | None = None
    ) -> FulfillmentValidationResponse: ...
    async def begin_fulfillment(
        self, body: FulfillmentRequestBody, *, request_id: str | None = None
    ) -> FulfillmentAcceptanceResponse: ...
    async def begin_fulfillment_teardown(
        self, fulfillment_id: str, *, request_id: str | None = None
    ) -> FulfillmentAcceptanceResponse: ...
    async def get_fulfillment_status(
        self, fulfillment_id: str, *, request_id: str | None = None
    ) -> FulfillmentStatusResponse: ...
    async def get_fulfillment_result(
        self, fulfillment_id: str, *, request_id: str | None = None
    ) -> VersionedEnvelope[dict[str, Any]]: ...


class ComputeProvisioningClient(SigningBase):
    """Authenticated async client for the compute provisioning family's routes."""

    def __init__(
        self,
        base_url: str,
        signer: Signer,
        caller_role: str,
        expected_authorities: TrustedIdentitySet,
        *,
        timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
        max_timestamp_skew: int = 300,
    ) -> None:
        super().__init__(
            base_url, signer, caller_role, expected_authorities, max_timestamp_skew=max_timestamp_skew
        )
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=timeout, transport=transport)

    async def __aenter__(self) -> "ComputeProvisioningClient":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    async def authenticated_request(
        self,
        method: str,
        path: str,
        body: Any = EMPTY_BODY,
        *,
        query: Mapping[str, Any] | None = None,
        files: Any = None,
        data: Mapping[str, Any] | None = None,
        request_id: str | None = None,
        route: Route | None = None,
        accepted_statuses: Collection[int] = (),
    ) -> Any:
        """Send one signed request and return its verified response body.

        The transport other owners' typed clients wrap: ``route`` names the
        declaration of a route this client has no method for, and without it
        the path resolves against the family's own routes. A multipart request
        (``files``, ``data``) is signed over its content type and digest. The
        response must carry a valid authority proof; a status outside 2xx and
        ``accepted_statuses`` then raises ``ComputeProvisioningError``.
        """
        resolved_request_id = request_id or uuid.uuid4().hex
        wire = wire_query(query)
        if files is not None or data is not None:
            request = self._client.build_request(method, path, files=files, data=data, params=wire or None)
            signed_body = multipart_descriptor(request, await request.aread())
            signed = self.sign(method, path, signed_body, request_id=resolved_request_id, route=route)
            request.headers.update(signed.headers)
        else:
            payload = self.payload(body)
            signed_body = self.canonical(method, path, payload, wire)
            signed = self.sign(method, path, signed_body, request_id=resolved_request_id, route=route)
            request = self._client.build_request(
                method,
                path,
                headers=signed.headers,
                params=wire or None,
                **({"json": payload} if payload is not EMPTY_BODY else {}),
            )
        response = await self._client.send(request)
        return self.finish(response, signed, accepted_statuses=accepted_statuses)

    async def _run(self, call: _Call, request_id: str | None) -> Any:
        return call.parse(
            await self.authenticated_request(
                call.method,
                call.path,
                call.body,
                query=call.query,
                request_id=request_id,
                accepted_statuses=call.accepted_statuses,
            )
        )

    # Fulfillment.

    async def schedule_resource(
        self, request: FulfillmentScheduleRequest, *, request_id: str | None = None
    ) -> FulfillmentScheduleResponse:
        return await self._run(_schedule(request), request_id)

    async def validate_fulfillment(
        self, body: FulfillmentRequestBody, *, request_id: str | None = None
    ) -> FulfillmentValidationResponse:
        """Ask whether this request would be accepted, without accepting it.

        Every rejection acceptance performs still runs; nothing durable is
        written and nothing is acquired.
        """
        return await self._run(_validate(body), request_id)

    async def begin_fulfillment(
        self, body: FulfillmentRequestBody, *, request_id: str | None = None
    ) -> FulfillmentAcceptanceResponse:
        return await self._run(_begin(body), request_id)

    async def begin_fulfillment_teardown(
        self, fulfillment_id: str, *, request_id: str | None = None
    ) -> FulfillmentAcceptanceResponse:
        return await self._run(_teardown(fulfillment_id), request_id)

    async def get_fulfillment_status(
        self, fulfillment_id: str, *, request_id: str | None = None
    ) -> FulfillmentStatusResponse:
        return await self._run(_status(fulfillment_id), request_id)

    async def get_fulfillment_result(
        self, fulfillment_id: str, *, request_id: str | None = None
    ) -> VersionedEnvelope[dict[str, Any]]:
        return await self._run(_result(fulfillment_id), request_id)

    # Leases.

    async def register_lease(
        self, registration: LeaseRegistration, *, request_id: str | None = None
    ) -> LeaseView:
        return await self._run(_register_lease(registration), request_id)

    async def get_lease(
        self, capacity_reservation_id: str, *, request_id: str | None = None
    ) -> LeaseView:
        return await self._run(_get_lease(capacity_reservation_id), request_id)

    async def terminate_lease(
        self, capacity_reservation_id: str, request: LeaseTermination, *, request_id: str | None = None
    ) -> LeaseView:
        return await self._run(_lease_action(capacity_reservation_id, "terminate", request), request_id)

    async def retry_lease_release(
        self, capacity_reservation_id: str, request: LeaseRetryRelease, *, request_id: str | None = None
    ) -> LeaseView:
        return await self._run(_lease_action(capacity_reservation_id, "retry-release", request), request_id)

    async def force_release_lease(
        self, capacity_reservation_id: str, request: LeaseForceRelease, *, request_id: str | None = None
    ) -> LeaseView:
        return await self._run(_lease_action(capacity_reservation_id, "force-release", request), request_id)

    # Jobs.

    async def list_jobs(
        self,
        *,
        status: str | None = None,
        offset: int = 0,
        limit: int = 20,
        escrow_uid: str | None = None,
        sort: JobListSort = "created_at_desc",
        request_id: str | None = None,
    ) -> JobListResponse:
        return await self._run(_list_jobs(status, offset, limit, escrow_uid, sort), request_id)

    async def get_job(self, job_id: str, *, request_id: str | None = None) -> JobStatusResponse:
        return await self._run(_get_job(job_id), request_id)

    async def get_job_credentials(
        self, job_id: str, *, request_id: str | None = None
    ) -> JobCredentialsResponse:
        return await self._run(_job_credentials(job_id), request_id)

    async def get_job_logs(self, job_id: str, *, request_id: str | None = None) -> JobLogsResponse:
        return await self._run(_job_logs(job_id), request_id)

    async def cancel_job(self, job_id: str, *, request_id: str | None = None) -> dict[str, Any]:
        return await self._run(_cancel_job(job_id), request_id)

    async def poll_until_complete(
        self, job_id: str, *, timeout: float = 600.0, poll_interval: float = 2.0
    ) -> JobStatusResponse:
        """Re-read a job until it succeeds; raise once it fails, is cancelled, or the deadline passes."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            job = await self.get_job(job_id)
            if _job_outcome(job, job_id):
                return job
            if loop.time() >= deadline:
                raise ComputeProvisioningTimeoutError(
                    f"job {job_id} did not finish within {timeout}s (status {job.status})"
                )
            await asyncio.sleep(poll_interval)

    # Hosts.

    async def list_hosts(
        self,
        *,
        search: str | None = None,
        include_disabled: bool = False,
        request_id: str | None = None,
    ) -> HostListResponse:
        return await self._run(_list_hosts(search, include_disabled), request_id)

    async def get_host(self, host_id: str, *, request_id: str | None = None) -> HostResponse:
        return await self._run(_get_host(host_id), request_id)

    async def register_host(self, body: HostCreate, *, request_id: str | None = None) -> HostResponse:
        return await self._run(_register_host(body), request_id)

    async def update_host(
        self, host_id: str, body: HostUpdate, *, request_id: str | None = None
    ) -> HostResponse:
        return await self._run(_update_host(host_id, body), request_id)

    async def enable_host(self, host_id: str, *, request_id: str | None = None) -> HostResponse:
        return await self._run(_set_host_enabled(host_id, True), request_id)

    async def disable_host(self, host_id: str, *, request_id: str | None = None) -> HostResponse:
        return await self._run(_set_host_enabled(host_id, False), request_id)

    async def check_connectivity(
        self, host_id: str, *, request_id: str | None = None
    ) -> ConnectivityResult:
        """Whether the host's connection is reachable; an unreachable host is a result, not an error."""
        return await self._run(_connectivity(host_id), request_id)

    # The service's system and identity routes.

    async def get_health(self) -> dict[str, Any]:
        """``GET /health``: unauthenticated local liveness."""
        return self.unsigned_body(await self._client.get("/health"))

    async def get_system_health(self, *, request_id: str | None = None) -> dict[str, Any]:
        return await self._run(_system_get("/api/v1/system/health"), request_id)

    async def get_system_status(self, *, request_id: str | None = None) -> dict[str, Any]:
        """The full diagnostic status; a degraded service answers 503 with the same body."""
        return await self._run(
            _system_get("/api/v1/system/status", accepted_statuses=(503,)), request_id
        )

    async def get_version(self, *, request_id: str | None = None) -> VersionResponse:
        return await self._run(_version(), request_id)

    async def get_ansible_readiness(self, *, request_id: str | None = None) -> dict[str, Any]:
        return await self._run(_system_get("/api/v1/system/ansible/readiness"), request_id)

    async def check_leases(self, *, request_id: str | None = None) -> dict[str, Any]:
        """Run one lease lifecycle cycle now."""
        return await self._run(_system_post("/api/v1/system/check-leases"), request_id)

    async def run_fulfillment_convergence_cycle(self, *, request_id: str | None = None) -> dict[str, Any]:
        return await self._run(_system_post(f"{_CONVERGENCE}/run-cycle"), request_id)

    async def advance_fulfillment_convergence_cycle(
        self, *, request_id: str | None = None
    ) -> dict[str, Any]:
        """One observable advance: the watchdog releases its own claims first; it must be paused."""
        return await self._run(_system_post(f"{_CONVERGENCE}/advance-cycle"), request_id)

    async def pause_fulfillment_convergence(self, *, request_id: str | None = None) -> dict[str, Any]:
        return await self._run(_system_post(f"{_CONVERGENCE}/pause"), request_id)

    async def resume_fulfillment_convergence(self, *, request_id: str | None = None) -> dict[str, Any]:
        return await self._run(_system_post(f"{_CONVERGENCE}/resume"), request_id)

    async def pause_lease_watchdog(self, *, request_id: str | None = None) -> dict[str, Any]:
        return await self._run(_system_post(f"{_LEASE_WATCHDOG}/pause"), request_id)

    async def resume_lease_watchdog(self, *, request_id: str | None = None) -> dict[str, Any]:
        return await self._run(_system_post(f"{_LEASE_WATCHDOG}/resume"), request_id)

    async def rotate_trusted_principal(
        self, role: str, rotation: RotationRequest, *, request_id: str | None = None
    ) -> dict[str, Any]:
        return await self._run(_rotate(role, rotation), request_id)


class SyncComputeProvisioningClient(SigningBase):
    """Authenticated sync client for the compute provisioning family's routes."""

    def __init__(
        self,
        base_url: str,
        signer: Signer,
        caller_role: str,
        expected_authorities: TrustedIdentitySet,
        *,
        timeout: float = 60.0,
        transport: httpx.BaseTransport | None = None,
        max_timestamp_skew: int = 300,
    ) -> None:
        super().__init__(
            base_url, signer, caller_role, expected_authorities, max_timestamp_skew=max_timestamp_skew
        )
        self._client = httpx.Client(base_url=self._base_url, timeout=timeout, transport=transport)

    def __enter__(self) -> "SyncComputeProvisioningClient":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def authenticated_request(
        self,
        method: str,
        path: str,
        body: Any = EMPTY_BODY,
        *,
        query: Mapping[str, Any] | None = None,
        files: Any = None,
        data: Mapping[str, Any] | None = None,
        request_id: str | None = None,
        route: Route | None = None,
        accepted_statuses: Collection[int] = (),
    ) -> Any:
        """Send one signed request; see ``ComputeProvisioningClient.authenticated_request``."""
        resolved_request_id = request_id or uuid.uuid4().hex
        wire = wire_query(query)
        if files is not None or data is not None:
            request = self._client.build_request(method, path, files=files, data=data, params=wire or None)
            signed_body = multipart_descriptor(request, request.read())
            signed = self.sign(method, path, signed_body, request_id=resolved_request_id, route=route)
            request.headers.update(signed.headers)
        else:
            payload = self.payload(body)
            signed_body = self.canonical(method, path, payload, wire)
            signed = self.sign(method, path, signed_body, request_id=resolved_request_id, route=route)
            request = self._client.build_request(
                method,
                path,
                headers=signed.headers,
                params=wire or None,
                **({"json": payload} if payload is not EMPTY_BODY else {}),
            )
        response = self._client.send(request)
        return self.finish(response, signed, accepted_statuses=accepted_statuses)

    def _run(self, call: _Call, request_id: str | None) -> Any:
        return call.parse(
            self.authenticated_request(
                call.method,
                call.path,
                call.body,
                query=call.query,
                request_id=request_id,
                accepted_statuses=call.accepted_statuses,
            )
        )

    # Fulfillment.

    def schedule_resource(
        self, request: FulfillmentScheduleRequest, *, request_id: str | None = None
    ) -> FulfillmentScheduleResponse:
        return self._run(_schedule(request), request_id)

    def validate_fulfillment(
        self, body: FulfillmentRequestBody, *, request_id: str | None = None
    ) -> FulfillmentValidationResponse:
        """See ``ComputeProvisioningClient.validate_fulfillment``."""
        return self._run(_validate(body), request_id)

    def begin_fulfillment(
        self, body: FulfillmentRequestBody, *, request_id: str | None = None
    ) -> FulfillmentAcceptanceResponse:
        return self._run(_begin(body), request_id)

    def begin_fulfillment_teardown(
        self, fulfillment_id: str, *, request_id: str | None = None
    ) -> FulfillmentAcceptanceResponse:
        return self._run(_teardown(fulfillment_id), request_id)

    def get_fulfillment_status(
        self, fulfillment_id: str, *, request_id: str | None = None
    ) -> FulfillmentStatusResponse:
        return self._run(_status(fulfillment_id), request_id)

    def get_fulfillment_result(
        self, fulfillment_id: str, *, request_id: str | None = None
    ) -> VersionedEnvelope[dict[str, Any]]:
        return self._run(_result(fulfillment_id), request_id)

    # Leases.

    def register_lease(
        self, registration: LeaseRegistration, *, request_id: str | None = None
    ) -> LeaseView:
        return self._run(_register_lease(registration), request_id)

    def get_lease(self, capacity_reservation_id: str, *, request_id: str | None = None) -> LeaseView:
        return self._run(_get_lease(capacity_reservation_id), request_id)

    def terminate_lease(
        self, capacity_reservation_id: str, request: LeaseTermination, *, request_id: str | None = None
    ) -> LeaseView:
        return self._run(_lease_action(capacity_reservation_id, "terminate", request), request_id)

    def retry_lease_release(
        self, capacity_reservation_id: str, request: LeaseRetryRelease, *, request_id: str | None = None
    ) -> LeaseView:
        return self._run(_lease_action(capacity_reservation_id, "retry-release", request), request_id)

    def force_release_lease(
        self, capacity_reservation_id: str, request: LeaseForceRelease, *, request_id: str | None = None
    ) -> LeaseView:
        return self._run(_lease_action(capacity_reservation_id, "force-release", request), request_id)

    # Jobs.

    def list_jobs(
        self,
        *,
        status: str | None = None,
        offset: int = 0,
        limit: int = 20,
        escrow_uid: str | None = None,
        sort: JobListSort = "created_at_desc",
        request_id: str | None = None,
    ) -> JobListResponse:
        return self._run(_list_jobs(status, offset, limit, escrow_uid, sort), request_id)

    def get_job(self, job_id: str, *, request_id: str | None = None) -> JobStatusResponse:
        return self._run(_get_job(job_id), request_id)

    def get_job_credentials(self, job_id: str, *, request_id: str | None = None) -> JobCredentialsResponse:
        return self._run(_job_credentials(job_id), request_id)

    def get_job_logs(self, job_id: str, *, request_id: str | None = None) -> JobLogsResponse:
        return self._run(_job_logs(job_id), request_id)

    def cancel_job(self, job_id: str, *, request_id: str | None = None) -> dict[str, Any]:
        return self._run(_cancel_job(job_id), request_id)

    def poll_until_complete(
        self, job_id: str, *, timeout: float = 600.0, poll_interval: float = 2.0
    ) -> JobStatusResponse:
        """See ``ComputeProvisioningClient.poll_until_complete``."""
        deadline = time.monotonic() + timeout
        while True:
            job = self.get_job(job_id)
            if _job_outcome(job, job_id):
                return job
            if time.monotonic() >= deadline:
                raise ComputeProvisioningTimeoutError(
                    f"job {job_id} did not finish within {timeout}s (status {job.status})"
                )
            time.sleep(poll_interval)

    # Hosts.

    def list_hosts(
        self,
        *,
        search: str | None = None,
        include_disabled: bool = False,
        request_id: str | None = None,
    ) -> HostListResponse:
        return self._run(_list_hosts(search, include_disabled), request_id)

    def get_host(self, host_id: str, *, request_id: str | None = None) -> HostResponse:
        return self._run(_get_host(host_id), request_id)

    def register_host(self, body: HostCreate, *, request_id: str | None = None) -> HostResponse:
        return self._run(_register_host(body), request_id)

    def update_host(self, host_id: str, body: HostUpdate, *, request_id: str | None = None) -> HostResponse:
        return self._run(_update_host(host_id, body), request_id)

    def enable_host(self, host_id: str, *, request_id: str | None = None) -> HostResponse:
        return self._run(_set_host_enabled(host_id, True), request_id)

    def disable_host(self, host_id: str, *, request_id: str | None = None) -> HostResponse:
        return self._run(_set_host_enabled(host_id, False), request_id)

    def check_connectivity(self, host_id: str, *, request_id: str | None = None) -> ConnectivityResult:
        """See ``ComputeProvisioningClient.check_connectivity``."""
        return self._run(_connectivity(host_id), request_id)

    # The service's system and identity routes.

    def get_health(self) -> dict[str, Any]:
        """``GET /health``: unauthenticated local liveness."""
        return self.unsigned_body(self._client.get("/health"))

    def get_system_health(self, *, request_id: str | None = None) -> dict[str, Any]:
        return self._run(_system_get("/api/v1/system/health"), request_id)

    def get_system_status(self, *, request_id: str | None = None) -> dict[str, Any]:
        """See ``ComputeProvisioningClient.get_system_status``."""
        return self._run(_system_get("/api/v1/system/status", accepted_statuses=(503,)), request_id)

    def get_version(self, *, request_id: str | None = None) -> VersionResponse:
        return self._run(_version(), request_id)

    def get_ansible_readiness(self, *, request_id: str | None = None) -> dict[str, Any]:
        return self._run(_system_get("/api/v1/system/ansible/readiness"), request_id)

    def check_leases(self, *, request_id: str | None = None) -> dict[str, Any]:
        """Run one lease lifecycle cycle now."""
        return self._run(_system_post("/api/v1/system/check-leases"), request_id)

    def run_fulfillment_convergence_cycle(self, *, request_id: str | None = None) -> dict[str, Any]:
        return self._run(_system_post(f"{_CONVERGENCE}/run-cycle"), request_id)

    def advance_fulfillment_convergence_cycle(self, *, request_id: str | None = None) -> dict[str, Any]:
        """See ``ComputeProvisioningClient.advance_fulfillment_convergence_cycle``."""
        return self._run(_system_post(f"{_CONVERGENCE}/advance-cycle"), request_id)

    def pause_fulfillment_convergence(self, *, request_id: str | None = None) -> dict[str, Any]:
        return self._run(_system_post(f"{_CONVERGENCE}/pause"), request_id)

    def resume_fulfillment_convergence(self, *, request_id: str | None = None) -> dict[str, Any]:
        return self._run(_system_post(f"{_CONVERGENCE}/resume"), request_id)

    def pause_lease_watchdog(self, *, request_id: str | None = None) -> dict[str, Any]:
        return self._run(_system_post(f"{_LEASE_WATCHDOG}/pause"), request_id)

    def resume_lease_watchdog(self, *, request_id: str | None = None) -> dict[str, Any]:
        return self._run(_system_post(f"{_LEASE_WATCHDOG}/resume"), request_id)

    def rotate_trusted_principal(
        self, role: str, rotation: RotationRequest, *, request_id: str | None = None
    ) -> dict[str, Any]:
        return self._run(_rotate(role, rotation), request_id)


__all__ = [
    "ComputeProvisioningClient",
    "ComputeProvisioningClientProtocol",
    "SyncComputeProvisioningClient",
]
