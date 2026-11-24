"""A lease's release follows its fulfillment, over the real API.

Bare-metal deals are set up as production sets them up, through scheduling
and ``begin``, which dispatches the grant through the bare-metal mock. Leases
are expired through the site's truncation and released by the lease watchdog's
cycle, through the canonical clients. Where a test does not step fulfillment
convergence, it sets the state convergence would leave; a failed create's
compensation is stepped through convergence, cycle by cycle, while the
convergence timer is held.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import injected_time
import pytest
from arkhai_bare_metal import NODE_GRANT_ACCESS_ACTION, NODE_RECLAIM_ACCESS_ACTION
from compute_provisioning.hosts.db import Host
from injected_time import InjectedTime
from market_fulfillment import CREATE_COMPENSATION, SettlementRecord, SettlementRecordState

from bare_metal_provisioning_adapter.services.mock_output import (
    bare_metal_mock_output,
    shipped_output,
)
from compute_provisioning.jobs.db import JobRecord
from compute_provisioning_ansible import SSH_CONNECTION_VERSION, MockAnsibleRunner
from compute_provisioning.lease_lifecycle import LeaseLifecycleService
from compute_provisioning.release import (
    FulfillmentReleaseExecutor,
    FulfillmentReleaseStatusPort,
    FulfillmentServiceTeardownPort,
)
from compute_provisioning_contracts import LeaseRetryRelease, LeaseState, LeaseTermination
from market_fulfillment import FulfillmentOrchestrator, SettlementRepository
from compute_provisioning_service import container as _container_module

from .bare_metal_deal import (
    HOST_ID,
    PHYSICAL_HOST_ID,
    SSH_HOST,
    bare_metal_capacity,
    begin,
    begun_bare_metal_deal,
    committed_reservation,
    create_job_id,
    schedule,
)

_State = SettlementRecordState


@pytest.fixture
def bare_metal_runner():
    return MockAnsibleRunner(default_output=bare_metal_mock_output)


def _aggregate_state(capacity_reservation_id: str) -> str:
    with _container_module.resolved_session_factory() as db:
        return db.get(SettlementRecord, capacity_reservation_id).state


def _converge(capacity_reservation_id: str, state: SettlementRecordState) -> None:
    """Leave the aggregate where fulfillment convergence would."""
    with _container_module.resolved_session_factory() as db, db.begin():
        db.get(SettlementRecord, capacity_reservation_id).state = state.value


async def _expire(clients, capacity_reservation_id: str) -> None:
    await clients.site.truncate_lease(
        capacity_reservation_id=capacity_reservation_id,
        lease_end_utc=(datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(),
    )


async def _granted(clients, escrow_uid: str) -> tuple[str, str]:
    """A delivered bare-metal deal: the grant ran, and the aggregate is active."""
    capacity_reservation_id, fulfillment_id = await begun_bare_metal_deal(clients, escrow_uid)
    finished = await _container_module.resolved_job_engine.wait_for_terminal(
        create_job_id(capacity_reservation_id), timeout=5.0
    )
    assert finished.status == "succeeded", finished.error
    _converge(capacity_reservation_id, _State.active)
    return capacity_reservation_id, fulfillment_id


async def test_a_bare_metal_lease_expires_through_its_fulfillment(client_and_queue):
    clients, _ = client_and_queue
    capacity_reservation_id, fulfillment_id = await _granted(clients, "escrow-bm-expiry")
    await _expire(clients, capacity_reservation_id)

    await clients.family.check_leases()

    releasing = await clients.family.get_lease(capacity_reservation_id)
    assert (releasing.status, releasing.release_job_id) == (
        LeaseState.RELEASING,
        fulfillment_id,
    )
    assert _aggregate_state(capacity_reservation_id) == _State.teardown_dispatch_pending.value

    _converge(capacity_reservation_id, _State.torn_down)
    await clients.family.check_leases()

    assert (await clients.family.get_lease(capacity_reservation_id)).status == (
        LeaseState.RELEASED
    )


async def test_a_lease_whose_fulfillment_never_began_is_released_directly(client_and_queue):
    clients, _ = client_and_queue
    await bare_metal_capacity(clients)
    capacity_reservation_id = committed_reservation("escrow-bm-never")
    await schedule(clients, capacity_reservation_id)
    await _expire(clients, capacity_reservation_id)

    await clients.family.check_leases()

    assert (await clients.family.get_lease(capacity_reservation_id)).status == (
        LeaseState.RELEASED
    )
    assert _aggregate_state(capacity_reservation_id) == _State.abandoned.value


async def test_a_lease_terminated_while_its_grant_is_in_flight_waits_then_tears_down(
    client_and_queue, test_client, bare_metal_runner
):
    clients, job_queue = client_and_queue
    await test_client.add_bare_metal_mock_rule(
        rule_id="grant-gate",
        match={"action": NODE_GRANT_ACCESS_ACTION, "host_id": HOST_ID},
        pause_before_result=True,
    )
    await bare_metal_capacity(clients)
    capacity_reservation_id = committed_reservation("escrow-bm-inflight")
    await schedule(clients, capacity_reservation_id)
    fulfillment_id = await begin(clients, capacity_reservation_id, "escrow-bm-inflight")
    await asyncio.wait_for(bare_metal_runner.rules.wait_until_held("grant-gate"), timeout=5.0)
    assert _aggregate_state(capacity_reservation_id) == _State.dispatching.value

    terminated = await clients.family.terminate_lease(capacity_reservation_id, LeaseTermination())
    await clients.family.check_leases()

    assert (terminated.status, terminated.release_job_id) == (
        LeaseState.RELEASING,
        fulfillment_id,
    )
    assert _aggregate_state(capacity_reservation_id) == _State.dispatching.value

    await test_client.resume_bare_metal_rule("grant-gate")
    await _container_module.resolved_job_engine.wait_for_terminal(
        create_job_id(capacity_reservation_id), timeout=5.0
    )
    _converge(capacity_reservation_id, _State.active)
    await clients.family.check_leases()

    assert _aggregate_state(capacity_reservation_id) == _State.teardown_dispatch_pending.value
    assert (await clients.family.get_lease(capacity_reservation_id)).status == (
        LeaseState.RELEASING
    )
    await asyncio.wait_for(job_queue.wait_until_idle(), timeout=5.0)


async def test_the_site_refuses_to_free_a_delivered_lease(client_and_queue):
    """Whoever asks, the site frees capacity only on fulfillment's proof: a
    storefront's or an operator's direct release of a delivered lease changes
    nothing, and the lease is released only through its lifecycle."""
    clients, _ = client_and_queue
    capacity_reservation_id, _ = await _granted(clients, "escrow-bm-delivered")

    released = await clients.site.release(capacity_reservation_id=capacity_reservation_id)

    assert released is None
    assert (await clients.family.get_lease(capacity_reservation_id)).status == LeaseState.ACTIVE


def _aggregate(capacity_reservation_id: str) -> SettlementRecord:
    with _container_module.resolved_session_factory() as db:
        record = db.get(SettlementRecord, capacity_reservation_id)
        db.expunge(record)
        return record


async def _converge_cycle(clients) -> None:
    """One convergence cycle, stepped while the timer-driven loop is held."""
    await clients.family.pause_fulfillment_convergence()
    try:
        await clients.family.advance_fulfillment_convergence_cycle()
    finally:
        await clients.family.resume_fulfillment_convergence()


async def _capacity_held(clients, capacity_reservation_id: str) -> bool:
    """The site's guarded release refuses: the capacity is still held."""
    return await clients.site.release(capacity_reservation_id=capacity_reservation_id) is None


