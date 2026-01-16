import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from async_provisioning_service.api.schemas import (
    ProvisionLogsResponse,
    ProvisionRequest,
    ProvisionResponse,
    ProvisionStatusResponse,
)
from async_provisioning_service.db.database import get_db
from async_provisioning_service.db.models import JobStatus, ProvisioningJob
from async_provisioning_service.services.queue import enqueue_job


router = APIRouter()


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@router.post("/provision", response_model=ProvisionResponse, status_code=status.HTTP_202_ACCEPTED)
async def submit_provisioning(request: ProvisionRequest, db: Session = Depends(get_db)):
    job_id = str(uuid.uuid4())
    job = ProvisioningJob(
        id=job_id,
        status=JobStatus.queued.value,
        params=request.model_dump(),
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
    )


@router.get("/provision/{job_id}/logs", response_model=ProvisionLogsResponse)
async def get_logs(job_id: str, db: Session = Depends(get_db)):
    job = db.query(ProvisioningJob).filter(ProvisioningJob.id == job_id).one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return ProvisionLogsResponse(job_id=job.id, status=job.status, logs=job.logs)
