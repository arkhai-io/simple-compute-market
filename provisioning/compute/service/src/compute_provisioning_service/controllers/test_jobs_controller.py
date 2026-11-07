"""Job observation routes for tests, mounted only under the mock profile."""

from __future__ import annotations

from compute_provisioning.jobs.route_service import JobTestRouteService
from fastapi import APIRouter, Depends, Query

from compute_provisioning_service import container as _container_module
from compute_provisioning_service.controllers.route_errors import routed, routed_async

router = APIRouter(prefix="/test/jobs", tags=["test"])


def _service() -> JobTestRouteService:
    return JobTestRouteService(_container_module.resolved_job_engine)


@router.get("/summary", summary="Job status counts")
def job_summary(service: JobTestRouteService = Depends(_service)) -> dict:
    return routed(service.summary)


@router.get("/drain", summary="Wait until all jobs are terminal")
async def drain_jobs(
    timeout: float = Query(default=30.0, description="Max seconds to wait"),
    service: JobTestRouteService = Depends(_service),
) -> dict:
    """Return once every job is terminal; 408 if some are still active at the deadline."""
    return await routed_async(lambda: service.drain(timeout))


@router.get("/{job_id}/wait", summary="Wait for a job to reach a terminal state")
async def wait_for_job(
    job_id: str,
    timeout: float = Query(default=10.0, description="Max seconds to wait"),
    service: JobTestRouteService = Depends(_service),
) -> dict:
    """A job's final status once terminal: 404 if it never existed, 408 at the deadline."""
    return await routed_async(lambda: service.wait(job_id, timeout))