async def _grant_without_evidence(clients, test_client, escrow_uid: str) -> tuple[str, str]:
    """A grant that runs, but whose printed fact names another tenant, so it
    carries no delivery evidence: convergence fails the create as reported by
    the provider, with its job-backed metadata recorded."""
    other_tenant = shipped_output(
        HOST_ID,
        "node_grant_access_data",
        {
            "action": NODE_GRANT_ACCESS_ACTION,
            "host_id": HOST_ID,
            "physical_host_id": PHYSICAL_HOST_ID,
            "ssh_user": "tenant-other",
            "escrow_uid": escrow_uid,
            "timestamp": "2030-01-01T00:00:01Z",
            "host": SSH_HOST,
            "port": "2201",
            "status": "success",
        },
    )
    await test_client.add_bare_metal_mock_rule(
        rule_id=f"no-evidence-{escrow_uid}",
        match={"action": NODE_GRANT_ACCESS_ACTION},
        result_stdout=other_tenant,
    )
    capacity_reservation_id, fulfillment_id = await begun_bare_metal_deal(clients, escrow_uid)
    granted = await test_client.wait_for_job(create_job_id(capacity_reservation_id), timeout=5.0)
    assert granted["status"] == "succeeded", granted
    await _converge_cycle(clients)
    record = _aggregate(capacity_reservation_id)
    assert (record.state, record.failure_reason) == (
        _State.failed.value,
        "provider_reported_failure",
    )
    return capacity_reservation_id, fulfillment_id


def _teardown_jobs(capacity_reservation_id: str) -> list[JobRecord]:
    with _container_module.resolved_session_factory() as db:
        return (
            db.query(JobRecord)
            .filter(
                JobRecord.capacity_reservation_id == capacity_reservation_id,
                JobRecord.action_kind == "teardown",
            )
            .all()
        )


