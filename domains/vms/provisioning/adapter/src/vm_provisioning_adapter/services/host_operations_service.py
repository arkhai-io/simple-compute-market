"""Service boundary for host operational checks.

HostController owns HTTP details.  This service owns operational work such as
submitting capacity check jobs and rendering temporary inventories for Ansible
connectivity checks.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from vm_provisioning_operator.models import VmActionRequest
from compute_provisioning_contracts import JobSubmitResponse
from compute_provisioning_contracts import ConnectivityResult
from vm_provisioning_adapter.models.vm_request_model import build_simple_params
from compute_provisioning.jobs.queue import AsyncJobQueue
from compute_provisioning.hosts.service import HostNotFoundError
from compute_provisioning_ansible import probe_connectivity

if TYPE_CHECKING:
    from compute_provisioning_ansible.runner import AnsibleRunner
    from compute_provisioning.hosts.service import HostAuthority
    from vm_provisioning_adapter.services.job_service import AnsibleJobService


class HostOperationsService:
    """Operational host checks that may call Ansible or submit jobs."""

    def __init__(
        self,
        *,
        ansible_service: "AnsibleRunner",
        host_service: "HostAuthority",
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
        execution_host = self._host_service.lookup(host)
        if execution_host is None:
            raise HostNotFoundError(f"Host '{host}' not found")

        return await probe_connectivity(self._ansible_service, execution_host)
