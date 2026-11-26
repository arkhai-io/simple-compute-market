"""The job authority's engine: durable jobs, run by whatever executor their route names.

``JobEngine`` owns a job from submission to a terminal state: deduplicating
submissions by contract identity or request operation, persisting the job,
the pre-execution host lookup, dispatch to the executor its offering mode and
action resolve to, retries (how many and when, from a ``JobRetryPolicy``; the
executor says whether a failure is retryable), cancellation through the
executor's opaque handle, and storing the logs, result, and credentials the
executor reports. It never reads a job's parameters: they are the executor's.

A failed attempt's classified failure, a ``ProvisioningErrorEnvelope``, is
kept on the job as ``failure`` beside ``error``, whose text carries the
failure's message. The executor classifies what it ran; the engine classifies
only what no executor reached, none of it retried: a job it cannot dispatch
(``not_dispatchable``), a preparation the executor refused as
``ConfigurationRefusedError`` (``configuration_refused``), and anything an
executor raised (``internal_error``).

State changes are conditional ``UPDATE``s on the job's current status, so they
hold across sessions and worker processes. A job runs only from ``queued``; once
a job is cancelled, no outcome its executor reports afterwards changes its
state, result, or credentials (its logs are still recorded, to show what the
cancelled execution did), and a cancellation requested before the executor
reported a handle is passed to the executor as soon as the handle arrives.

The engine records two instants from the process's time source:
``execution_started_at``, committed when the executor reports it is about to
start, before it starts anything, and kept from a job's first start; and
``finished_at``, stamped on the transition to any terminal status. A job that
failed, was not cancelled, and records ``finished_at`` but neither a start nor
a handle therefore never started an execution.

Given an event recorder, the engine records ``provisioning.job_finished`` in
every transition to a terminal status, and ``provisioning.teardown_attempt_held``
in a teardown's retry transition when its failure's class is one the
composition names as an operator's to repair (see
``compute_provisioning.operator_events``); each is written in the transition's own transaction, so a
transition that is not applied records nothing, and one that is cannot commit
without its event.

The in-process ``AsyncJobQueue`` owns concurrency and dispatch; this engine's
``process_job`` is the handler it runs.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import injected_time
from sqlalchemy import DateTime, func, literal, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from compute_provisioning.adapters import JobExecutorResolver, UnsupportedExecutorActionError
from compute_provisioning_contracts import CredentialEnvelope
from compute_provisioning.jobs.action_request import JobActionRequest
from compute_provisioning.hosts.execution import ExecutionHost
from compute_provisioning.operator_events import (
    job_finished_draft,
    teardown_attempt_held_draft,
)
from market_site.events import EventRecorder

from .db import TERMINAL_JOB_STATUSES, JobCredential, JobRecord, JobStatus
from .executor import (
    CONFIGURATION_REFUSED,
    INTERNAL_ERROR,
    NOT_DISPATCHABLE,
    ConfigurationRefusedError,
    JobRetryPolicy,
    JobRun,
    JobSuccess,
)
from compute_provisioning_contracts import (
    JobCredentialsResponse,
    JobListResponse,
    JobLogsResponse,
    JobStatusResponse,
    JobSubmitResponse,
    ProvisioningErrorEnvelope,
)

logger = logging.getLogger(__name__)

HostLookup = Callable[[str], ExecutionHost | None]

_UNSET = object()


def _utcnow() -> datetime:
    """The process time source's instant as a job's retry time is stored: UTC
    with no zone. A retry time is stored and compared later, so it is an
    instant of the time of the world, not a duration of the engine's own."""
    return injected_time.now_datetime().replace(tzinfo=None)


def _first_start():
    """A job's recorded start once set, else the process source's instant now.

    Written inside the conditional ``UPDATE`` itself, so a retry's later start
    never moves the instant its first start recorded.
    """
    return func.coalesce(
        JobRecord.execution_started_at, literal(_utcnow(), DateTime(timezone=True))
    )


@dataclass(frozen=True)
class BoundJob:
    """One job bound to a reservation under a contract action, as the job
    authority's own record answers for it. Not a wire view."""

    job_id: str
    status: str
    #: The job failed, was not cancelled, and records ``finished_at`` but
    #: neither a start nor a handle, so its execution never started. A job
    #: with no ``finished_at`` is never so classified: no start was recorded
    #: for it before it could act on its host.
    never_started: bool
    #: When it reached a terminal status, in UTC; ``None`` while it runs, and
    #: for a job whose finish was never recorded.
    finished_at: datetime | None
    #: The class of its latest failed attempt, ``None`` when none failed.
    failure_class: str | None = None


