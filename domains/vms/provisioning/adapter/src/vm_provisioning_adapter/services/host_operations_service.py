"""VM's host operation: submitting a capacity check job for a registered host."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from compute_provisioning.hosts.service import HostNotFoundError
from compute_provisioning.jobs.queue import AsyncJobQueue
from compute_provisioning_contracts import JobSubmitResponse
from vm_provisioning_operator.models import VmActionRequest

from vm_provisioning_adapter.models.vm_request_model import build_simple_params

if TYPE_CHECKING:
    from compute_provisioning.hosts.service import HostAuthority
    from vm_provisioning_adapter.services.job_submitter import VmJobSubmitter


class HostOperationsService:
    def __init__(
        self,
        *,
        host_service: "HostAuthority",
        job_submitter: "VmJobSubmitter",
        job_queue_provider: Callable[[], AsyncJobQueue],
    ) -> None:
        self._host_service = host_service
        self._job_submitter = job_submitter
        self._job_queue_provider = job_queue_provider

    async def check_capacity(self, *, host: str, body: VmActionRequest) -> JobSubmitResponse:
        """Submit a capacity check job for a registered host."""
        if self._host_service.get_host(host) is None:
            raise HostNotFoundError(f"Host '{host}' not found")
        params = build_simple_params("check", host, body)
        return await self._job_submitter.submit(params, self._job_queue_provider())
