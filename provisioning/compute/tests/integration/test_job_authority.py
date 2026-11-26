"""The job engine against a real SQLite database and fake executors."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from compute_provisioning import JobExecutorTable
from compute_provisioning_contracts import CredentialEnvelope, ResultEnvelope
from compute_provisioning.hosts import ConnectionEnvelope, ExecutionHost
from compute_provisioning.jobs import (
    ConfigurationRefusedError,
    JobFailure,
    JobRetryPolicy,
    JobSuccess,
    JobActionRequest,
    ProvisioningErrorEnvelope,
)
from compute_provisioning.jobs.db import JobCredential, JobRecord
from compute_provisioning.jobs.migrations import BASELINE as JOBS_BASELINE
from compute_provisioning.jobs.migrations import MIGRATIONS as JOBS_MIGRATIONS
from compute_provisioning.jobs.engine import JobEngine, JobIdentityConflictError

_HOST = ExecutionHost("h1", "default", ConnectionEnvelope(kind="fake", version=1))


class _Queue:
    def __init__(self) -> None:
        self.enqueued: list[str] = []

    async def enqueue(self, job_id: str) -> None:
        self.enqueued.append(job_id)


class _Executor:
    """Reports its start, then its handle, as a real executor does on either
    side of starting its execution, then waits for ``release`` before
    reporting ``outcome``."""

    def __init__(self, outcome=None, *, hold: bool = False) -> None:
        self.outcome = outcome or JobSuccess(
            result=ResultEnvelope(offering_mode="fake", result_kind="made", value={"n": 1}),
            credentials=(
                CredentialEnvelope(
                    offering_mode="fake", credential_kind="token", value={"t": "x"}
                ),
            ),
            logs="done",
        )
        self.hold = hold
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.cancelled: list[dict] = []
        self.cancel_requested = asyncio.Event()
        self.runs = 0
        self.handle_before_start = False

    async def execute(self, run):
        self.runs += 1
        run.report_starting()
        if not self.handle_before_start:
            run.report_handle({"pid": 7})
        self.started.set()
        if self.hold:
            await self.release.wait()
        if self.handle_before_start:
            run.report_handle({"pid": 7})
        run.report_logs("partial")
        return self.outcome

    async def cancel(self, handle):
        self.cancelled.append(dict(handle))
        self.cancel_requested.set()


class _GatedStart:
    """Waits at ``gate`` before reporting its start, then spawns only if the
    start was recorded; ``spawned`` says whether it was asked to start."""

    def __init__(self, outcome=None) -> None:
        self.outcome = outcome or JobSuccess(result=None)
        self.at_gate = asyncio.Event()
        self.gate = asyncio.Event()
        self.spawned = False

    async def execute(self, run):
        self.at_gate.set()
        await self.gate.wait()
        run.report_starting()
        self.spawned = True
        return self.outcome

    async def cancel(self, handle):
        raise AssertionError("an execution that never started has no handle to cancel")


class _UnrecordableHandle:
    """Spawns once its start is recorded, then reports a handle whose write
    fails, as a playbook running before its handle is stored does."""

    async def execute(self, run):
        run.report_starting()
        run.report_handle({"pid": object()})
        raise AssertionError("the handle's failed write must end the attempt")

    async def cancel(self, handle):
        pass


def _engine(executor, *, hosts=None, database=None, migrate=True):
    """An engine over ``database``, its job tables built by the package's own
    migrations unless ``migrate`` is false, for a database already built."""
    if database is None:
        database = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
    if migrate:
        with database.begin() as connection:
            for migration in (JOBS_BASELINE, *JOBS_MIGRATIONS):
                migration.apply(connection)
    factory = sessionmaker(bind=database)
    table = JobExecutorTable()
    table.register("fake", "make", executor)
    table.freeze()
    known = {"h1": _HOST} if hosts is None else hosts
    engine = JobEngine(
        factory,
        executors=table,
        host_lookup=known.get,
        retry_policy=JobRetryPolicy(
            default_max_retries=2, backoff_initial_seconds=60, backoff_max_seconds=600
        ),
    )
    return engine, factory


async def _submit(engine, queue, **fields):
    values = dict(offering_mode="fake", action="make", host_id="h1", params={"p": 1})
    values.update(fields)
    return await engine.submit(job_queue=queue, **values)


@pytest.mark.asyncio
async def test_a_success_stores_the_reported_envelopes_and_signals_completion() -> None:
    executor = _Executor()
    engine, factory = _engine(executor)
    finished: list[tuple[str, str]] = []
    engine.add_terminal_observer(lambda job_id, status: finished.append((job_id, status)))
    queue = _Queue()
    job = await _submit(engine, queue)

    waiting = asyncio.create_task(engine.wait_for_terminal(job.job_id, timeout=5))
    await engine.process_job(job.job_id)
    status = await waiting

    assert status.status == "succeeded"
    assert status.host_id == "h1"
    assert status.result.value == {"n": 1}
    assert engine.get_credentials(job.job_id).credentials[0].value == {"t": "x"}
    assert engine.get_logs(job.job_id).logs == "done"
    assert finished == [(job.job_id, "succeeded")]
    with factory() as db:
        assert db.get(JobRecord, job.job_id).execution_handle == {"pid": 7}


@pytest.mark.asyncio
async def test_the_executor_decides_whether_a_failure_is_retried() -> None:
    def failing(retryable: bool) -> _Executor:
        return _Executor(JobFailure(
            error=ProvisioningErrorEnvelope(code="x", message="boom", retryable=retryable),
            logs="failed",
        ))

    engine, _ = _engine(failing(True))
    job = await _submit(engine, _Queue())
    await engine.process_job(job.job_id)
    retried = engine.get_job(job.job_id)
    assert (retried.status, retried.retry_count) == ("queued", 1)
    assert retried.next_retry_at is not None
    assert "Attempt 1 failed: boom" in retried.error

    engine, _ = _engine(failing(False))
    job = await _submit(engine, _Queue())
    await engine.process_job(job.job_id)
    failed = engine.get_job(job.job_id)
    assert failed.status == "failed"
    assert failed.error == "Job failed (non-retryable error): boom"


@pytest.mark.asyncio
async def test_a_job_s_creation_and_retry_are_the_process_source_s_instants(source) -> None:
    """A job is stamped, its retry scheduled and the retry found due by the
    process's time source: the retry is due only once the source reaches it."""
    engine, factory = _engine(_Executor(JobFailure(
        error=ProvisioningErrorEnvelope(code="x", message="boom", retryable=True),
        logs="failed",
    )))
    start = source.now()
    job = await _submit(engine, _Queue())
    await engine.process_job(job.job_id)

    with factory() as db:
        row = db.get(JobRecord, job.job_id)
        assert row.created_at == _naive_utc(start)
        assert row.next_retry_at == _naive_utc(start + 60)

    queue = _Queue()
    source.set(start + 59)
    assert await engine.requeue_due_retries(queue) == 0
    source.set(start + 60)
    assert await engine.requeue_due_retries(queue) == 1
    assert queue.enqueued == [job.job_id]


