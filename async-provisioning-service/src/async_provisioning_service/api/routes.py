import logging
import os
import signal
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from async_provisioning_service.api.schemas import (
    JobListResponse,
    ProvisionLogsResponse,
    ProvisionRequest,
    ProvisionResponse,
    ProvisionStatusResponse,
)
from async_provisioning_service.config import settings
from async_provisioning_service.db.database import get_db
from async_provisioning_service.db.models import JobStatus, ProvisioningJob
from async_provisioning_service.services.queue import enqueue_job


logger = logging.getLogger(__name__)


def agent_id_header(
    x_agent_id: str | None = Header(
        default=None,
        alias="X-Agent-ID",
        description="ERC-8004 agent identifier: eip155:<chain_id>:0x<address>:<token_id>",
    )
) -> str | None:
    return x_agent_id


router = APIRouter(dependencies=[Depends(agent_id_header)])


def _get_agent_id(request: Request) -> str | None:
    """Extract agent_id from request state (set by auth middleware)."""
    return getattr(request.state, "agent_id", None)


@router.get(
    "/health",
    tags=["health"],
    summary="Service health check",
    response_description="Health status object",
)
async def health() -> dict:
    """Returns `{\"status\": \"ok\"}` when the API server is running.

    Does **not** verify database or Redis connectivity.
    """
    return {"status": "ok"}


@router.post(
    "/provision",
    response_model=ProvisionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["provisioning"],
    summary="Submit a provisioning job",
    response_description="Job ID and initial queued status",
)
async def submit_provisioning(
    provision_request: ProvisionRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Enqueue a new VM provisioning job.

    The request is validated, persisted to the database, and pushed onto the
    Redis queue.  The background worker picks it up asynchronously.

    Requires `X-Agent-ID` header when auth is enabled.
    """
    job_id = str(uuid.uuid4())
    agent_id = _get_agent_id(request)

    max_retries = (
        provision_request.max_retries
        if provision_request.max_retries is not None
        else settings.default_max_retries
    )

    job = ProvisioningJob(
        id=job_id,
        status=JobStatus.queued.value,
        params=provision_request.model_dump(),
        agent_id=agent_id,
        retry_count=0,
        max_retries=max_retries,
        next_retry_at=None,
    )
    db.add(job)
    db.commit()

    await enqueue_job(job_id)

    return ProvisionResponse(job_id=job_id, status=job.status)


@router.get(
    "/provision",
    response_model=JobListResponse,
    tags=["provisioning"],
    summary="List provisioning jobs",
    response_description="Paginated list of jobs",
)
async def list_jobs(
    request: Request,
    offset: int = Query(default=0, ge=0, description="Number of jobs to skip (pagination offset)"),
    limit: int = Query(default=20, ge=1, le=100, description="Max jobs per page (1-100)"),
    status_filter: str | None = Query(default=None, alias="status", description="Filter by job status: queued, running, succeeded, failed, cancelled"),
    db: Session = Depends(get_db),
):
    """List provisioning jobs with pagination and optional status filtering.

    Authenticated agents only see their own jobs.  Unauthenticated requests
    (when auth is disabled) see all jobs.
    """
    agent_id = _get_agent_id(request)

    query = db.query(ProvisioningJob)

    # Authenticated agents only see their own jobs
    if agent_id:
        query = query.filter(ProvisioningJob.agent_id == agent_id)

    if status_filter:
        query = query.filter(ProvisioningJob.status == status_filter)

    total = query.count()
    jobs = query.order_by(ProvisioningJob.created_at.desc()).offset(offset).limit(limit).all()

    return JobListResponse(
        jobs=[
            ProvisionStatusResponse(
                job_id=job.id,
                status=job.status,
                params=job.params,
                result=job.result,
                error=job.error,
                retry_count=job.retry_count,
                max_retries=job.max_retries,
                next_retry_at=job.next_retry_at,
                agent_id=job.agent_id,
            )
            for job in jobs
        ],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get(
    "/provision/{job_id}",
    response_model=ProvisionStatusResponse,
    tags=["provisioning"],
    summary="Get job status",
    response_description="Full job status with params, result, and retry info",
)
async def get_status(job_id: str, request: Request, db: Session = Depends(get_db)):
    """Return the full status of a single provisioning job.

    Includes parameters, result (on success), error (on failure), and retry
    metadata.  Returns **403** if the job belongs to a different agent.
    """
    job = db.query(ProvisioningJob).filter(ProvisioningJob.id == job_id).one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    agent_id = _get_agent_id(request)
    if job.agent_id and job.agent_id != agent_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: job belongs to another agent",
        )

    return ProvisionStatusResponse(
        job_id=job.id,
        status=job.status,
        params=job.params,
        result=job.result,
        error=job.error,
        retry_count=job.retry_count,
        max_retries=job.max_retries,
        next_retry_at=job.next_retry_at,
        agent_id=job.agent_id,
    )


@router.get(
    "/provision/{job_id}/logs",
    response_model=ProvisionLogsResponse,
    tags=["provisioning"],
    summary="Get Ansible playbook logs",
    response_description="Raw Ansible stdout/stderr for the job",
)
async def get_logs(job_id: str, request: Request, db: Session = Depends(get_db)):
    """Return the raw Ansible playbook output captured during job execution.

    Logs are updated in real-time while the job is running and remain
    available after completion.  Returns **403** if the job belongs to a
    different agent.
    """
    job = db.query(ProvisioningJob).filter(ProvisioningJob.id == job_id).one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    agent_id = _get_agent_id(request)
    if job.agent_id and job.agent_id != agent_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: job belongs to another agent",
        )

    return ProvisionLogsResponse(job_id=job.id, status=job.status, logs=job.logs)


@router.post(
    "/provision/{job_id}/cancel",
    tags=["provisioning"],
    summary="Cancel a provisioning job",
    response_description="Cancellation confirmation with final job status",
)
async def cancel_job(job_id: str, request: Request, db: Session = Depends(get_db)):
    """Cancel a queued or running provisioning job.

    If the job is currently running, sends SIGTERM to the Ansible process.
    Agents can only cancel their own jobs (returns **403** otherwise).
    Jobs that have already completed cannot be cancelled.
    """
    job = db.query(ProvisioningJob).filter(ProvisioningJob.id == job_id).one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    agent_id = _get_agent_id(request)
    if agent_id and job.agent_id and job.agent_id != agent_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot cancel another agent's job",
        )

    if job.status not in (JobStatus.queued.value, JobStatus.running.value):
        return {
            "job_id": job.id,
            "status": job.status,
            "message": f"Job cannot be cancelled (current status: {job.status})",
        }

    if job.status == JobStatus.running.value and job.process_id:
        try:
            pid = int(job.process_id)
            os.kill(pid, signal.SIGTERM)
            logger.info("Sent SIGTERM to process %d for job %s", pid, job_id)
        except ProcessLookupError:
            logger.warning("Process %d for job %s not found (already terminated)", pid, job_id)
        except ValueError:
            logger.error("Invalid process_id '%s' for job %s", job.process_id, job_id)
        except Exception as exc:
            logger.error("Failed to terminate process %d for job %s: %s", pid, job_id, exc)

    job.status = JobStatus.cancelled.value
    job.error = "Job cancelled by user"
    db.add(job)
    db.commit()

    return {
        "job_id": job.id,
        "status": job.status,
        "message": "Job cancelled successfully",
    }
