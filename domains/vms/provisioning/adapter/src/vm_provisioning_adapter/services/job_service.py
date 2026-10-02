"""Ansible job lifecycle management.

``AnsibleJobService`` owns:
  - Job submission (HTTP layer -> DB -> queue).
  - Job read operations (list, get, credentials, logs).
  - Job cancellation.
  - The ``_process_job`` coroutine: DB state transitions, the pre-execution
    host lookup, dispatch to the job's executor, retry scheduling, and storage
    of the logs, result, and credentials the executor reports.

It does **not** own queue mechanics (concurrency, task dispatch).  That belongs
to ``AsyncJobQueue``, which is injected and started separately in the FastAPI
lifespan.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import uuid
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from compute_provisioning import JobExecutorResolver, UnsupportedExecutorActionError
from compute_provisioning.contracts import ExecutorActionEnvelope
from compute_provisioning.jobs import JobRun, JobSuccess
from compute_provisioning_service.config import Settings
from compute_provisioning_service.db.models import (
    AnsibleJob,
    Credential,
    JobStatus,
)
from vm_provisioning_adapter.models.jobs_model import AnsibleJobParams
from vm_provisioning_operator.models import (
    CredentialListResponse,
    CredentialResponse,
    JobListResponse,
    JobLogsResponse,
    JobStatusResponse,
    JobSubmitResponse,
)
from vm_provisioning_adapter.services.ansible_job_executor import (
    execution_host_from_record,
)

logger = logging.getLogger(__name__)

# The columns a stored credential row has; a reported credential's value
# supplies them by name.
_CREDENTIAL_COLUMNS = ("password", "ssh_commands", "ssh_key_path_host", "key_type")


class AnsibleJobService:
    """Manages the full lifecycle of Ansible jobs.

    The in-process ``AsyncJobQueue`` is injected separately and started in the
    FastAPI lifespan via::

        await job_queue.start(job_service._process_job)

    ``AnsibleJobService`` does not hold a reference to the queue; the controller
    layer passes it into ``submit()`` for enqueuing.
    """

    def __init__(
        self,
        settings: Settings,
        session_factory: sessionmaker[Session],
        executors: JobExecutorResolver,
        host_service,  # services.host_service.HostService
    ) -> None:
        # The host registry is required: it is the only source of the host a
        # job runs against. See _process_job.
        self._settings = settings
        self._session_factory = session_factory
        # Which executor runs a job is decided by compute-provisioning
        # composition from the job's offering mode and action; this service
        # persists and drives the job but routes nothing.
        self._executors = executors
        self._host_service = host_service

    # ------------------------------------------------------------------
    # HTTP-layer operations
    # ------------------------------------------------------------------

    async def submit(
        self,
        params: AnsibleJobParams,
        job_queue,
        *,
        contract: ExecutorActionEnvelope | None = None,
        operation_id: str | None = None,
    ) -> JobSubmitResponse:
        """Persist and enqueue a job, deduplicating contracts and request operations."""
        max_retries = (
            params.max_retries
            if params.max_retries is not None
            else self._settings.default_max_retries
        )
        raw_params = dataclasses.asdict(params)
        job_id = operation_id or str(uuid.uuid4())
        created = False

        with self._session_factory() as db:
            if operation_id is not None:
                existing = db.get(AnsibleJob, operation_id)
                if existing is not None:
                    if existing.params != raw_params:
                        raise ValueError(
                            "operation_id is already bound to different job parameters"
                        )
                    return JobSubmitResponse(job_id=existing.id, status=existing.status)
            if contract is not None:
                existing = self._contract_job(
                    db,
                    capacity_reservation_id=contract.capacity_reservation_id,
                    action_kind=contract.action_kind,
                    idempotency_key=contract.idempotency_key,
                )
                if existing is not None:
                    return JobSubmitResponse(job_id=existing.id, status=existing.status)
            job = AnsibleJob(
                id=job_id,
                status=JobStatus.queued.value,
                params=raw_params,
                escrow_uid=params.escrow_uid,
                retry_count=0,
                max_retries=max_retries,
                next_retry_at=None,
                contract_version=contract.contract_version if contract else None,
                capacity_reservation_id=contract.capacity_reservation_id if contract else None,
                deal_ref=contract.deal_ref if contract else None,
                offering_mode=contract.offering_mode if contract else params.offering_mode,
                action_kind=contract.action_kind if contract else params.executor_action,
                idempotency_key=contract.idempotency_key if contract else None,
            )
            db.add(job)
            try:
                db.commit()
                created = True
            except IntegrityError:
                db.rollback()
                if contract is None and operation_id is None:
                    raise
                if operation_id is not None:
                    existing = db.get(AnsibleJob, operation_id)
                    if existing is None or existing.params != raw_params:
                        raise
                    return JobSubmitResponse(
                        job_id=existing.id,
                        status=existing.status,
                    )
                existing = self._contract_job(
                    db,
                    capacity_reservation_id=contract.capacity_reservation_id,
                    action_kind=contract.action_kind,
                    idempotency_key=contract.idempotency_key,
                )
                if existing is None:
                    raise
                job_id = existing.id
                return JobSubmitResponse(job_id=existing.id, status=existing.status)

        if created:
            await job_queue.enqueue(job_id)
        return JobSubmitResponse(job_id=job_id, status=JobStatus.queued.value)

    # ------------------------------------------------------------------
    # Retry scheduler — re-enqueue jobs whose backoff delay has elapsed
    # ------------------------------------------------------------------

    async def requeue_due_retries(self, job_queue) -> int:
        """Re-enqueue queued jobs whose scheduled retry time has arrived.

        On a retryable failure ``_process_job`` flips the job back to
        ``queued`` and stamps ``next_retry_at`` for backoff, but does not
        put it back on the in-process queue (which is intentionally
        transient). This sweep finds those jobs once their delay elapses,
        clears ``next_retry_at`` to mark them claimed, and enqueues them.

        Clearing ``next_retry_at`` before enqueue is what prevents a
        double-enqueue: the row no longer matches the due-retry filter on
        the next sweep, and ``_process_job`` flips it to ``running`` when it
        picks it up. ``retry_count`` is untouched, so ``max_retries`` still
        bounds the attempts. Returns the number re-enqueued.
        """
        now = datetime.utcnow()
        with self._session_factory() as db:
            due = (
                db.query(AnsibleJob)
                .filter(
                    AnsibleJob.status == JobStatus.queued.value,
                    AnsibleJob.next_retry_at.isnot(None),
                    AnsibleJob.next_retry_at <= now,
                )
                .all()
            )
            job_ids = [job.id for job in due]
            for job in due:
                job.next_retry_at = None
            if job_ids:
                db.commit()

        for job_id in job_ids:
            await job_queue.enqueue(job_id)
            logger.info("Retry scheduler re-enqueued job %s", job_id)
        return len(job_ids)

    async def run_retry_scheduler(
        self, job_queue, poll_interval_seconds: float
    ) -> None:
        """Long-lived loop: sweep for due retries every poll interval.

        Started as an asyncio task in the FastAPI lifespan; exits cleanly on
        cancellation.
        """
        logger.info(
            "Retry scheduler started (interval=%.0fs)", poll_interval_seconds
        )
        while True:
            try:
                await asyncio.sleep(poll_interval_seconds)
                await self.requeue_due_retries(job_queue)
            except asyncio.CancelledError:
                logger.info("Retry scheduler cancelled")
                break
            except Exception as exc:
                logger.exception("Retry scheduler sweep failed: %s", exc)

    def list_jobs(
        self,
        offset: int = 0,
        limit: int = 20,
        status_filter: str | None = None,
        sort: str = "created_at_desc",
        escrow_uid: str | None = None,
    ) -> JobListResponse:
        sort_map = {
            "created_at_asc": AnsibleJob.created_at.asc(),
            "created_at_desc": AnsibleJob.created_at.desc(),
        }
        with self._session_factory() as db:
            query = db.query(AnsibleJob)
            if status_filter:
                query = query.filter(AnsibleJob.status == status_filter)
            if escrow_uid:
                query = query.filter(AnsibleJob.escrow_uid == escrow_uid)
            total = query.count()
            order_fn = sort_map.get(sort, sort_map["created_at_desc"])
            jobs = query.order_by(order_fn).offset(offset).limit(limit).all()
            return JobListResponse(
                jobs=[self._to_status_response(j) for j in jobs],
                total=total,
                offset=offset,
                limit=limit,
            )

    def get_job(self, job_id: str) -> JobStatusResponse:
        """Return full job status. Raises LookupError for 404."""
        with self._session_factory() as db:
            job = (
                db.query(AnsibleJob)
                .filter(AnsibleJob.id == job_id)
                .one_or_none()
            )
            if not job:
                raise LookupError(f"Job {job_id} not found")
            return self._to_status_response(job)

    def reserved_var_keys(self, params: AnsibleJobParams) -> frozenset[str]:
        """Built-in variable keys that would be emitted for these params.

        Thin passthrough to the executor that would run these params. Lets
        callers (AnsibleFulfillmentProvider) validate proposed pool extra-vars
        synchronously, before submit(), without depending on the runner directly.
        """
        return self._executors.resolve(
            params.offering_mode, params.executor_action or params.vm_action
        ).reserved_var_keys(params)

    def get_contract_job_record(self, job_id: str) -> dict:
        """Return persisted contract correlation and executor-owned payloads."""
        with self._session_factory() as db:
            job = db.query(AnsibleJob).filter(AnsibleJob.id == job_id).one_or_none()
            if job is None:
                raise LookupError(f"Job {job_id} not found")
            if not job.contract_version:
                raise LookupError(f"Job {job_id} is not a contract job")
            credentials = (
                db.query(Credential)
                .filter(Credential.job_id == job_id)
                .all()
            )
            return {
                "contract_version": job.contract_version,
                "job_id": job.id,
                "status": job.status,
                "capacity_reservation_id": job.capacity_reservation_id,
                "deal_ref": dict(job.deal_ref or {}),
                "offering_mode": job.offering_mode,
                "action_kind": job.action_kind,
                "idempotency_key": job.idempotency_key,
                "result": dict(job.result or {}) if job.result is not None else None,
                "credentials": [
                    {
                        "role": credential.role,
                        "password": credential.password,
                        "ssh_commands": credential.ssh_commands,
                        "ssh_key_path_host": credential.ssh_key_path_host,
                        "key_type": credential.key_type,
                    }
                    for credential in credentials
                ],
                "error": job.error,
                "logs": job.logs,
                "retry_count": job.retry_count,
                "max_retries": job.max_retries,
                "created_at": job.created_at,
                "updated_at": job.updated_at,
            }

    def get_credentials(self, job_id: str) -> CredentialListResponse:
        """Return all credentials for a job. Raises LookupError for 404.

        The provisioning service trusts its caller (the storefront); the
        storefront decides which credentials to surface to which tenant.
        """
        with self._session_factory() as db:
            job = (
                db.query(AnsibleJob)
                .filter(AnsibleJob.id == job_id)
                .one_or_none()
            )
            if not job:
                raise LookupError(f"Job {job_id} not found")

            creds = (
                db.query(Credential)
                .filter(Credential.job_id == job_id)
                .all()
            )
            return CredentialListResponse(
                job_id=job_id,
                credentials=[
                    CredentialResponse(
                        role=c.role,
                        password=c.password,
                        ssh_commands=c.ssh_commands,
                        ssh_key_path_host=c.ssh_key_path_host,
                        key_type=c.key_type,
                    )
                    for c in creds
                ],
            )

    def get_logs(self, job_id: str) -> JobLogsResponse:
        """Return raw Ansible logs for a job."""
        with self._session_factory() as db:
            job = (
                db.query(AnsibleJob)
                .filter(AnsibleJob.id == job_id)
                .one_or_none()
            )
            if not job:
                raise LookupError(f"Job {job_id} not found")

            return JobLogsResponse(job_id=job.id, status=job.status, logs=job.logs)

    async def cancel_job(self, job_id: str) -> dict:
        """Cancel a queued or running job, asking a running job's executor to stop."""
        with self._session_factory() as db:
            job = (
                db.query(AnsibleJob)
                .filter(AnsibleJob.id == job_id)
                .one_or_none()
            )
            if not job:
                raise LookupError(f"Job {job_id} not found")

            if job.status not in (JobStatus.queued.value, JobStatus.running.value):
                return {
                    "job_id": job.id,
                    "status": job.status,
                    "message": f"Job cannot be cancelled (current status: {job.status})",
                }

            if job.status == JobStatus.running.value and job.process_id:
                try:
                    offering_mode, action, _host_id = self._route(job.params)
                    executor = self._executors.resolve(offering_mode, action)
                    await executor.cancel(json.loads(job.process_id))
                except Exception as exc:
                    logger.error(
                        "Failed to cancel the execution of job %s: %s", job_id, exc
                    )

            job.status = JobStatus.cancelled.value
            job.error = "Job cancelled by user"
            db.add(job)
            db.commit()

        return {
            "job_id": job_id,
            "status": JobStatus.cancelled.value,
            "message": "Job cancelled successfully",
        }

    @staticmethod
    def _contract_job(
        db: Session,
        *,
        capacity_reservation_id: str,
        action_kind: str,
        idempotency_key: str,
    ) -> AnsibleJob | None:
        return (
            db.query(AnsibleJob)
            .filter(
                AnsibleJob.capacity_reservation_id == capacity_reservation_id,
                AnsibleJob.action_kind == action_kind,
                AnsibleJob.idempotency_key == idempotency_key,
            )
            .one_or_none()
        )

    # ------------------------------------------------------------------
    # Job processor -- passed as handler to AsyncJobQueue.start()
    # ------------------------------------------------------------------

    async def _process_job(self, job_id: str) -> None:
        """Run one attempt of a job end-to-end.

        This is the ``handler`` argument to ``AsyncJobQueue.start()``.
        ``AsyncJobQueue`` owns concurrency and task dispatch; this method owns
        every DB state transition, the pre-execution host lookup, retry
        scheduling, and storing what the job's executor reports.
        """
        db = self._session_factory()
        try:
            job = (
                db.query(AnsibleJob)
                .filter(AnsibleJob.id == job_id)
                .one_or_none()
            )
            if not job:
                logger.warning("Job %s not found", job_id)
                return

            # Respect scheduled retry delay: if the job's next_retry_at is in
            # the future just return; the retry scheduler (run_retry_scheduler)
            # re-enqueues it once the delay elapses.
            if job.next_retry_at and datetime.utcnow() < job.next_retry_at:
                return

            logger.info(
                "Processing job %s (attempt %d/%d)",
                job_id,
                job.retry_count + 1,
                job.max_retries + 1,
            )

            self._update_job(db, job, status=JobStatus.running.value)
            offering_mode, action, host_id = self._route(job.params)
            # The job runs only against the registered host record it names: the
            # record is its whole inventory and its tenant-facing address. A
            # host with no record fails here, before any credential or
            # variable reaches a file and before any executor runs; there is
            # no fallback inventory, because one would run against whatever a
            # file happens to say rather than what the registry holds. See
            # openspec/specs/physical-provisioning/spec.md#requirement-execution-inventory-comes-only-from-the-registered-host-record.
            host = self._host_service.get_host(host_id)
            if host is None:
                error_message = (
                    f"host {host_id!r} is not registered; register or "
                    "import it before dispatching work to it"
                )
                self._update_job(
                    db, job, status=JobStatus.failed.value, error=error_message
                )
                logger.error("Job %s refused: %s", job_id, error_message)
                return
            try:
                executor = self._executors.resolve(offering_mode, action)
            except UnsupportedExecutorActionError as exc:
                self._update_job(
                    db, job, status=JobStatus.failed.value, error=str(exc)
                )
                logger.error("Job %s refused: %s", job_id, exc)
                return

            def report_handle(handle: Mapping[str, Any]) -> None:
                self._update_job(
                    db,
                    job,
                    status=JobStatus.running.value,
                    process_id=json.dumps(dict(handle), sort_keys=True),
                )

            outcome = await executor.execute(
                JobRun(
                    job_id=job_id,
                    offering_mode=offering_mode,
                    action=action,
                    host=execution_host_from_record(host),
                    parameters=dict(job.params),
                    report_handle=report_handle,
                    report_logs=self._log_writer(job_id),
                )
            )

            if isinstance(outcome, JobSuccess):
                for credential in outcome.credentials:
                    db.add(
                        Credential(
                            job_id=job.id,
                            role=credential.credential_kind,
                            **{
                                name: credential.value.get(name)
                                for name in _CREDENTIAL_COLUMNS
                            },
                        )
                    )
                self._update_job(
                    db,
                    job,
                    status=JobStatus.succeeded.value,
                    result=(
                        dict(outcome.result.value)
                        if outcome.result is not None
                        else None
                    ),
                    error=None,
                    logs=outcome.logs,
                )
                logger.info("Job %s succeeded", job_id)
                return

            error_message = outcome.error.message
            should_retry = (
                job.retry_count < job.max_retries and outcome.error.retryable
            )
            if should_retry:
                retry_delay = self._calculate_retry_delay(job.retry_count)
                next_retry_at = datetime.utcnow() + timedelta(seconds=retry_delay)
                job.retry_count += 1
                job.next_retry_at = next_retry_at
                job.status = JobStatus.queued.value
                job.error = (
                    f"Attempt {job.retry_count} failed: {error_message}. "
                    f"Retrying at {next_retry_at}"
                )
                job.logs = outcome.logs
                db.add(job)
                db.commit()
                # The job now sits in `queued` with next_retry_at set;
                # run_retry_scheduler re-enqueues it once the delay elapses.
                logger.warning(
                    "Job %s failed (attempt %d/%d), retry at %s: %s",
                    job_id,
                    job.retry_count,
                    job.max_retries + 1,
                    next_retry_at,
                    error_message,
                )
            else:
                reason = (
                    "max retries exceeded"
                    if job.retry_count >= job.max_retries
                    else "non-retryable error"
                )
                self._update_job(
                    db,
                    job,
                    status=JobStatus.failed.value,
                    error=f"Job failed ({reason}): {error_message}",
                    logs=outcome.logs,
                )
                logger.error("Job %s failed permanently: %s", job_id, error_message)

        except Exception as exc:
            logger.exception("Unexpected error processing job %s: %s", job_id, exc)
            try:
                # The error may have come from a failed flush/commit (e.g. an
                # IntegrityError while storing credentials), which leaves the
                # session in an aborted transaction. Roll back first so the
                # recovery query/update below can run instead of silently
                # re-raising and leaving the job stuck in `running`.
                db.rollback()
                job = (
                    db.query(AnsibleJob)
                    .filter(AnsibleJob.id == job_id)
                    .one_or_none()
                )
                if job:
                    self._update_job(
                        db,
                        job,
                        status=JobStatus.failed.value,
                        error=f"Internal error: {exc}",
                    )
            except Exception:
                logger.exception(
                    "Failed to mark job %s as failed after an unexpected error",
                    job_id,
                )
        finally:
            db.close()

    def _log_writer(self, job_id: str):
        """Write a job's reported output in a session of its own."""

        def write(logs: str) -> None:
            try:
                callback_db = self._session_factory()
                try:
                    with callback_db.begin():
                        callback_job = (
                            callback_db.query(AnsibleJob)
                            .filter(AnsibleJob.id == job_id)
                            .one_or_none()
                        )
                        if callback_job:
                            callback_job.logs = logs
                finally:
                    callback_db.close()
            except Exception as e:
                logger.warning("Failed to update logs for job %s: %s", job_id, e)

        return write

    def _route(self, params: Mapping[str, Any]) -> tuple[str, str, Any]:
        """The offering mode, action, and host a job's stored parameters name."""
        executor_action = params.get("executor_action") or params.get(
            "vm_action", "create"
        )
        executor_target = params.get("executor_target") or params.get("vm_target")
        action = executor_action or params.get("vm_action")
        host_id = params.get(
            "host_id", executor_target or self._settings.default_host_id
        )
        return params["offering_mode"], action, host_id

    # ------------------------------------------------------------------
    # Private utilities
    # ------------------------------------------------------------------

    _UNSET = object()

    def _update_job(
        self,
        db: Session,
        job: AnsibleJob,
        *,
        status: str,
        result: object = _UNSET,
        error: object = _UNSET,
        logs: object = _UNSET,
        process_id: str | None = None,
    ) -> None:
        job.status = status
        if result is not self._UNSET:
            job.result = result
        if error is not self._UNSET:
            job.error = error
        if logs is not self._UNSET:
            job.logs = logs
        if process_id is not None:
            job.process_id = process_id
        db.add(job)
        db.commit()

    def _calculate_retry_delay(self, retry_count: int) -> int:
        delay = self._settings.retry_backoff_initial_seconds * (
            self._settings.retry_backoff_multiplier ** retry_count
        )
        return min(int(delay), self._settings.retry_backoff_max_seconds)

    @staticmethod
    def _to_status_response(job: AnsibleJob) -> JobStatusResponse:
        return JobStatusResponse(
            job_id=job.id,
            status=job.status,
            params=job.params,
            result=job.result,
            error=job.error,
            retry_count=job.retry_count,
            max_retries=job.max_retries,
            next_retry_at=job.next_retry_at,
            escrow_uid=job.escrow_uid,
        )
