"""Bounded-policy correlation and release through typed application clients.

The executor is the domain mock; these cases prove job/lifecycle ownership, not
host data deletion. The native role gate owns actual cleanup and refusal/retry.
"""
import asyncio

import pytest
from arkhai_bare_metal import NODE_RECLAIM_ACCESS_ACTION
from compute_provisioning_ansible import MockAnsibleRunner
from compute_provisioning_contracts import LeaseTermination
from compute_provisioning_client import ComputeProvisioningError

from bare_metal_provisioning_adapter.services.mock_output import bare_metal_mock_output
from compute_provisioning_service import container as _container_module
from .bare_metal_deal import (bare_metal_capacity, begun_bare_metal_deal, committed_reservation, create_job_id, fulfillment_body, schedule)
from .test_lease_release_api import (
    _aggregate, _capacity_held, _converge_cycle, _grant_without_evidence, _teardown_jobs,
)


@pytest.fixture
def bare_metal_runner():
    return MockAnsibleRunner(default_output=bare_metal_mock_output)


@pytest.fixture
def bare_metal_plan_options():
    return {"reclaim_policy": "bounded_working_data", "working_data_policy_id": "fixture-policy-v1"}


@pytest.fixture
def job_retry_options():
    # A deterministic due-now scheduler seam, with no sleeps or row mutations.
    return {"default_max_retries": 2, "retry_backoff_initial_seconds": 0,
            "retry_backoff_multiplier": 1.0, "retry_backoff_max_seconds": 0}


async def _active(clients, test_client):
    reservation, fulfillment = await begun_bare_metal_deal(clients, "bounded-fixture-deal")
    assert (await test_client.wait_for_job(create_job_id(reservation), timeout=5))["status"] == "succeeded"
    await _converge_cycle(clients)
    assert _aggregate(reservation).state == "active"
    return reservation, fulfillment


_HELPER_TASK = "Clean attributable bounded scratch and IPC after verified termination"
#: The record a real run's notification callback writes when the working-data
#: helper refuses, as the bounded reclaim's tagged task fails.
_HELPER_REFUSAL = {
    "task": _HELPER_TASK,
    "role": "bare-metal-access",
    "tags": ["failure_class:cleanup_refused"],
    "module": "ansible.builtin.command",
    "rc": 1,
    "msg": "non-zero return code",
    "stderr": '{"version": 1, "error": "Refusal", "message": "working-data helper refused unsafe fixture"}',
}


async def test_bounded_cleanup_failure_retries_same_correlated_job_then_releases(
    client_and_queue, test_client
):
    clients, queue = client_and_queue
    reservation, _ = await _active(clients, test_client)
    create = await clients.family.get_job(create_job_id(reservation))
    assert create.params["reclaim_policy"] == "bounded_working_data"
    assert create.params["working_data_policy_id"] == "fixture-policy-v1"
    await test_client.add_bare_metal_mock_rule(
        rule_id="bounded-refusal",
        match={"action": NODE_RECLAIM_ACCESS_ACTION},
        fail_with="working-data helper refused unsafe fixture",
        failure_record=_HELPER_REFUSAL,
    )
    await clients.family.terminate_lease(reservation, LeaseTermination())
    await _converge_cycle(clients)
    await asyncio.wait_for(queue.wait_until_idle(), timeout=5)
    (reclaim,) = _teardown_jobs(reservation)
    first = await clients.family.get_job(reclaim.id)
    assert first.status == "queued" and first.retry_count == 1
    assert "working-data helper refused unsafe fixture" in first.error
    # The job's view carries the attempt's classified failure beside its text.
    assert (first.failure.code, first.failure.retryable) == ("cleanup_refused", True)
    assert first.failure.message == (
        f'{create.host_id}: task "{_HELPER_TASK}" failed: '
        "working-data helper refused unsafe fixture"
    )
    assert first.failure.details["task"] == _HELPER_TASK
    assert first.failure.details["domain_detail"] == {
        "error": "Refusal", "message": "working-data helper refused unsafe fixture",
    }
    for field in ("capacity_reservation_id", "working_data_policy_id", "reclaim_policy", "ssh_user"):
        assert first.params[field] == create.params[field]
    assert await _capacity_held(clients, reservation)
    assert (await clients.family.get_lease(reservation)).status == "releasing"
    await test_client.delete_bare_metal_mock_rule("bounded-refusal")
    # Run the real retry scheduler at its injected due-now boundary.
    assert await _container_module.resolved_job_engine.requeue_due_retries(queue) == 1
    assert (await test_client.wait_for_job(reclaim.id, timeout=5))["status"] == "succeeded"
    await asyncio.wait_for(queue.wait_until_idle(), timeout=5)
    await _converge_cycle(clients)
    assert _aggregate(reservation).state == "torn_down"
    assert (await clients.family.check_leases()).released == 1
    assert (await clients.family.get_lease(reservation)).status == "released"
    assert len(_teardown_jobs(reservation)) == 1


