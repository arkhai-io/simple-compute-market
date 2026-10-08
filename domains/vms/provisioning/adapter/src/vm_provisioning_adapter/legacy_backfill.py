"""Compiles one legacy VM lease row into a fulfillment backfill draft.

Pure: no database session and no I/O. A compiled record is in the compute
family's job-backed shapes, its teardown prepared through VM's own plan. A migration is
responsible for enumerating candidates, deduplicating identity/target
across the whole population, comparing against already-persisted rows, and
committing the batch atomically; this module only compiles one already-read
row.

See ``openspec/specs/physical-provisioning/spec.md#vm-lease-migration-uses-current-provider-contracts``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from market_fulfillment.backfill import (
    LegacyBackfillValidationError,
    LegacyFulfillmentBackfillDraft,
)
from market_fulfillment.ids import derive_provisioned_resource_id
from market_fulfillment.provider import SettlementResult
from market_fulfillment.settlement_types import SettlementResource

from compute_provisioning.job_fulfillment import teardown_operation

from vm_provisioning_adapter.codec import VmAnsibleCodec
from vm_provisioning_adapter.services.vm_fulfillment_plan import VmFulfillmentPlan

_LEGACY_OFFERING_MODE = "vm"


_STATE_BY_LEASE_STATUS = {
    "provisioning": "dispatching",
    "leased": "active",
    "release_failed": "teardown_failed",
}


@dataclass(frozen=True)
class LegacyVmLeaseCandidate:
    """Validated historical coordinates for one legacy VM lease row.

    Field values are read as-is from the join a migration performs; this
    type carries no derived state and applies no validation of its own —
    ``compile_legacy_vm_fulfillment_backfill`` does both.
    """

    lease_id: str
    capacity_reservation_id: str
    status: str
    # Named for the retired ``vm_leases`` column it is read from; it holds the
    # host's identity and becomes ``host_id`` in everything compiled from it.
    vm_host: str | None
    pool_id: str | None
    provider: str | None
    playbook_path: str | None
    inventory_group: str | None
    extra_vars: dict[str, Any]
    vm_target: str | None
    executor_target: str | None
    create_job_id: str | None
    vm_remove_job_id: str | None


def prepare_historical_vm_teardown(
    settlement_result: SettlementResult, pool_config: dict[str, Any]
):
    """Prepare a teardown envelope for an existing VM during schema cutover.

    Uses VM's plan and the family's teardown envelope, as a teardown prepared
    at runtime is, rather than hand-assembling payload JSON. It reads no job:
    VM's teardown takes its target from the fulfillment, its playbook from the
    pool, and its relay from the lease, and a historical VM leased none through
    this path.
    """
    metadata = settlement_result.provider_metadata
    plan = VmFulfillmentPlan(reserved_var_keys=VmAnsibleCodec().reserved_var_keys)
    prepared = plan.prepare_teardown(
        capacity_reservation_id=settlement_result.capacity_reservation_id,
        resource=settlement_result.resource,
        host_id=metadata["host_id"],
        executor_target=metadata["executor_target"],
        create_parameters={},
        pool_config=pool_config,
    )
    return teardown_operation(
        settlement_result.capacity_reservation_id,
        prepared,
        create_job_id=metadata["create_job_id"],
    )


def _derive_state(candidate: LegacyVmLeaseCandidate) -> str:
    if candidate.status == "releasing":
        return "tearing_down" if candidate.vm_remove_job_id else "teardown_dispatch_pending"
    try:
        return _STATE_BY_LEASE_STATUS[candidate.status]
    except KeyError:
        raise LegacyBackfillValidationError(
            f"legacy VM lease {candidate.lease_id} has unsupported status {candidate.status!r}"
        ) from None


def compile_legacy_vm_fulfillment_backfill(
    candidate: LegacyVmLeaseCandidate,
    *,
    fulfillment_id: str,
) -> LegacyFulfillmentBackfillDraft:
    """Compile one legacy VM lease into a durable fulfillment backfill draft.

    Raises ``LegacyBackfillValidationError`` rather than backfilling a row a
    migration cannot safely reconstruct; never submits a replacement create
    operation because a prior job identity was lost or ambiguous.
    """
    if candidate.provider != "ansible" or not candidate.vm_host or not candidate.pool_id:
        raise LegacyBackfillValidationError(
            f"legacy VM lease {candidate.lease_id} has no unique usable Ansible host/pool"
        )
    if not candidate.playbook_path or not candidate.inventory_group:
        raise LegacyBackfillValidationError(
            f"legacy VM lease {candidate.lease_id} has no usable Ansible pool configuration"
        )
    if (
        candidate.vm_target
        and candidate.executor_target
        and candidate.vm_target != candidate.executor_target
    ):
        raise LegacyBackfillValidationError(
            f"legacy VM lease {candidate.lease_id} has conflicting VM targets"
        )
    target = candidate.vm_target or candidate.executor_target

    if candidate.status == "provisioning" and not candidate.create_job_id:
        raise LegacyBackfillValidationError(
            f"provisioning VM lease {candidate.lease_id} has no tracked create job"
        )
    if candidate.status != "provisioning" and not target:
        raise LegacyBackfillValidationError(
            f"legacy VM lease {candidate.lease_id} has no VM target"
        )
    if target and not candidate.create_job_id:
        # The job-backed metadata requires its create job: a teardown for this
        # lease is recorded against the create job that produced the resource
        # being torn down. A row without
        # this identity cannot be backfilled as recovery-ready.
        raise LegacyBackfillValidationError(
            f"legacy VM lease {candidate.lease_id} has a live target with no known create job "
            "to record in provider metadata"
        )

    state = _derive_state(candidate)

    # A provisioning lease may name no target yet; the job-backed migration
    # takes it from the lease's create job, which names the guest it creates.
    metadata = {
        "create_job_id": candidate.create_job_id,
        "teardown_job_id": None,
        "current_job_id": candidate.create_job_id,
        "operation": "create",
        "host_id": candidate.vm_host,
        "executor_target": target or "",
    }
    teardown_metadata = None
    if candidate.vm_remove_job_id:
        teardown_metadata = {
            "create_job_id": candidate.create_job_id,
            "teardown_job_id": candidate.vm_remove_job_id,
            "current_job_id": candidate.vm_remove_job_id,
            "operation": "teardown",
            "host_id": candidate.vm_host,
            "executor_target": target or "",
        }

    prepared_teardown = None
    if target:
        # Retries reproduce the same fulfillment-owned opaque ID from the
        # stable legacy reservation identity and provider output key.
        provisioned_resource_id = derive_provisioned_resource_id(
            identity_scope=f"legacy-reservation:{candidate.capacity_reservation_id}",
            provider_output_key=target,
        )
        # This compiler's input is the migration's validated historical VM
        # lease join, so "vm" is bounded migration evidence, not runtime
        # inference from the matched host or provider.
        resource = SettlementResource(
            settlement_resource_id=candidate.vm_host,
            pool_id=candidate.pool_id,
            offering_mode=_LEGACY_OFFERING_MODE,
            resource_kind="vm",
            provider="ansible",
            host_id=candidate.vm_host,
        )
        result = SettlementResult(
            capacity_reservation_id=candidate.capacity_reservation_id,
            fulfillment_id=fulfillment_id,
            resource=resource,
            provisioned_resources=({"provisioned_resource_id": provisioned_resource_id},),
            provider_metadata=metadata,
        )
        envelope = prepare_historical_vm_teardown(
            result,
            {
                "playbook_path": candidate.playbook_path,
                "inventory_group": candidate.inventory_group,
                "extra_vars": candidate.extra_vars,
            },
        )
        prepared_teardown = envelope.model_dump(mode="json")

    return LegacyFulfillmentBackfillDraft(
        capacity_reservation_id=candidate.capacity_reservation_id,
        fulfillment_id=fulfillment_id,
        state=state,
        settlement_resource_id=candidate.vm_host,
        pool_id=candidate.pool_id,
        offering_mode=_LEGACY_OFFERING_MODE,
        provider="ansible",
        resource_attributes={},
        resource_host_id=candidate.vm_host,
        provider_metadata=metadata,
        teardown_provider_metadata=teardown_metadata,
        prepared_teardown_operation=prepared_teardown,
        provisioned_resource_id=provisioned_resource_id if target else None,
    )