_REFUSAL = ProvisioningErrorEnvelope(
    code="cleanup_refused",
    message='bm-02: task "Clean attributable bounded scratch and IPC" failed: '
    "cleanup refused a foreign-owned descendant",
    retryable=True,
    details={
        "host": "bm-02", "task": "Clean attributable bounded scratch and IPC", "rc": 1,
        "domain_detail": {"error": "Refusal", "message": "cleanup refused a foreign-owned descendant"},
    },
)


@pytest.mark.asyncio
async def test_a_reclaim_that_exhausts_its_retries_keeps_its_structured_failure(source) -> None:
    """Every attempt keeps the latest failure on the job; the last one fails it."""
    engine, _ = _engine(_Executor(JobFailure(error=_REFUSAL, logs="refused")))
    job = await _submit(engine, _Queue())

    for attempt in (1, 2):
        await engine.process_job(job.job_id)
        retrying = engine.get_job(job.job_id)
        assert (retrying.status, retrying.retry_count) == ("queued", attempt)
        assert retrying.failure == _REFUSAL
        source.set(source.now() + 600)
    await engine.process_job(job.job_id)

    failed = engine.get_job(job.job_id)
    assert failed.status == "failed"
    assert failed.failure == _REFUSAL
    assert failed.error == f"Job failed (max retries exceeded): {_REFUSAL.message}"


