import logging
import os
import signal
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from async_provisioning_service.api.schemas import (
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


router = APIRouter()


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@router.post("/provision", response_model=ProvisionResponse, status_code=status.HTTP_202_ACCEPTED)
async def submit_provisioning(request: ProvisionRequest, db: Session = Depends(get_db)):
    job_id = str(uuid.uuid4())

    # Use request max_retries or fall back to config default
    max_retries = request.max_retries if request.max_retries is not None else settings.default_max_retries

    job = ProvisioningJob(
        id=job_id,
        status=JobStatus.queued.value,
        params=request.model_dump(),
        retry_count=0,
        max_retries=max_retries,
        next_retry_at=None,
    )
    db.add(job)
    db.commit()

    await enqueue_job(job_id)

    return ProvisionResponse(job_id=job_id, status=job.status)


@router.get("/provision/{job_id}", response_model=ProvisionStatusResponse)
async def get_status(job_id: str, db: Session = Depends(get_db)):
    job = db.query(ProvisioningJob).filter(ProvisioningJob.id == job_id).one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return ProvisionStatusResponse(
        job_id=job.id,
        status=job.status,
        params=job.params,
        result=job.result,
        error=job.error,
        retry_count=job.retry_count,
        max_retries=job.max_retries,
        next_retry_at=job.next_retry_at,
    )


@router.get("/provision/{job_id}/logs", response_model=ProvisionLogsResponse)
async def get_logs(job_id: str, db: Session = Depends(get_db)):
    job = db.query(ProvisioningJob).filter(ProvisioningJob.id == job_id).one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return ProvisionLogsResponse(job_id=job.id, status=job.status, logs=job.logs)


@router.post("/provision/{job_id}/cancel")
async def cancel_job(job_id: str, db: Session = Depends(get_db)):
    """
    Cancel a running provisioning job.

    This endpoint attempts to cancel a job by:
    1. Checking if the job exists and is in a cancellable state (queued or running)
    2. If running, attempting to terminate the ansible-playbook process
    3. Updating the job status to "cancelled"

    Note: Cancellation is best-effort. If the job has already completed or failed,
    this endpoint returns the current status without modification.
    """
    job = db.query(ProvisioningJob).filter(ProvisioningJob.id == job_id).one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Check if job is in a cancellable state
    if job.status not in (JobStatus.queued.value, JobStatus.running.value):
        return {
            "job_id": job.id,
            "status": job.status,
            "message": f"Job cannot be cancelled (current status: {job.status})",
        }

    # If job is running and we have a process ID, try to kill it
    if job.status == JobStatus.running.value and job.process_id:
        try:
            pid = int(job.process_id)
            # Send SIGTERM first (graceful shutdown)
            os.kill(pid, signal.SIGTERM)
            logger.info("Sent SIGTERM to process %d for job %s", pid, job_id)
        except ProcessLookupError:
            logger.warning("Process %d for job %s not found (already terminated)", pid, job_id)
        except ValueError:
            logger.error("Invalid process_id '%s' for job %s", job.process_id, job_id)
        except Exception as exc:
            logger.error("Failed to terminate process %d for job %s: %s", pid, job_id, exc)

    # Update job status to cancelled
    job.status = JobStatus.cancelled.value
    job.error = "Job cancelled by user"
    db.add(job)
    db.commit()

    return {
        "job_id": job.id,
        "status": job.status,
        "message": "Job cancelled successfully",
    }
