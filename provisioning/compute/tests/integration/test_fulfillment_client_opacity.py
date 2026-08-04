"""Opaque fulfillment boundary, exercised against a mock transport.

Covers `ComputeProvisioningClient` -- the client class this same package
defines -- proving `schedule_resource`/`begin_fulfillment` never *send* a
placement field. Lives here, not in `core/storefront`, because fulfillment
scheduling is a physical-resource-domain concept (VM, bare-metal today),
not a universal one `core` should know about. See the companion
`RemoteCapacityClient` test in
`core/storefront/tests/integration/test_capacity_client_opacity.py` for
the capacity-reservation half of this same boundary, and that test's
docstring for why the two were split apart.

What this test does *not* prove: that a real server actually implements
this contract correctly end to end. That is a genuine two-real-services
proof and belongs in the e2e suite.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from compute_provisioning.client import ComputeProvisioningClient
from compute_provisioning.contracts import (
    FulfillmentAcceptanceResponse,
    FulfillmentRequestBody,
    FulfillmentScheduleRequest,
    FulfillmentScheduleResponse,
)

_CAPACITY_RESERVATION_ID = "resv-mock-001"
_SETTLEMENT_RESOURCE_ID = "settlement-resource-mock-001"
_FULFILLMENT_ID = "fulfillment-mock-001"


class _RecordingHandler:
    """Mock transport handler that records every request it answers.

    Lets assertions check what the client actually sent, not just what it
    received back -- the point of this test is proving the client never
    sends a placement field, which can only be checked from the request
    side.
    """

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path

        if path == "/api/v1/fulfillment/schedule" and request.method == "POST":
            response = FulfillmentScheduleResponse(
                settlement_resource_id=_SETTLEMENT_RESOURCE_ID,
                pool_id="pool-mock",
                resource_kind="compute.gpu",
                provider="ansible",
            )
            return httpx.Response(200, json=response.model_dump(mode="json"))

        if path == "/api/v1/fulfillment/begin" and request.method == "POST":
            response = FulfillmentAcceptanceResponse(
                fulfillment_id=_FULFILLMENT_ID,
                capacity_reservation_id=_CAPACITY_RESERVATION_ID,
                state="dispatching",
            )
            return httpx.Response(200, json=response.model_dump(mode="json"))

        return httpx.Response(404, json={"detail": f"unhandled mock path {path!r}"})


def _fulfillment_request(**overrides: Any) -> dict[str, Any]:
    payload = {
        "vm_target": "caller-value-is-not-placement",
        "vm_ram": 8192,
        "vm_vcpus": 4,
        "vm_disk_size": "80G",
        "vm_os_variant": "ubuntu22.04",
        "ssh_pubkey": "ssh-ed25519 AAAAtest",
    }
    payload.update(overrides)
    return {"kind": "vm.fulfillment.request", "schema_version": 1, "payload": payload}


@pytest.mark.asyncio
async def test_schedule_begin_send_no_placement_fields() -> None:
    """The opaque fulfillment boundary holds from the client side.

    Proves `ComputeProvisioningClient` never *sends* `resource_id` as a
    required or populated field across schedule/begin -- the same
    invariant the retired cross-service test proved by exercising a real
    server, now proved from the client's own request bodies against a
    mock instead.
    """
    handler = _RecordingHandler()
    transport = httpx.MockTransport(handler)

    provisioning = ComputeProvisioningClient("http://provisioning.test", transport=transport)
    scheduled = await provisioning.schedule_resource(
        FulfillmentScheduleRequest(
            capacity_reservation_id=_CAPACITY_RESERVATION_ID,
            market="vms",
            requirements={},
            resource_id=None,
        )
    )
    assert scheduled.settlement_resource_id == _SETTLEMENT_RESOURCE_ID

    from market_fulfillment.envelopes import VersionedEnvelope

    accepted = await provisioning.begin_fulfillment(
        FulfillmentRequestBody(
            capacity_reservation_id=_CAPACITY_RESERVATION_ID,
            market="vms",
            fulfillment_request=VersionedEnvelope[Any].model_validate(
                _fulfillment_request()
            ),
        )
    )
    assert accepted.fulfillment_id == _FULFILLMENT_ID
    assert accepted.state == "dispatching"

    for sent in handler.requests:
        if sent.content:
            import json

            body = json.loads(sent.content)
            assert body.get("resource_id") in (None, ""), (
                f"{sent.url.path} sent a non-null resource_id: {body}"
            )

    await provisioning.close()