@pytest.mark.asyncio
async def test_an_attempt_that_succeeds_after_a_failure_clears_it(source) -> None:
    executor = _Executor(JobFailure(error=_REFUSAL, logs="refused"))
    engine, _ = _engine(executor)
    job = await _submit(engine, _Queue())
    await engine.process_job(job.job_id)
    assert engine.get_job(job.job_id).failure == _REFUSAL

    executor.outcome = JobSuccess(result=None)
    source.set(source.now() + 600)
    await engine.process_job(job.job_id)

    succeeded = engine.get_job(job.job_id)
    assert (succeeded.status, succeeded.error, succeeded.failure) == ("succeeded", None, None)


class _Raising:
    """Raises ``error`` before reporting a start, as a refused preparation does."""

    def __init__(self, error: Exception) -> None:
        self.error = error

    async def execute(self, run):
        raise self.error

    async def cancel(self, handle):
        pass


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error,code,text",
    [
        (ConfigurationRefusedError("relay 'r-1' holds no lease"), "configuration_refused",
         "Configuration refused: relay 'r-1' holds no lease"),
        (RuntimeError("unexpected"), "internal_error", "Internal error: unexpected"),
    ],
    ids=["configuration", "internal"],
)
async def test_a_raising_executor_fails_the_job_with_the_engines_code_and_no_retry(
    error, code, text
) -> None:
    engine, _ = _engine(_Raising(error))
    job = await _submit(engine, _Queue())

    await engine.process_job(job.job_id)

    failed = engine.get_job(job.job_id)
    assert (failed.status, failed.retry_count, failed.error) == ("failed", 0, text)
    assert failed.failure == ProvisioningErrorEnvelope(code=code, message=text, retryable=False)


def test_a_job_recorded_before_failures_were_kept_reads_none() -> None:
    """The migration adds the column and backfills nothing; ``error`` keeps its text."""
    database = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    *earlier, failure = JOBS_MIGRATIONS
    with database.begin() as connection:
        for migration in (JOBS_BASELINE, *earlier):
            migration.apply(connection)
        connection.exec_driver_sql(
            "INSERT INTO ansible_jobs (id, status, params, retry_count, max_retries, error) "
            "VALUES ('j-old', 'failed', '{}', 3, 3, 'Job failed (max retries exceeded): "
            "Playbook failed')"
        )
        failure.apply(connection)
    engine, _ = _engine(_Executor(), database=database, migrate=False)

    old = engine.get_job("j-old")

    assert old.failure is None
    assert old.error == "Job failed (max retries exceeded): Playbook failed"


def _naive_utc(instant: int) -> datetime:
    """An instant as SQLite returns a stored time: UTC with no zone."""
    return datetime.fromtimestamp(instant, timezone.utc).replace(tzinfo=None)


def _instants(factory, job_id: str) -> tuple:
    with factory() as db:
        row = db.get(JobRecord, job_id)
        return row.execution_started_at, row.finished_at, row.execution_handle


def _failing(retryable: bool) -> _Executor:
    return _Executor(JobFailure(
        error=ProvisioningErrorEnvelope(code="x", message="boom", retryable=retryable),
        logs="failed",
    ))


@pytest.mark.asyncio
@pytest.mark.parametrize("refusal", ["no host", "unregistered host", "unsupported action"])
async def test_a_job_refused_before_its_executor_runs_records_no_start_and_its_finish(
    source, refusal
) -> None:
    executor = _Executor()
    engine, factory = _engine(executor, hosts={} if refusal == "unregistered host" else None)
    job = await _submit(
        engine, _Queue(), **({"action": "unknown"} if refusal == "unsupported action" else {})
    )
    if refusal == "no host":
        with factory() as db, db.begin():
            db.get(JobRecord, job.job_id).host_id = None
    source.set(source.now() + 30)

    await engine.process_job(job.job_id)

    assert executor.runs == 0
    status = engine.get_job(job.job_id)
    assert status.status == "failed"
    assert status.execution_started_at is None
    assert status.finished_at == _naive_utc(source.now())
    assert _instants(factory, job.job_id) == (None, _naive_utc(source.now()), None)
    assert (status.failure.code, status.failure.retryable) == ("not_dispatchable", False)
    assert status.failure.message == status.error


@pytest.mark.asyncio
async def test_a_job_whose_execution_started_and_then_failed_records_both(source) -> None:
    engine, factory = _engine(_failing(False))
    job = await _submit(engine, _Queue())

    await engine.process_job(job.job_id)

    status = engine.get_job(job.job_id)
    assert status.status == "failed"
    assert status.execution_started_at == status.finished_at == _naive_utc(source.now())
    assert _instants(factory, job.job_id)[2] == {"pid": 7}


