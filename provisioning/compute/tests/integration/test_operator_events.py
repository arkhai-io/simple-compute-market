"""Compute provisioning records its operator events in the transitions they report.

Library integration over one SQLite database, as the provisioning service
shares one: the job engine with stand-in executors, and the lease lifecycle
over the real site ledger, with the release decision and status ports standing
in for the fulfillment aggregate. The tables are built by the pool and site
baselines, the package's job migrations, and the eventing component's own
schema steps.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import injected_time
import pytest
from eventing import SCHEMA_STEPS, Catalogue, EventReader, Recorder, Reference, Source
from market_resource_pools.migrations import BASELINE as POOLS_BASELINE
from market_site.authority import LedgerSiteAuthority
from market_site.db import CapacityReservation
from market_site.events import SITE_KINDS
from market_site.ledger import CapacityLedgerService
from market_site.migrations import BASELINE as SITE_BASELINE
from market_site.migrations import MIGRATIONS as SITE_MIGRATIONS
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from compute_provisioning import JobExecutorTable
from compute_provisioning.hosts import ConnectionEnvelope, ExecutionHost
from compute_provisioning.jobs import (
    JobActionRequest,
    JobFailure,
    JobRetryPolicy,
    JobSuccess,
    ProvisioningErrorEnvelope,
)
from compute_provisioning.jobs.engine import JobEngine
from compute_provisioning.jobs.migrations import BASELINE as JOBS_BASELINE
from compute_provisioning.jobs.migrations import MIGRATIONS as JOBS_MIGRATIONS
from compute_provisioning.lease_lifecycle import LeaseLifecycleService
from compute_provisioning.operator_events import PROVISIONING_KINDS
from compute_provisioning.release import ReleaseProgress, ReleaseStatus

_HOST = ExecutionHost("bm-02", "default", ConnectionEnvelope(kind="fake", version=1))
LEASE = "cr-fixture"

_REFUSAL = ProvisioningErrorEnvelope(
    code="cleanup_refused",
    message='bm-02: task "Clean attributable bounded scratch and IPC" failed: '
    "cleanup refused a foreign-owned descendant",
    retryable=True,
    details={"host": "bm-02", "task": "Clean attributable bounded scratch and IPC", "rc": 1},
)
_TIMEOUT = ProvisioningErrorEnvelope(
    code="timed_out", message="bm-02: the playbook timed out", retryable=True
)


class _Queue:
    async def enqueue(self, job_id: str) -> None:
        return None


class _Executor:
    """Reports its start, lets ``runs_for`` seconds of the source's time pass,
    then reports ``outcome``."""

    def __init__(self, outcome, *, runs_for: int = 0) -> None:
        self.outcome = outcome
        self.runs_for = runs_for

    async def execute(self, run):
        run.report_starting()
        if self.runs_for:
            installed = injected_time.installed()
            installed.set(installed.now() + self.runs_for)
        return self.outcome

    async def cancel(self, handle):
        return None


@pytest.fixture
def database(source):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    with engine.begin() as connection:
        for migration in (
            POOLS_BASELINE, SITE_BASELINE, *SITE_MIGRATIONS, JOBS_BASELINE, *JOBS_MIGRATIONS
        ):
            migration.apply(connection)
        for step in SCHEMA_STEPS:
            step.apply(connection)
    yield sessionmaker(bind=engine)
    engine.dispose()


@pytest.fixture
def recorder() -> Recorder:
    return Recorder(
        Catalogue((*SITE_KINDS, *PROVISIONING_KINDS), schema_prefix="urn:arkhai:event"),
        source=Source(service="compute-provisioning", instance="fixture"),
        clock=injected_time.now_datetime,
    )


def _engine(sessions, recorder, executor, *, max_retries: int = 2) -> JobEngine:
    table = JobExecutorTable()
    table.register("bare_metal", "reclaim", executor)
    table.register("vm", "create", executor)
    table.freeze()
    return JobEngine(
        sessions,
        executors=table,
        host_lookup={"bm-02": _HOST}.get,
        retry_policy=JobRetryPolicy(
            default_max_retries=max_retries, backoff_initial_seconds=60, backoff_max_seconds=600
        ),
        event_recorder=recorder,
        held_failure_classes=frozenset({"cleanup_refused"}),
    )


async def _teardown(engine, *, key: str = "teardown") -> str:
    submitted = await engine.submit(
        offering_mode="bare_metal", action="reclaim", host_id="bm-02", params={"p": 1},
        job_queue=_Queue(),
        contract=JobActionRequest(
            capacity_reservation_id=LEASE, offering_mode="bare_metal",
            action_kind="teardown", idempotency_key=f"{LEASE}:{key}",
        ),
    )
    return submitted.job_id


def _events(sessions, kind: str | None = None, **filters):
    return EventReader(sessions).events(kind=kind, limit=500, **filters)


# --- The job engine ------------------------------------------------------


@pytest.mark.asyncio
async def test_a_refused_cleanup_that_is_retried_records_the_attempt_held(database, recorder, source):
    engine = _engine(database, recorder, _Executor(JobFailure(error=_REFUSAL, logs="refused")),
                     max_retries=3)
    job_id = await _teardown(engine)

    await engine.process_job(job_id)

    (held,) = _events(database, "provisioning.teardown_attempt_held")
    retry_at = engine.get_job(job_id).next_retry_at.replace(tzinfo=timezone.utc)
    assert held.subject == Reference(type="job", id=job_id)
    assert set(held.related) == {Reference(type="lease", id=LEASE), Reference(type="host", id="bm-02")}
    assert held.severity.value == "action_required"
    assert held.attributes == {
        "failure_class": "cleanup_refused",
        "retry_at": retry_at.isoformat().replace("+00:00", "Z"),
        "retries_left": 2,
        "offering_mode": "bare_metal",
    }
    assert held.details["task"] == "Clean attributable bounded scratch and IPC"
    assert held.details["retry_count"] == 1
    assert _events(database, "provisioning.job_finished") == []


@pytest.mark.asyncio
async def test_a_teardown_attempt_failing_with_a_class_not_repairable_records_no_hold(
    database, recorder, source
):
    engine = _engine(database, recorder, _Executor(JobFailure(error=_TIMEOUT, logs="timeout")))
    job_id = await _teardown(engine)

    await engine.process_job(job_id)

    assert engine.get_job(job_id).status == "queued"
    assert _events(database, "provisioning.teardown_attempt_held") == []


@pytest.mark.asyncio
async def test_a_long_job_records_its_finish_with_its_duration(database, recorder, source):
    engine = _engine(database, recorder, _Executor(JobSuccess(result=None), runs_for=2832))
    submitted = await engine.submit(
        offering_mode="vm", action="create", host_id="bm-02", params={"p": 1}, job_queue=_Queue(),
    )

    await engine.process_job(submitted.job_id)

    (finished,) = _events(database, "provisioning.job_finished")
    assert finished.severity.value == "info"
    assert finished.attributes == {
        "status": "succeeded",
        "action": "create",
        "offering_mode": "vm",
        "duration_seconds": 2832,
        "failure_class": None,
        "operator_job": True,
    }


@pytest.mark.asyncio
async def test_a_job_that_exhausts_its_retries_records_its_finish_as_a_warning(
    database, recorder, source
):
    engine = _engine(database, recorder, _Executor(JobFailure(error=_REFUSAL, logs="refused")),
                     max_retries=0)
    job_id = await _teardown(engine)

    await engine.process_job(job_id)

    (finished,) = _events(database, "provisioning.job_finished",
                          reference=Reference(type="lease", id=LEASE))
    assert finished.severity.value == "warning"
    assert finished.attributes["failure_class"] == "cleanup_refused"
    assert finished.attributes["operator_job"] is False
    assert finished.details["failure"]["code"] == "cleanup_refused"
    assert _events(database, "provisioning.teardown_attempt_held") == []


class _Raising:
    async def execute(self, run):
        raise RuntimeError("connection string postgresql://operator:fixture-secret@db")

    async def cancel(self, handle):
        return None


@pytest.mark.asyncio
async def test_an_engine_classified_failure_reports_its_class_and_not_its_text(
    database, recorder, source
):
    engine = _engine(database, recorder, _Raising())
    job_id = await _teardown(engine)

    await engine.process_job(job_id)

    assert "fixture-secret" in engine.get_job(job_id).error
    (finished,) = _events(database, "provisioning.job_finished")
    assert finished.details["failure"] == {"code": "internal_error", "retryable": False}
    assert "fixture-secret" not in finished.model_dump_json()


@pytest.mark.asyncio
async def test_a_cancelled_job_records_its_finish_with_no_class(database, recorder, source):
    engine = _engine(database, recorder, _Executor(JobSuccess(result=None)))
    job_id = await _teardown(engine)

    await engine.cancel_job(job_id)

    (finished,) = _events(database, "provisioning.job_finished")
    assert (finished.attributes["status"], finished.attributes["failure_class"]) == ("cancelled", None)
    assert finished.attributes["duration_seconds"] is None


# --- The lease lifecycle -------------------------------------------------


class _Decision:
    async def submit_release(self, reservation):
        raise AssertionError("a releasing lease is not decided again")

    async def begin_teardown(self, fulfillment_id):
        raise AssertionError("no teardown begins here")


class _Status:
    def __init__(self, status: ReleaseStatus, before=None) -> None:
        self.status = status
        self.before = before

    def get_status(self, fulfillment_id):
        if self.before is not None:
            self.before()
        return self.status


def _lifecycle(
    sessions, recorder, engine, status: _Status, *, deliver_events=None
) -> tuple[LeaseLifecycleService, CapacityLedgerService]:
    ledger = CapacityLedgerService(sessions, site_id="fixture-site", event_recorder=recorder)
    settings = type("Settings", (), {"lease_watchdog_grace_period_seconds": 3600})()
    return LeaseLifecycleService(
        settings, LedgerSiteAuthority(ledger),
        release_executor=_Decision(), release_status=status, jobs=engine,
        deliver_events=deliver_events,
    ), ledger


def _releasing(sessions, *, requested_at: datetime) -> None:
    with sessions() as db, db.begin():
        db.add(CapacityReservation(
            capacity_reservation_id=LEASE, state="releasing", offering_mode="bare_metal",
            release_job_id="fulfillment-1", release_requested_at=requested_at.isoformat(),
        ))


@pytest.mark.asyncio
async def test_a_teardown_failed_by_a_refused_cleanup_records_the_lease_release_failed(
    database, recorder, source
):
    engine = _engine(database, recorder, _Executor(JobFailure(error=_REFUSAL, logs="refused")),
                     max_retries=0)
    job_id = await _teardown(engine)
    await engine.process_job(job_id)
    _releasing(database, requested_at=injected_time.now_datetime())
    lifecycle, ledger = _lifecycle(database, recorder, engine, _Status(
        ReleaseStatus(ReleaseProgress.FAILED, reason="teardown_failed", error="teardown failed")
    ))

    await lifecycle.force_check_leases()

    assert ledger.get_reservation(LEASE)["state"] == "release_failed"
    (failed,) = _events(database, "provisioning.lease_release_failed")
    assert failed.subject == Reference(type="lease", id=LEASE)
    assert failed.severity.value == "action_required"
    assert failed.attributes == {
        "reason": "teardown_failed", "failure_class": "cleanup_refused", "offering_mode": "bare_metal",
    }
    assert failed.details["release_handle"] == "fulfillment-1"
    assert failed.details["teardown_job_id"] == job_id
    lease_events = [e.kind for e in _events(database, reference=Reference(type="lease", id=LEASE))]
    assert lease_events == ["provisioning.job_finished", "site.lease_ended",
                            "provisioning.lease_release_failed"]


@pytest.mark.asyncio
async def test_a_lease_whose_teardown_times_out_records_the_lease_release_failed(
    database, recorder, source
):
    engine = _engine(database, recorder, _Executor(JobSuccess(result=None)))
    _releasing(database, requested_at=injected_time.now_datetime() - timedelta(seconds=3601))
    lifecycle, ledger = _lifecycle(database, recorder, engine, _Status(
        ReleaseStatus(ReleaseProgress.TEARING_DOWN)
    ))

    await lifecycle.force_check_leases()
    await lifecycle.force_check_leases()

    assert ledger.get_reservation(LEASE)["state"] == "release_failed"
    (failed,) = _events(database, "provisioning.lease_release_failed")
    assert failed.attributes["reason"] == "teardown_timeout"
    assert failed.details["teardown_job_id"] is None


@pytest.mark.asyncio
async def test_a_stale_release_failure_is_refused_and_records_no_event(database, recorder, source):
    engine = _engine(database, recorder, _Executor(JobSuccess(result=None)))
    _releasing(database, requested_at=injected_time.now_datetime())
    ledger_for_operator = CapacityLedgerService(database, site_id="fixture-site", event_recorder=recorder)
    # The operator force-releases the lease after the lifecycle read it as releasing.
    status = _Status(
        ReleaseStatus(ReleaseProgress.FAILED, reason="teardown_failed", error="teardown failed"),
        before=lambda: ledger_for_operator.release(capacity_reservation_id=LEASE, forced=True),
    )
    lifecycle, ledger = _lifecycle(database, recorder, engine, status)

    await lifecycle.force_check_leases()

    assert ledger.get_reservation(LEASE)["state"] == "force_released"
    assert _events(database, "provisioning.lease_release_failed") == []
    assert [e.kind for e in _events(database, "site.capacity_released")] == ["site.capacity_released"]


@pytest.mark.asyncio
async def test_a_release_asks_for_delivery_once_its_events_are_committed(database, recorder, source):
    """What the storefront's consumers deliver is recorded, its transition's
    session closed, by the time the lifecycle asks for it to be delivered."""
    engine = _engine(database, recorder, _Executor(JobSuccess(result=None)))
    _releasing(database, requested_at=injected_time.now_datetime())
    seen: list[list[str]] = []

    async def deliver_events():
        seen.append([e.kind for e in _events(database, reference=Reference(type="lease", id=LEASE))])

    lifecycle, ledger = _lifecycle(database, recorder, engine, _Status(
        ReleaseStatus(ReleaseProgress.TORN_DOWN)
    ), deliver_events=deliver_events)

    await lifecycle.force_check_leases()

    assert ledger.get_reservation(LEASE)["state"] == "released"
    assert seen == [["site.lease_ended", "site.capacity_released"]]
