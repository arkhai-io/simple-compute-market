"""How VM operations put a job on the compute family's job authority.

``VmJobSubmitter`` turns ``VmJobParams`` into an engine submission: the route
key (offering mode and action), the host the job runs against, and the opaque
parameters. Everything about a job's durable lifecycle -- persistence,
retries, cancellation, processing, reads -- is the ``JobEngine`` the
composition root builds, which knows nothing of VM.
"""

from __future__ import annotations

import dataclasses

from compute_provisioning.jobs.engine import JobEngine
from compute_provisioning_contracts import JobSubmitResponse
from compute_provisioning.jobs import JobActionRequest

from vm_provisioning_adapter.models.jobs_model import VmJobParams


class VmJobSubmitter:
    def __init__(self, engine: JobEngine, *, default_host_id: str | None) -> None:
        self._engine = engine
        # The host a job names no other way; deployment configuration.
        self._default_host_id = default_host_id

    async def submit(
        self,
        params: VmJobParams,
        job_queue,
        *,
        contract: JobActionRequest | None = None,
        operation_id: str | None = None,
    ) -> JobSubmitResponse:
        """Persist and enqueue a VM job."""
        return await self._engine.submit(
            offering_mode=params.offering_mode,
            action=params.executor_action or params.vm_action,
            host_id=(
                params.host_id
                or params.executor_target
                or params.vm_target
                or self._default_host_id
            ),
            params=dataclasses.asdict(params),
            job_queue=job_queue,
            escrow_uid=params.escrow_uid,
            max_retries=params.max_retries,
            contract=contract,
            operation_id=operation_id,
        )


__all__ = ["VmJobSubmitter"]
