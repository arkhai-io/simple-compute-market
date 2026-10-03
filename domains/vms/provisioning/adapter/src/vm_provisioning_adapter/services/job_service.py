"""VM jobs' front to the compute family's job authority.

``AnsibleJobService`` is how VM operations submit jobs: it turns
``VmJobParams`` into a submission (route key, host, opaque parameters).
Everything about a job's durable lifecycle — persistence, retries,
cancellation, processing, reads — is the ``compute_provisioning.jobs.JobEngine``
it holds, which knows nothing of Ansible or of any domain. The engine is built
here until the composition root builds it; other domains submit to it directly.

The in-process ``AsyncJobQueue`` is started in the FastAPI lifespan with the
engine's ``process_job`` as its handler.
"""

from __future__ import annotations

import dataclasses

from sqlalchemy.orm import Session, sessionmaker

from compute_provisioning import JobExecutorResolver
from compute_provisioning.contracts import ExecutorActionEnvelope
from compute_provisioning.jobs import (
    JobCredentialsResponse,
    JobListResponse,
    JobLogsResponse,
    JobRetryPolicy,
    JobStatusResponse,
    JobSubmitResponse,
)
from compute_provisioning.jobs.engine import JobEngine
from compute_provisioning_service.config import Settings
from vm_provisioning_adapter.models.jobs_model import VmJobParams


def retry_policy_from(settings: Settings) -> JobRetryPolicy:
    """The deployment's retry policy, as its settings declare it."""
    return JobRetryPolicy(
        default_max_retries=settings.default_max_retries,
        backoff_initial_seconds=settings.retry_backoff_initial_seconds,
        backoff_multiplier=settings.retry_backoff_multiplier,
        backoff_max_seconds=settings.retry_backoff_max_seconds,
    )


class AnsibleJobService:
    def __init__(
        self,
        settings: Settings,
        session_factory: sessionmaker[Session],
        executors: JobExecutorResolver,
        host_service,  # compute_provisioning.hosts.service.HostAuthority
    ) -> None:
        # The host registry is required: it is the only source of the host a
        # job runs against.
        self._settings = settings
        self._engine = JobEngine(
            session_factory,
            executors=executors,
            host_lookup=host_service.lookup,
            retry_policy=retry_policy_from(settings),
        )

    @property
    def engine(self) -> JobEngine:
        return self._engine

    async def submit(
        self,
        params: VmJobParams,
        job_queue,
        *,
        contract: ExecutorActionEnvelope | None = None,
        operation_id: str | None = None,
    ) -> JobSubmitResponse:
        """Persist and enqueue a VM job."""
        return await self._engine.submit(
            offering_mode=params.offering_mode,
            action=params.executor_action or params.vm_action,
            host_id=(
                params.host_id
                or params.executor_target
                or params.vm_target
                or self._settings.default_host_id
            ),
            params=dataclasses.asdict(params),
            job_queue=job_queue,
            escrow_uid=params.escrow_uid,
            max_retries=params.max_retries,
            contract=contract,
            operation_id=operation_id,
        )

    # The job authority's operations, unchanged.

    async def requeue_due_retries(self, job_queue) -> int:
        return await self._engine.requeue_due_retries(job_queue)

    async def run_retry_scheduler(self, job_queue, poll_interval_seconds: float) -> None:
        await self._engine.run_retry_scheduler(job_queue, poll_interval_seconds)

    def list_jobs(self, *args, **kwargs) -> JobListResponse:
        return self._engine.list_jobs(*args, **kwargs)

    def get_job(self, job_id: str) -> JobStatusResponse:
        return self._engine.get_job(job_id)

    def get_logs(self, job_id: str) -> JobLogsResponse:
        return self._engine.get_logs(job_id)

    def get_credentials(self, job_id: str) -> JobCredentialsResponse:
        return self._engine.get_credentials(job_id)

    def get_contract_job_record(self, job_id: str) -> dict:
        return self._engine.get_contract_job_record(job_id)

    async def cancel_job(self, job_id: str) -> dict:
        return await self._engine.cancel_job(job_id)

    async def wait_for_terminal(self, job_id: str, timeout: float) -> JobStatusResponse:
        return await self._engine.wait_for_terminal(job_id, timeout)

    async def process_job(self, job_id: str) -> None:
        await self._engine.process_job(job_id)
