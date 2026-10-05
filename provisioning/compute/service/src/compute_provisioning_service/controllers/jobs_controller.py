"""The job authority's operator routes, bound to ``JobRouteService``."""

from __future__ import annotations

from compute_provisioning.jobs.route_service import JobRouteService
from compute_provisioning_contracts import (
    JobCredentialsResponse,
    JobListResponse,
    JobLogsResponse,
    JobStatusResponse,
)
from fastapi import APIRouter, Depends, Query

from compute_provisioning_service import container as _container_module
from compute_provisioning_service.controllers.route_errors import routed, routed_async

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _service() -> JobRouteService:
    return JobRouteService(_container_module.resolved_job_engine)


@router.get("/", response_model=JobListResponse, summary="List provisioning jobs")
def list_jobs(
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    limit: int = Query(default=20, ge=1, le=100, description="Max jobs per page"),
    status: str | None = Query(
        default=None, description="Filter by status: queued, running, succeeded, failed, cancelled"
    ),
    sort: str = Query(default="created_at_desc", description="created_at_asc or created_at_desc"),
    escrow_uid: str | None = Query(default=None, description="Filter by the escrow UID a job records"),
    service: JobRouteService = Depends(_service),
) -> JobListResponse:
    return routed(
        lambda: service.list_jobs(
            offset=offset, limit=limit, status=status, sort=sort, escrow_uid=escrow_uid
        )
    )


@router.get("/{job_id}", response_model=JobStatusResponse, summary="Get job status")
def get_job(job_id: str, service: JobRouteService = Depends(_service)) -> JobStatusResponse:
    """A job's full status. Terminal statuses: ``succeeded``, ``failed``, ``cancelled``."""
    return routed(lambda: service.get_job(job_id))


@router.get(
    "/{job_id}/credentials", response_model=JobCredentialsResponse, summary="Get job credentials"
)
def get_credentials(job_id: str, service: JobRouteService = Depends(_service)) -> JobCredentialsResponse:
    """The credentials the job's executor reported, as envelopes."""
    return routed(lambda: service.get_credentials(job_id))


@router.get("/{job_id}/logs", response_model=JobLogsResponse, summary="Get job logs")
def get_logs(job_id: str, service: JobRouteService = Depends(_service)) -> JobLogsResponse:
    """Raw output the job's executor captured."""
    return routed(lambda: service.get_logs(job_id))


@router.post("/{job_id}/cancel", summary="Cancel a job")
async def cancel_job(job_id: str, service: JobRouteService = Depends(_service)) -> dict:
    """Cancel a queued or running job; a running job's executor is asked to stop."""
    return await routed_async(lambda: service.cancel_job(job_id))
