"""Bare-metal access jobs under the provisioning mock profile.

Grant and reclaim run through the bare-metal adapter's own mock: the job
service's host check, inventory rendering, and result parsing are the real ones,
and the job's result carries the access fields the bare-metal fulfillment
provider reads. Rules installed through ``/test/bare-metal/mock-rules`` hold or
shape those jobs and never touch the VM mock.

A grant is dispatched as production dispatches it, by beginning the deal's
fulfillment, and a held job is awaited through the job queue's dispatch seam
and the rule's gate-reached signal, never through elapsed time.
"""

from __future__ import annotations

import asyncio

import pytest
from arkhai_bare_metal import NODE_GRANT_ACCESS_ACTION, NODE_RECLAIM_ACCESS_ACTION

from bare_metal_provisioning_adapter.services.mock_output import (
    bare_metal_mock_output,
    shipped_output,
)
from compute_provisioning_service import container as _container_module
from compute_provisioning_ansible import MockAnsibleRunner
from compute_provisioning.jobs.queue import AsyncJobQueue
from compute_provisioning_client import ComputeProvisioningError
from compute_provisioning_contracts import (
    ACCESS_DELIVERY_KIND,
    CREATE_JOB_RESULT_KIND,
    AccessDelivery,
    CreateJobResult,
    LeaseTermination,
    MockJobEvaluation,
)

from .bare_metal_deal import (
    HOST_ID,
    PHYSICAL_HOST_ID,
    SSH_HOST,
    bare_metal_capacity,
    begin,
    committed_reservation,
    create_job_id,
    schedule,
)


@pytest.fixture
def bare_metal_runner():
    return MockAnsibleRunner(default_output=bare_metal_mock_output)


async def _scheduled(clients, escrow_uid: str) -> str:
    await bare_metal_capacity(clients)
    capacity_reservation_id = committed_reservation(escrow_uid)
    await schedule(clients, capacity_reservation_id)
    return capacity_reservation_id


def _record_dispatches(job_queue: AsyncJobQueue) -> tuple[list[str], asyncio.Event]:
    """Record each job the queue dispatches, through its ``on_job_started`` seam."""

    dispatched: list[str] = []
    first = asyncio.Event()
    previous = job_queue._on_job_started

    def _on_started(job_id: str) -> None:
        dispatched.append(job_id)
        first.set()
        if previous is not None:
            previous(job_id)

    job_queue._on_job_started = _on_started
    return dispatched, first


async def test_a_held_grant_runs_through_the_bare_metal_mock(
    test_client, bare_metal_runner, client_and_queue
) -> None:
    clients, job_queue = client_and_queue
    capacity_reservation_id = await _scheduled(clients, "escrow-bm-mock")
    await test_client.add_bare_metal_mock_rule(
        rule_id="grant-gate",
        match={"action": NODE_GRANT_ACCESS_ACTION, "host_id": HOST_ID},
        pause_before_result=True,
    )

    preview = await test_client.evaluate_bare_metal_job(
        HOST_ID, action=NODE_GRANT_ACCESS_ACTION
    )
    assert preview == MockJobEvaluation(
        params_valid=True, host_exists=True, rule_matched="grant-gate", would_pause=True
    )

    dispatched, first_dispatch = _record_dispatches(job_queue)
    await begin(clients, capacity_reservation_id, "escrow-bm-mock")
    grant_job_id = create_job_id(capacity_reservation_id)

    await asyncio.wait_for(first_dispatch.wait(), timeout=5.0)
    assert dispatched == [grant_job_id]
    await asyncio.wait_for(
        bare_metal_runner.rules.wait_until_held("grant-gate"), timeout=5.0
    )

    rules = await test_client.list_bare_metal_mock_rules()
    assert (rules[0].rule_id, rules[0].paused, rules[0].waiting) == ("grant-gate", True, 1)
    # A bare-metal rule is installed through bare metal's mount alone.
    assert await test_client.list_mock_rules() == []
    job = _container_module.resolved_job_engine.get_job(grant_job_id)
    assert job.status not in {"succeeded", "failed"}

    await test_client.resume_bare_metal_rule("grant-gate")
    finished = await test_client.wait_for_job(grant_job_id, timeout=5.0)

    assert finished["status"] == "succeeded", finished
    # The grant's result is the family's delivery evidence for the host.
    assert finished["result"]["result_kind"] == CREATE_JOB_RESULT_KIND
    created = CreateJobResult.model_validate(finished["result"]["value"])
    (endpoint,) = created.evidence.endpoints
    assert (endpoint.protocol, endpoint.host, endpoint.port) == ("ssh", SSH_HOST, 2201)
    assert endpoint.user
    assert (await test_client.list_bare_metal_mock_rules())[0].waiting == 0



