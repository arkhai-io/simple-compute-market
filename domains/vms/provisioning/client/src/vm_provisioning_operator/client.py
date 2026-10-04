"""Typed VM methods over the compute provisioning client's transport.

The family client names no domain's routes. VM's operations, its host capacity
check, relay administration, and VM's lease routes are VM's, so these clients
wrap any transport offering ``authenticated_request`` -- the family's async or
sync client -- and name each route's declaration from ``routes``, the same
declarations the provisioning service assembles into the table its request
authentication reads. ``VmOperatorClient`` wraps an async transport and
``SyncVmOperatorClient`` a sync one, with identical method signatures.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional, Protocol

from compute_provisioning_contracts import JobSubmitResponse

from vm_provisioning_operator.models import CreateVmRequest, VmActionRequest
from vm_provisioning_operator.relays import (
    RelayCreate,
    RelayListResponse,
    RelayResponse,
    RelayTokenRotate,
    RelayUpdate,
)
from vm_provisioning_operator.routes import vm_route


class _Transport(Protocol):
    def authenticated_request(self, method: str, path: str, *args: Any, **kwargs: Any) -> Any: ...


_NO_BODY = object()


def _same(value: Any) -> Any:
    return value


@dataclass(frozen=True)
class _Call:
    operation: str
    method: str
    path: str
    body: Any = _NO_BODY
    query: Mapping[str, Any] | None = None
    parse: Callable[[Any], Any] = _same

    def arguments(self) -> tuple[tuple, dict[str, Any]]:
        args: tuple = (self.method, self.path)
        if self.body is not _NO_BODY:
            args += (self.body,)
        kwargs: dict[str, Any] = {"route": vm_route(self.operation)}
        if self.query:
            kwargs["query"] = self.query
        return args, kwargs


def _submitted(payload: Any) -> JobSubmitResponse:
    return JobSubmitResponse.model_validate(payload)


def _vm(operation: str, host: str, vm_name: str, body: Optional[VmActionRequest]) -> _Call:
    action = operation.removeprefix("provisioning_vm_").replace("_", "-")
    return _Call(
        operation,
        "POST",
        f"/api/v1/hosts/{host}/vms/{vm_name}/{action}",
        body or VmActionRequest(),
        parse=_submitted,
    )


def _create_vm(host: str, body: CreateVmRequest) -> _Call:
    return _Call("provisioning_vm_create", "POST", f"/api/v1/hosts/{host}/vms/", body, parse=_submitted)


def _list_vms(host: str, body: Optional[VmActionRequest]) -> _Call:
    query = (body or VmActionRequest()).model_dump(exclude_none=True)
    return _Call("provisioning_vm_list", "GET", f"/api/v1/hosts/{host}/vms/", query=query, parse=_submitted)


def _monitor_vm(host: str, vm_name: str) -> _Call:
    return _Call(
        "provisioning_vm_monitor", "GET", f"/api/v1/hosts/{host}/vms/{vm_name}/monitor", parse=_submitted
    )


def _check_capacity(host: str) -> _Call:
    return _Call("provisioning_host_capacity", "GET", f"/api/v1/hosts/{host}/capacity", parse=_submitted)


def _list_relays() -> _Call:
    return _Call("provisioning_relays_list", "GET", "/api/v1/relays/", parse=RelayListResponse.model_validate)


def _create_relay(body: RelayCreate) -> _Call:
    return _Call("provisioning_relay_create", "POST", "/api/v1/relays/", body, parse=RelayResponse.model_validate)


def _get_relay(relay_id: str) -> _Call:
    return _Call("provisioning_relay_get", "GET", f"/api/v1/relays/{relay_id}", parse=RelayResponse.model_validate)


def _update_relay(relay_id: str, body: RelayUpdate) -> _Call:
    return _Call(
        "provisioning_relay_update", "PATCH", f"/api/v1/relays/{relay_id}", body, parse=RelayResponse.model_validate
    )


def _rotate_relay_token(relay_id: str, body: RelayTokenRotate) -> _Call:
    return _Call(
        "provisioning_relay_rotate_token",
        "POST",
        f"/api/v1/relays/{relay_id}/token",
        body,
        parse=RelayResponse.model_validate,
    )


def _set_relay_enabled(relay_id: str, enabled: bool) -> _Call:
    action = "enable" if enabled else "disable"
    return _Call(
        f"provisioning_relay_{action}",
        "POST",
        f"/api/v1/relays/{relay_id}/{action}",
        {},
        parse=RelayResponse.model_validate,
    )


def _iso(value: datetime | str) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _register_lease(
    resource_id: str,
    escrow_uid: str,
    host_id: str,
    vm_target: str,
    lease_end_utc: datetime | str,
    lease_start_utc: datetime | str | None,
    create_job_id: str | None,
    capacity_reservation_id: str | None,
) -> _Call:
    body: dict[str, Any] = {
        "resource_id": resource_id,
        "escrow_uid": escrow_uid,
        "host_id": host_id,
        "vm_target": vm_target,
        "lease_end_utc": _iso(lease_end_utc),
    }
    if capacity_reservation_id is not None:
        body["capacity_reservation_id"] = capacity_reservation_id
    if lease_start_utc is not None:
        body["lease_start_utc"] = _iso(lease_start_utc)
    if create_job_id is not None:
        body["create_job_id"] = create_job_id
    return _Call("provisioning_lease_create", "POST", "/api/v1/leases/", body)


def _list_leases(status: str | None, host_id: str | None, escrow_uid: str | None) -> _Call:
    query = {"status": status, "host_id": host_id, "escrow_uid": escrow_uid}
    return _Call(
        "provisioning_leases_list",
        "GET",
        "/api/v1/leases/",
        query={key: value for key, value in query.items() if value is not None},
    )


def _get_lease(lease_id: str) -> _Call:
    return _Call("provisioning_lease_admin_get", "GET", f"/api/v1/leases/{lease_id}")


def _get_lease_by_escrow(escrow_uid: str) -> _Call:
    return _Call("provisioning_lease_by_escrow", "GET", f"/api/v1/leases/by-escrow/{escrow_uid}")


def _update_lease(lease_id: str, fields: dict[str, Any]) -> _Call:
    return _Call("provisioning_lease_update", "PATCH", f"/api/v1/leases/{lease_id}", fields)


def _terminate_lease(lease_id: str, fields: dict[str, Any]) -> _Call:
    return _Call("provisioning_lease_admin_terminate", "POST", f"/api/v1/leases/{lease_id}/terminate", fields)


def _release_oversight(lease_id: str, reason: str) -> _Call:
    return _Call(
        "provisioning_lease_release_oversight",
        "POST",
        f"/api/v1/leases/{lease_id}/release-oversight",
        {"reason": reason},
    )


def _retry_release(lease_id: str, reason: str | None, max_retries: int | None) -> _Call:
    body = {key: value for key, value in (("reason", reason), ("max_retries", max_retries)) if value is not None}
    return _Call(
        "provisioning_lease_admin_retry_release",
        "POST",
        f"/api/v1/admin/leases/{lease_id}/retry-release",
        body,
    )


def _force_release(lease_id: str, reason: str, evidence: str | None) -> _Call:
    body: dict[str, Any] = {"reason": reason}
    if evidence is not None:
        body["evidence"] = evidence
    return _Call(
        "provisioning_lease_admin_force_release",
        "POST",
        f"/api/v1/admin/leases/{lease_id}/force-release",
        body,
    )


class VmOperatorClient:
    """VM's provisioning routes over an async signing transport."""

    def __init__(self, transport: _Transport) -> None:
        self._transport = transport

    async def _run(self, call: _Call) -> Any:
        args, kwargs = call.arguments()
        return call.parse(await self._transport.authenticated_request(*args, **kwargs))

    # VM operations.

    async def create_vm(self, host: str, body: CreateVmRequest) -> JobSubmitResponse:
        return await self._run(_create_vm(host, body))

    async def list_vms(self, host: str, body: Optional[VmActionRequest] = None) -> JobSubmitResponse:
        return await self._run(_list_vms(host, body))

    async def start_vm(self, host: str, vm_name: str, body: Optional[VmActionRequest] = None) -> JobSubmitResponse:
        return await self._run(_vm("provisioning_vm_start", host, vm_name, body))

    async def shutdown_vm(self, host: str, vm_name: str, body: Optional[VmActionRequest] = None) -> JobSubmitResponse:
        return await self._run(_vm("provisioning_vm_shutdown", host, vm_name, body))

    async def reboot_vm(self, host: str, vm_name: str, body: Optional[VmActionRequest] = None) -> JobSubmitResponse:
        return await self._run(_vm("provisioning_vm_reboot", host, vm_name, body))

    async def destroy_vm(self, host: str, vm_name: str, body: Optional[VmActionRequest] = None) -> JobSubmitResponse:
        return await self._run(_vm("provisioning_vm_destroy", host, vm_name, body))

    async def undefine_vm(self, host: str, vm_name: str, body: Optional[VmActionRequest] = None) -> JobSubmitResponse:
        return await self._run(_vm("provisioning_vm_undefine", host, vm_name, body))

    async def monitor_vm(self, host: str, vm_name: str) -> JobSubmitResponse:
        return await self._run(_monitor_vm(host, vm_name))

    async def reset_password(
        self, host: str, vm_name: str, body: Optional[VmActionRequest] = None
    ) -> JobSubmitResponse:
        return await self._run(_vm("provisioning_vm_reset_password", host, vm_name, body))

    async def check_capacity(self, host: str) -> JobSubmitResponse:
        return await self._run(_check_capacity(host))

    # Relays.

    async def list_relays(self) -> RelayListResponse:
        return await self._run(_list_relays())

    async def create_relay(self, body: RelayCreate) -> RelayResponse:
        return await self._run(_create_relay(body))

    async def get_relay(self, relay_id: str) -> RelayResponse:
        return await self._run(_get_relay(relay_id))

    async def update_relay(self, relay_id: str, body: RelayUpdate) -> RelayResponse:
        return await self._run(_update_relay(relay_id, body))

    async def rotate_relay_token(self, relay_id: str, body: RelayTokenRotate) -> RelayResponse:
        """Replace a relay's admission token; separate from ``update_relay`` deliberately."""
        return await self._run(_rotate_relay_token(relay_id, body))

    async def set_relay_enabled(self, relay_id: str, enabled: bool) -> RelayResponse:
        return await self._run(_set_relay_enabled(relay_id, enabled))

    # VM's lease routes.

    async def register_lease(
        self,
        *,
        resource_id: str,
        escrow_uid: str,
        host_id: str,
        vm_target: str,
        lease_end_utc: datetime | str,
        lease_start_utc: datetime | str | None = None,
        create_job_id: str | None = None,
        capacity_reservation_id: str | None = None,
    ) -> dict:
        return await self._run(
            _register_lease(
                resource_id, escrow_uid, host_id, vm_target, lease_end_utc,
                lease_start_utc, create_job_id, capacity_reservation_id,
            )
        )

    async def list_leases(
        self, *, status: str | None = None, host_id: str | None = None, escrow_uid: str | None = None
    ) -> dict:
        return await self._run(_list_leases(status, host_id, escrow_uid))

    async def get_lease(self, lease_id: str) -> dict:
        return await self._run(_get_lease(lease_id))

    async def get_lease_by_escrow(self, escrow_uid: str) -> dict:
        return await self._run(_get_lease_by_escrow(escrow_uid))

    async def update_lease(self, lease_id: str, **fields: Any) -> dict:
        return await self._run(_update_lease(lease_id, fields))

    async def terminate_lease(self, lease_id: str, **fields: Any) -> dict:
        return await self._run(_terminate_lease(lease_id, fields))

    async def release_lease_oversight(self, lease_id: str, *, reason: str) -> dict:
        return await self._run(_release_oversight(lease_id, reason))

    async def retry_lease_release(
        self, lease_id: str, *, reason: str | None = None, max_retries: int | None = None
    ) -> dict:
        return await self._run(_retry_release(lease_id, reason, max_retries))

    async def force_release_lease(self, lease_id: str, *, reason: str, evidence: str | None = None) -> dict:
        return await self._run(_force_release(lease_id, reason, evidence))


