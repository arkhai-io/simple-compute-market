"""Bare-metal executor job submission.

This is a transitional adapter inside the VM provisioning service. It keeps
bare-metal action construction separate so the implementation can move with the
multi-domain provisioner later.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TYPE_CHECKING

from arkhai_bare_metal import (
    BARE_METAL_EXECUTOR_KIND,
    BareMetalLeaseCreate,
    NODE_GRANT_ACCESS_ACTION,
    NODE_RECLAIM_ACCESS_ACTION,
    bare_metal_executor_ref,
)
from config import DEFAULT_BARE_METAL_RECLAIM_POLICY
from models.jobs_model import AnsibleJobParams
from provisioning_client.models import JobSubmitResponse
from services.async_job_queue import AsyncJobQueue
from services.bare_metal_lease_service import bare_metal_access_ref
from services.release_executors import get_physical_host_id

if TYPE_CHECKING:
    from services.job_service import AnsibleJobService
    from services.host_service import HostService


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
        settings: Any | None = None,
        host_service: "HostService | None" = None,
    ) -> None:
        self._job_service = job_service
        self._job_queue_provider = job_queue_provider
        self._settings = settings
        self._host_service = host_service

    async def grant_access(self, body: BareMetalLeaseCreate) -> JobSubmitResponse:
        self._validate_machine(body.machine_id)
        access_ref = dict(body.access_ref or {})
        return await self._job_service.submit(
            AnsibleJobParams(
                vm_host=body.machine_id,
                vm_action=NODE_GRANT_ACCESS_ACTION,
                vm_target=body.machine_id,
                executor_kind=BARE_METAL_EXECUTOR_KIND,
                executor_action=NODE_GRANT_ACCESS_ACTION,
                executor_target=body.machine_id,
                executor_ref=bare_metal_executor_ref(
                    body.physical_host_id,
                    access_ref=access_ref or None,
                ),
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
        try:
            submit = await self.reclaim_access(allocation)
        except BareMetalHostValidationError:
            return None
        return submit.job_id

    async def reclaim_access(self, allocation: dict[str, Any]) -> JobSubmitResponse:
        machine_id = str(allocation.get("executor_target") or "")
        self._validate_machine(machine_id)
        access_ref = bare_metal_access_ref(allocation)
        return await self._job_service.submit(
            AnsibleJobParams(
                vm_host=machine_id,
                vm_action=NODE_RECLAIM_ACCESS_ACTION,
                vm_target=machine_id,
                executor_kind=BARE_METAL_EXECUTOR_KIND,
                executor_action=NODE_RECLAIM_ACCESS_ACTION,
                executor_target=machine_id,
                executor_ref=allocation.get("executor_ref"),
                escrow_uid=allocation.get("escrow_uid"),
                physical_host_id=get_physical_host_id(allocation),
                ssh_user=_access_value(access_ref, "ssh_user", "user"),
                ssh_public_key=_access_value(
                    access_ref, "ssh_public_key", "ssh_pubkey", "public_key",
                ),
                access_ref=access_ref,
                bare_metal_reclaim_policy=self._reclaim_policy(),
            ),
            self._job_queue_provider(),
        )

    def _reclaim_policy(self) -> str:
        if self._settings is None:
            return DEFAULT_BARE_METAL_RECLAIM_POLICY
        try:
            return str(self._settings.bare_metal_reclaim_policy)
        except AttributeError:
            return DEFAULT_BARE_METAL_RECLAIM_POLICY

    def _validate_machine(self, machine_id: str) -> None:
        if self._host_service is None:
            return
        host = self._host_service.get_host(machine_id)
        if host is None:
            raise BareMetalHostValidationError(
                f"Bare-metal machine {machine_id!r} is not registered in host inventory.",
                status_code=404,
            )
        if not bool(getattr(host, "enabled", False)):
            raise BareMetalHostValidationError(
                f"Bare-metal machine {machine_id!r} is disabled in host inventory.",
                status_code=409,
            )


class BareMetalHostValidationError(Exception):
    """Raised when a bare-metal machine is not eligible for access jobs."""

    def __init__(self, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code
