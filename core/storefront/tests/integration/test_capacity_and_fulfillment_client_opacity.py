"""Opaque capacity/fulfillment boundary, exercised against a mock transport.

Replaces the "fast, always-run" half of what
``domains/vms/storefront/tests/cross_service/test_capacity_fulfillment_boundary.py``
used to prove alone, via a special execution environment (PYTHONPATH trick
running a storefront-owned test file inside the provisioning service's own
process, to avoid either production package depending on the other).

This test needs no such trick: ``RemoteCapacityClient`` and
``ComputeProvisioningClient`` both already declare an
``httpx.AsyncBaseTransport`` test seam for exactly this purpose (see each
class's ``transport`` constructor parameter). Driving them against a
``httpx.MockTransport`` that returns responses built from the same shared,
typed contract models (``compute_provisioning.contracts``) both a real
client and a real server already validate against proves the client's wire
behavior -- specifically, that it never needs or sends physical-placement
fields -- without importing ``compute_provisioning_service`` at all.

What this test does *not* prove: that a real server actually implements
this contract correctly end to end. That is a genuine two-real-services
proof and belongs in the e2e suite
(``refactor-e2e-fulfillment-lifecycle`` Section 3) -- see
``openspec/changes/refactor-e2e-fulfillment-lifecycle/design.md``.
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
from core_storefront.capacity_remote import RemoteCapacityClient

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

        if path == "/api/v1/capacity/reservations" and request.method == "POST":
            # Mirrors kit/site's router.py: the reservation response never
            # carries resource_id/capacity_bucket_id/backing_resource_id/
            # vm_host (openspec/specs/site-capacity/spec.md's opaque-
            # reservation requirement).
            return httpx.Response(
                200,
                json={"reservation": {"capacity_reservation_id": _CAPACITY_RESERVATION_ID}},
            )

        if (
            path == f"/api/v1/capacity/reservations/{_CAPACITY_RESERVATION_ID}/commit"
            and request.method == "POST"
        ):
            return httpx.Response(200, json={"reservation": None})

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
async def test_reserve_commit_schedule_begin_send_no_placement_fields() -> None:
    """The opaque capacity/fulfillment boundary holds from the client side.

    Proves ``RemoteCapacityClient``/``ComputeProvisioningClient`` never
    *send* ``resource_id`` as a required or populated field across
    reserve/commit/schedule/begin -- the same invariant the retired
    cross-service test proved by exercising a real server, now proved from
    the client's own request bodies against a mock instead.
    """
    handler = _RecordingHandler()
    transport = httpx.MockTransport(handler)

    capacity = RemoteCapacityClient("http://capacity.test", transport=transport)
    reservation = await capacity.reserve(claim={"pool_id": "pool-mock", "gpu_count": 1})
    assert reservation == {"capacity_reservation_id": _CAPACITY_RESERVATION_ID}

    await capacity.commit(
        resource_id=None,
        capacity_reservation_id=_CAPACITY_RESERVATION_ID,
        idempotency_ref="agreement-mock-boundary",
    )

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

    # The actual proof: not one request body across all four calls named a
    # physical placement identifier, even though every call had the
    # opportunity to (commit/schedule both accept an optional resource_id).
    for sent in handler.requests:
        if sent.content:
            import json

            body = json.loads(sent.content)
            assert body.get("resource_id") in (None, ""), (
                f"{sent.url.path} sent a non-null resource_id: {body}"
            )

    await provisioning.close()
