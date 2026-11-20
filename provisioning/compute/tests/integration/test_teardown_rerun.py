"""A teardown that never started, run again, against real SQLite and a real job engine.

The job-backed provider, the job engine, the fulfillment aggregate and the
release status port share one file-backed database, as in the provisioning
service. The executor is a test double that refuses before reporting its start,
as a codec or inventory refusal does, starts and fails, or starts and succeeds.
Convergence lives in the provisioning service, so each test makes the moves its
watchdog makes, through the same repository transitions: dispatch a
``teardown_dispatch_pending`` row, poll a ``tearing_down`` row's job, and
requeue a ``teardown_failed`` row. Instants are driven by the injected time
source.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from market_core import VersionedEnvelope
from market_fulfillment import (
    CREATE_COMPENSATION,
    FulfillmentOrchestrator,
    ProviderOperationState,
    ProviderRegistry,
    SettlementRecordState,
    SettlementResource,
    SqlAlchemyFulfillmentUnitOfWork,
)
from market_fulfillment.db import SettlementRecord
from market_fulfillment.migrations import BASELINE as FULFILLMENT_BASELINE
from market_fulfillment.settlement_repository import SettlementRepository
from market_resource_pools import ResourcePoolService
from market_resource_pools.db import DEFAULT_POOL_ID, ResourcePool
from market_resource_pools.migrations import BASELINE as POOLS_BASELINE
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from compute_provisioning import JobExecutorTable
from compute_provisioning.hosts import ConnectionEnvelope, ExecutionHost
from compute_provisioning.job_fulfillment import (
    JobFulfillmentProvider,
    PreparedJob,
    job_contract,
)
from compute_provisioning.jobs import (
    JobFailure,
    JobRetryPolicy,
    JobSuccess,
    ProvisioningErrorEnvelope,
)
from compute_provisioning.jobs.db import JobRecord
from compute_provisioning.jobs.engine import JobEngine
from compute_provisioning.jobs.migrations import BASELINE as JOBS_BASELINE
from compute_provisioning.jobs.migrations import MIGRATIONS as JOBS_MIGRATIONS
from compute_provisioning.jobs.submission import JobSubmissionService, contract_operation_id
from compute_provisioning.release import (
    FulfillmentReleaseStatusPort,
    ReleaseProgress,
    compensable,
)
from compute_provisioning.teardown_rerun import TeardownRerunPolicy

_State = SettlementRecordState
_RESERVATION = "r-1"
_FULFILLMENT = "f-1"
_HOST = ExecutionHost("h1", DEFAULT_POOL_ID, ConnectionEnvelope(kind="fake", version=1))
# Reruns wait 60, 120 and 240 seconds after the previous teardown job finished.
_RETRIES = JobRetryPolicy(default_max_retries=0, backoff_initial_seconds=60)


class _Executor:
    """Runs every job as ``mode`` says: ``refuse`` before reporting its start,
    ``fail`` after starting, or ``succeed`` after starting."""

    def __init__(self) -> None:
        self.mode = "succeed"
        self.started = 0

    async def execute(self, run):
        if self.mode == "refuse":
            raise ValueError("refused before the start: the host key cannot be decrypted")
        run.report_starting()
        self.started += 1
        if self.mode == "fail":
            return JobFailure(
                error=ProvisioningErrorEnvelope(code="x", message="playbook failed")
            )
        return JobSuccess(result=None)

    async def cancel(self, handle):
        pass


class _Queue:
    def __init__(self) -> None:
        self.enqueued: list[str] = []

    async def enqueue(self, job_id: str) -> None:
        self.enqueued.append(job_id)


class _Hosts:
    def get_host(self, host_id):
        return SimpleNamespace(host_id=host_id, enabled=True)


class _Plan:
    def prepare_create(self, **kwargs):
        raise AssertionError("no create is prepared here")

    def prepare_teardown(
        self, *, capacity_reservation_id, resource, host_id, executor_target,
        create_parameters, pool_config,
    ):
        return PreparedJob(
            offering_mode="vm",
            action="unmake",
            host_id=host_id,
            executor_target=executor_target,
            parameters={"undo": dict(create_parameters)},
        )


class _PoolHandler:
    provider = "test"

    def read_config(self, db, pool_id):
        return {}

    def read_config_for_execution(self, db, pool_id):
        return {}


class _World:
    def __init__(self, tmp_path, *, limit: int = 3) -> None:
        database = create_engine(
            f"sqlite:///{tmp_path / 'provisioning.db'}",
            connect_args={"check_same_thread": False},
        )
        with database.begin() as connection:
            for migration in (
                POOLS_BASELINE, JOBS_BASELINE, *JOBS_MIGRATIONS, FULFILLMENT_BASELINE
            ):
                migration.apply(connection)
        self.factory = sessionmaker(bind=database)
        with self.factory() as db, db.begin():
            db.add(
                ResourcePool(
                    id=DEFAULT_POOL_ID,
                    label="default",
                    provider="test",
                    policy_tags={"deliverable_modes": ["vm"]},
                )
            )
        self.executor = _Executor()
        table = JobExecutorTable()
        table.register("vm", "make", self.executor)
        table.register("vm", "unmake", self.executor)
        table.freeze()
        self.engine = JobEngine(
            self.factory, executors=table, host_lookup={"h1": _HOST}.get,
            retry_policy=_RETRIES,
        )
        self.queue = _Queue()
        self.policy = TeardownRerunPolicy(teardown_rerun_limit=limit, retry_policy=_RETRIES)
        self.provider = JobFulfillmentProvider(
            plan=_Plan(),
            submission=JobSubmissionService(
                engine=self.engine, hosts=_Hosts(), job_queue_provider=lambda: self.queue
            ),
            jobs=self.engine,
            rerun_policy=self.policy,
        )
        self.repository = SettlementRepository()
        self.orchestrator = FulfillmentOrchestrator(
            provider_registry=ProviderRegistry({"test": self.provider}),
            unit_of_work=SqlAlchemyFulfillmentUnitOfWork(
                self.factory,
                ResourcePoolService(self.factory, {"test": _PoolHandler()}),
                repository=self.repository,
            ),
        )
        self.status_port = FulfillmentReleaseStatusPort(
            settlement_repository=self.repository,
            session_factory=self.factory,
            rerun_policy=self.policy,
            jobs=self.engine,
        )

    async def run_queued(self) -> None:
        while self.queue.enqueued:
            await self.engine.process_job(self.queue.enqueued.pop(0))

    async def created(self, state: str, **fields) -> None:
        """A create job that succeeded, and its aggregate in ``state``."""
        submitted = await JobSubmissionService(
            engine=self.engine, hosts=_Hosts(), job_queue_provider=lambda: self.queue
        ).submit(
            offering_mode="vm", action="make", host_id="h1", params={"size": 1},
            contract=job_contract(_RESERVATION, "create", "vm"),
        )
        await self.run_queued()
        with self.factory() as db, db.begin():
            db.add(
                SettlementRecord(
                    capacity_reservation_id=_RESERVATION,
                    fulfillment_id=_FULFILLMENT,
                    market="vms",
                    scheduling_requirements={"offering_mode": "vm", "resource_kind": "vm"},
                    settlement_resource_id="s-1",
                    pool_id=DEFAULT_POOL_ID,
                    provider="test",
                    resource_host_id="h1",
                    provider_metadata={
                        "create_job_id": submitted.job_id,
                        "current_job_id": submitted.job_id,
                        "operation": "create",
                        "host_id": "h1",
                        "executor_target": "guest-r-1",
                    },
                    state=state,
                    **fields,
                )
            )

    def record(self) -> SettlementRecord:
        with self.factory() as db:
            record = self.repository.get(db, _RESERVATION)
            db.expunge(record)
            return record

    def transition(self, state: str, **updates) -> None:
        with self.factory() as db, db.begin():
            self.repository.transition(db, _RESERVATION, state, **updates)

    async def dispatch(self) -> str:
        """Convergence's dispatch of a ``teardown_dispatch_pending`` row."""
        record = self.record()
        assert record.state == _State.teardown_dispatch_pending.value
        result = await self.provider.dispatch_teardown(
            VersionedEnvelope.model_validate(record.prepared_teardown_operation)
        )
        self.transition(
            _State.tearing_down.value,
            teardown_provider_metadata=dict(result.provider_metadata),
        )
        return result.provider_metadata["teardown_job_id"]

    async def poll(self) -> ProviderOperationState:
        """Convergence's poll of a ``tearing_down`` row's job, applying its
        outcome as the watchdog does, a compensation's reason kept."""
        record = self.record()
        status = await self.provider.get_status(
            _RESERVATION,
            SettlementResource(
                settlement_resource_id="s-1", pool_id=DEFAULT_POOL_ID, offering_mode="vm",
                resource_kind="vm", provider="test", host_id="h1",
            ),
            dict(record.teardown_provider_metadata),
        )
        if status.state is ProviderOperationState.succeeded:
            self.transition(_State.torn_down.value)
        elif status.state is ProviderOperationState.failed:
            reason = (
                CREATE_COMPENSATION
                if record.failure_reason == CREATE_COMPENSATION
                else "provider_reported_failure"
            )
            self.transition(
                _State.teardown_failed.value,
                failure_reason=reason,
                failure_message=status.detail,
            )
        return status.state

    def requeue(self) -> None:
        self.transition(_State.teardown_dispatch_pending.value)

    def progress(self):
        return self.status_port.get_status(_FULFILLMENT)

    def teardown_keys(self) -> list[str]:
        with self.factory() as db:
            return sorted(
                job.idempotency_key
                for job in db.query(JobRecord).filter(JobRecord.action_kind == "teardown")
            )


