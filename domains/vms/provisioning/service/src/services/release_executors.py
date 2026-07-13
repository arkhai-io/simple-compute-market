"""Release executor dispatch for leased site allocations."""

from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable, Callable
from typing import Any


from arkhai_bare_metal import (
    BARE_METAL_EXECUTOR_KIND,
    PHYSICAL_HOST_ID_REF_KEY,
    bare_metal_executor_ref,
)
from models.jobs_model import AnsibleJobParams

logger = logging.getLogger(__name__)

VM_EXECUTOR_KIND = "vm"
BareMetalReleaseDelegate = Callable[[dict[str, Any]], Awaitable[str | None] | str | None]


def get_physical_host_id(allocation: dict[str, Any]) -> str | None:
    """Return the shared physical-host identity carried by executor_ref."""
    executor_ref = allocation.get("executor_ref") or {}
    if not isinstance(executor_ref, dict):
        return None
    physical_host_id = executor_ref.get(PHYSICAL_HOST_ID_REF_KEY)
    return str(physical_host_id) if physical_host_id else None


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


class BareMetalReleaseExecutor:
    """Release executor for bare-metal allocations.

    The default path is intentionally local/direct: the first bare-metal slice
    only needs to release accounting after access is revoked out-of-band. A
    concrete access revocation implementation can be injected as the domain
    grows.
    """

    def __init__(
        self,
        *,
        release_delegate: BareMetalReleaseDelegate | None = None,
    ) -> None:
        self._release_delegate = release_delegate

    async def submit_release(self, allocation: dict[str, Any]) -> str | None:
        if self._release_delegate is None:
            return "direct-release"
        result = self._release_delegate(allocation)
        if inspect.isawaitable(result):
            result = await result
        return result
