"""Bare-metal executor job submission.

This is a transitional adapter inside the VM provisioning service. It keeps
bare-metal action construction separate so the implementation can move with the
multi-domain provisioner later.
"""

from __future__ import annotations

import hashlib

from collections.abc import Callable
from typing import Any, TYPE_CHECKING

from arkhai_bare_metal import (
    BARE_METAL_OFFERING_MODE,
    BareMetalLeaseCreate,
    NODE_GRANT_ACCESS_ACTION,
    NODE_RECLAIM_ACCESS_ACTION,
    BareMetalLeaseAccountError,
    admissible_lease_account,
    bare_metal_executor_ref,
)
from compute_provisioning.contracts import ExecutorActionEnvelope
from compute_provisioning_service.config import DEFAULT_BARE_METAL_RECLAIM_POLICY
from vm_provisioning_adapter.models.jobs_model import AnsibleJobParams
from vm_provisioning_operator.models import JobSubmitResponse
from compute_provisioning_service.services.async_job_queue import AsyncJobQueue
from bare_metal_provisioning_adapter.services.bare_metal_lease_service import bare_metal_access_ref
from bare_metal_provisioning_adapter.release import get_physical_host_id

if TYPE_CHECKING:
    from vm_provisioning_adapter.services.job_service import AnsibleJobService
    from vm_provisioning_adapter.services.host_service import HostService


def _access_value(access_ref: dict[str, Any] | None, *keys: str) -> str | None:
    if not access_ref:
        return None
    for key in keys:
        value = access_ref.get(key)
        if value:
            return str(value)
    return None


def _reclaim_settlement_identity(reservation: dict[str, Any]) -> str:
    """Return the one settlement identity a reclaim request names.

    Fulfillment teardown passes the lease's own ``escrow_uid`` or
    ``settlement_obligation_ref``. A site reservation carries ``escrow_uid`` as
    a column and a hosted lease's obligation as ``deal_ref`` key
    ``hosted_obligation_ref``, the key the storefront reserves under.

    Values are compared exactly as stored. No identity, or more than one
    distinct identity, refuses the reclaim: without the lease's own identity an
    account name cannot be bound to that lease, and a canonically shaped name
    alone could belong to any lease on the host.
    """
    deal_ref = reservation.get("deal_ref")
    if not isinstance(deal_ref, dict):
        deal_ref = {}
    candidates = (
        reservation.get("escrow_uid"),
        reservation.get("settlement_obligation_ref"),
        deal_ref.get("escrow_uid"),
        deal_ref.get("hosted_obligation_ref"),
    )
    identities = {value for value in candidates if isinstance(value, str) and value}
    if not identities:
        raise BareMetalLeaseAccountError(
            "privileged reclaim requires its lease's settlement identity"
        )
    if len(identities) > 1:
        raise BareMetalLeaseAccountError(
            "privileged reclaim names more than one settlement identity"
        )
    return identities.pop()


def _stable_operation_id(action: str, *parts: object) -> str:
    material = "\0".join((action, *(str(part or "") for part in parts)))
    return "bare-metal:" + hashlib.sha256(material.encode()).hexdigest()


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

    async def grant_access(
        self,
        body: BareMetalLeaseCreate,
        *,
        contract: ExecutorActionEnvelope | None = None,
        operation_id: str | None = None,
    ) -> JobSubmitResponse:
        self._validate_machine(body.machine_id)
        access_ref = dict(body.access_ref or {})
        # Admission precedes dispatch: once the name is a play variable it is
        # already an argument to a privileged task that installs a buyer key.
        ssh_user = admissible_lease_account(
            _access_value(access_ref, "ssh_user", "user"),
            settlement_identity=body.settlement_identity,
        )
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
                body.machine_id,
                body.physical_host_id,
            )
        return await self._job_service.submit(
            AnsibleJobParams(
                vm_host=body.machine_id,
                vm_action=NODE_GRANT_ACCESS_ACTION,
                vm_target=body.machine_id,
                offering_mode=BARE_METAL_OFFERING_MODE,
                executor_action=NODE_GRANT_ACCESS_ACTION,
                executor_target=body.machine_id,
                executor_ref=bare_metal_executor_ref(
                    body.physical_host_id,
                    access_ref=access_ref or None,
                ),
                escrow_uid=body.escrow_uid,
                physical_host_id=body.physical_host_id,
                ssh_user=ssh_user,
                ssh_public_key=_access_value(
                    access_ref, "ssh_public_key", "ssh_pubkey", "public_key",
                ),
                access_ref=access_ref or None,
            ),
            self._job_queue_provider(),
            contract=contract,
            operation_id=resolved_operation_id,
        )

    async def reclaim_access_for_reservation(
        self, reservation: dict[str, Any],
    ) -> str | None:
        if not reservation.get("executor_target"):
            return None
        try:
            submit = await self.reclaim_access(reservation)
        except BareMetalHostValidationError:
            return None
        return submit.job_id

    async def reclaim_access(
        self,
        reservation: dict[str, Any],
        *,
        contract: ExecutorActionEnvelope | None = None,
        operation_id: str | None = None,
    ) -> JobSubmitResponse:
        machine_id = str(reservation.get("executor_target") or "")
        self._validate_machine(machine_id)
        access_ref = bare_metal_access_ref(reservation)
        # Reclaim needs the same admission as grant, bound to the lease's own
        # identity: its lock and delete policies act on an account that
        # already exists on the host.
        ssh_user = admissible_lease_account(
            _access_value(access_ref, "ssh_user", "user"),
            settlement_identity=_reclaim_settlement_identity(reservation),
        )
        resolved_operation_id = operation_id
        if resolved_operation_id is None and contract is not None:
            resolved_operation_id = _stable_operation_id(
                "executor_contract",
                contract.idempotency_key,
            )
        if resolved_operation_id is None:
            resolved_operation_id = _stable_operation_id(
                NODE_RECLAIM_ACCESS_ACTION,
                reservation.get("capacity_reservation_id"),
                reservation.get("escrow_uid"),
                machine_id,
                get_physical_host_id(reservation),
            )
        return await self._job_service.submit(
            AnsibleJobParams(
                vm_host=machine_id,
                vm_action=NODE_RECLAIM_ACCESS_ACTION,
                vm_target=machine_id,
                offering_mode=BARE_METAL_OFFERING_MODE,
                executor_action=NODE_RECLAIM_ACCESS_ACTION,
                executor_target=machine_id,
                executor_ref=reservation.get("executor_ref"),
                escrow_uid=reservation.get("escrow_uid"),
                physical_host_id=get_physical_host_id(reservation),
                ssh_user=ssh_user,
                ssh_public_key=_access_value(
                    access_ref, "ssh_public_key", "ssh_pubkey", "public_key",
                ),
                access_ref=access_ref,
                bare_metal_reclaim_policy=self._reclaim_policy(),
            ),
            self._job_queue_provider(),
            contract=contract,
            operation_id=resolved_operation_id,
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