def _rerun_job_id(n: int) -> str:
    return contract_operation_id(job_contract(_RESERVATION, "teardown", "vm", rerun=n))


async def _failed_without_starting(world: _World) -> None:
    """An active fulfillment whose first teardown job is refused before its start."""
    await world.created(_State.active.value)
    await world.orchestrator.begin_fulfillment_teardown(_FULFILLMENT)
    world.executor.mode = "refuse"
    await world.dispatch()
    await world.run_queued()
    assert await world.poll() is ProviderOperationState.failed


@pytest.mark.asyncio
async def test_a_teardown_that_never_started_waits_then_runs_again(tmp_path, source) -> None:
    world = _World(tmp_path)
    finished = source.now()
    await _failed_without_starting(world)
    first = world.record().teardown_provider_metadata["teardown_job_id"]
    assert world.progress().progress is ReleaseProgress.TEARING_DOWN

    # Before the delay: the dispatch adopts the failed job, submitting nothing.
    source.set(finished + 59)
    world.requeue()
    assert world.progress().progress is ReleaseProgress.TEARING_DOWN
    assert await world.dispatch() == first
    assert world.queue.enqueued == []
    assert await world.poll() is ProviderOperationState.failed
    assert world.progress().progress is ReleaseProgress.TEARING_DOWN

    # At the delay: rerun 1, of the same prepared teardown.
    source.set(finished + 60)
    world.requeue()
    assert await world.dispatch() == _rerun_job_id(1)
    assert world.teardown_keys() == ["r-1:teardown", "r-1:teardown:rerun-1"]
    metadata = world.record().teardown_provider_metadata
    assert metadata["current_job_id"] == metadata["teardown_job_id"] == _rerun_job_id(1)
    assert metadata["create_job_id"] == world.record().provider_metadata["create_job_id"]
    assert world.engine.get_job(_rerun_job_id(1)).params == world.engine.get_job(first).params
    assert world.progress().progress is ReleaseProgress.TEARING_DOWN


