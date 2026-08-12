"""Opaque fulfillment boundary, exercised against a mock transport.

Covers `ComputeProvisioningClient` -- the client class this same package
defines -- proving `schedule_resource`/`begin_fulfillment` never *send* a
placement field. Lives here, not in `kit/site-client`, because fulfillment
scheduling is a physical-resource-domain concept (VM, bare-metal today),
not a universal one that package should know about. See the companion
`SiteCapacityClient` test in
`kit/site-client/tests/unit/test_opacity.py` for
the capacity-reservation half of this same boundary, and that test's
docstring for why the two were split apart.

What this test does *not* prove: that a real server actually implements
this contract correctly end to end. That is a genuine two-real-services
proof and belongs in the e2e suite.
"""

from __future__ import annotations

from typing import Any

import httpx
import json
import time

from market_identity import (
    Ed25519Signer,
    ResponseEnvelope,
    TrustedIdentitySet,
    canonical_body_hash,
    sign_response,
)
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
_CALLER = Ed25519Signer(b"\x11" * 32)
_AUTHORITY = Ed25519Signer(b"\x12" * 32)


def _signed_response(
    request: httpx.Request,
    payload: dict[str, Any],
    operation: str,
) -> httpx.Response:
    request_body = json.loads(request.content)
    authenticated = sign_response(
        signer=_AUTHORITY,
        envelope=ResponseEnvelope(
            role="service",
            principal=_AUTHORITY.identity,
            method=request.method,
            operation=operation,
            resource=request_body["capacity_reservation_id"],
            request_id=request.headers["X-Market-Request-ID"],
            timestamp=int(time.time()),
            status=200,
            body_hash=canonical_body_hash(payload),
        ),
    )
    return httpx.Response(
        200,
        json=payload,
        headers={
            "X-Market-Signature-Version": authenticated.protocol,
            "X-Market-Identity-Scheme": authenticated.principal.scheme.value,
            "X-Market-Identity-Identifier": authenticated.principal.identifier,
            "X-Market-Role": authenticated.role,
            "X-Market-Request-ID": authenticated.request_id,
            "X-Market-Timestamp": str(authenticated.timestamp),
            "X-Market-Signature": authenticated.proof.value,
        },
    )


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
            return _signed_response(
                request,
                response.model_dump(mode="json"),
                "provisioning_fulfillment_schedule",
            )

        if path == "/api/v1/fulfillment/begin" and request.method == "POST":
            response = FulfillmentAcceptanceResponse(
                fulfillment_id=_FULFILLMENT_ID,
                capacity_reservation_id=_CAPACITY_RESERVATION_ID,
                state="dispatching",
            )
            return _signed_response(
                request,
                response.model_dump(mode="json"),
                "provisioning_fulfillment_begin",
            )

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
    """`ComputeProvisioningClient` never sends `resource_id` as a required
    or populated field across schedule/begin -- proved from the client's
    own request bodies against a mock, since the point is what the client
    actually transmits, not just what it receives back."""
    handler = _RecordingHandler()
    transport = httpx.MockTransport(handler)

    provisioning = ComputeProvisioningClient(
        "http://provisioning.test",
        signer=_CALLER,
        caller_role="seller",
        expected_authorities=TrustedIdentitySet(
            identities=(_AUTHORITY.identity,)
        ),
        transport=transport,
    )
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
