"""Wire models of the job authority's operator routes.

Parameters and results are carried as opaque mappings: what a job's parameters
mean and how its result reads belong to the domain whose executor ran it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


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
    result: Optional[dict] = Field(
        default=None,
        description="Structured result the job's executor reported on success",
    )
    error: Optional[str] = Field(default=None, description="Error message if the job failed")
    retry_count: int = Field(default=0, description="Number of retries attempted so far")
    max_retries: int = Field(default=3, description="Maximum retries allowed for this job")
    next_retry_at: Optional[datetime] = Field(
        default=None,
        description="Scheduled time for the next retry attempt (UTC)",
    )
    escrow_uid: Optional[str] = Field(
        default=None,
        description="On-chain escrow UID linking this job to a deal (set at submission time)",
    )


class JobLogsResponse(BaseModel):
    """Raw output an executor captured for a job."""

    job_id: str = Field(description="Unique job identifier")
    status: str = Field(description="Current job status")
    logs: Optional[str] = Field(
        default=None, description="Raw stdout/stderr captured during execution"
    )


class JobListResponse(BaseModel):
    """Paginated list of provisioning jobs."""

    jobs: list[JobStatusResponse] = Field(description="Jobs on the current page")
    total: int = Field(description="Total number of jobs matching the query")
    offset: int = Field(description="Number of jobs skipped (pagination offset)")
    limit: int = Field(description="Maximum jobs returned per page")


__all__ = ["JobListResponse", "JobLogsResponse", "JobStatusResponse", "JobSubmitResponse"]