async def test_a_grant_without_evidence_is_compensated_by_its_reclaim(
    client_and_queue, test_client
):
    """The lease is terminated after the create failed: the release begins the
    domain's reclaim as a compensating teardown, one reclaim job runs, and the
    capacity returns once, only once the aggregate is ``torn_down``."""
    clients, job_queue = client_and_queue
    capacity_reservation_id, fulfillment_id = await _grant_without_evidence(
        clients, test_client, "escrow-bm-compensated"
    )

    lease = await clients.family.terminate_lease(capacity_reservation_id, LeaseTermination())

    assert (lease.status, lease.release_job_id) == (LeaseState.RELEASING, fulfillment_id)
    record = _aggregate(capacity_reservation_id)
    assert (record.state, record.failure_reason) == (
        _State.teardown_dispatch_pending.value,
        CREATE_COMPENSATION,
    )
    assert "delivery evidence" in (record.failure_message or "")

    repeated = await clients.family.terminate_lease(capacity_reservation_id, LeaseTermination())
    assert (repeated.status, repeated.release_job_id) == (LeaseState.RELEASING, fulfillment_id)

    await _converge_cycle(clients)
    (reclaim,) = _teardown_jobs(capacity_reservation_id)
    reclaimed = await test_client.wait_for_job(reclaim.id, timeout=5.0)
    assert reclaimed["status"] == "succeeded", reclaimed
    assert reclaim.params["action"] == NODE_RECLAIM_ACCESS_ACTION
    await asyncio.wait_for(job_queue.wait_until_idle(), timeout=5.0)

    # The reclaim succeeded, but the aggregate is not yet torn down.
    assert (await clients.family.check_leases()).released == 0
    assert await _capacity_held(clients, capacity_reservation_id)

    await _converge_cycle(clients)
    record = _aggregate(capacity_reservation_id)
    assert (record.state, record.failure_reason) == (
        _State.torn_down.value,
        CREATE_COMPENSATION,
    )

    assert (await clients.family.check_leases()).released == 1
    assert (await clients.family.get_lease(capacity_reservation_id)).status == (
        LeaseState.RELEASED
    )
    assert (await clients.family.check_leases()).released == 0
    await clients.family.terminate_lease(capacity_reservation_id, LeaseTermination())
    assert len(_teardown_jobs(capacity_reservation_id)) == 1


async def test_a_create_in_flight_at_termination_is_compensated_once_it_fails(
    client_and_queue, test_client, bare_metal_runner
):
    clients, job_queue = client_and_queue
    await test_client.add_bare_metal_mock_rule(
        rule_id="grant-gate",
        match={"action": NODE_GRANT_ACCESS_ACTION, "host_id": HOST_ID},
        pause_before_result=True,
        fail_with="host unreachable",
    )
    capacity_reservation_id, fulfillment_id = await begun_bare_metal_deal(
        clients, "escrow-bm-inflight-failed"
    )
    await asyncio.wait_for(bare_metal_runner.rules.wait_until_held("grant-gate"), timeout=5.0)

    lease = await clients.family.terminate_lease(capacity_reservation_id, LeaseTermination())
    assert (lease.status, lease.release_job_id) == (LeaseState.RELEASING, fulfillment_id)
    assert _aggregate(capacity_reservation_id).state == _State.dispatching.value

    await test_client.resume_bare_metal_rule("grant-gate")
    failed = await test_client.wait_for_job(create_job_id(capacity_reservation_id), timeout=5.0)
    assert failed["status"] == "failed", failed
    await _converge_cycle(clients)
    assert _aggregate(capacity_reservation_id).state == _State.failed.value

    await clients.family.check_leases()

    record = _aggregate(capacity_reservation_id)
    assert (record.state, record.failure_reason) == (
        _State.teardown_dispatch_pending.value,
        CREATE_COMPENSATION,
    )
    await _converge_cycle(clients)
    (reclaim,) = _teardown_jobs(capacity_reservation_id)
    await test_client.wait_for_job(reclaim.id, timeout=5.0)
    await asyncio.wait_for(job_queue.wait_until_idle(), timeout=5.0)
    assert await _capacity_held(clients, capacity_reservation_id)

    await _converge_cycle(clients)
    await clients.family.check_leases()

    assert (await clients.family.get_lease(capacity_reservation_id)).status == (
        LeaseState.RELEASED
    )


def _set_failed(capacity_reservation_id: str, **fields) -> None:
    """Leave the aggregate failed as an ineligible path leaves it."""
    with _container_module.resolved_session_factory() as db, db.begin():
        record = db.get(SettlementRecord, capacity_reservation_id)
        record.state = _State.failed.value
        for name, value in fields.items():
            setattr(record, name, value)


