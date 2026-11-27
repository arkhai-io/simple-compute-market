"""Compute provisioning's operator event kinds, and the drafts that record them.

Each kind is recorded in the transaction of the change it reports:

- ``provisioning.lease_release_failed`` when a lease enters ``release_failed``,
  prepared by the lease lifecycle and recorded by the site in its
  release-failure transition, keyed on the lease and its release handle;
- ``provisioning.teardown_attempt_held`` when a teardown attempt fails with a
  class an operator can repair and a retry is scheduled, in the job engine's
  retry transition, keyed on the job and its retry count;
- ``provisioning.job_finished`` when a job reaches a terminal status, in the
  engine's terminal transition, keyed on the job.

Every event concerning a lease names it among its related references
(``market_site.events.lease_reference``), as the site's own events do, so one
read by reference finds every event of a lease. ``details`` hold only what may
leave the service: a job's failure envelope is redacted by its executor.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from compute_provisioning.jobs.executor import CONFIGURATION_REFUSED, INTERNAL_ERROR
from eventing import EventDraft, Kind, Reference, Severity
from market_site.events import lease_reference
from pydantic import BaseModel, ConfigDict

JOB_REFERENCE_TYPE = "job"
HOST_REFERENCE_TYPE = "host"


class LeaseReleaseFailedDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capacity_reservation_id: str
    reason: str
    message: str | None = None
    release_handle: str | None = None
    teardown_job_id: str | None = None
    failure_class: str | None = None


class TeardownAttemptHeldDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    capacity_reservation_id: str | None = None
    host_id: str | None = None
    task: str | None = None
    message: str
    retry_count: int
    max_retries: int
    retry_at: str


class JobFinishedDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    status: str
    action: str | None = None
    capacity_reservation_id: str | None = None
    host_id: str | None = None
    retry_count: int
    max_retries: int
    execution_started_at: str | None = None
    finished_at: str | None = None
    failure: dict[str, Any] | None = None


def _lease_release_failed_summary(draft: EventDraft, details: LeaseReleaseFailedDetails) -> str:
    cls = f", class {details.failure_class}" if details.failure_class else ""
    job = f", teardown job {details.teardown_job_id}" if details.teardown_job_id else ""
    return (
        f"Lease {details.capacity_reservation_id} is release_failed "
        f"({details.reason}{cls}{job}); an operator must act."
    )


def _teardown_attempt_held_summary(draft: EventDraft, details: TeardownAttemptHeldDetails) -> str:
    lease = f" (lease {details.capacity_reservation_id})" if details.capacity_reservation_id else ""
    return (
        f"Teardown on {details.host_id or 'its host'} failed: {details.message}; "
        f"retry {details.retry_count} of {details.max_retries} at {details.retry_at}{lease}."
    )


def _job_finished_summary(draft: EventDraft, details: JobFinishedDetails) -> str:
    duration = draft.attributes.get("duration_seconds")
    took = f" after {duration}s" if duration is not None else ""
    host = f" on {details.host_id}" if details.host_id else ""
    return f"Job {details.job_id} ({details.action}{host}) {details.status}{took}."


PROVISIONING_LEASE_RELEASE_FAILED: Kind[LeaseReleaseFailedDetails] = Kind(
    name="provisioning.lease_release_failed",
    version=1,
    severity=Severity.ACTION_REQUIRED,
    details=LeaseReleaseFailedDetails,
    summary=_lease_release_failed_summary,
    attributes={"reason": str, "failure_class": str, "offering_mode": str},
    dedup_key=("subject", "details.release_handle"),
)

PROVISIONING_TEARDOWN_ATTEMPT_HELD: Kind[TeardownAttemptHeldDetails] = Kind(
    name="provisioning.teardown_attempt_held",
    version=1,
    severity=Severity.ACTION_REQUIRED,
    details=TeardownAttemptHeldDetails,
    summary=_teardown_attempt_held_summary,
    attributes={
        "failure_class": str,
        "retry_at": str,
        "retries_left": int,
        "offering_mode": str,
    },
    dedup_key=("subject", "details.retry_count"),
)

PROVISIONING_JOB_FINISHED: Kind[JobFinishedDetails] = Kind(
    name="provisioning.job_finished",
    version=1,
    severity=Severity.INFO,
    details=JobFinishedDetails,
    summary=_job_finished_summary,
    attributes={
        "status": str,
        "action": str,
        "offering_mode": str,
        "duration_seconds": int,
        "failure_class": str,
        "operator_job": bool,
    },
    dedup_key=("subject",),
)

PROVISIONING_KINDS: tuple[Kind[Any], ...] = (
    PROVISIONING_LEASE_RELEASE_FAILED,
    PROVISIONING_TEARDOWN_ATTEMPT_HELD,
    PROVISIONING_JOB_FINISHED,
)


def job_reference(job_id: str) -> Reference:
    return Reference(type=JOB_REFERENCE_TYPE, id=job_id)


def _related(capacity_reservation_id: str | None, host_id: str | None,
             job_id: str | None = None) -> tuple[Reference, ...]:
    related: list[Reference] = []
    if capacity_reservation_id:
        related.append(lease_reference(capacity_reservation_id))
    if host_id:
        related.append(Reference(type=HOST_REFERENCE_TYPE, id=host_id))
    if job_id:
        related.append(job_reference(job_id))
    return tuple(related)


def _iso(instant: datetime | None) -> str | None:
    if instant is None:
        return None
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    return instant.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def lease_release_failed_draft(
    *,
    capacity_reservation_id: str,
    reason: str,
    message: str | None,
    release_handle: str | None,
    offering_mode: str | None,
    teardown_job_id: str | None,
    failure_class: str | None,
) -> EventDraft:
    """The event a lease entering ``release_failed`` records with its transition."""
    return PROVISIONING_LEASE_RELEASE_FAILED.draft(
        subject=lease_reference(capacity_reservation_id),
        details=LeaseReleaseFailedDetails(
            capacity_reservation_id=capacity_reservation_id,
            reason=reason,
            message=message,
            release_handle=release_handle,
            teardown_job_id=teardown_job_id,
            failure_class=failure_class,
        ),
        attributes={
            "reason": reason,
            "failure_class": failure_class,
            "offering_mode": offering_mode,
        },
        related=_related(capacity_reservation_id, None, teardown_job_id),
        correlation_id=capacity_reservation_id,
    )


def teardown_attempt_held_draft(
    *,
    job_id: str,
    capacity_reservation_id: str | None,
    host_id: str | None,
    offering_mode: str | None,
    failure: dict[str, Any],
    retry_count: int,
    max_retries: int,
    retry_at: datetime,
) -> EventDraft:
    """The event a teardown attempt held for an operator's repair records."""
    details = failure.get("details") or {}
    at = _iso(retry_at) or ""
    return PROVISIONING_TEARDOWN_ATTEMPT_HELD.draft(
        subject=job_reference(job_id),
        details=TeardownAttemptHeldDetails(
            job_id=job_id,
            capacity_reservation_id=capacity_reservation_id,
            host_id=host_id,
            task=details.get("task") if isinstance(details.get("task"), str) else None,
            message=str(failure.get("message") or ""),
            retry_count=retry_count,
            max_retries=max_retries,
            retry_at=at,
        ),
        attributes={
            "failure_class": failure.get("code"),
            "retry_at": at,
            "retries_left": max(max_retries - retry_count, 0),
            "offering_mode": offering_mode,
        },
        related=_related(capacity_reservation_id, host_id),
        correlation_id=capacity_reservation_id,
    )


