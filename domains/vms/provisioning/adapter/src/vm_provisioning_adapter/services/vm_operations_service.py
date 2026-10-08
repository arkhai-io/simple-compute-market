"""Service boundary for direct admin/operator VM operations.

The controller layer owns HTTP routing and schema metadata.  This service owns
conversion from VM operation requests into job submissions through the compute
family's job submission.  Lease-aware teardown is intentionally not exposed here; market
managed VM removal belongs to the lease lifecycle service.
"""

from __future__ import annotations

import dataclasses
from typing import Optional

from compute_provisioning.jobs.submission import JobSubmissionService
from compute_provisioning_contracts import JobSubmitResponse
from vm_provisioning_operator.models import CreateVmRequest, VmActionRequest

from vm_provisioning_adapter.models.jobs_model import VmJobParams
from vm_provisioning_adapter.models.vm_request_model import build_create_params, build_simple_params


async def submit_vm_job(
    submission: JobSubmissionService,
    params: VmJobParams,
    *,
    operation_id: str | None = None,
) -> JobSubmitResponse:
    """Submit an operator's VM job, under the operation id its request names.

    An operator's job is not a fulfillment's: it has no contract, and its host
    need only be registered.
    """
    return await submission.submit(
        offering_mode=params.offering_mode,
        action=str(params.executor_action),
        host_id=params.host_id,
        params=dataclasses.asdict(params),
        operation_id=operation_id,
        max_retries=params.max_retries,
    )


class VmOperationsService:
    """Submit direct VM operation jobs for admin/operator endpoints."""

    def __init__(self, *, submission: JobSubmissionService) -> None:
        self._submission = submission

    async def create_vm(
        self,
        *,
        host: str,
        body: CreateVmRequest,
        operation_id: str | None = None,
    ) -> JobSubmitResponse:
        """Submit a VM creation job for ``host``."""
        return await submit_vm_job(
            self._submission, build_create_params(host, body), operation_id=operation_id
        )

    async def list_vms(
        self,
        *,
        host: str,
        body: VmActionRequest,
        operation_id: str | None = None,
    ) -> JobSubmitResponse:
        """Submit a host-scoped VM list job."""
        return await self._submit_simple(
            action="list",
            host=host,
            body=body,
            operation_id=operation_id,
        )

    async def submit_action(
        self,
        *,
        action: str,
        host: str,
        body: VmActionRequest,
        vm_name: Optional[str] = None,
        operation_id: str | None = None,
    ) -> JobSubmitResponse:
        """Submit a single-VM lifecycle/diagnostic action job."""
        return await self._submit_simple(
            action=action,
            host=host,
            body=body,
            vm_name=vm_name,
            operation_id=operation_id,
        )

    async def _submit_simple(
        self,
        *,
        action: str,
        host: str,
        body: VmActionRequest,
        vm_name: Optional[str] = None,
        operation_id: str | None = None,
    ) -> JobSubmitResponse:
        return await submit_vm_job(
            self._submission,
            build_simple_params(action, host, body, vm_name),
            operation_id=operation_id,
        )
