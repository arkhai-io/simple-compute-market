"""Service boundary for direct admin/operator VM operations.

The controller layer owns HTTP routing and schema metadata.  This service owns
conversion from VM operation requests into Ansible job submissions, including
queue selection.  Lease-aware teardown is intentionally not exposed here; market
managed VM removal belongs to the lease lifecycle service.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Optional

from models.jobs_model import JobSubmitResponse
from models.vm_request_model import CreateVmRequest, VmActionRequest, build_simple_params
from services.async_job_queue import AsyncJobQueue

if TYPE_CHECKING:
    from services.job_service import AnsibleJobService


class VmOperationsService:
    """Submit direct VM operation jobs for admin/operator endpoints."""

    def __init__(
        self,
        *,
        job_service: "AnsibleJobService",
        job_queue_provider: Callable[[], AsyncJobQueue],
    ) -> None:
        self._job_service = job_service
        self._job_queue_provider = job_queue_provider

    async def create_vm(self, *, host: str, body: CreateVmRequest) -> JobSubmitResponse:
        """Submit a VM creation job for ``host``."""
        return await self._job_service.submit(
            body.to_ansible_job_params(host),
            self._job_queue_provider(),
        )

    async def list_vms(self, *, host: str, body: VmActionRequest) -> JobSubmitResponse:
        """Submit a host-scoped VM list job."""
        return await self._submit_simple(action="list", host=host, body=body)

    async def submit_action(
        self,
        *,
        action: str,
        host: str,
        body: VmActionRequest,
        vm_name: Optional[str] = None,
    ) -> JobSubmitResponse:
        """Submit a single-VM lifecycle/diagnostic action job."""
        return await self._submit_simple(
            action=action,
            host=host,
            body=body,
            vm_name=vm_name,
        )

    async def _submit_simple(
        self,
        *,
        action: str,
        host: str,
        body: VmActionRequest,
        vm_name: Optional[str] = None,
    ) -> JobSubmitResponse:
        params = build_simple_params(action, host, body, vm_name)
        return await self._job_service.submit(params, self._job_queue_provider())