async def test_terminal_bounded_cleanup_failure_keeps_capacity_held(client_and_queue, test_client):
    clients, queue = client_and_queue
    reservation, _ = await _active(clients, test_client)
    await test_client.add_bare_metal_mock_rule(rule_id="bounded-terminal", match={"action": NODE_RECLAIM_ACCESS_ACTION}, fail_with="UNREACHABLE cleanup target")
    await clients.family.terminate_lease(reservation, LeaseTermination())
    await _converge_cycle(clients)
    (reclaim,) = _teardown_jobs(reservation)
    assert (await test_client.wait_for_job(reclaim.id, timeout=5))["status"] == "failed"
    # A failure whose run recorded no failed task: a failed job's view carries it.
    failed = await clients.family.get_job(reclaim.id)
    assert (failed.failure.code, failed.failure.retryable) == ("playbook_error", False)
    assert failed.error == f"Job failed (non-retryable error): {failed.failure.message}"
    await asyncio.wait_for(queue.wait_until_idle(), timeout=5)
    await _converge_cycle(clients)
    await clients.family.check_leases()
    assert _aggregate(reservation).state == "teardown_failed"
    assert (await clients.family.get_lease(reservation)).status == "release_failed"
    assert await _capacity_held(clients, reservation)
    await test_client.delete_bare_metal_mock_rule("bounded-terminal")
    assert await _container_module.resolved_job_engine.requeue_due_retries(queue) == 0
    assert (await clients.family.get_job(reclaim.id)).status == "failed"


async def test_bounded_failed_create_compensates_with_accepted_policy(client_and_queue, test_client):
    clients, queue = client_and_queue
    reservation, _ = await _grant_without_evidence(clients, test_client, "bounded-partial-create")
    await clients.family.terminate_lease(reservation, LeaseTermination())
    await _converge_cycle(clients)
    (reclaim,) = _teardown_jobs(reservation)
    assert reclaim.params["capacity_reservation_id"] == reservation
    assert reclaim.params["reclaim_policy"] == "bounded_working_data"
    assert reclaim.params["working_data_policy_id"] == "fixture-policy-v1"
    assert (await test_client.wait_for_job(reclaim.id, timeout=5))["status"] == "succeeded"
    await asyncio.wait_for(queue.wait_until_idle(), timeout=5)
    await _converge_cycle(clients)
    assert _aggregate(reservation).state == "torn_down"
    assert (await clients.family.check_leases()).released == 1


@pytest.mark.parametrize("override", [{"working_data_policy_id": "buyer-policy"}, {"access_ref": {"cleanup_roots": ["/root"]}}])
async def test_buyer_cleanup_authority_is_refused_before_dispatch(client_and_queue, override):
    clients, queue = client_and_queue
    await bare_metal_capacity(clients)
    reservation = committed_reservation("bounded-rejected-authority")
    await schedule(clients, reservation)
    body = fulfillment_body(reservation, "bounded-rejected-authority")
    body = body.model_copy(update={"fulfillment_request": body.fulfillment_request.model_copy(update={"payload": {**body.fulfillment_request.payload, **override}})})
    assert (await clients.family.validate_fulfillment(body)).valid is False
    with pytest.raises(ComputeProvisioningError) as refused:
        await clients.family.begin_fulfillment(body)
    assert refused.value.status_code == 422
    await asyncio.wait_for(queue.wait_until_idle(), timeout=5)
    assert (await clients.family.list_jobs()).jobs == []
