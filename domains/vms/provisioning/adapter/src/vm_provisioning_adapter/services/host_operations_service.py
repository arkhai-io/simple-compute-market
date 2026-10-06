"""VM's host operation: submitting a capacity check job for a registered host."""

from __future__ import annotations

from compute_provisioning.jobs.submission import JobSubmissionService
from compute_provisioning_contracts import JobSubmitResponse
from vm_provisioning_operator.models import VmActionRequest

from vm_provisioning_adapter.models.vm_request_model import build_simple_params
from vm_provisioning_adapter.services.vm_operations_service import submit_vm_job


class HostOperationsService:
    def __init__(self, *, submission: JobSubmissionService) -> None:
        self._submission = submission

    async def check_capacity(self, *, host: str, body: VmActionRequest) -> JobSubmitResponse:
        """Submit a capacity check job for a registered host.

        Raises ``HostNotFoundError`` for an unregistered host, as every job's
        submission does.
        """
        return await submit_vm_job(self._submission, build_simple_params("check", host, body))