@pytest.mark.asyncio
async def test_a_dispatch_repeated_after_an_unrecorded_rerun_adopts_it(tmp_path, source) -> None:
    world = _World(tmp_path)
    finished = source.now()
    await _failed_without_starting(world)
    source.set(finished + 60)
    world.requeue()
    prepared = VersionedEnvelope.model_validate(world.record().prepared_teardown_operation)

    # A dispatch that submitted rerun 1 and stopped before recording it.
    submitted = await world.provider.dispatch_teardown(prepared)
    again = await world.dispatch()

    assert submitted.provider_metadata["teardown_job_id"] == again == _rerun_job_id(1)
    assert world.teardown_keys() == ["r-1:teardown", "r-1:teardown:rerun-1"]
    assert world.queue.enqueued == [_rerun_job_id(1)]


@pytest.mark.asyncio
async def test_a_rerun_that_succeeds_tears_the_fulfillment_down(tmp_path, source) -> None:
    world = _World(tmp_path)
    finished = source.now()
    await _failed_without_starting(world)
    source.set(finished + 60)
    world.requeue()
    await world.dispatch()

    world.executor.mode = "succeed"
    await world.run_queued()

    assert await world.poll() is ProviderOperationState.succeeded
    assert world.progress().progress is ReleaseProgress.TORN_DOWN


@pytest.mark.asyncio
async def test_a_teardown_whose_execution_started_is_adopted_and_never_run_again(
    tmp_path, source
) -> None:
    world = _World(tmp_path)
    await world.created(_State.active.value)
    await world.orchestrator.begin_fulfillment_teardown(_FULFILLMENT)
    world.executor.mode = "fail"
    first = await world.dispatch()
    await world.run_queued()
    await world.poll()

    source.set(source.now() + 86400)
    status = world.progress()
    world.requeue()

    assert (status.progress, status.reason) == (ReleaseProgress.FAILED, "teardown_failed")
    assert "never started" not in status.error
    assert await world.dispatch() == first
    assert world.teardown_keys() == ["r-1:teardown"]


