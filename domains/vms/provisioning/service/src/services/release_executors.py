"""Release executor dispatch for leased site allocations."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Protocol

from models.jobs_model import AnsibleJobParams

logger = logging.getLogger(__name__)

VM_EXECUTOR_KIND = "vm"


class ReleaseExecutor(Protocol):
    async def submit_release(self, allocation: dict[str, Any]) -> str | None:
        """Submit release work for an allocation and return its job id."""


class VmReleaseExecutor:
    """Release executor for VM allocations."""

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
            if self._job_queue_provider is not None:
                job_queue = self._job_queue_provider()
            else:
                import container as _container_module

                job_queue = _container_module.resolved_job_queue
            if job_queue is None:
                raise RuntimeError("job_queue not initialised")
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


class ExecutorReleaseDispatcher:
    """Route release requests by allocation executor kind."""

    def __init__(self, executors: dict[str, ReleaseExecutor]) -> None:
        self._executors = dict(executors)

    async def submit_release(self, allocation: dict[str, Any]) -> str | None:
        executor_kind = allocation.get("executor_kind") or VM_EXECUTOR_KIND
        executor = self._executors.get(str(executor_kind))
        if executor is None:
            logger.warning(
                "[LEASE_LIFECYCLE] No release executor registered for executor_kind=%s",
                executor_kind,
            )
            return None
        return await executor.submit_release(allocation)
