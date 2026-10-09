"""VM's host route: the capacity check.

``GET /api/v1/hosts/{host}/capacity`` submits a VM capacity check job. The host
registry's own routes are the compute family's, bound by the provisioning
service; VM operations scoped to a host are ``make_vms_router``'s.
"""

from __future__ import annotations

from collections.abc import Callable

from compute_provisioning.hosts.service import HostNotFoundError
from compute_provisioning_contracts import JobSubmitResponse
from fastapi import APIRouter, Depends, HTTPException, status
from vm_provisioning_operator.models import VmActionRequest

from vm_provisioning_adapter.controllers.route_binding import dependency
from vm_provisioning_adapter.services.host_operations_service import HostOperationsService


def make_host_capacity_router(
    host_operations: Callable[[], HostOperationsService | None],
) -> APIRouter:
    """The capacity check, over the service ``host_operations`` resolves per request."""
    router = APIRouter(prefix="/hosts", tags=["hosts"])
    resolve_operations = dependency(host_operations, "VM host operations")

    @router.get(
        "/{host}/capacity",
        response_model=JobSubmitResponse,
        status_code=status.HTTP_202_ACCEPTED,
        summary="Check host resource capacity",
    )
    async def check_capacity(
        host: str,
        body: VmActionRequest = Depends(),
        operations: HostOperationsService = Depends(resolve_operations),
    ) -> JobSubmitResponse:
        """Submit a job reporting total, allocated, and available resources on ``host``.

        Reports vCPU, RAM, and GPU inventory; ``result.resources`` carries the
        breakdown on success. Returns **404** if the host is not registered.
        Poll ``GET /api/v1/jobs/{job_id}`` for the job's status.
        """
        try:
            return await operations.check_capacity(host=host, body=body)
        except HostNotFoundError:
            raise HTTPException(status_code=404, detail=f"Host '{host}' not found")

    return router