class SyncVmOperatorClient:
    """VM's provisioning routes over a sync signing transport."""

    def __init__(self, transport: _Transport) -> None:
        self._transport = transport

    def _run(self, call: _Call) -> Any:
        args, kwargs = call.arguments()
        return call.parse(self._transport.authenticated_request(*args, **kwargs))

    # VM operations.

    def create_vm(self, host: str, body: CreateVmRequest) -> JobSubmitResponse:
        return self._run(_create_vm(host, body))

    def list_vms(self, host: str, body: Optional[VmActionRequest] = None) -> JobSubmitResponse:
        return self._run(_list_vms(host, body))

    def start_vm(self, host: str, vm_name: str, body: Optional[VmActionRequest] = None) -> JobSubmitResponse:
        return self._run(_vm("provisioning_vm_start", host, vm_name, body))

    def shutdown_vm(self, host: str, vm_name: str, body: Optional[VmActionRequest] = None) -> JobSubmitResponse:
        return self._run(_vm("provisioning_vm_shutdown", host, vm_name, body))

    def reboot_vm(self, host: str, vm_name: str, body: Optional[VmActionRequest] = None) -> JobSubmitResponse:
        return self._run(_vm("provisioning_vm_reboot", host, vm_name, body))

    def destroy_vm(self, host: str, vm_name: str, body: Optional[VmActionRequest] = None) -> JobSubmitResponse:
        return self._run(_vm("provisioning_vm_destroy", host, vm_name, body))

    def undefine_vm(self, host: str, vm_name: str, body: Optional[VmActionRequest] = None) -> JobSubmitResponse:
        return self._run(_vm("provisioning_vm_undefine", host, vm_name, body))

    def monitor_vm(self, host: str, vm_name: str) -> JobSubmitResponse:
        return self._run(_monitor_vm(host, vm_name))

    def reset_password(self, host: str, vm_name: str, body: Optional[VmActionRequest] = None) -> JobSubmitResponse:
        return self._run(_vm("provisioning_vm_reset_password", host, vm_name, body))

    def check_capacity(self, host: str) -> JobSubmitResponse:
        return self._run(_check_capacity(host))

    # Relays.

    def list_relays(self) -> RelayListResponse:
        return self._run(_list_relays())

    def create_relay(self, body: RelayCreate) -> RelayResponse:
        return self._run(_create_relay(body))

    def get_relay(self, relay_id: str) -> RelayResponse:
        return self._run(_get_relay(relay_id))

    def update_relay(self, relay_id: str, body: RelayUpdate) -> RelayResponse:
        return self._run(_update_relay(relay_id, body))

    def rotate_relay_token(self, relay_id: str, body: RelayTokenRotate) -> RelayResponse:
        """See ``VmOperatorClient.rotate_relay_token``."""
        return self._run(_rotate_relay_token(relay_id, body))

    def set_relay_enabled(self, relay_id: str, enabled: bool) -> RelayResponse:
        return self._run(_set_relay_enabled(relay_id, enabled))

    # VM's lease routes.

    def register_lease(
        self,
        *,
        resource_id: str,
        escrow_uid: str,
        host_id: str,
        vm_target: str,
        lease_end_utc: datetime | str,
        lease_start_utc: datetime | str | None = None,
        create_job_id: str | None = None,
        capacity_reservation_id: str | None = None,
    ) -> dict:
        return self._run(
            _register_lease(
                resource_id, escrow_uid, host_id, vm_target, lease_end_utc,
                lease_start_utc, create_job_id, capacity_reservation_id,
            )
        )

    def list_leases(
        self, *, status: str | None = None, host_id: str | None = None, escrow_uid: str | None = None
    ) -> dict:
        return self._run(_list_leases(status, host_id, escrow_uid))

    def get_lease(self, lease_id: str) -> dict:
        return self._run(_get_lease(lease_id))

    def get_lease_by_escrow(self, escrow_uid: str) -> dict:
        return self._run(_get_lease_by_escrow(escrow_uid))

    def update_lease(self, lease_id: str, **fields: Any) -> dict:
        return self._run(_update_lease(lease_id, fields))

    def terminate_lease(self, lease_id: str, **fields: Any) -> dict:
        return self._run(_terminate_lease(lease_id, fields))

    def release_lease_oversight(self, lease_id: str, *, reason: str) -> dict:
        return self._run(_release_oversight(lease_id, reason))

    def retry_lease_release(
        self, lease_id: str, *, reason: str | None = None, max_retries: int | None = None
    ) -> dict:
        return self._run(_retry_release(lease_id, reason, max_retries))

    def force_release_lease(self, lease_id: str, *, reason: str, evidence: str | None = None) -> dict:
        return self._run(_force_release(lease_id, reason, evidence))


__all__ = ["SyncVmOperatorClient", "VmOperatorClient"]
