"""VM release adapter for leased site allocations."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from vm_provisioning_adapter.models.jobs_model import AnsibleJobParams

logger = logging.getLogger(__name__)
VM_EXECUTOR_KIND = "vm"


class VmReleaseExecutor:
    def __init__(
        self,
        *,
        job_service=None,
        job_queue_provider: Callable[[], Any] | None = None,
    ) -> None:
        self._job_svc = job_service
        self._job_queue_provider = job_queue_provider

    async def submit_release(self, allocation: dict[str, Any]) -> str | None:
        return await self._submit_vm_remove_job(
            vm_host=allocation.get("vm_host"),
            vm_target=allocation.get("executor_target") or allocation.get("vm_target"),
        )

    async def _submit_vm_remove_job(self, *, vm_host, vm_target) -> str | None:
        if self._job_svc is None:
            return "direct-release"
        if not vm_host or not vm_target:
            return None
        try:
            if self._job_queue_provider is None:
                raise RuntimeError("job queue provider is not configured")
            job_queue = self._job_queue_provider()
            params = AnsibleJobParams(
                vm_host=vm_host,
                vm_action="vm_remove",
                vm_target=vm_target,
            )
            submit = await self._job_svc.submit(params, job_queue=job_queue)
            return submit.job_id
        except Exception as exc:
            logger.warning(
                "[LEASE_LIFECYCLE] Failed to submit vm_remove job for %s/%s: %s",
                vm_host,
                vm_target,
                exc,
            )
            return None