def _never_started(job: JobRecord) -> bool:
    return (
        job.status == JobStatus.failed.value
        and job.execution_started_at is None
        and not job.execution_handle
        and job.finished_at is not None
    )


def _utc(instant: datetime | None) -> datetime | None:
    """A stored instant as an aware UTC datetime; SQLite returns it naive."""
    if instant is None or instant.tzinfo is not None:
        return instant
    return instant.replace(tzinfo=timezone.utc)


class JobNotRunningError(RuntimeError):
    """A job's start was reported after it stopped running: it was cancelled
    since the engine claimed it, so its executor must start nothing."""


class JobIdentityConflictError(ValueError):
    """A repeated job identity names different job parameters.

    A job identity, whether a request's ``operation_id`` or a contract's
    reservation, action, and idempotency key, stands for one job's content: a
    retry with the same parameters returns the job already recorded, and one
    with different parameters is refused rather than answered with a job that
    does not run what it asked for.
    """


class JobEngine:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        executors: JobExecutorResolver,
        host_lookup: HostLookup,
        retry_policy: JobRetryPolicy,
        event_recorder: EventRecorder | None = None,
        held_failure_classes: frozenset[str] = frozenset(),
    ) -> None:
        """``held_failure_classes`` are the failure classes an operator can
        repair while a teardown waits for its retry; the family kit names
        none, and a composition takes them from the domains that raise them."""
        self._session_factory = session_factory
        self._event_recorder = event_recorder
        self._held_failure_classes = frozenset(held_failure_classes)
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
        max_retries: int | None = None,
        contract: JobActionRequest | None = None,
        operation_id: str | None = None,
    ) -> JobSubmitResponse:
        """Persist and enqueue a job, deduplicating contracts and request operations.

        A repeated ``operation_id`` or contract identity returns the job it
        already names when the parameters are the same, and raises
        ``JobIdentityConflictError`` when they differ.
        """
        raw_params = dict(params)
        job_id = operation_id or str(uuid.uuid4())
        if max_retries is None:
            max_retries = self._retry_policy.default_max_retries

        with self._session_factory() as db:
            if operation_id is not None:
                existing = db.get(JobRecord, operation_id)
                if existing is not None:
                    return _repeat(existing, raw_params, "operation_id")
            if contract is not None:
                existing = self._contract_job(db, contract)
                if existing is not None:
                    return _repeat(existing, raw_params, "contract identity")
            db.add(JobRecord(
                id=job_id,
                status=JobStatus.queued.value,
                params=raw_params,
                host_id=host_id,
                retry_count=0,
                max_retries=max_retries,
                next_retry_at=None,
                capacity_reservation_id=contract.capacity_reservation_id if contract else None,
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
                    if existing is None:
                        raise
                    return _repeat(existing, raw_params, "operation_id")
                if contract is None:
                    raise
                existing = self._contract_job(db, contract)
                if existing is None:
                    raise
                return _repeat(existing, raw_params, "contract identity")

        await job_queue.enqueue(job_id)
        return JobSubmitResponse(job_id=job_id, status=JobStatus.queued.value)

    @staticmethod
    def _contract_job(db: Session, contract: JobActionRequest) -> JobRecord | None:
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
        now = _utcnow()
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
        capacity_reservation_id: str | None = None,
    ) -> JobListResponse:
        order = {
            "created_at_asc": JobRecord.created_at.asc(),
            "created_at_desc": JobRecord.created_at.desc(),
        }
        with self._session_factory() as db:
            query = db.query(JobRecord)
            if status_filter:
                query = query.filter(JobRecord.status == status_filter)
            if capacity_reservation_id:
                query = query.filter(
                    JobRecord.capacity_reservation_id == capacity_reservation_id
                )
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

    def bound_jobs(
        self, capacity_reservation_id: str, action_kind: str
    ) -> tuple[BoundJob, ...]:
        """Every job bound to a reservation under ``action_kind``, oldest first.

        Unpaginated, unlike the listing, because a caller deciding from them
        needs them all, and only a reservation's own jobs under one action are
        read. Jobs are ordered by creation instant; two created in one instant
        are ordered by their idempotency key, shorter first, so keys numbered
        in sequence under a common prefix (``…:teardown``, ``…:teardown:rerun-1``,
        ``…:teardown:rerun-10``) keep their order.
        """
        with self._session_factory() as db:
            jobs = (
                db.query(JobRecord)
                .filter(
                    JobRecord.capacity_reservation_id == capacity_reservation_id,
                    JobRecord.action_kind == action_kind,
                )
                .order_by(
                    JobRecord.created_at.asc(),
                    func.length(JobRecord.idempotency_key).asc(),
                    JobRecord.idempotency_key.asc(),
                )
                .all()
            )
            return tuple(
                BoundJob(
                    job_id=job.id,
                    status=job.status,
                    never_started=_never_started(job),
                    finished_at=_utc(job.finished_at),
                    failure_class=(job.failure or {}).get("code"),
                )
                for job in jobs
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
                .values(
                    status=JobStatus.cancelled.value,
                    error="Job cancelled by user",
                    finished_at=_utcnow(),
                )
                .execution_options(synchronize_session=False)
            ).rowcount
            if cancelled:
                db.refresh(job)
                self._record_finished(db, job)
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
            if job.next_retry_at and _utcnow() < job.next_retry_at:
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

            # The job runs only against the registered host it names; a job
            # naming none, or a host with no record, fails before any executor
            # runs, because there is no fallback inventory. A stored job names
            # no host when nothing in it identified a physical host.
            if not job.host_id:
                self._fail(
                    db, job,
                    "job names no host, so it cannot be dispatched; submit it again "
                    "naming a registered host",
                    code=NOT_DISPATCHABLE,
                )
                return
            host = self._host_lookup(job.host_id)
            if host is None:
                self._fail(
                    db, job,
                    f"host {job.host_id!r} is not registered; register or import it "
                    "before dispatching work to it",
                    code=NOT_DISPATCHABLE,
                )
                return
            try:
                executor = self._executors.resolve(
                    str(job.offering_mode), str(job.executor_action)
                )
            except UnsupportedExecutorActionError as exc:
                self._fail(db, job, str(exc), code=NOT_DISPATCHABLE)
                return

            loop = asyncio.get_running_loop()

            def report_starting() -> None:
                # Committed before the executor starts anything, and only while
                # the job is still running: unlike a handle, which arrives once
                # the execution already runs, a start reported for a job
                # cancelled since its claim must stop the executor, so it
                # raises. A failed write raises too. Either way nothing is
                # started, and the attempt ends through the internal-error path
                # below, which leaves a cancelled job cancelled.
                if not self._transition(
                    db,
                    job,
                    expected=(JobStatus.running.value,),
                    status=JobStatus.running.value,
                    execution_started_at=_first_start(),
                ):
                    raise JobNotRunningError(
                        f"job {job_id} is {job.status}, so its execution is not started"
                    )

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
                report_starting=report_starting,
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
                    failure=None,
                    logs=outcome.logs,
                    credentials=outcome.credentials,
                )
                if stored:
                    logger.info("Job %s succeeded", job_id)
                return

            message = outcome.error.message
            failure = outcome.error.model_dump(mode="json")
            if job.retry_count < job.max_retries and outcome.error.retryable:
                next_retry_at = _utcnow() + timedelta(
                    seconds=self._retry_policy.delay_seconds(job.retry_count)
                )
                if self._transition(
                    db,
                    job,
                    expected=(JobStatus.running.value,),
                    status=JobStatus.queued.value,
                    error=f"Attempt {job.retry_count + 1} failed: {message}. "
                    f"Retrying at {next_retry_at}",
                    failure=failure,
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
                failure=failure,
                logs=outcome.logs,
            ):
                logger.error("Job %s failed permanently: %s", job_id, message)

        except ConfigurationRefusedError as exc:
            logger.error("Job %s refused by its executor's preparation: %s", job_id, exc)
            self._fail_after_error(
                db, job_id, f"Configuration refused: {exc}", code=CONFIGURATION_REFUSED
            )
        except Exception as exc:
            logger.exception("Unexpected error processing job %s: %s", job_id, exc)
            self._fail_after_error(db, job_id, f"Internal error: {exc}", code=INTERNAL_ERROR)
        finally:
            db.close()

    def _fail_after_error(self, db: Session, job_id: str, message: str, *, code: str) -> None:
        """Fail a job whose attempt raised, unless it has left ``running``.

        A job cancelled meanwhile stays cancelled: ``_fail`` expects ``queued``
        or ``running``.
        """
        try:
            # A failed flush leaves the session in an aborted transaction;
            # roll back so the job can still be marked failed.
            db.rollback()
            job = db.get(JobRecord, job_id)
            if job is not None:
                self._fail(db, job, message, code=code)
        except Exception:
            logger.exception("Failed to mark job %s as failed after an error", job_id)

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
        failure: object = _UNSET,
        logs: object = _UNSET,
        execution_handle: object = _UNSET,
        execution_started_at: object = _UNSET,
        retry_count: object = _UNSET,
        next_retry_at: object = _UNSET,
        credentials: tuple[CredentialEnvelope, ...] = (),
    ) -> bool:
        """Apply a change only if the job is still in one of ``expected``.

        One conditional ``UPDATE``: when another session or process has moved
        the job on (cancelled it, above all) the update matches no row, nothing
        is written, and ``False`` is returned. Credentials are written in the
        same transaction, so they land only with the transition that reports
        them. A transition to a terminal status stamps ``finished_at`` from the
        process's time source in the same statement; every terminal transition
        expects ``queued`` or ``running``, so a job finishes, and is stamped,
        once. ``updated_at`` takes the database's clock and moves on every
        write, so it cannot say when a job finished. ``job`` is reloaded either
        way.
        """
        values: dict[str, object] = {"status": status}
        for name, value in (
            ("result", result),
            ("error", error),
            ("failure", failure),
            ("logs", logs),
            ("execution_handle", execution_handle),
            ("execution_started_at", execution_started_at),
            ("retry_count", retry_count),
            ("next_retry_at", next_retry_at),
        ):
            if value is not _UNSET:
                values[name] = value
        if status in TERMINAL_JOB_STATUSES:
            values["finished_at"] = _utcnow()
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
        if self._event_recorder is not None:
            db.refresh(job)
            if status in TERMINAL_JOB_STATUSES:
                self._record_finished(db, job)
            elif next_retry_at is not _UNSET and failure is not _UNSET:
                self._record_held(db, job)
        db.commit()
        db.refresh(job)
        if status in TERMINAL_JOB_STATUSES:
            self._finished(job.id, status)
        return True

    def _record_finished(self, db: Session, job: JobRecord) -> None:
        if self._event_recorder is None:
            return
        self._event_recorder.record(db, job_finished_draft(
            job_id=job.id,
            status=job.status,
            action=job.action_kind or job.executor_action,
            offering_mode=job.offering_mode,
            capacity_reservation_id=job.capacity_reservation_id,
            host_id=job.host_id,
            retry_count=job.retry_count,
            max_retries=job.max_retries,
            execution_started_at=_utc(job.execution_started_at),
            finished_at=_utc(job.finished_at),
            failure=job.failure,
        ))

    def _record_held(self, db: Session, job: JobRecord) -> None:
        """Record a teardown attempt held for an operator, when its class is one."""
        failure = job.failure or {}
        if (
            self._event_recorder is None
            or job.action_kind != "teardown"
            or failure.get("code") not in self._held_failure_classes
            or job.next_retry_at is None
        ):
            return
        self._event_recorder.record(db, teardown_attempt_held_draft(
            job_id=job.id,
            capacity_reservation_id=job.capacity_reservation_id,
            host_id=job.host_id,
            offering_mode=job.offering_mode,
            failure=dict(failure),
            retry_count=job.retry_count,
            max_retries=job.max_retries,
            retry_at=job.next_retry_at,
        ))

    def _fail(self, db: Session, job: JobRecord, message: str, *, code: str) -> None:
        """Fail a job the engine itself classified, without a retry."""
        if self._transition(
            db,
            job,
            expected=(JobStatus.queued.value, JobStatus.running.value),
            status=JobStatus.failed.value,
            error=message,
            failure=ProvisioningErrorEnvelope(
                code=code, message=message, retryable=False
            ).model_dump(mode="json"),
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
            failure=job.failure,
            retry_count=job.retry_count,
            max_retries=job.max_retries,
            next_retry_at=job.next_retry_at,
            capacity_reservation_id=job.capacity_reservation_id,
            execution_started_at=job.execution_started_at,
            finished_at=job.finished_at,
        )



def _repeat(existing: JobRecord, params: dict[str, Any], identity: str) -> JobSubmitResponse:
    """The job a repeated identity names, provided it asks for the same content."""
    if existing.params != params:
        raise JobIdentityConflictError(
            f"{identity} is already bound to job {existing.id} with different parameters"
        )
    return JobSubmitResponse(job_id=existing.id, status=existing.status)

__all__ = [
    "BoundJob",
    "HostLookup",
    "JobEngine",
    "JobIdentityConflictError",
    "JobNotRunningError",
]
