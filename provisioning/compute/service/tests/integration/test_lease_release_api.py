"""A lease's release follows its fulfillment, over the real API.

Bare-metal deals are set up as production sets them up, through scheduling
and ``begin``, which dispatches the grant through the bare-metal mock. Leases
are expired through the site's truncation and released by the lease watchdog's
cycle, through the canonical clients. Fulfillment convergence is not run: where
it would move the aggregate, the test sets the state it would leave.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from arkhai_bare_metal import NODE_GRANT_ACCESS_ACTION
from market_fulfillment import SettlementRecord, SettlementRecordState

from bare_metal_provisioning_adapter.services.mock_output import bare_metal_mock_output
from compute_provisioning_ansible import MockAnsibleRunner
from compute_provisioning.lease_lifecycle import LeaseLifecycleService
from compute_provisioning.release import (
    FulfillmentReleaseExecutor,
    FulfillmentReleaseStatusPort,
    FulfillmentServiceTeardownPort,
)
from compute_provisioning_contracts import LeaseState, LeaseTermination
from market_fulfillment import FulfillmentOrchestrator, SettlementRepository
from compute_provisioning_service import container as _container_module

from .bare_metal_deal import (
    HOST_ID,
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


async def test_a_failed_grant_leaves_the_lease_for_an_operator(
    client_and_queue, test_client, bare_metal_runner
):
    clients, _ = client_and_queue
    await test_client.add_bare_metal_mock_rule(
        rule_id="grant-fails",
        match={"action": NODE_GRANT_ACCESS_ACTION},
        fail_with="host unreachable",
    )
    capacity_reservation_id, _ = await begun_bare_metal_deal(clients, "escrow-bm-failed")
    await _container_module.resolved_job_engine.wait_for_terminal(
        create_job_id(capacity_reservation_id), timeout=5.0
    )
    _converge(capacity_reservation_id, _State.failed)

    lease = await clients.family.terminate_lease(capacity_reservation_id, LeaseTermination())

    assert (lease.status, lease.failure_reason) == (
        LeaseState.RELEASE_FAILED,
        "fulfillment_failed",
    )


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
        release_status=FulfillmentReleaseStatusPort(teardown_port),
    )
    await restarted.check_leases()

    assert _aggregate_state(capacity_reservation_id) == _State.teardown_dispatch_pending.value
    assert (await clients.family.get_lease(capacity_reservation_id)).status == (
        LeaseState.RELEASING
    )


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