async def test_cancelling_a_held_grant_ends_its_execution_without_a_resume(
    test_client, bare_metal_runner, client_and_queue
) -> None:
    """A cancelled job held at a gate leaves it and frees its queue slot.

    The job's status turns terminal when it is cancelled, but its processing is
    still parked at the gate until the run itself is stopped; this proves the
    processing ends, so no resume is needed and nothing is left held for the
    next test.
    """
    provisioning_client, job_queue = client_and_queue
    capacity_reservation_id = await _scheduled(provisioning_client, "escrow-bm-mock-cancel")
    await test_client.add_bare_metal_mock_rule(
        rule_id="grant-gate",
        match={"action": NODE_GRANT_ACCESS_ACTION, "host_id": HOST_ID},
        pause_before_result=True,
    )
    await begin(provisioning_client, capacity_reservation_id, "escrow-bm-mock-cancel")
    grant_job_id = create_job_id(capacity_reservation_id)
    await asyncio.wait_for(
        bare_metal_runner.rules.wait_until_held("grant-gate"), timeout=5.0
    )

    await provisioning_client.family.cancel_job(grant_job_id)

    await asyncio.wait_for(
        bare_metal_runner.rules.wait_until_released("grant-gate"), timeout=5.0
    )
    await asyncio.wait_for(job_queue.wait_until_idle(), timeout=5.0)
    rules = await test_client.list_bare_metal_mock_rules()
    assert (rules[0].paused, rules[0].waiting) == (True, 0)
    # The run ended as a failed playbook after the cancellation was committed;
    # that late outcome does not replace it.
    job = _container_module.resolved_job_engine.get_job(grant_job_id)
    assert job.status == "cancelled"

async def test_a_bare_metal_rule_can_fail_a_grant(test_client, client_and_queue) -> None:
    clients, _ = client_and_queue
    capacity_reservation_id = await _scheduled(clients, "escrow-bm-mock-fail")
    await test_client.add_bare_metal_mock_rule(
        rule_id="grant-fails",
        match={"action": NODE_GRANT_ACCESS_ACTION},
        fail_with="host unreachable",
    )

    await begin(clients, capacity_reservation_id, "escrow-bm-mock-fail")
    finished = await test_client.wait_for_job(create_job_id(capacity_reservation_id), timeout=5.0)

    assert finished["status"] == "failed"
    assert "host unreachable" in finished["error"]


async def test_a_rule_installed_through_vms_mount_is_not_bare_metals(
    test_client, bare_metal_runner, client_and_queue
) -> None:
    """A catch-all rule installed through VM's mount is in VM's rules alone:
    bare metal's routes neither list it nor evaluate a job against it."""
    await test_client.add_mock_rule(rule_id="vm-catch-all", match={}, fail_with="VM rule met")

    preview = await test_client.evaluate_bare_metal_job(HOST_ID, action=NODE_GRANT_ACCESS_ACTION)

    assert preview.rule_matched is None
    assert await test_client.list_bare_metal_mock_rules() == []
    assert bare_metal_runner.list_rules() == []
    assert [rule.rule_id for rule in await test_client.list_mock_rules()] == ["vm-catch-all"]


async def test_bare_metal_rule_routes_refuse_an_unknown_resume(test_client) -> None:
    with pytest.raises(ComputeProvisioningError) as refused:
        await test_client.resume_bare_metal_rule("missing")
    assert refused.value.status_code == 404


async def _converge(clients) -> None:
    """One convergence cycle, stepped while the timer-driven loop is held."""
    await clients.family.pause_fulfillment_convergence()
    try:
        await clients.family.advance_fulfillment_convergence_cycle()
    finally:
        await clients.family.resume_fulfillment_convergence()


