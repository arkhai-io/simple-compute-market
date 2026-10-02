"""Integration tests for the retry scheduler (requeue_due_retries).

On a retryable failure the job engine flips a job back to ``queued`` and
stamps ``next_retry_at``, but does not re-enqueue it (the in-process queue is
transient). ``requeue_due_retries`` is the sweep that picks those jobs up once
their backoff elapses. These tests use a real sqlite session_factory.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock

from compute_provisioning_service.db.models import JobRecord, JobStatus
from compute_provisioning.jobs import JobRetryPolicy
from compute_provisioning.jobs.engine import JobEngine


class _RecordingQueue:
    """Stand-in for AsyncJobQueue that records enqueued job ids."""

    def __init__(self) -> None:
        self.enqueued: list[str] = []

    async def enqueue(self, job_id: str) -> None:
        self.enqueued.append(job_id)


def _insert(session_factory, job_id, status, next_retry_at, retry_count=1) -> None:
    with session_factory() as db:
        db.add(
            JobRecord(
                id=job_id,
                status=status,
                params={"vm_target": "t", "vm_action": "create"},
                retry_count=retry_count,
                max_retries=3,
                next_retry_at=next_retry_at,
            )
        )
        db.commit()


def _service(session_factory) -> JobEngine:
    return JobEngine(
        session_factory,
        # Requeueing never resolves an executor or a host.
        executors=MagicMock(),
        host_lookup=lambda host_id: None,
        retry_policy=JobRetryPolicy(),
    )


async def test_requeue_only_enqueues_due_queued_jobs(session_factory):
    """Only queued jobs with a past next_retry_at are re-enqueued.

    Fresh queued jobs (next_retry_at=None, already on the queue at submit),
    not-yet-due retries, and running jobs must all be left alone.
    """
    now = datetime.utcnow()
    _insert(session_factory, "due", JobStatus.queued.value, now - timedelta(seconds=5))
    _insert(session_factory, "future", JobStatus.queued.value, now + timedelta(seconds=300))
    _insert(session_factory, "fresh", JobStatus.queued.value, None)
    _insert(session_factory, "running", JobStatus.running.value, now - timedelta(seconds=5))

    queue = _RecordingQueue()
    count = await _service(session_factory).requeue_due_retries(queue)

    assert count == 1
    assert queue.enqueued == ["due"]


async def test_requeue_clears_next_retry_at_to_prevent_double_enqueue(session_factory):
    """A second sweep must not re-enqueue the same job.

    Clearing next_retry_at on enqueue is what makes the job stop matching the
    due-retry filter; retry_count is preserved so max_retries still bounds it.
    """
    now = datetime.utcnow()
    _insert(session_factory, "due", JobStatus.queued.value, now - timedelta(seconds=5))
    svc = _service(session_factory)
    queue = _RecordingQueue()

    await svc.requeue_due_retries(queue)
    await svc.requeue_due_retries(queue)

    assert queue.enqueued == ["due"]
    with session_factory() as db:
        job = db.query(JobRecord).filter(JobRecord.id == "due").one()
        assert job.next_retry_at is None
        assert job.status == JobStatus.queued.value  # awaiting the worker
        assert job.retry_count == 1                  # preserved