@pytest.mark.parametrize(
    "fields",
    [
        {"failure_reason": "legacy_executor_identity_quarantined"},
        {"failure_reason": "invalid_provisioned_resource_metadata"},
        {"failure_reason": "provider_reported_failure", "provider_metadata": {}},
        {
            "failure_reason": "provider_reported_failure",
            "provider_metadata": {"vm_name": "vm-1", "job_id": "job-1"},
        },
    ],
    ids=["quarantined", "unresolvable-metadata", "no-metadata", "another-provider"],
)
async def test_an_ineligible_failed_create_leaves_the_lease_for_an_operator(
    client_and_queue, fields
):
    clients, _ = client_and_queue
    capacity_reservation_id, _ = await _granted(clients, "escrow-bm-ineligible")
    _set_failed(capacity_reservation_id, **fields)

    lease = await clients.family.terminate_lease(capacity_reservation_id, LeaseTermination())

    assert (lease.status, lease.failure_reason) == (
        LeaseState.RELEASE_FAILED,
        "fulfillment_failed",
    )
    assert _aggregate(capacity_reservation_id).state == _State.failed.value
    assert _teardown_jobs(capacity_reservation_id) == []
    assert await _capacity_held(clients, capacity_reservation_id)


async def test_a_compensation_whose_create_job_is_missing_is_refused(
    client_and_queue, test_client
):
    clients, _ = client_and_queue
    capacity_reservation_id, fulfillment_id = await _grant_without_evidence(
        clients, test_client, "escrow-bm-refused"
    )
    with _container_module.resolved_session_factory() as db, db.begin():
        db.query(JobRecord).filter(
            JobRecord.id == create_job_id(capacity_reservation_id)
        ).delete()

    lease = await clients.family.terminate_lease(capacity_reservation_id, LeaseTermination())

    assert (lease.status, lease.failure_reason, lease.release_job_id) == (
        LeaseState.RELEASE_FAILED,
        "compensation_refused",
        fulfillment_id,
    )
    record = _aggregate(capacity_reservation_id)
    assert (record.state, record.failure_reason) == (
        _State.failed.value,
        "provider_reported_failure",
    )
    assert record.prepared_teardown_operation is None
    assert await _capacity_held(clients, capacity_reservation_id)


async def test_a_failing_compensation_leaves_the_lease_for_an_operator(
    client_and_queue, test_client
):
    clients, job_queue = client_and_queue
    capacity_reservation_id, _ = await _grant_without_evidence(
        clients, test_client, "escrow-bm-failing-reclaim"
    )
    await test_client.add_bare_metal_mock_rule(
        rule_id="reclaim-fails",
        match={"action": NODE_RECLAIM_ACCESS_ACTION},
        fail_with="host unreachable",
    )
    await clients.family.terminate_lease(capacity_reservation_id, LeaseTermination())
    await _converge_cycle(clients)
    (reclaim,) = _teardown_jobs(capacity_reservation_id)
    reclaimed = await test_client.wait_for_job(reclaim.id, timeout=5.0)
    assert reclaimed["status"] == "failed", reclaimed
    await asyncio.wait_for(job_queue.wait_until_idle(), timeout=5.0)
    await _converge_cycle(clients)

    record = _aggregate(capacity_reservation_id)
    assert (record.state, record.failure_reason) == (
        _State.teardown_failed.value,
        CREATE_COMPENSATION,
    )
    await clients.family.check_leases()
    lease = await clients.family.get_lease(capacity_reservation_id)
    assert (lease.status, lease.failure_reason) == (
        LeaseState.RELEASE_FAILED,
        "teardown_failed",
    )
    assert await _capacity_held(clients, capacity_reservation_id)


async def test_a_delivered_teardown_that_fails_once_is_not_read_as_compensated(
    client_and_queue, test_client
):
    """The reclaim of a delivered grant fails, and convergence records it.
    A teardown job whose playbook ran and failed is not run again, so its later
    success is the state convergence would leave; the operator's retry then
    releases the lease, and the aggregate never carries ``create_compensation``."""
    clients, job_queue = client_and_queue
    capacity_reservation_id, _ = await begun_bare_metal_deal(clients, "escrow-bm-delivered-once")
    await test_client.wait_for_job(create_job_id(capacity_reservation_id), timeout=5.0)
    await _converge_cycle(clients)
    assert _aggregate(capacity_reservation_id).state == _State.active.value
    await test_client.add_bare_metal_mock_rule(
        rule_id="delivered-reclaim-fails",
        match={"action": NODE_RECLAIM_ACCESS_ACTION},
        fail_with="host unreachable",
    )

    await clients.family.terminate_lease(capacity_reservation_id, LeaseTermination())
    await _converge_cycle(clients)
    (reclaim,) = _teardown_jobs(capacity_reservation_id)
    await test_client.wait_for_job(reclaim.id, timeout=5.0)
    await asyncio.wait_for(job_queue.wait_until_idle(), timeout=5.0)
    await _converge_cycle(clients)
    assert _aggregate(capacity_reservation_id).failure_reason == "provider_reported_failure"
    await clients.family.check_leases()

    _converge(capacity_reservation_id, _State.torn_down)
    lease = await clients.family.retry_lease_release(capacity_reservation_id, LeaseRetryRelease())

    assert lease.status == LeaseState.RELEASED
    record = _aggregate(capacity_reservation_id)
    assert record.state == _State.torn_down.value
    assert record.failure_reason != CREATE_COMPENSATION