@pytest.mark.asyncio
async def test_a_start_that_cannot_be_recorded_spawns_nothing(tmp_path, source) -> None:
    """The database refuses the start's write, as a failed commit would: the
    report raises, the executor spawns nothing, and the attempt fails."""
    database = create_engine(f"sqlite:///{tmp_path / 'jobs.db'}")
    executor = _GatedStart()
    executor.gate.set()
    engine, _ = _engine(executor, database=database)
    with database.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TRIGGER refuse_start BEFORE UPDATE OF execution_started_at "
            "ON ansible_jobs WHEN NEW.execution_started_at IS NOT NULL "
            "BEGIN SELECT RAISE(ABORT, 'start refused'); END"
        )
    job = await _submit(engine, _Queue())

    await engine.process_job(job.job_id)

    assert executor.spawned is False
    status = engine.get_job(job.job_id)
    assert status.status == "failed"
    assert status.error.startswith("Internal error:")
    assert (status.execution_started_at, status.finished_at) == (
        None, _naive_utc(source.now())
    )


@pytest.mark.asyncio
async def test_a_job_cancelled_between_its_claim_and_its_start_stays_cancelled(
    source,
) -> None:
    executor = _GatedStart()
    engine, _ = _engine(executor)
    job = await _submit(engine, _Queue())

    running = asyncio.create_task(engine.process_job(job.job_id))
    await asyncio.wait_for(executor.at_gate.wait(), timeout=5)
    await engine.cancel_job(job.job_id)
    executor.gate.set()
    await asyncio.wait_for(running, timeout=5)

    assert executor.spawned is False
    status = engine.get_job(job.job_id)
    assert status.status == "cancelled"
    assert status.error == "Job cancelled by user"
    assert (status.execution_started_at, status.finished_at) == (
        None, _naive_utc(source.now())
    )


@pytest.mark.asyncio
async def test_a_retried_job_keeps_its_first_start(source) -> None:
    executor = _failing(True)
    engine, _ = _engine(executor)
    first = source.now()
    job = await _submit(engine, _Queue())
    await engine.process_job(job.job_id)
    assert engine.get_job(job.job_id).finished_at is None

    source.set(first + 60)
    executor.outcome = JobSuccess(result=None)
    assert await engine.requeue_due_retries(_Queue()) == 1
    await engine.process_job(job.job_id)

    status = engine.get_job(job.job_id)
    assert (status.status, status.retry_count) == ("succeeded", 1)
    assert status.execution_started_at == _naive_utc(first)
    assert status.finished_at == _naive_utc(first + 60)


@pytest.mark.asyncio
async def test_a_spawned_job_whose_handle_cannot_be_recorded_keeps_its_start(source) -> None:
    engine, factory = _engine(_UnrecordableHandle())
    job = await _submit(engine, _Queue())

    await engine.process_job(job.job_id)

    status = engine.get_job(job.job_id)
    assert status.status == "failed"
    assert status.error.startswith("Internal error:")
    assert _instants(factory, job.job_id) == (
        _naive_utc(source.now()), _naive_utc(source.now()), None
    )


@pytest.mark.asyncio
async def test_a_terminal_job_s_finish_does_not_move(source) -> None:
    engine, _ = _engine(_Executor())
    finished = source.now()
    job = await _submit(engine, _Queue())
    await engine.process_job(job.job_id)

    source.set(finished + 600)
    refused = await engine.cancel_job(job.job_id)
    await engine.process_job(job.job_id)

    assert refused["status"] == "succeeded"
    status = engine.get_job(job.job_id)
    assert (status.status, status.finished_at) == ("succeeded", _naive_utc(finished))
    assert status.execution_started_at == _naive_utc(finished)


@pytest.mark.asyncio
async def test_a_cancelled_job_stays_cancelled_whatever_its_executor_reports() -> None:
    executor = _Executor(hold=True)
    engine, factory = _engine(executor)
    job = await _submit(engine, _Queue())

    running = asyncio.create_task(engine.process_job(job.job_id))
    await asyncio.wait_for(executor.started.wait(), timeout=5)
    await engine.cancel_job(job.job_id)
    executor.release.set()
    await running

    status = engine.get_job(job.job_id)
    assert status.status == "cancelled"
    assert status.result is None
    assert executor.cancelled == [{"pid": 7}]
    with factory() as db:
        assert db.query(JobCredential).count() == 0


