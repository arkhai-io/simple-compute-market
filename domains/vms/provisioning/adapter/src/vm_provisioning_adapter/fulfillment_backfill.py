"""Pure VM provider command compilation for historical fulfillment rows."""

from __future__ import annotations

import dataclasses
from typing import Any

from compute_provisioning import ExecutorActionEnvelope
from market_fulfillment import (
    LegacyFulfillmentBackfillDraft,
    LegacyFulfillmentBackfillInput,
    VersionedEnvelope,
)
from vm_provisioning_adapter.models.fulfillment_model import (
    AnyAnsibleFulfillmentMetadata,
    BackfilledAnsibleFulfillmentMetadata,
)
from vm_provisioning_adapter.models.jobs_model import AnsibleJobParams


def compile_vm_teardown_operation(
    *,
    capacity_reservation_id: str,
    metadata: AnyAnsibleFulfillmentMetadata,
    playbook_path: str,
    provider_extra_vars: dict[str, Any],
) -> VersionedEnvelope:
    """Freeze one deterministic VM-removal provider command."""
    base_params = AnsibleJobParams(
        vm_host=metadata.vm_host,
        vm_action="vm_remove",
        vm_target=metadata.vm_target,
        escrow_uid=capacity_reservation_id,
        playbook_path=playbook_path,
    )
    reserved = {
        field.name
        for field in dataclasses.fields(base_params)
        if field.name != "provider_extra_vars"
    }
    collisions = sorted(reserved.intersection(provider_extra_vars))
    if collisions:
        raise ValueError(
            "provider extra_vars override reserved job variables: "
            + ", ".join(collisions)
        )
    params = dataclasses.replace(
        base_params, provider_extra_vars=dict(provider_extra_vars)
    )
    contract = ExecutorActionEnvelope(
        capacity_reservation_id=capacity_reservation_id,
        deal_ref={},
        executor_kind="vm",
        action_kind="fulfillment_teardown",
        idempotency_key=(
            f"{capacity_reservation_id}:fulfillment_teardown:v1"
        ),
        parameters=dataclasses.asdict(params),
    )
    return VersionedEnvelope(
        kind="ansible.vm.teardown",
        schema_version=1,
        payload={
            "job_params": dataclasses.asdict(params),
            "contract": contract.model_dump(mode="json"),
            "create_metadata": metadata.model_dump(mode="json"),
        },
    )


def compile_legacy_vm_fulfillment_backfill(
    source: LegacyFulfillmentBackfillInput,
) -> LegacyFulfillmentBackfillDraft:
    """Compile validated historical coordinates without service dependencies."""
    operation = "teardown" if source.teardown_job_id else "create"
    metadata = BackfilledAnsibleFulfillmentMetadata(
        create_job_id=source.create_job_id,
        vm_host=source.executor_host,
        vm_target=source.executor_target,
        teardown_job_id=source.teardown_job_id,
        current_job_id=source.teardown_job_id or source.create_job_id,
        operation=operation,
    )
    prepared = compile_vm_teardown_operation(
        capacity_reservation_id=source.capacity_reservation_id,
        metadata=metadata,
        playbook_path=source.playbook_path,
        provider_extra_vars=source.provider_extra_vars,
    )
    dumped = metadata.model_dump(mode="json")
    return LegacyFulfillmentBackfillDraft(
        provider_metadata=dumped,
        prepared_teardown_operation=prepared,
        teardown_provider_metadata=(dumped if source.teardown_job_id else None),
    )
