"""The job view's recorded instants and structured failure, as a client reads them."""

from __future__ import annotations

from datetime import datetime, timezone

from compute_provisioning_contracts import JobStatusResponse, ProvisioningErrorEnvelope

_VIEW = {"job_id": "job-1", "status": "failed", "params": {}}


def test_a_service_that_reports_no_instants_is_read_as_null() -> None:
    """Neither instant is defaulted or inferred: a view without them, as a
    service that does not record them answers, reads null in both."""
    view = JobStatusResponse.model_validate(_VIEW)

    assert (view.execution_started_at, view.finished_at) == (None, None)


def test_the_recorded_instants_are_read_as_reported() -> None:
    started = "2026-11-18T10:00:00Z"
    finished = "2026-11-18T10:05:00Z"

    view = JobStatusResponse.model_validate(
        {**_VIEW, "execution_started_at": started, "finished_at": finished}
    )

    assert view.execution_started_at == datetime(2026, 11, 18, 10, 0, tzinfo=timezone.utc)
    assert view.finished_at == datetime(2026, 11, 18, 10, 5, tzinfo=timezone.utc)


def test_a_failed_jobs_view_carries_its_structured_failure_beside_its_error() -> None:
    failure = {
        "code": "cleanup_refused",
        "message": 'bm-02: task "Clean up" failed: cleanup refused a foreign-owned descendant',
        "retryable": True,
        "details": {"host": "bm-02", "task": "Clean up", "rc": 1},
    }
    error = f"Job failed (max retries exceeded): {failure['message']}"

    view = JobStatusResponse.model_validate({**_VIEW, "error": error, "failure": failure})

    assert view.failure == ProvisioningErrorEnvelope(**failure)
    assert view.error == error
    assert view.model_dump(mode="json")["failure"] == failure


def test_a_job_that_failed_before_failures_were_kept_reads_none() -> None:
    """A service that does not report ``failure`` answers a view without it."""
    view = JobStatusResponse.model_validate({**_VIEW, "error": "Job failed: Playbook failed"})

    assert view.failure is None
    assert view.error == "Job failed: Playbook failed"


def test_a_failures_retryable_flag_and_details_default_to_none_retried() -> None:
    envelope = ProvisioningErrorEnvelope(code="internal_error", message="boom")

    assert (envelope.retryable, envelope.details) == (False, {})
