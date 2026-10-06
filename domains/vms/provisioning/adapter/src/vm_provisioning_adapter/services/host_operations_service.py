"""Service boundary for host operational checks.

HostController owns HTTP details.  This service owns operational work such as
submitting capacity check jobs and rendering temporary inventories for Ansible
connectivity checks.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from vm_provisioning_operator.models import JobSubmitResponse, VmActionRequest
from vm_provisioning_adapter.models.ansible import ConnectivityResult
from vm_provisioning_adapter.models.vm_request_model import build_simple_params
from compute_provisioning_service.services.async_job_queue import AsyncJobQueue
from vm_provisioning_adapter.services.host_service import HostNotFoundError

if TYPE_CHECKING:
    from vm_provisioning_adapter.services.ansible_service import AnsibleService
    from vm_provisioning_adapter.services.host_service import HostService
    from vm_provisioning_adapter.services.job_service import AnsibleJobService


class HostOperationsService:
    """Operational host checks that may call Ansible or submit jobs."""

    def __init__(
        self,
        *,
        ansible_service: "AnsibleService",
        host_service: "HostService",
        job_service: "AnsibleJobService",
        job_queue_provider: Callable[[], AsyncJobQueue],
    ) -> None:
        self._ansible_service = ansible_service
        self._host_service = host_service
        self._job_service = job_service
        self._job_queue_provider = job_queue_provider

    async def check_capacity(
        self,
        *,
        host: str,
        body: VmActionRequest,
    ) -> JobSubmitResponse:
        """Submit a capacity check job for a registered host."""
        if self._host_service.get_host(host) is None:
            raise HostNotFoundError(f"Host '{host}' not found")
        params = build_simple_params("check", host, body)
        return await self._job_service.submit(params, self._job_queue_provider())

    async def check_connectivity(self, *, host: str) -> ConnectivityResult:
        """Run an Ansible connectivity check for a registered host."""
        host_row = self._host_service.get_host(host)
        if host_row is None:
            raise HostNotFoundError(f"Host '{host}' not found")

        inv_path = self._ansible_service.write_inventory([host_row])
        try:
            return await self._ansible_service.check_connectivity_with_inventory(
                host,
                inv_path,
            )
        finally:
            try:
                inv_path.unlink(missing_ok=True)
            except Exception:
                pass