@pytest.mark.asyncio
async def test_a_cancelled_teardown_job_is_not_run_again(tmp_path, source) -> None:
    world = _World(tmp_path)
    await world.created(_State.active.value)
    await world.orchestrator.begin_fulfillment_teardown(_FULFILLMENT)
    first = await world.dispatch()
    await world.engine.cancel_job(first)
    world.queue.enqueued.clear()
    await world.poll()

    source.set(source.now() + 86400)
    world.requeue()

    assert await world.dispatch() == first
    assert world.teardown_keys() == ["r-1:teardown"]


@pytest.mark.asyncio
async def test_spent_reruns_report_the_teardown_failed_saying_it_never_started(
    tmp_path, source
) -> None:
    world = _World(tmp_path, limit=1)
    finished = source.now()
    await _failed_without_starting(world)
    source.set(finished + 60)
    world.requeue()
    await world.dispatch()
    await world.run_queued()
    await world.poll()

    source.set(finished + 86400)
    status = world.progress()
    world.requeue()

    assert (status.progress, status.reason) == (ReleaseProgress.FAILED, "teardown_failed")
    assert "never started" in status.error and "1 rerun(s) were spent" in status.error
    assert await world.dispatch() == _rerun_job_id(1)
    assert world.teardown_keys() == ["r-1:teardown", "r-1:teardown:rerun-1"]


@pytest.mark.asyncio
async def test_a_compensating_teardown_runs_again_and_keeps_its_reason(
    tmp_path, source
) -> None:
    world = _World(tmp_path)
    finished = source.now()
    await world.created(
        _State.failed.value,
        failure_reason="provider_reported_failure",
        failure_message="create failed",
    )
    await world.orchestrator.begin_compensating_teardown(
        _FULFILLMENT,
        authorize=lambda c: compensable(c.state, c.failure_reason, c.provider_metadata),
    )
    world.executor.mode = "refuse"
    await world.dispatch()
    await world.run_queued()
    await world.poll()
    assert world.record().failure_reason == CREATE_COMPENSATION
    assert world.progress().progress is ReleaseProgress.TEARING_DOWN

    source.set(finished + 60)
    world.requeue()

    assert await world.dispatch() == _rerun_job_id(1)
    assert world.record().failure_reason == CREATE_COMPENSATION


def test_teardown_jobs_created_in_one_instant_are_read_in_their_keys_sequence(
    tmp_path, source
) -> None:
    """Inserted out of order under one held instant, and with keys whose
    alphabetical order differs from their sequence."""
    world = _World(tmp_path)
    keys = [f"r-1:teardown:rerun-{n}" for n in (10, 9, 2)] + ["r-1:teardown"]
    with world.factory() as db, db.begin():
        for key in keys:
            db.add(
                JobRecord(
                    id=key, status="failed", params={}, capacity_reservation_id="r-1",
                    action_kind="teardown", idempotency_key=key,
                )
            )

    jobs = world.engine.bound_jobs("r-1", "teardown")

    assert [job.job_id for job in jobs] == [
        "r-1:teardown", "r-1:teardown:rerun-2", "r-1:teardown:rerun-9",
        "r-1:teardown:rerun-10",
    ]


@pytest.mark.parametrize("handle", [None, {"pid": 7}], ids=["no handle", "a handle"])
def test_a_job_finished_before_its_instants_were_recorded_never_reads_never_started(
    tmp_path, source, handle
) -> None:
    """The teardown-job read classifies a failed job with no ``finished_at``
    as not never-started, whether or not it records a handle; one recording
    its finish and neither a start nor a handle never started."""
    world = _World(tmp_path)
    recorded = datetime(2026, 11, 18, 12, 0)
    with world.factory() as db, db.begin():
        for key, finished in (("r-1:teardown", None), ("r-1:teardown:rerun-1", recorded)):
            db.add(
                JobRecord(
                    id=key, status="failed", params={}, capacity_reservation_id="r-1",
                    action_kind="teardown", idempotency_key=key, execution_handle=handle,
                    finished_at=finished,
                )
            )
        db.add(
            JobRecord(
                id="other", status="failed", params={}, capacity_reservation_id="r-1",
                action_kind="create", idempotency_key="r-1:create",
            )
        )

    jobs = world.engine.bound_jobs("r-1", "teardown")

    assert [job.job_id for job in jobs] == ["r-1:teardown", "r-1:teardown:rerun-1"]
    assert [job.never_started for job in jobs] == [False, handle is None]
    assert jobs[1].finished_at == recorded.replace(tzinfo=timezone.utc)
