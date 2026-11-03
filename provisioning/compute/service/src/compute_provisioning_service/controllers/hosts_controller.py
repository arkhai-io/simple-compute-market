"""The host registry's routes, bound to ``HostRouteService``.

Host import, which reads an Ansible inventory, is bound separately; a domain's
own host routes, such as VM's capacity check, are its adapter's. The host
definitions export and import are this registry's, since the document is the
family's, in the registration contract's own field names.
"""

from __future__ import annotations

from compute_provisioning.hosts.route_service import HostRouteService
from compute_provisioning_contracts import (
    ConnectivityResult,
    HostCreate,
    HostDefinitionsImportRequest,
    HostDefinitionsImportResponse,
    HostListResponse,
    HostResponse,
    HostUpdate,
)
from fastapi import APIRouter, Depends, Response, status

from compute_provisioning_service import container as _container_module
from compute_provisioning_service.controllers.route_errors import routed, routed_async

router = APIRouter(prefix="/hosts", tags=["hosts"])


def _service() -> HostRouteService:
    return HostRouteService(
        _container_module.resolved_host_authority,
        _container_module.resolved_connectivity_probes,
    )


@router.get("/", response_model=HostListResponse, summary="List registered hosts")
def list_hosts(
    search: str | None = None,
    include_disabled: bool = False,
    service: HostRouteService = Depends(_service),
) -> HostListResponse:
    """Registered hosts; ``search`` filters on the host id, case-insensitively."""
    return service.list_hosts(search=search, include_disabled=include_disabled)


@router.post(
    "/", response_model=HostResponse, status_code=status.HTTP_201_CREATED, summary="Register a host"
)
def register_host(body: HostCreate, service: HostRouteService = Depends(_service)) -> HostResponse:
    """Register a host; a submitted secret is protected before storage and never returned."""
    return routed(lambda: service.register_host(body))


@router.get(
    "/definitions/export",
    response_class=Response,
    responses={200: {"content": {"application/yaml": {}}}},
    summary="Export the registry as a host definitions document",
)
def export_host_definitions(service: HostRouteService = Depends(_service)) -> Response:
    """Every host an entry can state, in YAML, with no secret; importing it
    unedited changes nothing."""
    return Response(content=service.export_definitions(), media_type="application/yaml")


@router.post(
    "/definitions/import",
    response_model=HostDefinitionsImportResponse,
    summary="Reconcile a host definitions document",
)
def import_host_definitions(
    body: HostDefinitionsImportRequest, service: HostRouteService = Depends(_service)
) -> HostDefinitionsImportResponse:
    """Register or wholly replace each host the document names; leave the rest.

    Reconciles regardless of any document applied before, and records no digest. An
    applying request with any problem answers 422 with every problem and applies
    nothing; ``validate_only`` answers 200 with the problems and the changes an
    import would make, applying nothing either way.
    """
    return routed(lambda: service.import_definitions(body))


@router.get("/{host}", response_model=HostResponse, summary="Get host details")
def get_host(host: str, service: HostRouteService = Depends(_service)) -> HostResponse:
    return routed(lambda: service.get_host(host))


@router.put("/{host}", response_model=HostResponse, summary="Update a host")
def update_host(host: str, body: HostUpdate, service: HostRouteService = Depends(_service)) -> HostResponse:
    """Update a host's supplied fields; a connection replaces the whole connection."""
    return routed(lambda: service.update_host(host, body))


@router.post("/{host}/enable", response_model=HostResponse, summary="Re-enable a host")
def enable_host(host: str, service: HostRouteService = Depends(_service)) -> HostResponse:
    return routed(lambda: service.set_enabled(host, True))


@router.post("/{host}/disable", response_model=HostResponse, summary="Disable a host")
def disable_host(host: str, service: HostRouteService = Depends(_service)) -> HostResponse:
    """Disable a host; it is never deleted, so job history keeps resolving."""
    return routed(lambda: service.set_enabled(host, False))


@router.get(
    "/{host}/connectivity", response_model=ConnectivityResult, summary="Probe a host's connection"
)
async def check_connectivity(host: str, service: HostRouteService = Depends(_service)) -> ConnectivityResult:
    """Probe the host's connection by its kind: 200 with ``reachable`` either way, 404 if unknown."""
    return await routed_async(lambda: service.check_connectivity(host))
