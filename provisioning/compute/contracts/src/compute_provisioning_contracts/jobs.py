"""Wire models of the job authority's operator routes.

Parameters are carried as opaque mappings, and results and credentials as the
envelopes the job's executor reported: what any of them mean belongs to the
domain whose executor ran the job.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from .contracts import CredentialEnvelope, ResultEnvelope


class ProvisioningErrorEnvelope(BaseModel):
    """Why a job's attempt failed, as its executor or the job authority classified it.

    ``code`` is the failure's class, from an open set of strings: a generic
    class (``task_failed``, ``unreachable``, ``timed_out``, the job
    authority's ``not_dispatchable`` and ``internal_error``, among others) or
    one a domain declares. ``retryable`` says whether running the job again
    could succeed; whether and when a retry happens is the job authority's.
    ``details`` are what the failure's reader may want — its host, task,
    module, return code — already redacted, since they leave the service.
    """

    code: str
    message: str
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class JobSubmitResponse(BaseModel):
    """Returned immediately when a job is accepted into the queue.

    Poll ``GET /api/v1/jobs/{job_id}`` for status updates.
    The job_id is stable across retries; use it for credentials and logs too.
    """

    job_id: str = Field(description="Stable unique identifier for the queued job")
    status: str = Field(description="Initial job status (always 'queued')")


class JobStatusResponse(BaseModel):
    """Full job status including parameters, result, and retry metadata."""

    job_id: str = Field(description="Unique job identifier")
    status: str = Field(
        description="Current status: queued, running, succeeded, failed, or cancelled"
    )
    params: dict = Field(
        description="Original request parameters submitted with the job"
    )
    host_id: Optional[str] = Field(default=None, description="The host the job runs against")
    result: Optional[ResultEnvelope] = Field(
        default=None,
        description="The result the job's executor reported on success",
    )
    error: Optional[str] = Field(default=None, description="Error message if the job failed")
    failure: Optional[ProvisioningErrorEnvelope] = Field(
        default=None,
        description=(
            "The latest failed attempt's classified failure: its code, message, "
            "whether it is retryable, and redacted details. Null while no attempt "
            "has failed, once an attempt succeeds, and for a job that failed before "
            "its service kept structured failures; a job cancelled after a failed "
            "attempt keeps it. ``error`` carries the failure's text"
        ),
    )
    retry_count: int = Field(default=0, description="Number of retries attempted so far")
    max_retries: int = Field(default=3, description="Maximum retries allowed for this job")
    next_retry_at: Optional[datetime] = Field(
        default=None,
        description="Scheduled time for the next retry attempt (UTC)",
    )
    capacity_reservation_id: Optional[str] = Field(
        default=None,
        description=(
            "The capacity reservation a fulfillment's job serves; none for an "
            "operator's job"
        ),
    )
    execution_started_at: Optional[datetime] = Field(
        default=None,
        description=(
            "When the job authority recorded that the job's execution was "
            "starting, before anything acted on the host; kept from its first "
            "start. Null for a job whose execution has not started, and for one "
            "recorded before this instant existed, which is no evidence that its "
            "execution never started"
        ),
    )
    finished_at: Optional[datetime] = Field(
        default=None,
        description=(
            "When the job authority recorded the job reaching a terminal status. "
            "Null for a job not yet finished, and for one finished before this "
            "instant existed"
        ),
    )


class JobCredentialsResponse(BaseModel):
    """The credentials a job's executor reported, as envelopes."""

    job_id: str
    credentials: list[CredentialEnvelope] = Field(default_factory=list)


class JobLogsResponse(BaseModel):
    """Raw output an executor captured for a job."""

    job_id: str = Field(description="Unique job identifier")
    status: str = Field(description="Current job status")
    logs: Optional[str] = Field(
        default=None, description="Raw stdout/stderr captured during execution"
    )


#: The orders a job listing may be read in, by creation time.
JobListSort = Literal["created_at_asc", "created_at_desc"]


class JobListResponse(BaseModel):
    """Paginated list of provisioning jobs."""

    jobs: list[JobStatusResponse] = Field(description="Jobs on the current page")
    total: int = Field(description="Total number of jobs matching the query")
    offset: int = Field(description="Number of jobs skipped (pagination offset)")
    limit: int = Field(description="Maximum jobs returned per page")


__all__ = [
    "JobListSort",
    "JobCredentialsResponse",
    "JobListResponse",
    "JobLogsResponse",
    "JobStatusResponse",
    "JobSubmitResponse",
    "ProvisioningErrorEnvelope",
]