async def test_a_grant_is_delivered_through_convergence_and_reclaimed_from_its_parameters(
    test_client, client_and_queue
) -> None:
    """The family's job-backed provider, composed as the service composes it:
    convergence makes the fulfillment active only on the grant's delivery
    evidence, the result route delivers how to reach the host, and the reclaim
    is prepared from what the grant job ran with."""
    clients, job_queue = client_and_queue
    capacity_reservation_id = await _scheduled(clients, "escrow-bm-delivered")
    fulfillment_id = await begin(clients, capacity_reservation_id, "escrow-bm-delivered")
    grant_job_id = create_job_id(capacity_reservation_id)
    granted = await test_client.wait_for_job(grant_job_id, timeout=5.0)
    assert granted["status"] == "succeeded", granted

    await _converge(clients)

    status = await clients.family.get_fulfillment_status(fulfillment_id)
    assert status.state == "active"
    result = await clients.family.get_fulfillment_result(fulfillment_id)
    assert result.payload["domain_result"]["kind"] == ACCESS_DELIVERY_KIND
    delivery = AccessDelivery.model_validate(result.payload["domain_result"]["payload"])
    (endpoint,) = delivery.endpoints
    assert (endpoint.protocol, endpoint.host, endpoint.port) == ("ssh", SSH_HOST, 2201)
    assert endpoint.user
    assert delivery.credentials == ()
    assert len(result.payload["provisioned_resources"]) == 1

    await clients.family.terminate_lease(capacity_reservation_id, LeaseTermination())
    await _converge(clients)

    listed = await clients.family.list_jobs(capacity_reservation_id=capacity_reservation_id)
    reclaim = next(job for job in listed.jobs if job.job_id != grant_job_id)
    assert listed.total == 2
    assert reclaim.capacity_reservation_id == capacity_reservation_id
    grant_params = (await clients.family.get_job(grant_job_id)).params
    # Both jobs' stored parameters carry the access playbook the harness
    # configures.
    assert grant_params["playbook_path"] == "/fake/bare-metal-node-access.yml"
    assert reclaim.params == {
        **grant_params,
        "action": NODE_RECLAIM_ACCESS_ACTION,
        "reclaim_policy": "remove_lease_key",
    }
    reclaimed = await test_client.wait_for_job(reclaim.job_id, timeout=5.0)
    assert reclaimed["status"] == "succeeded", reclaimed
    await asyncio.wait_for(job_queue.wait_until_idle(), timeout=5.0)

    await _converge(clients)

    assert (await clients.family.get_fulfillment_status(fulfillment_id)).state == "torn_down"


# A tenant-facing route on RFC 5737 documentation addresses: development fixture
# values that must never be used on a public network.
TENANT_HOST = "198.51.100.20"
TENANT_PORT = 22


async def test_a_shipped_form_grant_becomes_active_on_the_hosts_tenant_route(
    test_client, client_and_queue
) -> None:
    """The default mock output is the shipped YAML form, read through the real
    codec; the fulfillment becomes active, and its delivery names the host's
    tenant-facing address and port rather than the provisioner's route."""
    clients, _ = client_and_queue
    await bare_metal_capacity(clients, public_host=TENANT_HOST, public_port=TENANT_PORT)
    capacity_reservation_id = committed_reservation("escrow-bm-route")
    await schedule(clients, capacity_reservation_id)
    fulfillment_id = await begin(clients, capacity_reservation_id, "escrow-bm-route")
    granted = await test_client.wait_for_job(create_job_id(capacity_reservation_id), timeout=5.0)
    assert granted["status"] == "succeeded", granted

    await _converge(clients)

    assert (await clients.family.get_fulfillment_status(fulfillment_id)).state == "active"
    result = await clients.family.get_fulfillment_result(fulfillment_id)
    delivery = AccessDelivery.model_validate(result.payload["domain_result"]["payload"])
    (endpoint,) = delivery.endpoints
    assert (endpoint.protocol, endpoint.host, endpoint.port) == ("ssh", TENANT_HOST, TENANT_PORT)
    created = CreateJobResult.model_validate(granted["result"]["value"])
    assert endpoint.user == created.detail["ssh_user"]
    # The fact's own host and port, the provisioner's route, are detail only.
    assert (created.detail["host"], created.detail["port"]) == (SSH_HOST, "2201")


async def test_a_grant_naming_another_tenant_leaves_the_fulfillment_failed(
    test_client, client_and_queue
) -> None:
    """A grant whose printed fact names a tenant account other than the job's
    succeeds as a job, carries no evidence, and fails its fulfillment."""
    clients, _ = client_and_queue
    capacity_reservation_id = await _scheduled(clients, "escrow-bm-other-tenant")
    other_tenant = shipped_output(
        HOST_ID,
        "node_grant_access_data",
        {
            "action": NODE_GRANT_ACCESS_ACTION,
            "host_id": HOST_ID,
            "physical_host_id": PHYSICAL_HOST_ID,
            "ssh_user": "tenant-other",
            "escrow_uid": "escrow-bm-other-tenant",
            "timestamp": "2030-01-01T00:00:01Z",
            "host": SSH_HOST,
            "port": "2201",
            "status": "success",
        },
    )
    await test_client.add_bare_metal_mock_rule(
        rule_id="other-tenant",
        match={"action": NODE_GRANT_ACCESS_ACTION},
        result_stdout=other_tenant,
    )

    fulfillment_id = await begin(clients, capacity_reservation_id, "escrow-bm-other-tenant")
    granted = await test_client.wait_for_job(create_job_id(capacity_reservation_id), timeout=5.0)
    assert granted["status"] == "succeeded", granted
    created = CreateJobResult.model_validate(granted["result"]["value"])
    assert created.evidence is None
    assert created.detail["mismatch"].startswith("ssh_user:")

    await _converge(clients)

    status = await clients.family.get_fulfillment_status(fulfillment_id)
    assert status.state == "failed"
    assert "delivery evidence" in (status.failure_message or "")