# ----------------------------------------------------------------------
# A teardown refused before its playbook is run again while the lease waits
# ----------------------------------------------------------------------


@pytest.fixture
def source() -> Iterator[InjectedTime]:
    """The process time source, held at the wall instant it is installed; a
    test sets it forward past a rerun's delay or the harness's 300-second
    grace."""
    before = injected_time.installed()
    installed = InjectedTime()
    injected_time.install(installed)
    yield installed
    injected_time.install(before)


def _host_version(version: int) -> None:
    """Store the bare-metal host's ssh connection at ``version``. At 1, which
    no codec serves, every job against it is refused before its playbook, as a
    job's executor refuses an inventory it cannot render; seeded directly, as
    the API registers only the version it serves."""
    with _container_module.resolved_session_factory() as db, db.begin():
        db.get(Host, HOST_ID).connection_version = version


async def _reclaim_refused(clients, test_client, job_queue, escrow_uid: str) -> str:
    """A delivered deal whose lease was terminated and whose reclaim job was
    refused before its playbook: the aggregate is ``teardown_failed``."""
    capacity_reservation_id, _ = await _granted(clients, escrow_uid)
    _host_version(1)
    await clients.family.terminate_lease(capacity_reservation_id, LeaseTermination())
    await _converge_cycle(clients)
    (reclaim,) = _teardown_jobs(capacity_reservation_id)
    refused = await clients.family.get_job(
        (await test_client.wait_for_job(reclaim.id, timeout=5.0))["job_id"]
    )
    assert refused.status == "failed", refused
    assert (refused.execution_started_at, refused.finished_at is not None) == (None, True)
    await asyncio.wait_for(job_queue.wait_until_idle(), timeout=5.0)
    await _converge_cycle(clients)
    assert _aggregate_state(capacity_reservation_id) == _State.teardown_failed.value
    return capacity_reservation_id


def _teardown_keys(capacity_reservation_id: str) -> list[str]:
    return sorted(job.idempotency_key for job in _teardown_jobs(capacity_reservation_id))


async def test_a_reclaim_refused_before_its_playbook_is_run_again_while_the_lease_waits(
    client_and_queue, test_client, source
):
    """No operator call: the lease stays releasing while the rerun waits for
    its delay, the rerun runs once the host is repaired, and the capacity
    returns when the aggregate is torn down."""
    clients, job_queue = client_and_queue
    capacity_reservation_id = await _reclaim_refused(
        clients, test_client, job_queue, "escrow-bm-rerun"
    )

    await clients.family.check_leases()
    assert (await clients.family.get_lease(capacity_reservation_id)).status == (
        LeaseState.RELEASING
    )
    assert await _capacity_held(clients, capacity_reservation_id)

    _host_version(SSH_CONNECTION_VERSION)
    source.set(source.now() + 60)
    await _converge_cycle(clients)
    assert _teardown_keys(capacity_reservation_id) == [
        f"{capacity_reservation_id}:teardown",
        f"{capacity_reservation_id}:teardown:rerun-1",
    ]
    rerun = _aggregate(capacity_reservation_id).teardown_provider_metadata["teardown_job_id"]
    assert (await test_client.wait_for_job(rerun, timeout=5.0))["status"] == "succeeded"
    await asyncio.wait_for(job_queue.wait_until_idle(), timeout=5.0)
    await _converge_cycle(clients)

    assert _aggregate_state(capacity_reservation_id) == _State.torn_down.value
    assert (await clients.family.check_leases()).released == 1
    assert (await clients.family.get_lease(capacity_reservation_id)).status == (
        LeaseState.RELEASED
    )


