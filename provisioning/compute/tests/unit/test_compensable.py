"""Which failed creates a release compensates: ``compensable``, one pure rule."""

from __future__ import annotations

import pytest

from compute_provisioning.release import compensable

# A job-backed create's metadata, as its dispatch acknowledgement records it.
# Synthetic development values.
CREATE = {
    "create_job_id": "job-1",
    "current_job_id": "job-1",
    "operation": "create",
    "host_id": "host-1",
    "executor_target": "target-1",
}


def test_a_reported_failure_of_a_job_backed_create_is_compensable():
    assert compensable("failed", "provider_reported_failure", CREATE)


@pytest.mark.parametrize(
    "state",
    ["active", "dispatching", "teardown_failed", "torn_down", "assigned", None],
)
def test_only_a_failed_aggregate_is_compensable(state):
    assert not compensable(state, "provider_reported_failure", CREATE)


@pytest.mark.parametrize(
    "failure_reason",
    [
        "legacy_executor_identity_quarantined",
        "invalid_provisioned_resource_metadata",
        "create_compensation",
        None,
    ],
)
def test_a_failure_the_provider_did_not_report_is_not_compensable(failure_reason):
    assert not compensable("failed", failure_reason, CREATE)


@pytest.mark.parametrize(
    "provider_metadata",
    [
        None,
        {},
        "job-1",
        {**CREATE, "host_id": ""},
        {key: value for key, value in CREATE.items() if key != "create_job_id"},
        {key: value for key, value in CREATE.items() if key != "executor_target"},
        {**CREATE, "operation": "teardown", "teardown_job_id": "job-2"},
        {"vm_name": "vm-1", "job_id": "job-1"},
        {**CREATE, "unexpected": True},
    ],
    ids=[
        "none",
        "empty",
        "not-a-mapping",
        "no-host",
        "no-create-job",
        "no-target",
        "a-teardown",
        "another-provider",
        "unreadable",
    ],
)
def test_metadata_that_does_not_name_a_job_backed_create_is_not_compensable(
    provider_metadata,
):
    assert not compensable("failed", "provider_reported_failure", provider_metadata)
