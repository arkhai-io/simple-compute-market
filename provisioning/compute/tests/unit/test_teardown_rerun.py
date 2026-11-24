"""The teardown rerun predicate, one case per outcome, and its policy."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from compute_provisioning.jobs import JobRetryPolicy
from compute_provisioning.jobs.engine import BoundJob
from compute_provisioning.teardown_rerun import (
    LatestJobUnsettled,
    NotRerunnable,
    RerunReady,
    RerunsSpent,
    RerunWaiting,
    TeardownRerunPolicy,
    never_started_account,
    rerun_pending,
    teardown_rerun,
)

_FINISHED = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)
# Reruns wait 60, 120 and 240 seconds after the previous job finished.
_POLICY = TeardownRerunPolicy(
    teardown_rerun_limit=3,
    retry_policy=JobRetryPolicy(backoff_initial_seconds=60, backoff_multiplier=2.0),
)


def _never_started(job_id: str = "t-1", finished_at: datetime = _FINISHED) -> BoundJob:
    return BoundJob(job_id=job_id, status="failed", never_started=True, finished_at=finished_at)


def _job(status: str, *, finished_at: datetime | None = _FINISHED) -> BoundJob:
    return BoundJob(job_id="t-1", status=status, never_started=False, finished_at=finished_at)


def test_a_teardown_whose_execution_started_is_not_rerun() -> None:
    outcome = teardown_rerun([_job("failed")], _POLICY, _FINISHED + timedelta(hours=1))

    assert outcome == NotRerunnable("started", 0)
    assert not rerun_pending(outcome)
    assert never_started_account(outcome, _POLICY) is None


def test_a_reservation_with_no_teardown_job_has_no_rerun() -> None:
    outcome = teardown_rerun([], _POLICY, _FINISHED)

    assert outcome == NotRerunnable("no_teardown_job", 0)
    assert not rerun_pending(outcome)


@pytest.mark.parametrize("status", ["queued", "running", "succeeded"])
def test_a_latest_job_that_has_not_failed_is_still_to_be_observed(status) -> None:
    """Nothing is rerun, and the teardown is not settled: convergence observes
    the job, so a lease waiting on it keeps waiting."""
    jobs = [_never_started(), _job(status, finished_at=None)]

    outcome = teardown_rerun(jobs, _POLICY, _FINISHED + timedelta(days=1))

    assert outcome == LatestJobUnsettled(status)
    assert rerun_pending(outcome)


def test_a_cancelled_teardown_is_not_rerun() -> None:
    outcome = teardown_rerun([_job("cancelled")], _POLICY, _FINISHED + timedelta(hours=1))

    assert outcome == NotRerunnable("cancelled", 0)


def test_a_teardown_finished_before_starts_were_recorded_is_not_rerun() -> None:
    """The job authority classifies such a job as not never-started, handle or
    none (its read's own test shows both); the predicate names why."""
    outcome = teardown_rerun(
        [_job("failed", finished_at=None)], _POLICY, _FINISHED + timedelta(hours=1)
    )

    assert outcome == NotRerunnable("finished_before_starts_recorded", 0)


def test_disabled_reruns_run_none_and_say_so() -> None:
    disabled = TeardownRerunPolicy(teardown_rerun_limit=0, retry_policy=JobRetryPolicy())

    outcome = teardown_rerun([_never_started()], disabled, _FINISHED + timedelta(hours=1))

    assert outcome == NotRerunnable("reruns_disabled", 0)
    assert "reruns are disabled" in never_started_account(outcome, disabled)


def test_a_rerun_waits_for_its_delay_after_the_previous_finish() -> None:
    outcome = teardown_rerun([_never_started()], _POLICY, _FINISHED + timedelta(seconds=59))

    assert outcome == RerunWaiting(1, _FINISHED + timedelta(seconds=60))
    assert rerun_pending(outcome)


def test_a_rerun_is_ready_at_its_delay_numbered_by_the_jobs_already_bound() -> None:
    first = teardown_rerun([_never_started()], _POLICY, _FINISHED + timedelta(seconds=60))
    second_finished = _FINISHED + timedelta(seconds=90)
    second = teardown_rerun(
        [_never_started(), _never_started("t-2", second_finished)],
        _POLICY,
        second_finished + timedelta(seconds=120),
    )

    assert first == RerunReady(1)
    assert second == RerunReady(2)
    assert rerun_pending(second)


def test_the_reruns_are_spent_at_the_limit() -> None:
    jobs = [_never_started(f"t-{n}") for n in range(1, 5)]

    outcome = teardown_rerun(jobs, _POLICY, _FINISHED + timedelta(days=1))

    assert outcome == RerunsSpent(3)
    assert not rerun_pending(outcome)
    account = never_started_account(outcome, _POLICY)
    assert "never started" in account and "3 rerun(s) were spent" in account
    assert "teardown_rerun_limit is 3" in account


def test_only_the_latest_teardown_job_decides() -> None:
    """A rerun whose execution started settles the teardown as started."""
    jobs = [_never_started(), _job("failed")]

    assert teardown_rerun(jobs, _POLICY, _FINISHED + timedelta(days=1)) == NotRerunnable(
        "started", 1
    )


def test_a_negative_limit_is_refused_naming_the_setting() -> None:
    with pytest.raises(ValueError, match="teardown_rerun_limit must not be negative"):
        TeardownRerunPolicy(teardown_rerun_limit=-1, retry_policy=JobRetryPolicy())