@pytest.mark.parametrize("teardown_rerun_limit", [0])
async def test_with_reruns_disabled_a_refused_reclaim_waits_for_an_operator(
    client_and_queue, test_client, source, teardown_rerun_limit
):
    clients, job_queue = client_and_queue
    capacity_reservation_id = await _reclaim_refused(
        clients, test_client, job_queue, "escrow-bm-disabled"
    )

    await clients.family.check_leases()
    lease = await clients.family.get_lease(capacity_reservation_id)
    _host_version(SSH_CONNECTION_VERSION)
    source.set(source.now() + 86400)
    await _converge_cycle(clients)
    await _converge_cycle(clients)

    assert (lease.status, lease.failure_reason) == (LeaseState.RELEASE_FAILED, "teardown_failed")
    assert _teardown_keys(capacity_reservation_id) == [f"{capacity_reservation_id}:teardown"]
    assert await _capacity_held(clients, capacity_reservation_id)


async def test_a_reclaim_finished_before_starts_were_recorded_is_not_run_again(
    client_and_queue, test_client, source
):
    """A job with no ``finished_at``, as one an earlier release left, proves
    nothing about whether its playbook ran: the lease waits for an operator."""
    clients, job_queue = client_and_queue
    capacity_reservation_id = await _reclaim_refused(
        clients, test_client, job_queue, "escrow-bm-upgrade"
    )
    with _container_module.resolved_session_factory() as db, db.begin():
        for job in db.query(JobRecord).filter(
            JobRecord.capacity_reservation_id == capacity_reservation_id,
            JobRecord.action_kind == "teardown",
        ):
            job.finished_at = None

    await clients.family.check_leases()
    lease = await clients.family.get_lease(capacity_reservation_id)
    _host_version(SSH_CONNECTION_VERSION)
    source.set(source.now() + 86400)
    await _converge_cycle(clients)

    assert (lease.status, lease.failure_reason) == (LeaseState.RELEASE_FAILED, "teardown_failed")
    assert _teardown_keys(capacity_reservation_id) == [f"{capacity_reservation_id}:teardown"]


async def test_a_lease_timed_out_with_a_rerun_pending_is_retried_and_waits_for_it(
    client_and_queue, test_client, source
):
    """Past the grace the lease is release_failed with teardown_timeout. An
    operator's retry-release returns it to releasing under the same
    fulfillment, timing its grace afresh, and the rerun releases it."""
    clients, job_queue = client_and_queue
    capacity_reservation_id = await _reclaim_refused(
        clients, test_client, job_queue, "escrow-bm-timeout"
    )
    fulfillment_id = (await clients.family.get_lease(capacity_reservation_id)).release_job_id

    source.set(source.now() + 301)
    await clients.family.check_leases()
    timed_out = await clients.family.get_lease(capacity_reservation_id)
    assert (timed_out.status, timed_out.failure_reason) == (
        LeaseState.RELEASE_FAILED,
        "teardown_timeout",
    )

    retried = await clients.family.retry_lease_release(capacity_reservation_id, LeaseRetryRelease())
    await clients.family.check_leases()
    assert (retried.status, retried.release_job_id) == (LeaseState.RELEASING, fulfillment_id)
    assert (await clients.family.get_lease(capacity_reservation_id)).status == (
        LeaseState.RELEASING
    )

    _host_version(SSH_CONNECTION_VERSION)
    await _converge_cycle(clients)
    rerun = _aggregate(capacity_reservation_id).teardown_provider_metadata["teardown_job_id"]
    assert (await test_client.wait_for_job(rerun, timeout=5.0))["status"] == "succeeded"
    await asyncio.wait_for(job_queue.wait_until_idle(), timeout=5.0)
    await _converge_cycle(clients)

    assert (await clients.family.check_leases()).released == 1
    assert len(_teardown_jobs(capacity_reservation_id)) == 2


async def test_a_teardown_that_outlasts_the_grace_is_released_by_one_retry(
    client_and_queue, test_client, bare_metal_runner, source
):
    """The reclaim is held running past the grace: the lease times out. Once
    it succeeds and the aggregate is torn down, one retry-release releases the
    lease under the same fulfillment, and no second teardown is begun."""
    clients, job_queue = client_and_queue
    capacity_reservation_id, fulfillment_id = await _granted(clients, "escrow-bm-slow")
    await test_client.add_bare_metal_mock_rule(
        rule_id="slow-reclaim",
        match={"action": NODE_RECLAIM_ACCESS_ACTION},
        pause_before_result=True,
    )
    await clients.family.terminate_lease(capacity_reservation_id, LeaseTermination())
    await _converge_cycle(clients)
    await asyncio.wait_for(bare_metal_runner.rules.wait_until_held("slow-reclaim"), timeout=5.0)

    try:
        source.set(source.now() + 301)
        await clients.family.check_leases()
        timed_out = await clients.family.get_lease(capacity_reservation_id)
    finally:
        # The hold ends whatever the assertions find, and nothing stays held.
        await test_client.resume_bare_metal_rule("slow-reclaim")
        await asyncio.wait_for(
            bare_metal_runner.rules.wait_until_released("slow-reclaim"), timeout=5.0
        )
        await asyncio.wait_for(job_queue.wait_until_idle(), timeout=5.0)
    (rule,) = [r for r in bare_metal_runner.list_rules() if r["rule_id"] == "slow-reclaim"]
    assert rule["waiting"] == 0
    assert (timed_out.status, timed_out.failure_reason) == (
        LeaseState.RELEASE_FAILED,
        "teardown_timeout",
    )

    await _converge_cycle(clients)
    assert _aggregate_state(capacity_reservation_id) == _State.torn_down.value

    lease = await clients.family.retry_lease_release(capacity_reservation_id, LeaseRetryRelease())

    assert (lease.status, lease.release_job_id) == (LeaseState.RELEASED, fulfillment_id)
    assert _teardown_keys(capacity_reservation_id) == [f"{capacity_reservation_id}:teardown"]


