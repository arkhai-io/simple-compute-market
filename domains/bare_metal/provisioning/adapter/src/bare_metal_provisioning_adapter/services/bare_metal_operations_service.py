"""Bare-metal access job submission.

Grants and reclaims are submitted to the compute family's job authority as
``BareMetalJobParams``, which the bare-metal codec turns into the access
playbook's variables when the job runs.
"""

from __future__ import annotations

import hashlib

from collections.abc import Callable
from typing import Any

from arkhai_bare_metal import (
    BARE_METAL_OFFERING_MODE,
    BareMetalAccessGrant,
    NODE_GRANT_ACCESS_ACTION,
    NODE_RECLAIM_ACCESS_ACTION,
    bare_metal_executor_ref,
)
from compute_provisioning.jobs import JobActionRequest
from compute_provisioning.hosts.service import HostAuthority
from compute_provisioning_contracts import JobSubmitResponse
from compute_provisioning.jobs.engine import JobEngine
from compute_provisioning.jobs.queue import AsyncJobQueue
from bare_metal_provisioning_adapter.codec import BareMetalJobParams, reclaim_policy_from


def _access_value(access_ref: dict[str, Any] | None, *keys: str) -> str | None:
    if not access_ref:
        return None
    for key in keys:
        value = access_ref.get(key)
        if value:
            return str(value)
    return None


def _stable_operation_id(action: str, *parts: object) -> str:
    material = "\0".join((action, *(str(part or "") for part in parts)))
    return "bare-metal:" + hashlib.sha256(material.encode()).hexdigest()


class BareMetalOperationsService:
    """Submit bare-metal access grant/reclaim jobs."""

    def __init__(
        self,
        *,
        jobs: JobEngine,
        job_queue_provider: Callable[[], AsyncJobQueue],
        host_service: HostAuthority,
        reclaim_policy: str | None = None,
    ) -> None:
        self._jobs = jobs
        self._job_queue_provider = job_queue_provider
        self._host_service = host_service
        # Validated here, at composition, so a deployment configured with a
        # policy the access role does not implement refuses to start.
        self._reclaim_policy = reclaim_policy_from(reclaim_policy)

    async def grant_access(
        self,
        body: BareMetalAccessGrant,
        *,
        contract: JobActionRequest | None = None,
        operation_id: str | None = None,
    ) -> JobSubmitResponse:
        self._validate_host(body.host_id)
        access_ref = dict(body.access_ref or {})
        resolved_operation_id = operation_id
        if resolved_operation_id is None and contract is not None:
            resolved_operation_id = _stable_operation_id(
                "executor_contract",
                contract.idempotency_key,
            )
        if resolved_operation_id is None:
            resolved_operation_id = _stable_operation_id(
                NODE_GRANT_ACCESS_ACTION,
                body.capacity_reservation_id,
                body.escrow_uid,
                body.host_id,
                body.physical_host_id,
            )
        return await self._submit(
            BareMetalJobParams(
                action=NODE_GRANT_ACCESS_ACTION,
                host_id=body.host_id,
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
            contract=contract,
            operation_id=resolved_operation_id,
        )

    async def reclaim_access(
        self,
        grant: BareMetalAccessGrant,
        *,
        contract: JobActionRequest | None = None,
        operation_id: str | None = None,
    ) -> JobSubmitResponse:
        """Reclaim exactly the access ``grant`` gave, on the same host."""
        self._validate_host(grant.host_id)
        access_ref = dict(grant.access_ref or {})
        resolved_operation_id = operation_id
        if resolved_operation_id is None and contract is not None:
            resolved_operation_id = _stable_operation_id(
                "executor_contract",
                contract.idempotency_key,
            )
        if resolved_operation_id is None:
            resolved_operation_id = _stable_operation_id(
                NODE_RECLAIM_ACCESS_ACTION,
                grant.capacity_reservation_id,
                grant.escrow_uid,
                grant.host_id,
                grant.physical_host_id,
            )
        return await self._submit(
            BareMetalJobParams(
                action=NODE_RECLAIM_ACCESS_ACTION,
                host_id=grant.host_id,
                executor_ref=bare_metal_executor_ref(
                    grant.physical_host_id,
                    access_ref=access_ref or None,
                ),
                escrow_uid=grant.escrow_uid,
                physical_host_id=grant.physical_host_id,
                ssh_user=_access_value(access_ref, "ssh_user", "user"),
                ssh_public_key=_access_value(
                    access_ref, "ssh_public_key", "ssh_pubkey", "public_key",
                ),
                access_ref=access_ref or None,
                reclaim_policy=self._reclaim_policy,
            ),
            contract=contract,
            operation_id=resolved_operation_id,
        )

    async def _submit(
        self,
        params: BareMetalJobParams,
        *,
        contract: JobActionRequest | None,
        operation_id: str,
    ) -> JobSubmitResponse:
        return await self._jobs.submit(
            offering_mode=BARE_METAL_OFFERING_MODE,
            action=params.action,
            host_id=params.host_id,
            params=params.model_dump(mode="json"),
            job_queue=self._job_queue_provider(),
            escrow_uid=params.escrow_uid,
            contract=contract,
            operation_id=operation_id,
        )

    def _validate_host(self, host_id: str) -> None:
        # Access jobs run only against a registered, enabled host record; there
        # is no path that skips this check.
        host = self._host_service.get_host(host_id)
        if host is None:
            raise BareMetalHostValidationError(
                f"Bare-metal machine {host_id!r} is not registered in host inventory.",
                status_code=404,
            )
        if not bool(getattr(host, "enabled", False)):
            raise BareMetalHostValidationError(
                f"Bare-metal machine {host_id!r} is disabled in host inventory.",
                status_code=409,
            )


class BareMetalHostValidationError(Exception):
    """Raised when a bare-metal machine is not eligible for access jobs."""

    def __init__(self, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code
