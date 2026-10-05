"""The host registry's routes, without a web framework.

``HostRouteService`` serves host CRUD, enable and disable, and connectivity
over the host authority. Connectivity is a probe of the host's connection, and
how a connection is probed belongs to the implementation that supports its
kind, so probes arrive keyed by connection kind, the way codecs do; a host
whose kind has no probe is refused rather than probed some other way.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from types import MappingProxyType

from compute_provisioning_contracts import (
    ConnectivityResult,
    HostCreate,
    HostListResponse,
    HostResponse,
    HostUpdate,
)
from sqlalchemy.exc import IntegrityError

from compute_provisioning.hosts.execution import ExecutionHost
from compute_provisioning.hosts.service import HostAuthority, HostNotFoundError
from compute_provisioning.route_errors import ProvisioningRouteError

ConnectivityProbe = Callable[[ExecutionHost], Awaitable[ConnectivityResult]]


def _missing(host_id: str) -> ProvisioningRouteError:
    return ProvisioningRouteError(404, f"Host '{host_id}' not found")


class HostRouteService:
    def __init__(
        self,
        host_authority: HostAuthority,
        probes: Mapping[str, ConnectivityProbe],
    ) -> None:
        self._hosts = host_authority
        self._probes = MappingProxyType(dict(probes))

    def list_hosts(self, *, search: str | None = None, include_disabled: bool = False) -> HostListResponse:
        hosts = list(self._hosts.list_hosts(search=search, enabled_only=not include_disabled))
        return HostListResponse(hosts=hosts, total=len(hosts))

    def register_host(self, body: HostCreate) -> HostResponse:
        """Register a host; its connection is validated and protected by its kind's codec."""
        try:
            return self._hosts.register_host(body)
        except IntegrityError as exc:
            raise ProvisioningRouteError(
                409,
                f"Host '{body.host_id}' already exists. Use PUT /hosts/{body.host_id} to "
                f"update or POST /hosts/{body.host_id}/enable to re-enable.",
            ) from exc
        except ValueError as exc:
            raise ProvisioningRouteError(400, str(exc)) from exc

    def get_host(self, host_id: str) -> HostResponse:
        host = self._hosts.get_host(host_id)
        if host is None:
            raise _missing(host_id)
        return host

    def update_host(self, host_id: str, body: HostUpdate) -> HostResponse:
        try:
            return self._hosts.update_host(host_id, body)
        except HostNotFoundError as exc:
            raise _missing(host_id) from exc
        except ValueError as exc:
            raise ProvisioningRouteError(400, str(exc)) from exc

    def set_enabled(self, host_id: str, enabled: bool) -> HostResponse:
        """Enable or disable a host; a disabled host is kept so job history resolves."""
        try:
            if enabled:
                return self._hosts.enable_host(host_id)
            return self._hosts.disable_host(host_id)
        except HostNotFoundError as exc:
            raise _missing(host_id) from exc

    async def check_connectivity(self, host_id: str) -> ConnectivityResult:
        """Probe a host's connection; an unreachable host is a result, not a refusal."""
        execution_host = self._hosts.lookup(host_id)
        if execution_host is None:
            raise _missing(host_id)
        kind = execution_host.connection.kind
        probe = self._probes.get(kind)
        if probe is None:
            raise ProvisioningRouteError(
                422, f"no connectivity probe is registered for connection kind {kind!r}"
            )
        return await probe(execution_host)


__all__ = ["ConnectivityProbe", "HostRouteService"]
