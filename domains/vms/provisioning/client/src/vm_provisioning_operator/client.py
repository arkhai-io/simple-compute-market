"""Typed VM methods over the compute provisioning client's transport.

The family client names no domain's routes. VM's operations, its host capacity
check, and relay administration are VM's, so these clients
wrap any transport offering ``authenticated_request`` -- the family's async or
sync client -- and name each route's declaration from ``routes``, the same
declarations the provisioning service assembles into the table its request
authentication reads. ``VmOperatorClient`` wraps an async transport and
``SyncVmOperatorClient`` a sync one, with identical method signatures.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
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


__all__ = ["SyncVmOperatorClient", "VmOperatorClient"]
