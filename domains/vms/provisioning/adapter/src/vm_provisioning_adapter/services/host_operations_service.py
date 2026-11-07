"""VM's host operations: the capacity check and diagnostics jobs for a registered host."""

from __future__ import annotations

import dataclasses

from compute_provisioning.jobs.submission import JobSubmissionService
from compute_provisioning_contracts import JobSubmitResponse
from vm_provisioning_operator.models import HostDiagnosticsRequest, VmActionRequest

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

    async def diagnose(self, *, host: str, body: HostDiagnosticsRequest) -> JobSubmitResponse:
        """Submit a host diagnostics job for a registered host.

        The request has already refused a management unit that is not a
        systemd service unit name. Raises ``HostNotFoundError`` for an unregistered
        host.
        """
        params = dataclasses.replace(
            build_simple_params("diagnose", host, body), management_unit=body.management_unit
        )
        return await submit_vm_job(self._submission, params)
