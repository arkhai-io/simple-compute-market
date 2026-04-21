from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi_utils.cbv import cbv

import container as _container_module
from models.jobs import (
    CredentialListResponse,
    JobListResponse,
    ProvisionLogsResponse,
    ProvisionRequest,
    ProvisionResponse,
    ProvisionStatusResponse,
)
from services.job_service import AnsibleJobService

router = APIRouter(prefix="/jobs", tags=["jobs"])


@cbv(router)
class AnsibleJobsController:
    def __init__(
        self,
        job_service: AnsibleJobService = Depends(lambda: _container_module.resolved_job_service),
    ) -> None:
        self._job_service = job_service

    # ------------------------------------------------------------------
    # Submit
    # ------------------------------------------------------------------

    @router.post(
        "/",
        response_model=ProvisionResponse,
        status_code=status.HTTP_202_ACCEPTED,
        summary="Submit a provisioning job",
        response_description="Job ID and initial queued status",
    )
    async def submit_job(
        self, body: ProvisionRequest, request: Request
    ) -> ProvisionResponse:
        """Enqueue a new VM provisioning job.

        The request is validated, persisted to the database, and pushed onto the
        in-process queue.  The background worker picks it up asynchronously.

        Requires ``X-Agent-ID`` header when auth is enabled.
        """
        agent_id: str | None = getattr(request.state, "agent_id", None)
        return await self._job_service.submit(body, agent_id)

    # ------------------------------------------------------------------
    # List
    # ------------------------------------------------------------------

    @router.get(
        "/",
        response_model=JobListResponse,
        summary="List provisioning jobs",
        response_description="Paginated list of jobs",
    )
    def list_jobs(
        self,
        request: Request,
        offset: int = Query(default=0, ge=0, description="Pagination offset"),
        limit: int = Query(default=20, ge=1, le=100, description="Max jobs per page"),
        status_filter: str | None = Query(
            default=None,
            alias="status",
            description="Filter by status: queued, running, succeeded, failed, cancelled",
        ),
        sort: str = Query(
            default="created_at_desc",
            description="Sort order: created_at_asc or created_at_desc",
        ),
    ) -> JobListResponse:
        """List provisioning jobs with pagination, filtering, and sorting.

        Authenticated agents only see jobs where they are the seller or buyer.
        Unauthenticated requests (when auth is disabled) see all jobs.
        """
        agent_id: str | None = getattr(request.state, "agent_id", None)
        return self._job_service.list_jobs(
            agent_id=agent_id,
            offset=offset,
            limit=limit,
            status_filter=status_filter,
            sort=sort,
        )

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    @router.get(
        "/{job_id}",
        response_model=ProvisionStatusResponse,
        summary="Get job status",
        response_description="Full job status with params, result, and retry info",
    )
    def get_job(self, job_id: str, request: Request) -> ProvisionStatusResponse:
        """Return the full status of a single provisioning job."""
        agent_id: str | None = getattr(request.state, "agent_id", None)
        try:
            return self._job_service.get_job(job_id, agent_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))

    # ------------------------------------------------------------------
    # Credentials
    # ------------------------------------------------------------------

    @router.get(
        "/{job_id}/credentials",
        response_model=CredentialListResponse,
        summary="Get job credentials",
        response_description="Credentials granted to the requesting agent for this job",
    )
    def get_credentials(self, job_id: str, request: Request) -> CredentialListResponse:
        """Return credentials the requesting agent is granted for a job.

        Sellers receive root + tenant credentials.
        Buyers receive tenant credentials only.
        Returns **401** without ``X-Agent-ID``, **403** for unauthorised agents.
        """
        agent_id: str | None = getattr(request.state, "agent_id", None)
        if not agent_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="X-Agent-ID header is required",
            )
        try:
            return self._job_service.get_credentials(job_id, agent_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))

    # ------------------------------------------------------------------
    # Logs
    # ------------------------------------------------------------------

    @router.get(
        "/{job_id}/logs",
        response_model=ProvisionLogsResponse,
        summary="Get Ansible playbook logs",
        response_description="Raw Ansible stdout/stderr for the job",
    )
    def get_logs(self, job_id: str, request: Request) -> ProvisionLogsResponse:
        """Return raw Ansible playbook output captured during job execution."""
        agent_id: str | None = getattr(request.state, "agent_id", None)
        try:
            return self._job_service.get_logs(job_id, agent_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))

    # ------------------------------------------------------------------
    # Cancel
    # ------------------------------------------------------------------

    @router.post(
        "/{job_id}/cancel",
        summary="Cancel a provisioning job",
        response_description="Cancellation confirmation with final job status",
    )
    def cancel_job(self, job_id: str, request: Request) -> dict:
        """Cancel a queued or running provisioning job.

        Sends SIGTERM to the Ansible process if the job is running.
        """
        agent_id: str | None = getattr(request.state, "agent_id", None)
        try:
            return self._job_service.cancel_job(job_id, agent_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))

    @classmethod
    def make_router(cls) -> APIRouter:
        return router