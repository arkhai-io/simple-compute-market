"""The job view's recorded instants, as a client reads them."""

from __future__ import annotations

from datetime import datetime, timezone

from compute_provisioning_contracts import JobStatusResponse

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