async def test_a_reclaim_that_succeeds_on_its_job_retry_releases_the_lease(
    client_and_queue, test_client, source
):
    """The reclaim's first attempt fails retryably after its playbook started;
    the job's own retry succeeds within the grace, and the lease, releasing
    while the retry waits, is released with no operator."""
    clients, job_queue = client_and_queue
    capacity_reservation_id, _ = await _granted(clients, "escrow-bm-retry")
    await test_client.add_bare_metal_mock_rule(
        rule_id="reclaim-busy",
        match={"action": NODE_RECLAIM_ACCESS_ACTION},
        fail_with="disk busy",
    )
    await clients.family.terminate_lease(capacity_reservation_id, LeaseTermination())
    await _converge_cycle(clients)
    (reclaim,) = _teardown_jobs(capacity_reservation_id)
    await asyncio.wait_for(job_queue.wait_until_idle(), timeout=5.0)
    retrying = await clients.family.get_job(reclaim.id)
    assert (retrying.status, retrying.retry_count) == ("queued", 1)
    assert retrying.execution_started_at is not None

    await _converge_cycle(clients)
    await clients.family.check_leases()
    assert (await clients.family.get_lease(capacity_reservation_id)).status == (
        LeaseState.RELEASING
    )

    await test_client.delete_bare_metal_mock_rule("reclaim-busy")
    source.set(source.now() + 60)
    assert await _container_module.resolved_job_engine.requeue_due_retries(job_queue) == 1
    assert (await test_client.wait_for_job(reclaim.id, timeout=5.0))["status"] == "succeeded"
    await asyncio.wait_for(job_queue.wait_until_idle(), timeout=5.0)
    await _converge_cycle(clients)

    assert (await clients.family.check_leases()).released == 1
    assert _teardown_keys(capacity_reservation_id) == [f"{capacity_reservation_id}:teardown"]


async def test_a_compensating_reclaim_refused_before_its_playbook_runs_again_compensated(
    client_and_queue, test_client, source
):
    """A failed create's compensating reclaim is refused before its playbook:
    convergence keeps ``create_compensation`` on the failure, the lease waits,
    and the rerun tears the aggregate down still marked compensated."""
    clients, job_queue = client_and_queue
    capacity_reservation_id, _ = await _grant_without_evidence(
        clients, test_client, "escrow-bm-compensated-rerun"
    )
    _host_version(1)
    await clients.family.terminate_lease(capacity_reservation_id, LeaseTermination())
    await _converge_cycle(clients)
    (reclaim,) = _teardown_jobs(capacity_reservation_id)
    assert (await test_client.wait_for_job(reclaim.id, timeout=5.0))["status"] == "failed"
    await asyncio.wait_for(job_queue.wait_until_idle(), timeout=5.0)
    await _converge_cycle(clients)
    record = _aggregate(capacity_reservation_id)
    assert (record.state, record.failure_reason) == (
        _State.teardown_failed.value,
        CREATE_COMPENSATION,
    )
    await clients.family.check_leases()
    assert (await clients.family.get_lease(capacity_reservation_id)).status == (
        LeaseState.RELEASING
    )

    _host_version(SSH_CONNECTION_VERSION)
    source.set(source.now() + 60)
    await _converge_cycle(clients)
    rerun = _aggregate(capacity_reservation_id).teardown_provider_metadata["teardown_job_id"]
    assert (await test_client.wait_for_job(rerun, timeout=5.0))["status"] == "succeeded"
    await asyncio.wait_for(job_queue.wait_until_idle(), timeout=5.0)
    await _converge_cycle(clients)

    record = _aggregate(capacity_reservation_id)
    assert (record.state, record.failure_reason) == (_State.torn_down.value, CREATE_COMPENSATION)
    assert (await clients.family.check_leases()).released == 1
    assert len(_teardown_jobs(capacity_reservation_id)) == 2


