"""Compiles one legacy VM lease row into a fulfillment backfill draft.

Pure: no database session, no I/O beyond building the versioned provider
envelope through the real Ansible provider contract. A migration is
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
from market_fulfillment.provider import SettlementResult
from market_fulfillment.settlement_types import SettlementResource

from vm_provisioning_adapter.services.ansible_fulfillment_provider import (
    AnsibleFulfillmentProvider,
)

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

    Uses the same provider validation and envelope contract as normal
    runtime teardown dispatch (``AnsibleFulfillmentProvider.prepare_teardown``)
    rather than hand-assembling provider payload JSON, so a backfilled
    teardown command is what normal dispatch would have produced.
    """

    class _PreparationOnlyJobService:
        @staticmethod
        def reserved_var_keys(params):
            return frozenset({"vm_host", "vm_action", "vm_target", "escrow_uid"})

    provider = AnsibleFulfillmentProvider(
        job_service=_PreparationOnlyJobService(),
        job_queue_provider=lambda: None,
    )
    return provider.prepare_teardown(settlement_result, pool_config)


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
        # AnsibleFulfillmentMetadata.create_job_id is required: a teardown
        # envelope for this lease can only be prepared by recording which
        # create job produced the resource being torn down. A row without
        # this identity cannot be backfilled as recovery-ready.
        raise LegacyBackfillValidationError(
            f"legacy VM lease {candidate.lease_id} has a live target with no known create job "
            "to record in provider metadata"
        )

    state = _derive_state(candidate)

    metadata = {
        "create_job_id": candidate.create_job_id,
        "current_job_id": candidate.create_job_id,
        "vm_host": candidate.vm_host,
        "vm_target": target or "",
        "operation": "create",
    }
    teardown_metadata = None
    if candidate.vm_remove_job_id:
        teardown_metadata = {
            "create_job_id": candidate.create_job_id,
            "current_job_id": candidate.vm_remove_job_id,
            "vm_host": candidate.vm_host,
            "vm_target": target or "",
            "operation": "teardown",
        }

    prepared_teardown = None
    if target:
        resource = SettlementResource(
            settlement_resource_id=candidate.vm_host,
            pool_id=candidate.pool_id,
            resource_kind="vm",
            provider="ansible",
            attributes={"vm_host": candidate.vm_host},
        )
        result = SettlementResult(
            capacity_reservation_id=candidate.capacity_reservation_id,
            fulfillment_id=fulfillment_id,
            resource=resource,
            provisioned_resources=({"domain_resource_ref": target},),
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
        provider="ansible",
        resource_attributes={"vm_host": candidate.vm_host},
        provider_metadata=metadata,
        teardown_provider_metadata=teardown_metadata,
        prepared_teardown_operation=prepared_teardown,
        provisioned_resource_ref=target,
    )
