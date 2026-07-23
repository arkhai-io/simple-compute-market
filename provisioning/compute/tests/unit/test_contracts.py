from datetime import datetime, timezone

import httpx
import pytest
from pydantic import ValidationError

from compute_provisioning import (
    COMPUTE_PROVISIONING_CONTRACT_VERSION,
    ComputeProvisioningClient,
    ExecutorActionEnvelope,
    ExecutorAdapterRegistry,
    FunctionalExecutorAdapter,
    FulfillmentBeginRequest,
    FulfillmentRequestEnvelope,
    FulfillmentScheduleRequest,
    IdempotentLifecycleEventSink,
    LifecycleEvent,
    ResultEnvelope,
    UnsupportedExecutorActionError,
)


def _action(**overrides):
    values = {
        "capacity_reservation_id": "alloc-1",
        "deal_ref": {"escrow_uid": "escrow-1"},
        "executor_kind": "vm",
        "action_kind": "create",
        "idempotency_key": "request-1",
        "parameters": {"vm_target": "tenant-1"},
    }
    values.update(overrides)
    return ExecutorActionEnvelope(**values)


def test_contract_rejects_unsupported_major_version():
    with pytest.raises(ValidationError, match="supported majors: 1"):
        _action(contract_version="2.0")


@pytest.mark.asyncio
async def test_registry_validates_without_generic_field_inspection():
    submitted = []

    async def submit(envelope, value):
        submitted.append((envelope.capacity_reservation_id, value))
        return "job-1"

    adapter = FunctionalExecutorAdapter(
        executor_kind="vm",
        parameter_validators={"create": lambda payload: payload["vm_target"]},
        submit_action=submit,
        result_validators={"create": lambda payload: ResultEnvelope(executor_kind="vm", result_kind="created", value=dict(payload))},
        credential_validators={},
    )
    registry = ExecutorAdapterRegistry([adapter])
    action = _action()
    validated = registry.get("vm").validate_parameters(action.action_kind, action.parameters)
    assert await registry.get("vm").submit(action, validated) == "job-1"
    assert submitted == [("alloc-1", "tenant-1")]
    with pytest.raises(UnsupportedExecutorActionError):
        registry.get("vm").validate_parameters("reimage", {})


@pytest.mark.asyncio
async def test_event_sink_deduplicates_only_after_successful_delivery():
    delivered = []
    sink = IdempotentLifecycleEventSink(lambda event: _record(delivered, event.event_id))
    event = LifecycleEvent(
        event_id="event-1",
        capacity_reservation_id="alloc-1",
        deal_ref={"escrow_uid": "escrow-1"},
        executor_kind="vm",
        event_kind="usage_ready",
        payload={},
        occurred_at=datetime.now(timezone.utc),
    )
    assert await sink.deliver(event) is True
    assert await sink.deliver(event) is False
    assert delivered == ["event-1"]


async def _record(values, value):
    values.append(value)


@pytest.mark.asyncio
async def test_client_maps_versioned_schedule_endpoint():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/fulfillment/schedules"
        payload = __import__("json").loads(request.content)
        assert payload["contract_version"] == COMPUTE_PROVISIONING_CONTRACT_VERSION
        return httpx.Response(
            200,
            json={
                "contract_version": COMPUTE_PROVISIONING_CONTRACT_VERSION,
                "capacity_reservation_id": payload["capacity_reservation_id"],
                "settlement_resource_id": "resource-1",
                "pool_id": "pool-1",
                "resource_kind": "bare_metal",
                "provider": "ansible",
                "attributes": {},
            },
        )

    async with ComputeProvisioningClient(
        "http://provisioner", transport=httpx.MockTransport(handler)
    ) as client:
        selected = await client.schedule_resource(
            FulfillmentScheduleRequest(
                capacity_reservation_id="reservation-1",
                market="bare_metal",
            ),
        )
    assert selected.settlement_resource_id == "resource-1"


@pytest.mark.asyncio
async def test_client_maps_fulfillment_acceptance_and_dry_run_endpoints():
    paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "contract_version": COMPUTE_PROVISIONING_CONTRACT_VERSION,
                    "fulfillment_id": "fulfillment-1",
                    "capacity_reservation_id": "reservation-1",
                    "state": "dispatching",
                },
            )
        payload = __import__("json").loads(request.content)
        if request.url.path.endswith("/dry-run"):
            return httpx.Response(
                200,
                json={
                    "contract_version": COMPUTE_PROVISIONING_CONTRACT_VERSION,
                    "valid": True,
                    "issues": [],
                },
            )
        return httpx.Response(
            200,
            json={
                "contract_version": COMPUTE_PROVISIONING_CONTRACT_VERSION,
                "capacity_reservation_id": payload["capacity_reservation_id"],
                "fulfillment_id": "fulfillment-1",
                "state": "dispatch_pending",
            },
        )

    request = FulfillmentBeginRequest(
        capacity_reservation_id="reservation-1",
        market="bare_metal",
        fulfillment_request=FulfillmentRequestEnvelope(
            kind="bare_metal.v1",
            schema_version=1,
            payload={"ssh_public_key": "ssh-ed25519 AAAA"},
        ),
    )
    async with ComputeProvisioningClient(
        "http://provisioner", transport=httpx.MockTransport(handler)
    ) as client:
        accepted = await client.begin_fulfillment(request)
        dry_run = await client.dry_run_fulfillment(request)
        status = await client.get_fulfillment_status(accepted.fulfillment_id)

    assert accepted.fulfillment_id == "fulfillment-1"
    assert dry_run.valid
    assert status.state == "dispatching"
    assert paths == [
        "/api/v1/fulfillments",
        "/api/v1/fulfillments/dry-run",
        "/api/v1/fulfillments/fulfillment-1/status",
    ]


@pytest.mark.asyncio
async def test_client_maps_versioned_action_endpoint():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/actions"
        payload = __import__("json").loads(request.content)
        assert payload["contract_version"] == COMPUTE_PROVISIONING_CONTRACT_VERSION
        return httpx.Response(202, json={**payload, "job_id": "job-1", "status": "queued"})

    async with ComputeProvisioningClient(
        "http://provisioner", transport=httpx.MockTransport(handler)
    ) as client:
        accepted = await client.submit_action(_action())
    assert accepted.job_id == "job-1"
    assert accepted.capacity_reservation_id == "alloc-1"


@pytest.mark.asyncio
async def test_client_maps_versioned_job_cancellation_endpoint():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/v1/jobs/job-1/contract/cancel"
        return httpx.Response(
            200,
            json={
                "contract_version": COMPUTE_PROVISIONING_CONTRACT_VERSION,
                "job_id": "job-1",
                "status": "cancelled",
                "capacity_reservation_id": "alloc-1",
                "deal_ref": {"escrow_uid": "escrow-1"},
                "executor_kind": "vm",
                "action_kind": "create",
                "idempotency_key": "request-1",
            },
        )

    async with ComputeProvisioningClient(
        "http://provisioner", transport=httpx.MockTransport(handler)
    ) as client:
        cancelled = await client.cancel_job("job-1")
    assert cancelled.status.value == "cancelled"
