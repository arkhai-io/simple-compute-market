"""The host registry's routes, without a web framework.

``HostRouteService`` serves host CRUD, enable and disable, connectivity, and
the host definitions export and import over the host authority. Connectivity is
a probe of the host's connection, and how a connection is probed belongs to the
implementation that supports its kind, so probes arrive keyed by connection
kind, the way codecs do; a host whose kind has no probe is refused rather than
probed some other way.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from types import MappingProxyType

from compute_provisioning_contracts import (
    ConnectivityResult,
    HostCreate,
    HostDefinitionsImportRequest,
    HostDefinitionsImportResponse,
    HostListResponse,
    HostResponse,
    HostUpdate,
)
from sqlalchemy.exc import IntegrityError

from compute_provisioning.hosts.definitions import (
    reconcile_host_definitions_in_session,
    render_host_definitions,
)
from compute_provisioning.hosts.execution import ExecutionHost
from compute_provisioning.hosts.service import (
    HostAuthority,
    HostNotFoundError,
    PoolChangeRefusedError,
)
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
        except PoolChangeRefusedError as exc:
            raise ProvisioningRouteError(409, str(exc)) from exc
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
        except PoolChangeRefusedError as exc:
            raise ProvisioningRouteError(409, str(exc)) from exc
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

    def export_definitions(self) -> str:
        """The registry as a host definitions document, with no secret.

        Importing it unedited changes nothing.
        """
        return render_host_definitions(self._hosts.host_definitions())

    def import_definitions(self, body: HostDefinitionsImportRequest) -> HostDefinitionsImportResponse:
        """Reconcile a submitted document, whatever document was applied before.

        Commits only an applying request whose document has no problem; any
        other is rolled back, so a validate-only request reports the changes it
        would make without making them, problems included. An applying request
        with any problem is refused with 422, its detail the same response, so a
        caller reads every problem whichever way it asked. A host the document
        creates that another request registered first fails the write, and is
        refused as a conflict: the document can be submitted again.
        """
        with self._hosts.session() as db:
            # A new host placed in a pool is flushed during reconciliation, so
            # its pool-change hooks can read it; that flush, like the commit,
            # can meet a host another request registered first.
            try:
                outcome = reconcile_host_definitions_in_session(db, self._hosts, body.yaml_text)
                applied = outcome.valid and not body.validate_only
                if applied:
                    db.commit()
                else:
                    db.rollback()
            except IntegrityError as exc:
                db.rollback()
                raise ProvisioningRouteError(
                    409,
                    "a host this document creates was registered by another request "
                    "while it was applied; submit the document again",
                ) from exc
        response = HostDefinitionsImportResponse(
            applied=applied,
            diff=outcome.diff,
            not_named=list(outcome.not_named),
            problems=list(outcome.problems),
        )
        if not outcome.valid and not body.validate_only:
            raise ProvisioningRouteError(422, response.model_dump(mode="json"))
        return response

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