def job_finished_draft(
    *,
    job_id: str,
    status: str,
    action: str | None,
    offering_mode: str | None,
    capacity_reservation_id: str | None,
    host_id: str | None,
    retry_count: int,
    max_retries: int,
    execution_started_at: datetime | None,
    finished_at: datetime | None,
    failure: dict[str, Any] | None,
) -> EventDraft:
    """The event a job reaching a terminal status records.

    ``info`` when it succeeded, ``warning`` otherwise. Its duration runs from
    its first execution's start to its finish, and is absent for a job that
    never started one. A cancelled job reports no failure class: the earlier
    attempt's failure it keeps did not end it. A job bound to no reservation
    was submitted by an operator. A failure's message and details are carried
    only where an executor classified it, since an executor redacts what it
    reports, while the engine's ``configuration_refused`` and
    ``internal_error`` carry an exception's own text, which may quote anything.
    """
    started, ended = _aware(execution_started_at), _aware(finished_at)
    reported_failure = _shareable(failure) if status == "failed" else None
    duration = (
        int((ended - started).total_seconds())
        if started is not None and ended is not None
        else None
    )
    return PROVISIONING_JOB_FINISHED.draft(
        subject=job_reference(job_id),
        details=JobFinishedDetails(
            job_id=job_id,
            status=status,
            action=action,
            capacity_reservation_id=capacity_reservation_id,
            host_id=host_id,
            retry_count=retry_count,
            max_retries=max_retries,
            execution_started_at=_iso(started),
            finished_at=_iso(ended),
            failure=reported_failure,
        ),
        attributes={
            "status": status,
            "action": action,
            "offering_mode": offering_mode,
            "duration_seconds": duration,
            "failure_class": (reported_failure or {}).get("code"),
            "operator_job": capacity_reservation_id is None,
        },
        related=_related(capacity_reservation_id, host_id),
        severity=Severity.INFO if status == "succeeded" else Severity.WARNING,
        correlation_id=capacity_reservation_id,
    )


#: Failure classes whose message is an exception's text the engine did not
#: redact, so an event carries their class and not their message.
_UNREDACTED_CLASSES = frozenset({CONFIGURATION_REFUSED, INTERNAL_ERROR})


def _shareable(failure: dict[str, Any] | None) -> dict[str, Any] | None:
    if failure is None or failure.get("code") not in _UNREDACTED_CLASSES:
        return failure
    return {"code": failure.get("code"), "retryable": failure.get("retryable")}


def _aware(instant: datetime | None) -> datetime | None:
    if instant is None or instant.tzinfo is not None:
        return instant
    return instant.replace(tzinfo=timezone.utc)


__all__ = [
    "PROVISIONING_JOB_FINISHED",
    "PROVISIONING_KINDS",
    "PROVISIONING_LEASE_RELEASE_FAILED",
    "PROVISIONING_TEARDOWN_ATTEMPT_HELD",
    "JobFinishedDetails",
    "LeaseReleaseFailedDetails",
    "TeardownAttemptHeldDetails",
    "job_finished_draft",
    "job_reference",
    "lease_release_failed_draft",
    "teardown_attempt_held_draft",
]
