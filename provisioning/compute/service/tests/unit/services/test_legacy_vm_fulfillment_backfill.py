"""Unit tests for the pure legacy VM lease -> fulfillment backfill compiler.

These cover the per-candidate scenario matrix directly against
``compile_legacy_vm_fulfillment_backfill`` -- no SQLite engine, no
migration harness -- because the compiler is a pure function of one
already-read row. Cross-candidate concerns (duplicate identity, duplicate
target, conflicting already-persisted rows, whole-migration rollback) are
enumeration-level and covered separately in ``test_database.py`` against a
real connection.
"""

from __future__ import annotations

import pytest

from market_fulfillment.backfill import LegacyBackfillValidationError
from vm_provisioning_adapter.legacy_backfill import (
    LegacyVmLeaseCandidate,
    compile_legacy_vm_fulfillment_backfill,
)


def _candidate(**overrides) -> LegacyVmLeaseCandidate:
    fields = {
        "lease_id": "lease-1",
        "capacity_reservation_id": "reservation-1",
        "status": "leased",
        "vm_host": "kvm1",
        "pool_id": "pool-1",
        "provider": "ansible",
        "playbook_path": "/configured/playbook.yaml",
        "inventory_group": "legacy_hosts",
        "extra_vars": {},
        "vm_target": "vm-active",
        "executor_target": None,
        "create_job_id": "job-create-1",
        "vm_remove_job_id": None,
    }
    fields.update(overrides)
    return LegacyVmLeaseCandidate(**fields)


def test_provisioning_with_tracked_create_job_becomes_dispatching():
    candidate = _candidate(
        status="provisioning",
        vm_target=None,
        executor_target=None,
        create_job_id="job-create-1",
    )

    draft = compile_legacy_vm_fulfillment_backfill(candidate, fulfillment_id="f-1")

    assert draft.state == "dispatching"
    assert draft.provisioned_resource_ref is None
    assert draft.prepared_teardown_operation is None
    assert draft.provider_metadata["create_job_id"] == "job-create-1"


def test_active_lease_becomes_active_with_provisioned_resource_and_teardown():
    candidate = _candidate(status="leased", vm_target="vm-active")

    draft = compile_legacy_vm_fulfillment_backfill(candidate, fulfillment_id="f-1")

    assert draft.state == "active"
    assert draft.provisioned_resource_ref == "vm-active"
    assert draft.prepared_teardown_operation is not None
    assert draft.prepared_teardown_operation["kind"] == "vm.ansible.teardown.v1"
    assert draft.teardown_provider_metadata is None


def test_releasing_before_teardown_dispatch_becomes_teardown_dispatch_pending():
    candidate = _candidate(
        status="releasing", vm_target="vm-releasing", vm_remove_job_id=None
    )

    draft = compile_legacy_vm_fulfillment_backfill(candidate, fulfillment_id="f-1")

    assert draft.state == "teardown_dispatch_pending"
    assert draft.teardown_provider_metadata is None
    assert draft.prepared_teardown_operation is not None


def test_releasing_with_inflight_teardown_job_becomes_tearing_down():
    candidate = _candidate(
        status="releasing", vm_target="vm-releasing", vm_remove_job_id="job-remove-1"
    )

    draft = compile_legacy_vm_fulfillment_backfill(candidate, fulfillment_id="f-1")

    assert draft.state == "tearing_down"
    assert draft.teardown_provider_metadata is not None
    assert draft.teardown_provider_metadata["current_job_id"] == "job-remove-1"
    assert draft.prepared_teardown_operation is not None


def test_failed_teardown_becomes_teardown_failed():
    candidate = _candidate(
        status="release_failed", vm_target="vm-failed", vm_remove_job_id="job-remove-1"
    )

    draft = compile_legacy_vm_fulfillment_backfill(candidate, fulfillment_id="f-1")

    assert draft.state == "teardown_failed"
    assert draft.prepared_teardown_operation is not None


def test_missing_host_or_pool_or_non_ansible_provider_is_rejected():
    for overrides in (
        {"vm_host": None},
        {"pool_id": None},
        {"provider": "some-other-provider"},
    ):
        with pytest.raises(LegacyBackfillValidationError, match="usable Ansible host/pool"):
            compile_legacy_vm_fulfillment_backfill(
                _candidate(**overrides), fulfillment_id="f-1"
            )


def test_missing_ansible_pool_configuration_is_rejected():
    for overrides in ({"playbook_path": None}, {"inventory_group": ""}):
        with pytest.raises(
            LegacyBackfillValidationError, match="usable Ansible pool configuration"
        ):
            compile_legacy_vm_fulfillment_backfill(
                _candidate(**overrides), fulfillment_id="f-1"
            )


def test_conflicting_vm_target_and_executor_target_is_rejected():
    with pytest.raises(LegacyBackfillValidationError, match="conflicting VM targets"):
        compile_legacy_vm_fulfillment_backfill(
            _candidate(vm_target="vm-a", executor_target="vm-b"),
            fulfillment_id="f-1",
        )


def test_provisioning_without_tracked_create_job_is_rejected():
    with pytest.raises(LegacyBackfillValidationError, match="no tracked create job"):
        compile_legacy_vm_fulfillment_backfill(
            _candidate(
                status="provisioning",
                vm_target=None,
                executor_target=None,
                create_job_id=None,
            ),
            fulfillment_id="f-1",
        )


def test_nonprovisioning_status_without_target_is_rejected():
    with pytest.raises(LegacyBackfillValidationError, match="no VM target"):
        compile_legacy_vm_fulfillment_backfill(
            _candidate(status="leased", vm_target=None, executor_target=None),
            fulfillment_id="f-1",
        )


def test_live_target_without_known_create_job_is_rejected():
    """A teardown envelope needs ``AnsibleFulfillmentMetadata.create_job_id``;

    a row that reaches active/tearing-down state with no known create job
    cannot be backfilled as recovery-ready, even though the original inline
    migration logic did not check this case explicitly before attempting
    provider-envelope preparation.
    """
    with pytest.raises(LegacyBackfillValidationError, match="no known create job"):
        compile_legacy_vm_fulfillment_backfill(
            _candidate(status="leased", vm_target="vm-active", create_job_id=None),
            fulfillment_id="f-1",
        )


def test_unsupported_status_is_rejected():
    with pytest.raises(LegacyBackfillValidationError, match="unsupported status"):
        compile_legacy_vm_fulfillment_backfill(
            _candidate(status="pending"), fulfillment_id="f-1"
        )