@pytest.mark.asyncio
async def test_a_cancellation_before_the_handle_reaches_the_executor_when_it_arrives() -> None:
    executor = _Executor(hold=True)
    executor.handle_before_start = True
    engine, _ = _engine(executor)
    job = await _submit(engine, _Queue())

    running = asyncio.create_task(engine.process_job(job.job_id))
    await asyncio.wait_for(executor.started.wait(), timeout=5)
    await engine.cancel_job(job.job_id)
    assert executor.cancelled == []
    executor.release.set()
    await running
    await asyncio.wait_for(executor.cancel_requested.wait(), timeout=5)

    assert executor.cancelled == [{"pid": 7}]
    assert engine.get_job(job.job_id).status == "cancelled"


@pytest.mark.asyncio
async def test_a_job_cancelled_while_queued_never_runs() -> None:
    executor = _Executor()
    engine, _ = _engine(executor)
    job = await _submit(engine, _Queue())

    await engine.cancel_job(job.job_id)
    await engine.process_job(job.job_id)

    assert executor.runs == 0
    assert engine.get_job(job.job_id).status == "cancelled"


@pytest.mark.asyncio
async def test_a_job_whose_host_is_not_registered_fails_before_any_executor_runs() -> None:
    executor = _Executor()
    engine, _ = _engine(executor, hosts={})
    job = await _submit(engine, _Queue())

    await engine.process_job(job.job_id)

    assert executor.runs == 0
    status = engine.get_job(job.job_id)
    assert status.status == "failed"
    assert "'h1' is not registered" in status.error
    assert status.failure.code == "not_dispatchable"
    assert (status.retry_count, status.failure.retryable) == (0, False)


@pytest.mark.asyncio
async def test_a_job_naming_no_host_fails_before_any_executor_runs() -> None:
    executor = _Executor()
    engine, factory = _engine(executor)
    job = await _submit(engine, _Queue())
    # A stored job can name no host: nothing in it identified a physical one.
    with factory() as db, db.begin():
        db.get(JobRecord, job.job_id).host_id = None

    await engine.process_job(job.job_id)

    assert executor.runs == 0
    status = engine.get_job(job.job_id)
    assert status.status == "failed"
    assert "job names no host" in status.error
    assert "None" not in status.error


@pytest.mark.asyncio
async def test_submissions_are_deduplicated_by_operation_and_by_contract() -> None:
    engine, _ = _engine(_Executor())
    queue = _Queue()

    first = await _submit(engine, queue, operation_id="op-1")
    again = await _submit(engine, queue, operation_id="op-1")
    with pytest.raises(JobIdentityConflictError, match="different parameters"):
        await _submit(engine, queue, operation_id="op-1", params={"p": 2})

    contract = JobActionRequest(
        capacity_reservation_id="r-1",
        offering_mode="fake",
        action_kind="make",
        idempotency_key="k-1",
    )
    by_contract = await _submit(engine, queue, contract=contract)
    repeated = await _submit(engine, queue, contract=contract)

    assert again.job_id == first.job_id == "op-1"
    assert repeated.job_id == by_contract.job_id
    assert queue.enqueued == ["op-1", by_contract.job_id]


@pytest.mark.asyncio
async def test_a_repeated_contract_identity_with_different_parameters_is_refused() -> None:
    """A contract identity stands for one job's content, as an operation id does:
    a retry naming other parameters is refused, not answered with a job that
    does not run them, and nothing new is recorded or enqueued."""
    engine, factory = _engine(_Executor())
    queue = _Queue()
    contract = JobActionRequest(
        capacity_reservation_id="r-3",
        offering_mode="fake",
        action_kind="make",
        idempotency_key="r-3:make",
    )
    first = await _submit(engine, queue, contract=contract)

    with pytest.raises(JobIdentityConflictError, match="contract identity"):
        await _submit(engine, queue, contract=contract, params={"p": 2})

    assert queue.enqueued == [first.job_id]
    with factory() as db:
        assert db.query(JobRecord).count() == 1
        assert db.get(JobRecord, first.job_id).params == {"p": 1}


def test_a_job_identity_record_carries_no_job_content() -> None:
    """The identity record names who a job acts for; its parameters are submitted
    beside it, so an identity cannot disagree with the job that runs."""
    with pytest.raises(ValueError):
        JobActionRequest(
            capacity_reservation_id="r-4",
                offering_mode="fake",
            action_kind="make",
            idempotency_key="r-4:make",
            parameters={"p": 1},
        )


