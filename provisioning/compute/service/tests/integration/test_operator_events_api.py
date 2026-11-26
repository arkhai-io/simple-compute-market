"""Operator events through the running application and its typed client.

A bare-metal deal is set up and released as production sets it up, through the
bare-metal mock, the job engine, fulfillment convergence and the lease
lifecycle, each stepped through its control. Its events are recorded in the
service's database by the transitions that report them, read back through the
administrator's event routes, and delivered by the event delivery worker's
cycle to a file sink standing for an operator's push sink.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from arkhai_bare_metal import NODE_RECLAIM_ACCESS_ACTION
from compute_provisioning_ansible import MockAnsibleRunner
from compute_provisioning_client import ComputeProvisioningError
from compute_provisioning_contracts import LeaseTermination
from dependency_injector import providers
from eventing import RouteRefused

from bare_metal_provisioning_adapter.services.mock_output import bare_metal_mock_output
from compute_provisioning_service import container as _container_module
from compute_provisioning_service.main import app
from compute_provisioning_service.services.operator_events import EventsSettings

from .test_bare_metal_leases_api import _HELPER_REFUSAL, _active
from .test_lease_release_api import _converge_cycle, _teardown_jobs


@pytest.fixture
def bare_metal_runner():
    return MockAnsibleRunner(default_output=bare_metal_mock_output)


@pytest.fixture
def bare_metal_plan_options():
    return {"reclaim_policy": "bounded_working_data", "working_data_policy_id": "fixture-policy-v1"}


@pytest.fixture
def job_retry_options():
    # One retry, due at once, so a refused cleanup is retried and then fails.
    return {"default_max_retries": 1, "retry_backoff_initial_seconds": 0,
            "retry_backoff_multiplier": 1.0, "retry_backoff_max_seconds": 0}


@pytest.fixture
def push_file(tmp_path):
    return tmp_path / "ops-push.jsonl"


@pytest.fixture
def events_config(push_file) -> dict:
    return {
        "sinks": {"enabled": ["ops-push"], "ops-push": {"sink": "file", "path": str(push_file)}},
        "routes": {"held-work": {"where": "severity = 'action_required'", "sinks": ["ops-push"]}},
    }


def _pushed(push_file) -> list[dict]:
    if not push_file.exists():
        return []
    return [json.loads(line) for line in push_file.read_text().splitlines() if line]


async def test_held_work_is_routed_to_the_push_sink(client_and_queue, test_client, push_file):
    clients, queue = client_and_queue
    # The worker's first cycle registers its consumer, as the service's timer
    # does at startup: a consumer starts at the events already recorded.
    await clients.family.run_event_delivery_cycle()
    reservation, _ = await _active(clients, test_client)
    await test_client.add_bare_metal_mock_rule(
        rule_id="bounded-refusal",
        match={"action": NODE_RECLAIM_ACCESS_ACTION},
        fail_with="working-data helper refused unsafe fixture",
        failure_record=_HELPER_REFUSAL,
    )
    await clients.family.terminate_lease(reservation, LeaseTermination())
    await _converge_cycle(clients)
    await asyncio.wait_for(queue.wait_until_idle(), timeout=5)
    assert await _container_module.resolved_job_engine.requeue_due_retries(queue) == 1
    await asyncio.wait_for(queue.wait_until_idle(), timeout=5)
    (reclaim,) = _teardown_jobs(reservation)
    assert (await clients.family.get_job(reclaim.id)).status == "failed"
    await _converge_cycle(clients)
    await clients.family.check_leases()
    assert (await clients.family.get_lease(reservation)).status == "release_failed"

    cycle = await clients.family.run_event_delivery_cycle()

    pushed = _pushed(push_file)
    assert [event["kind"] for event in pushed] == [
        "provisioning.teardown_attempt_held",
        "provisioning.lease_release_failed",
    ]
    held, failed = pushed
    assert held["subject"] == {"type": "job", "id": reclaim.id}
    assert held["attributes"]["failure_class"] == "cleanup_refused"
    assert failed["subject"] == {"type": "lease", "id": reservation}
    assert failed["attributes"]["failure_class"] == "cleanup_refused"
    assert failed["details"]["teardown_job_id"] == reclaim.id
    assert cycle.consumers["event-sinks"]["delivered"] == 2
    (destination,) = (await clients.family.get_event_deliveries()).destinations
    assert (destination.destination, destination.state, destination.delivered) == (
        "ops-push", "active", 2,
    )


async def test_an_administrator_lists_a_lease_s_events_in_sequence_order(
    client_and_queue, test_client
):
    clients, queue = client_and_queue
    reservation, _ = await _active(clients, test_client)
    await clients.family.terminate_lease(reservation, LeaseTermination())
    await _converge_cycle(clients)
    await asyncio.wait_for(queue.wait_until_idle(), timeout=5)
    await _converge_cycle(clients)
    assert (await clients.family.check_leases()).released == 1

    listed = await clients.family.list_events(reference=f"lease:{reservation}")

    kinds = [event.kind for event in listed.events]
    assert kinds == [
        "provisioning.job_finished",
        "site.lease_ended",
        "provisioning.job_finished",
        "site.capacity_released",
    ]
    sequences = [event.sequence for event in listed.events]
    assert sequences == sorted(sequences)
    create, ended, reclaim, released = listed.events
    assert create.attributes["action"] == "create" and reclaim.attributes["action"] == "teardown"
    assert ended.subject.id == reservation and released.attributes["forced"] is False
    only_ended = await clients.family.list_events(
        kind="site.lease_ended", reference=f"lease:{reservation}"
    )
    assert [event.id for event in only_ended.events] == [ended.id]


async def test_the_delivery_worker_is_held_and_released_by_its_controls(client_and_queue):
    clients, _ = client_and_queue

    paused = await clients.family.pause_event_delivery()
    resumed = await clients.family.resume_event_delivery()

    assert paused.paused and paused.at_gate
    assert not resumed.paused


async def test_resuming_a_destination_no_consumer_has_is_refused(client_and_queue):
    clients, _ = client_and_queue

    with pytest.raises(ComputeProvisioningError) as refused:
        await clients.family.resume_event_destination("ops-mail")

    assert refused.value.status_code == 404


async def test_a_route_naming_a_sink_not_enabled_refuses_the_service_s_start(client_and_queue):
    """The container's composition of the delivery worker, which the service's
    start resolves, refuses the configuration naming the route and the sink."""
    settings = EventsSettings.model_validate({
        "sinks": {"enabled": ["ops-push"], "ops-push": {"sink": "file", "path": "/dev/null"}},
        "routes": {"held-work": {"where": "severity = 'action_required'", "sinks": ["ops-mail"]}},
    })
    app.container.events_settings.override(providers.Object(settings))
    try:
        with pytest.raises(RouteRefused, match="held-work") as refused:
            app.container.event_delivery_worker()
    finally:
        app.container.events_settings.reset_override()
        app.container.event_sink_consumer.reset()
        app.container.event_delivery_worker.reset()
    assert "ops-mail" in str(refused.value)
