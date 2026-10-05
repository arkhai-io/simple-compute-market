"""VM's host route: the capacity check.

``GET /api/v1/hosts/{host}/capacity`` submits a VM capacity check job. The host
registry's own routes are the compute family's, bound by the provisioning
service; VM operations scoped to a host are ``VmController``'s.
"""

from __future__ import annotations

from compute_provisioning.hosts.service import HostNotFoundError
from compute_provisioning_contracts import JobSubmitResponse
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi_utils.cbv import cbv
from vm_provisioning_operator.models import VmActionRequest

from compute_provisioning_service import container as _container_module
from vm_provisioning_adapter.services.host_operations_service import HostOperationsService

router = APIRouter(prefix="/hosts", tags=["hosts"])


@cbv(router)
class HostController:
    def __init__(
        self,
        host_operations: HostOperationsService = Depends(
            lambda: _container_module.resolved_host_operations_service
        ),
    ) -> None:
        self._host_operations = host_operations

    @router.get(
        "/{host}/capacity",
        response_model=JobSubmitResponse,
        status_code=status.HTTP_202_ACCEPTED,
        summary="Check host resource capacity",
    )
    async def check_capacity(
        self,
        host: str,
        body: VmActionRequest = Depends(),
    ) -> JobSubmitResponse:
        """Submit a job reporting total, allocated, and available resources on ``host``.

        Reports vCPU, RAM, and GPU inventory; ``result.resources`` carries the
        breakdown on success. Returns **404** if the host is not registered.
        Poll ``GET /api/v1/jobs/{job_id}`` for the job's status.
        """
        try:
            return await self._host_operations.check_capacity(host=host, body=body)
        except HostNotFoundError:
            raise HTTPException(status_code=404, detail=f"Host '{host}' not found")

    @classmethod
    def make_router(cls) -> APIRouter:
        return router