async def test_a_release_is_durable_before_teardown_and_a_restart_resumes_it(
    client_and_queue, monkeypatch
):
    """The lease records ``releasing`` before teardown is asked for. When
    beginning teardown fails after that, the terminate still answers
    ``releasing``, the aggregate is untouched, and a lifecycle rebuilt over the
    same database, as after a restart, begins the teardown."""
    clients, _ = client_and_queue
    capacity_reservation_id, fulfillment_id = await _granted(clients, "escrow-bm-durable")

    async def unreachable(self, fulfillment_id):
        raise ConnectionError("fulfillment authority unreachable")

    with monkeypatch.context() as patched:
        patched.setattr(FulfillmentOrchestrator, "begin_fulfillment_teardown", unreachable)
        lease = await clients.family.terminate_lease(capacity_reservation_id, LeaseTermination())

    assert (lease.status, lease.release_job_id) == (LeaseState.RELEASING, fulfillment_id)
    assert _aggregate_state(capacity_reservation_id) == _State.active.value

    session_factory = _container_module.resolved_session_factory
    teardown_port = FulfillmentServiceTeardownPort(
        lambda: _container_module.resolved_fulfillment_service
    )
    # Rebuilt from configuration only: nothing in memory survives the restart.
    configured = _container_module.resolved_lease_lifecycle_service
    restarted = LeaseLifecycleService(
        settings=configured._settings,
        site_authority=configured._site_authority,
        release_executor=FulfillmentReleaseExecutor(
            settlement_repository=SettlementRepository(),
            session_factory=session_factory,
            teardown_port=teardown_port,
        ),
        release_status=FulfillmentReleaseStatusPort(
            settlement_repository=SettlementRepository(),
            session_factory=session_factory,
            rerun_policy=_container_module._make_teardown_rerun_policy(configured._settings),
            jobs=_container_module.resolved_job_engine,
        ),
    )
    await restarted.check_leases()

    assert _aggregate_state(capacity_reservation_id) == _State.teardown_dispatch_pending.value
    assert (await clients.family.get_lease(capacity_reservation_id)).status == (
        LeaseState.RELEASING
    )


async def test_a_teardown_that_keeps_failing_to_begin_times_out_after_the_grace(
    client_and_queue, monkeypatch, source
):
    """Beginning teardown keeps failing transiently: within the grace each
    cycle leaves the lease releasing to try again; past it, the lease is
    release_failed with teardown_timeout, its aggregate never torn down."""
    clients, _ = client_and_queue
    capacity_reservation_id, fulfillment_id = await _granted(clients, "escrow-bm-unbegun")

    async def unreachable(self, fulfillment_id):
        raise ConnectionError("fulfillment authority unreachable")

    with monkeypatch.context() as patched:
        patched.setattr(FulfillmentOrchestrator, "begin_fulfillment_teardown", unreachable)
        await clients.family.terminate_lease(capacity_reservation_id, LeaseTermination())
        await clients.family.check_leases()
        waiting = await clients.family.get_lease(capacity_reservation_id)

        source.set(source.now() + 301)
        await clients.family.check_leases()
        timed_out = await clients.family.get_lease(capacity_reservation_id)

    assert (waiting.status, waiting.release_job_id) == (LeaseState.RELEASING, fulfillment_id)
    assert (timed_out.status, timed_out.failure_reason, timed_out.release_job_id) == (
        LeaseState.RELEASE_FAILED,
        "teardown_timeout",
        fulfillment_id,
    )
    assert _aggregate_state(capacity_reservation_id) == _State.active.value


async def test_a_bare_metal_lease_reports_the_machine_its_activation_recorded(
    client_and_queue,
):
    """Nothing registers a lease: convergence, finding the grant succeeded,
    makes the fulfillment active and records the machine it acted on as the
    lease's target in the same transaction. The lease reads back through the
    family client as a bare-metal lease with its committed window."""
    clients, _ = client_and_queue
    capacity_reservation_id, _ = await begun_bare_metal_deal(clients, "escrow-bm-activated")
    finished = await _container_module.resolved_job_engine.wait_for_terminal(
        create_job_id(capacity_reservation_id), timeout=5.0
    )
    assert finished.status == "succeeded", finished.error
    committed = _container_module.resolved_capacity_ledger_service.get_reservation(
        capacity_reservation_id
    )
    assert committed["executor_target"] is None

    await _container_module.resolved_fulfillment_convergence_watchdog.converge_creates()

    assert _aggregate_state(capacity_reservation_id) == _State.active.value
    lease = await clients.family.get_lease(capacity_reservation_id)
    assert lease.executor_target == HOST_ID
    assert lease.offering_mode == "bare_metal"
    assert lease.lease_end_utc == datetime.fromisoformat(committed["lease_end_utc"])
    assert lease.create_job_id == create_job_id(capacity_reservation_id)
