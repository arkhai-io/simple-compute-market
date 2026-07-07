"""Bare-metal executor job submission.

This is a transitional adapter inside the VM provisioning service. It keeps
bare-metal action construction separate so the implementation can move with the
multi-domain provisioner later.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TYPE_CHECKING

from arkhai_bare_metal_contracts import BareMetalLeaseCreate
from models.jobs_model import AnsibleJobParams
from provisioning_client.models import JobSubmitResponse
from services.async_job_queue import AsyncJobQueue
from services.bare_metal_lease_service import bare_metal_access_ref
from services.release_executors import get_physical_host_id

if TYPE_CHECKING:
    from services.job_service import AnsibleJobService

NODE_GRANT_ACCESS_ACTION = "node_grant_access"
NODE_RECLAIM_ACCESS_ACTION = "node_reclaim_access"


def _access_value(access_ref: dict[str, Any] | None, *keys: str) -> str | None:
    if not access_ref:
        return None
    for key in keys:
        value = access_ref.get(key)
        if value:
            return str(value)
    return None


class BareMetalOperationsService:
    """Submit bare-metal access grant/reclaim jobs."""

    def __init__(
        self,
        *,
        job_service: "AnsibleJobService",
        job_queue_provider: Callable[[], AsyncJobQueue],
    ) -> None:
        self._job_service = job_service
        self._job_queue_provider = job_queue_provider

    async def grant_access(self, body: BareMetalLeaseCreate) -> JobSubmitResponse:
        access_ref = dict(body.access_ref or {})
        return await self._job_service.submit(
            AnsibleJobParams(
                vm_host=body.machine_id,
                vm_action=NODE_GRANT_ACCESS_ACTION,
                vm_target=body.machine_id,
                escrow_uid=body.escrow_uid,
                physical_host_id=body.physical_host_id,
                ssh_user=_access_value(access_ref, "ssh_user", "user"),
                ssh_public_key=_access_value(
                    access_ref, "ssh_public_key", "ssh_pubkey", "public_key",
                ),
                access_ref=access_ref or None,
            ),
            self._job_queue_provider(),
        )

    async def reclaim_access_for_allocation(
        self, allocation: dict[str, Any],
    ) -> str | None:
        if not allocation.get("executor_target"):
            return None
        submit = await self.reclaim_access(allocation)
        return submit.job_id

    async def reclaim_access(self, allocation: dict[str, Any]) -> JobSubmitResponse:
        machine_id = str(allocation.get("executor_target") or "")
        access_ref = bare_metal_access_ref(allocation)
        return await self._job_service.submit(
            AnsibleJobParams(
                vm_host=machine_id,
                vm_action=NODE_RECLAIM_ACCESS_ACTION,
                vm_target=machine_id,
                escrow_uid=allocation.get("escrow_uid"),
                physical_host_id=get_physical_host_id(allocation),
                ssh_user=_access_value(access_ref, "ssh_user", "user"),
                access_ref=access_ref,
            ),
            self._job_queue_provider(),
        )