@pytest.mark.asyncio
async def test_jobs_are_listed_by_the_capacity_reservation_they_serve() -> None:
    """A deal's jobs are found by its capacity reservation, whatever its
    settlement mechanism; an operator's job serves none, and none is recorded."""
    engine, _ = _engine(_Executor())
    queue = _Queue()
    for reservation, operation in (("r-5", "create"), ("r-5", "teardown"), ("r-6", "create")):
        await _submit(
            engine,
            queue,
            contract=JobActionRequest(
                capacity_reservation_id=reservation,
                offering_mode="fake",
                action_kind=operation,
                idempotency_key=f"{reservation}:{operation}",
            ),
        )
    operator_job = await _submit(engine, queue, operation_id="operator-1")

    listed = engine.list_jobs(capacity_reservation_id="r-5")

    assert listed.total == 2
    assert {job.capacity_reservation_id for job in listed.jobs} == {"r-5"}
    assert engine.get_job(operator_job.job_id).capacity_reservation_id is None
    assert engine.list_jobs().total == 4


@pytest.mark.asyncio
async def test_waiting_for_a_job_that_does_not_finish_times_out() -> None:
    engine, _ = _engine(_Executor())
    job = await _submit(engine, _Queue())

    with pytest.raises(TimeoutError):
        await engine.wait_for_terminal(job.job_id, timeout=0.1)
    with pytest.raises(LookupError):
        await engine.wait_for_terminal("missing", timeout=0.1)


@pytest.mark.asyncio
async def test_a_contract_action_runs_as_the_executor_action_it_was_submitted_with() -> None:
    """A contract action (``release``) may run as a different executor action
    (``make``): the job keeps the contract's identity and is routed by the
    executor action."""
    executor = _Executor()
    engine, factory = _engine(executor)
    contract = JobActionRequest(
        capacity_reservation_id="r-2",
        offering_mode="fake",
        action_kind="release",
        idempotency_key="r-2:release",
    )
    job = await _submit(engine, _Queue(), contract=contract)

    await engine.process_job(job.job_id)

    assert executor.runs == 1
    assert engine.get_job(job.job_id).status == "succeeded"
    with factory() as db:
        record = db.get(JobRecord, job.job_id)
        assert record.action_kind == "release"
        assert record.executor_action == "make"



@pytest.mark.asyncio
async def test_a_cancellation_from_another_process_holds_against_a_late_success(tmp_path) -> None:
    """Two engines on one database file stand for two worker processes: one runs
    the job, the other cancels it, and the late success is not applied."""
    url = f"sqlite:///{tmp_path / 'jobs.db'}"
    executor = _Executor(hold=True)
    worker, factory = _engine(executor, database=create_engine(url))
    other, _ = _engine(executor, database=create_engine(url), migrate=False)
    job = await _submit(worker, _Queue())

    running = asyncio.create_task(worker.process_job(job.job_id))
    await asyncio.wait_for(executor.started.wait(), timeout=5)
    await other.cancel_job(job.job_id)
    executor.release.set()
    await running

    assert executor.cancelled == [{"pid": 7}]
    status = worker.get_job(job.job_id)
    assert (status.status, status.result) == ("cancelled", None)
    with factory() as db:
        assert db.query(JobCredential).count() == 0


@pytest.mark.asyncio
async def test_a_transition_from_a_stale_session_does_not_overwrite_a_cancellation(
    tmp_path,
) -> None:
    """The check and the write are one statement: a session that loaded the job
    before another committed its cancellation cannot overwrite it."""
    url = f"sqlite:///{tmp_path / 'jobs.db'}"
    engine, factory = _engine(_Executor(), database=create_engine(url))
    job = await _submit(engine, _Queue())
    with factory() as db:
        db.get(JobRecord, job.job_id).status = "running"
        db.commit()

    stale = factory()
    try:
        loaded = stale.get(JobRecord, job.job_id)
        assert loaded.status == "running"
        await engine.cancel_job(job.job_id)

        applied = engine._transition(
            stale, loaded, expected=("running",), status="succeeded", result=None
        )

        assert applied is False
        assert loaded.status == "cancelled"
    finally:
        stale.close()
    assert engine.get_job(job.job_id).status == "cancelled"
