import logging
import os
import signal
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from async_provisioning_service.api.schemas import (
    JobListResponse,
    ProvisionLogsResponse,
    ProvisionRequest,
    ProvisionResponse,
    ProvisionStatusResponse,
    ProvisionedVMListResponse,
    ProvisionedVMResponse,
)
from async_provisioning_service.config import settings
from async_provisioning_service.db.database import get_db
from async_provisioning_service.db.models import JobStatus, ProvisionedVM, ProvisioningJob
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


# ---------------------------------------------------------------------------
# Provisioned VMs — credential-filtered access
# ---------------------------------------------------------------------------

def _vm_to_response(vm: ProvisionedVM) -> ProvisionedVMResponse:
    """Build a response directly from a pre-filtered ProvisionedVM record."""
    return ProvisionedVMResponse(
        id=vm.id,
        job_id=vm.job_id,
        vm_name=vm.vm_name,
        vm_host=vm.vm_host,
        vm_ip_internal=vm.vm_ip_internal,
        vm_state=vm.vm_state,
        seller_order_id=vm.seller_order_id,
        buyer_order_id=vm.buyer_order_id,
        role=vm.role,
        seller_agent_id=vm.seller_agent_id,
        buyer_agent_id=vm.buyer_agent_id,
        negotiation_id=vm.negotiation_id,
        escrow_uid=vm.escrow_uid,
        external_ssh_port=vm.external_ssh_port,
        frp_domain=vm.frp_domain,
        created_at=vm.created_at,
        root_password=vm.root_password,
        root_ssh_key_path=vm.root_ssh_key_path,
        root_ssh_commands=vm.root_ssh_commands,
        tenant_user=vm.tenant_user,
        tenant_password=vm.tenant_password,
        tenant_ssh_commands=vm.tenant_ssh_commands,
    )


@router.get(
    "/provisioned",
    response_model=ProvisionedVMListResponse,
    tags=["provisioned-vms"],
    summary="List provisioned VMs for the requesting agent",
    response_description="VMs where the agent is buyer or seller, with filtered credentials",
)
async def list_provisioned_vms(
    request: Request,
    order_id: str | None = Query(default=None, description="Filter by marketplace order ID"),
    negotiation_id: str | None = Query(default=None, description="Filter by negotiation ID"),
    db: Session = Depends(get_db),
):
    """List VMs where the requesting agent is buyer or seller.

    Credentials are filtered: sellers see root creds, buyers see tenant creds.
    Supports filtering by ``order_id`` and ``negotiation_id``.
    Requires `X-Agent-ID` header.
    """
    agent_id = _get_agent_id(request)

    query = db.query(ProvisionedVM)
    if agent_id:
        # Return only the role-specific record for this agent
        query = query.filter(
            or_(
                and_(ProvisionedVM.seller_agent_id == agent_id, ProvisionedVM.role == "seller"),
                and_(ProvisionedVM.buyer_agent_id == agent_id, ProvisionedVM.role == "buyer"),
            )
        )
    if order_id:
        query = query.filter(
            or_(
                ProvisionedVM.seller_order_id == order_id,
                ProvisionedVM.buyer_order_id == order_id,
            )
        )
    if negotiation_id:
        query = query.filter(ProvisionedVM.negotiation_id == negotiation_id)

    vms = query.order_by(ProvisionedVM.created_at.desc()).all()
    return ProvisionedVMListResponse(
        vms=[_vm_to_response(vm) for vm in vms],
        total=len(vms),
    )


@router.get(
    "/provisioned/{vm_name}",
    response_model=ProvisionedVMResponse,
    tags=["provisioned-vms"],
    summary="Get a provisioned VM by name",
    response_description="VM details with credentials filtered by agent role",
)
async def get_provisioned_vm(
    vm_name: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Return a single provisioned VM by name.

    Returns **403** if the requesting agent is neither buyer nor seller.
    Returns **404** if no VM with that name exists.
    """
    agent_id = _get_agent_id(request)

    query = db.query(ProvisionedVM).filter(ProvisionedVM.vm_name == vm_name)
    if agent_id:
        # Return the role-specific record for this agent
        query = query.filter(
            or_(
                and_(ProvisionedVM.seller_agent_id == agent_id, ProvisionedVM.role == "seller"),
                and_(ProvisionedVM.buyer_agent_id == agent_id, ProvisionedVM.role == "buyer"),
            )
        )

    vm = query.order_by(ProvisionedVM.created_at.desc()).first()
    if not vm:
        raise HTTPException(status_code=404, detail="Provisioned VM not found")

    return _vm_to_response(vm)
