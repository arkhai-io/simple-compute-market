"""The job engine against a real SQLite database and fake executors."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from compute_provisioning import JobExecutorTable
from compute_provisioning_contracts import CredentialEnvelope, ResultEnvelope
from compute_provisioning.hosts import ConnectionEnvelope, ExecutionHost
from compute_provisioning.jobs import (
    JobFailure,
    JobRetryPolicy,
    JobSuccess,
    JobActionRequest,
    ProvisioningErrorEnvelope,
)
from compute_provisioning.jobs.db import Base as JobsBase
from compute_provisioning.jobs.db import JobCredential, JobRecord
from compute_provisioning.jobs.engine import JobEngine, JobIdentityConflictError

_HOST = ExecutionHost("h1", "default", ConnectionEnvelope(kind="fake", version=1))


class _Queue:
    def __init__(self) -> None:
        self.enqueued: list[str] = []

    async def enqueue(self, job_id: str) -> None:
        self.enqueued.append(job_id)


class _Executor:
    """Reports a handle, then waits for ``release`` before reporting ``outcome``."""

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


def _engine(executor, *, hosts=None, database=None):
    if database is None:
        database = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
    JobsBase.metadata.create_all(database)
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
    other, _ = _engine(executor, database=create_engine(url))
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
