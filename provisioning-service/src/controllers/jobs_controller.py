"""Job read/cancel controller.

Handles all GET and cancel operations on the ``/api/v1/jobs`` resource.

Job *submission* is handled by the typed VM and host controllers
(``vms_controller.py``, ``hosts_controller.py``), which accept typed request
models and translate them to ``AnsibleJobParams`` before calling
``AnsibleJobService.submit()``.

Polling pattern
---------------
All job-creating endpoints return a ``JobSubmitResponse`` containing a
``job_id``.  Clients poll ``GET /api/v1/jobs/{job_id}`` for status.
The provisioning service may sit behind an API gateway; callers should
not assume any particular base URL and must construct the polling path
from the job_id alone.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi_utils.cbv import cbv

import container as _container_module
from models.jobs_model import (
    CredentialListResponse,
    JobListResponse,
    JobLogsResponse,
    JobStatusResponse,
)
from services.job_service import AnsibleJobService

router = APIRouter(prefix="/jobs", tags=["jobs"])


@cbv(router)
class AnsibleJobsController:
    def __init__(
        self,
        job_service: AnsibleJobService = Depends(
            lambda: _container_module.resolved_job_service
        ),
    ) -> None:
        self._job_service = job_service

    # ------------------------------------------------------------------
    # List
    # ------------------------------------------------------------------

    @router.get(
        "/",
        response_model=JobListResponse,
        summary="List Ansible jobs",
        response_description="Paginated list of jobs",
    )
    def list_jobs(
        self,
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
        escrow_uid: str | None = Query(
            default=None,
            description="Filter jobs by on-chain escrow UID (recovery query pattern)",
        ),
    ) -> JobListResponse:
        """List Ansible jobs with pagination, filtering, and sorting."""
        return self._job_service.list_jobs(
            offset=offset,
            limit=limit,
            status_filter=status_filter,
            sort=sort,
            escrow_uid=escrow_uid,
        )

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    @router.get(
        "/{job_id}",
        response_model=JobStatusResponse,
        summary="Get job status",
        response_description="Full job status with params, result, and retry info",
    )
    def get_job(self, job_id: str) -> JobStatusResponse:
        """Return the full status of a single Ansible job.

        Poll this endpoint after submitting any job-creating request.
        Terminal statuses: ``succeeded``, ``failed``, ``cancelled``.
        """
        try:
            return self._job_service.get_job(job_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    # ------------------------------------------------------------------
    # Credentials
    # ------------------------------------------------------------------

    @router.get(
        "/{job_id}/credentials",
        response_model=CredentialListResponse,
        summary="Get job credentials",
        response_description="Credentials granted to the requesting agent for this job",
    )
    def get_credentials(self, job_id: str) -> CredentialListResponse:
        """Return all credentials for a job.

        The storefront (the sole caller) decides which credentials to surface
        to which tenant; provisioning does not gate per-agent.
        """
        try:
            return self._job_service.get_credentials(job_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    # ------------------------------------------------------------------
    # Logs
    # ------------------------------------------------------------------

    @router.get(
        "/{job_id}/logs",
        response_model=JobLogsResponse,
        summary="Get Ansible playbook logs",
        response_description="Raw Ansible stdout/stderr for the job",
    )
    def get_logs(self, job_id: str) -> JobLogsResponse:
        """Return raw Ansible playbook output captured during job execution."""
        try:
            return self._job_service.get_logs(job_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    # ------------------------------------------------------------------
    # Cancel
    # ------------------------------------------------------------------

    @router.post(
        "/{job_id}/cancel",
        summary="Cancel a job",
        response_description="Cancellation confirmation with final job status",
    )
    def cancel_job(self, job_id: str) -> dict:
        """Cancel a queued or running Ansible job.

        Sends SIGTERM to the Ansible process if the job is running.
        """
        try:
            return self._job_service.cancel_job(job_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @classmethod
    def make_router(cls) -> APIRouter:
        return router
