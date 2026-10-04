"""The job authority's engine: durable jobs, run by whatever executor their route names.

``JobEngine`` owns a job from submission to a terminal state: deduplicating
submissions by contract identity or request operation, persisting the job,
the pre-execution host lookup, dispatch to the executor its offering mode and
action resolve to, retries (how many and when, from a ``JobRetryPolicy``; the
executor says whether a failure is retryable), cancellation through the
executor's opaque handle, and storing the logs, result, and credentials the
executor reports. It never reads a job's parameters: they are the executor's.

State changes are conditional ``UPDATE``s on the job's current status, so they
hold across sessions and worker processes. A job runs only from ``queued``; once
a job is cancelled, no outcome its executor reports afterwards changes its
state, result, or credentials (its logs are still recorded, to show what the
cancelled execution did), and a cancellation requested before the executor
reported a handle is passed to the executor as soon as the handle arrives.

The in-process ``AsyncJobQueue`` owns concurrency and dispatch; this engine's
``process_job`` is the handler it runs.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from compute_provisioning.adapters import JobExecutorResolver, UnsupportedExecutorActionError
from compute_provisioning_contracts import CredentialEnvelope, ExecutorActionEnvelope
from compute_provisioning.hosts.execution import ExecutionHost

from .db import TERMINAL_JOB_STATUSES, JobCredential, JobRecord, JobStatus
from .executor import JobRetryPolicy, JobRun, JobSuccess
from compute_provisioning_contracts import (
    JobCredentialsResponse,
    JobListResponse,
    JobLogsResponse,
    JobStatusResponse,
    JobSubmitResponse,
)

logger = logging.getLogger(__name__)

HostLookup = Callable[[str], ExecutionHost | None]

_UNSET = object()


class JobEngine:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        executors: JobExecutorResolver,
        host_lookup: HostLookup,
        retry_policy: JobRetryPolicy,
    ) -> None:
        self._session_factory = session_factory
        self._executors = executors
        self._host_lookup = host_lookup
        self._retry_policy = retry_policy
        self._terminal_events: dict[str, asyncio.Event] = {}
        self._terminal_observers: list[Callable[[str, str], None]] = []

    # ------------------------------------------------------------------
    # Submission
    # ------------------------------------------------------------------

    async def submit(
        self,
        *,
        offering_mode: str,
        action: str,
        host_id: str,
        params: Mapping[str, Any],
        job_queue,
        escrow_uid: str | None = None,
        max_retries: int | None = None,
        contract: ExecutorActionEnvelope | None = None,
        operation_id: str | None = None,
    ) -> JobSubmitResponse:
        """Persist and enqueue a job, deduplicating contracts and request operations.

        A repeated ``operation_id`` returns the job it already names, provided
        its parameters are the same; a repeated contract identity returns the
        job it already created.
        """
        raw_params = dict(params)
        job_id = operation_id or str(uuid.uuid4())
        if max_retries is None:
            max_retries = self._retry_policy.default_max_retries

        with self._session_factory() as db:
            if operation_id is not None:
                existing = db.get(JobRecord, operation_id)
                if existing is not None:
                    if existing.params != raw_params:
                        raise ValueError(
                            "operation_id is already bound to different job parameters"
                        )
                    return JobSubmitResponse(job_id=existing.id, status=existing.status)
            if contract is not None:
                existing = self._contract_job(db, contract)
                if existing is not None:
                    return JobSubmitResponse(job_id=existing.id, status=existing.status)
            db.add(JobRecord(
                id=job_id,
                status=JobStatus.queued.value,
                params=raw_params,
                host_id=host_id,
                escrow_uid=escrow_uid,
                retry_count=0,
                max_retries=max_retries,
                next_retry_at=None,
                contract_version=contract.contract_version if contract else None,
                capacity_reservation_id=contract.capacity_reservation_id if contract else None,
                deal_ref=contract.deal_ref if contract else None,
                offering_mode=contract.offering_mode if contract else offering_mode,
                action_kind=contract.action_kind if contract else action,
                executor_action=action,
                idempotency_key=contract.idempotency_key if contract else None,
            ))
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                if operation_id is not None:
                    existing = db.get(JobRecord, operation_id)
                    if existing is None or existing.params != raw_params:
                        raise
                    return JobSubmitResponse(job_id=existing.id, status=existing.status)
                if contract is None:
                    raise
                existing = self._contract_job(db, contract)
                if existing is None:
                    raise
                return JobSubmitResponse(job_id=existing.id, status=existing.status)

        await job_queue.enqueue(job_id)
        return JobSubmitResponse(job_id=job_id, status=JobStatus.queued.value)

    @staticmethod
    def _contract_job(db: Session, contract: ExecutorActionEnvelope) -> JobRecord | None:
        return (
            db.query(JobRecord)
            .filter(
                JobRecord.capacity_reservation_id == contract.capacity_reservation_id,
                JobRecord.action_kind == contract.action_kind,
                JobRecord.idempotency_key == contract.idempotency_key,
            )
            .one_or_none()
        )

    # ------------------------------------------------------------------
    # Retry scheduling
    # ------------------------------------------------------------------

    async def requeue_due_retries(self, job_queue) -> int:
        """Re-enqueue queued jobs whose scheduled retry time has arrived.

        A retryable failure returns a job to ``queued`` with ``next_retry_at``
        set, but not to the in-process queue, which is transient. This sweep
        clears ``next_retry_at`` (so the next sweep cannot claim the job again)
        and enqueues it. Returns the number re-enqueued.
        """
        now = datetime.utcnow()
        with self._session_factory() as db:
            due = (
                db.query(JobRecord)
                .filter(
                    JobRecord.status == JobStatus.queued.value,
                    JobRecord.next_retry_at.isnot(None),
                    JobRecord.next_retry_at <= now,
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

    async def run_retry_scheduler(self, job_queue, poll_interval_seconds: float) -> None:
        """Sweep for due retries every poll interval until cancelled."""
        logger.info("Retry scheduler started (interval=%.0fs)", poll_interval_seconds)
        while True:
            try:
                await asyncio.sleep(poll_interval_seconds)
                await self.requeue_due_retries(job_queue)
            except asyncio.CancelledError:
                logger.info("Retry scheduler cancelled")
                break
            except Exception as exc:
                logger.exception("Retry scheduler sweep failed: %s", exc)

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def list_jobs(
        self,
        offset: int = 0,
        limit: int = 20,
        status_filter: str | None = None,
        sort: str = "created_at_desc",
        escrow_uid: str | None = None,
    ) -> JobListResponse:
        order = {
            "created_at_asc": JobRecord.created_at.asc(),
            "created_at_desc": JobRecord.created_at.desc(),
        }
        with self._session_factory() as db:
            query = db.query(JobRecord)
            if status_filter:
                query = query.filter(JobRecord.status == status_filter)
            if escrow_uid:
                query = query.filter(JobRecord.escrow_uid == escrow_uid)
            total = query.count()
            jobs = (
                query.order_by(order.get(sort, order["created_at_desc"]))
                .offset(offset)
                .limit(limit)
                .all()
            )
            return JobListResponse(
                jobs=[self._status(job) for job in jobs],
                total=total,
                offset=offset,
                limit=limit,
            )

    def get_job(self, job_id: str) -> JobStatusResponse:
        """A job's status. Raises ``LookupError`` when there is no such job."""
        with self._session_factory() as db:
            return self._status(self._require(db, job_id))

    def get_logs(self, job_id: str) -> JobLogsResponse:
        with self._session_factory() as db:
            job = self._require(db, job_id)
            return JobLogsResponse(job_id=job.id, status=job.status, logs=job.logs)

    def get_credentials(self, job_id: str) -> JobCredentialsResponse:
        """The credentials a job's executor reported, as envelopes."""
        with self._session_factory() as db:
            self._require(db, job_id)
            return JobCredentialsResponse(
                job_id=job_id,
                credentials=[
                    CredentialEnvelope.model_validate(credential.envelope)
                    for credential in self._credentials(db, job_id)
                ],
            )

    def get_contract_job_record(self, job_id: str) -> dict:
        """A contract job's correlation, state, and stored envelopes."""
        with self._session_factory() as db:
            job = self._require(db, job_id)
            if not job.contract_version:
                raise LookupError(f"Job {job_id} is not a contract job")
            return {
                "contract_version": job.contract_version,
                "job_id": job.id,
                "status": job.status,
                "capacity_reservation_id": job.capacity_reservation_id,
                "deal_ref": dict(job.deal_ref or {}),
                "offering_mode": job.offering_mode,
                "action_kind": job.action_kind,
                "idempotency_key": job.idempotency_key,
                "result": dict(job.result) if job.result is not None else None,
                "credentials": [
                    dict(credential.envelope) for credential in self._credentials(db, job_id)
                ],
                "error": job.error,
                "logs": job.logs,
                "retry_count": job.retry_count,
                "max_retries": job.max_retries,
                "created_at": job.created_at,
                "updated_at": job.updated_at,
            }

    async def wait_for_terminal(self, job_id: str, timeout: float) -> JobStatusResponse:
        """Return a job's status once it is terminal.

        Signalled in-process when this engine finishes the job; a job finished
        by another process is seen by re-reading it. Raises ``LookupError`` if
        the job does not exist by the deadline and ``TimeoutError`` if it is
        not terminal by then.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        event = self._terminal_events.setdefault(job_id, asyncio.Event())
        try:
            while True:
                remaining = deadline - loop.time()
                try:
                    status = self.get_job(job_id)
                except LookupError:
                    if remaining <= 0:
                        raise
                    status = None
                if status is not None and status.status in TERMINAL_JOB_STATUSES:
                    return status
                if remaining <= 0:
                    raise TimeoutError(
                        f"Job {job_id!r} did not reach a terminal state within "
                        f"{timeout}s (current status: {status.status!r})"
                    )
                try:
                    await asyncio.wait_for(event.wait(), timeout=min(0.25, remaining))
                except asyncio.TimeoutError:
                    pass
        finally:
            if self._terminal_events.get(job_id) is event and not event.is_set():
                self._terminal_events.pop(job_id, None)

    def add_terminal_observer(self, observer: Callable[[str, str], None]) -> None:
        """Call ``observer(job_id, status)`` whenever this engine finishes a job."""
        self._terminal_observers.append(observer)

    # ------------------------------------------------------------------
    # Cancellation
    # ------------------------------------------------------------------

    async def cancel_job(self, job_id: str) -> dict:
        """Cancel a queued or running job, asking a running job's executor to stop.

        The cancellation is one conditional ``UPDATE``, committed before the
        executor is asked, so no outcome reported from then on can overwrite it.
        An executor that has not yet reported its handle is asked when it does.
        """
        with self._session_factory() as db:
            job = self._require(db, job_id)
            route = (job.offering_mode, job.executor_action)
            cancelled = db.execute(
                update(JobRecord)
                .where(
                    JobRecord.id == job_id,
                    JobRecord.status.in_(
                        (JobStatus.queued.value, JobStatus.running.value)
                    ),
                )
                .values(status=JobStatus.cancelled.value, error="Job cancelled by user")
                .execution_options(synchronize_session=False)
            ).rowcount
            db.commit()
            db.refresh(job)
            if not cancelled:
                return {
                    "job_id": job.id,
                    "status": job.status,
                    "message": f"Job cannot be cancelled (current status: {job.status})",
                }
            handle = dict(job.execution_handle) if job.execution_handle else None
        if handle is not None:
            await self._cancel_execution(job_id, route, handle)
        self._finished(job_id, JobStatus.cancelled.value)
        return {
            "job_id": job_id,
            "status": JobStatus.cancelled.value,
            "message": "Job cancelled successfully",
        }

    async def _cancel_execution(
        self, job_id: str, route: tuple[str | None, str | None], handle: Mapping[str, Any]
    ) -> None:
        try:
            executor = self._executors.resolve(str(route[0]), str(route[1]))
            await executor.cancel(handle)
        except Exception as exc:
            logger.error("Failed to cancel the execution of job %s: %s", job_id, exc)

    # ------------------------------------------------------------------
    # Processing: the AsyncJobQueue handler
    # ------------------------------------------------------------------

    async def process_job(self, job_id: str) -> None:
        """Run one attempt of a job end to end."""
        db = self._session_factory()
        try:
            job = db.get(JobRecord, job_id)
            if job is None:
                logger.warning("Job %s not found", job_id)
                return
            if job.status != JobStatus.queued.value:
                # Cancelled (or otherwise finished) before it started.
                return
            if job.next_retry_at and datetime.utcnow() < job.next_retry_at:
                # The retry scheduler re-enqueues it once the delay elapses.
                return
            logger.info(
                "Processing job %s (attempt %d/%d)",
                job_id, job.retry_count + 1, job.max_retries + 1,
            )
            if not self._transition(
                db, job, expected=(JobStatus.queued.value,), status=JobStatus.running.value
            ):
                return

            # The job runs only against the registered host it names; a host
            # with no record fails it before any executor runs, because there is
            # no fallback inventory.
            host = self._host_lookup(job.host_id) if job.host_id else None
            if host is None:
                self._fail(
                    db, job,
                    f"host {job.host_id!r} is not registered; register or import it "
                    "before dispatching work to it",
                )
                return
            try:
                executor = self._executors.resolve(
                    str(job.offering_mode), str(job.executor_action)
                )
            except UnsupportedExecutorActionError as exc:
                self._fail(db, job, str(exc))
                return

            loop = asyncio.get_running_loop()

            def report_handle(handle: Mapping[str, Any]) -> None:
                stored = self._transition(
                    db,
                    job,
                    expected=(JobStatus.running.value,),
                    status=JobStatus.running.value,
                    execution_handle=dict(handle),
                )
                if not stored and job.status == JobStatus.cancelled.value:
                    # Cancelled before the executor could be reached: reach it now.
                    loop.create_task(self._cancel_execution(
                        job_id, (job.offering_mode, job.executor_action), dict(handle)
                    ))

            outcome = await executor.execute(JobRun(
                job_id=job_id,
                offering_mode=str(job.offering_mode),
                action=str(job.executor_action),
                host=host,
                parameters=dict(job.params),
                report_handle=report_handle,
                report_logs=self._log_writer(job_id),
            ))

            if isinstance(outcome, JobSuccess):
                stored = self._transition(
                    db,
                    job,
                    expected=(JobStatus.running.value,),
                    status=JobStatus.succeeded.value,
                    result=(
                        outcome.result.model_dump(mode="json")
                        if outcome.result is not None
                        else None
                    ),
                    error=None,
                    logs=outcome.logs,
                    credentials=outcome.credentials,
                )
                if stored:
                    logger.info("Job %s succeeded", job_id)
                return

            message = outcome.error.message
            if job.retry_count < job.max_retries and outcome.error.retryable:
                next_retry_at = datetime.utcnow() + timedelta(
                    seconds=self._retry_policy.delay_seconds(job.retry_count)
                )
                if self._transition(
                    db,
                    job,
                    expected=(JobStatus.running.value,),
                    status=JobStatus.queued.value,
                    error=f"Attempt {job.retry_count + 1} failed: {message}. "
                    f"Retrying at {next_retry_at}",
                    logs=outcome.logs,
                    retry_count=job.retry_count + 1,
                    next_retry_at=next_retry_at,
                ):
                    logger.warning(
                        "Job %s failed (attempt %d/%d), retry at %s: %s",
                        job_id, job.retry_count, job.max_retries + 1, next_retry_at, message,
                    )
                return
            reason = (
                "max retries exceeded"
                if job.retry_count >= job.max_retries
                else "non-retryable error"
            )
            if self._transition(
                db,
                job,
                expected=(JobStatus.running.value,),
                status=JobStatus.failed.value,
                error=f"Job failed ({reason}): {message}",
                logs=outcome.logs,
            ):
                logger.error("Job %s failed permanently: %s", job_id, message)

        except Exception as exc:
            logger.exception("Unexpected error processing job %s: %s", job_id, exc)
            try:
                # A failed flush leaves the session in an aborted transaction;
                # roll back so the job can still be marked failed.
                db.rollback()
                job = db.get(JobRecord, job_id)
                if job is not None:
                    self._fail(db, job, f"Internal error: {exc}")
            except Exception:
                logger.exception(
                    "Failed to mark job %s as failed after an unexpected error", job_id
                )
        finally:
            db.close()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _transition(
        self,
        db: Session,
        job: JobRecord,
        *,
        expected: tuple[str, ...],
        status: str,
        result: object = _UNSET,
        error: object = _UNSET,
        logs: object = _UNSET,
        execution_handle: object = _UNSET,
        retry_count: object = _UNSET,
        next_retry_at: object = _UNSET,
        credentials: tuple[CredentialEnvelope, ...] = (),
    ) -> bool:
        """Apply a change only if the job is still in one of ``expected``.

        One conditional ``UPDATE``: when another session or process has moved
        the job on (cancelled it, above all) the update matches no row, nothing
        is written, and ``False`` is returned. Credentials are written in the
        same transaction, so they land only with the transition that reports
        them. ``job`` is reloaded either way.
        """
        values: dict[str, object] = {"status": status}
        for name, value in (
            ("result", result),
            ("error", error),
            ("logs", logs),
            ("execution_handle", execution_handle),
            ("retry_count", retry_count),
            ("next_retry_at", next_retry_at),
        ):
            if value is not _UNSET:
                values[name] = value
        applied = db.execute(
            update(JobRecord)
            .where(JobRecord.id == job.id, JobRecord.status.in_(expected))
            .values(**values)
            .execution_options(synchronize_session=False)
        ).rowcount
        if not applied:
            db.rollback()
            db.refresh(job)
            logger.info(
                "Job %s is %s; its executor's report is not applied", job.id, job.status
            )
            return False
        for credential in credentials:
            db.add(JobCredential(job_id=job.id, envelope=credential.model_dump(mode="json")))
        db.commit()
        db.refresh(job)
        if status in TERMINAL_JOB_STATUSES:
            self._finished(job.id, status)
        return True

    def _fail(self, db: Session, job: JobRecord, message: str) -> None:
        if self._transition(
            db,
            job,
            expected=(JobStatus.queued.value, JobStatus.running.value),
            status=JobStatus.failed.value,
            error=message,
        ):
            logger.error("Job %s failed: %s", job.id, message)

    def _finished(self, job_id: str, status: str) -> None:
        event = self._terminal_events.pop(job_id, None)
        if event is not None:
            event.set()
        for observer in self._terminal_observers:
            try:
                observer(job_id, status)
            except Exception:
                logger.exception("A terminal observer failed for job %s", job_id)

    def _log_writer(self, job_id: str) -> Callable[[str], None]:
        """Write a job's reported output in a session of its own."""

        def write(logs: str) -> None:
            try:
                with self._session_factory() as db, db.begin():
                    job = db.get(JobRecord, job_id)
                    if job is not None:
                        job.logs = logs
            except Exception as exc:
                logger.warning("Failed to update logs for job %s: %s", job_id, exc)

        return write

    @staticmethod
    def _require(db: Session, job_id: str) -> JobRecord:
        job = db.get(JobRecord, job_id)
        if job is None:
            raise LookupError(f"Job {job_id} not found")
        return job

    @staticmethod
    def _credentials(db: Session, job_id: str) -> list[JobCredential]:
        return db.query(JobCredential).filter(JobCredential.job_id == job_id).all()

    @staticmethod
    def _status(job: JobRecord) -> JobStatusResponse:
        return JobStatusResponse(
            job_id=job.id,
            status=job.status,
            params=job.params,
            host_id=job.host_id,
            result=job.result,
            error=job.error,
            retry_count=job.retry_count,
            max_retries=job.max_retries,
            next_retry_at=job.next_retry_at,
            escrow_uid=job.escrow_uid,
        )


__all__ = ["HostLookup", "JobEngine"]
