"""Opaque capacity boundary, exercised against a mock transport.

Covers `SiteCapacityClient` only. This class lives in `kit/site-client`
because reserving capacity is a concept every domain this repository could
host needs -- VM, bare-metal, apicredits, or anything hypothetical.

A companion test for `ComputeProvisioningClient` (schedule/begin
fulfillment) lives in `provisioning/compute/tests/integration/` instead,
not here: fulfillment scheduling is a physical-resource-domain concept
(VM, bare-metal), not a universal one, and this package must not carry a
dependency on `compute_provisioning` to test it. The two clients were
originally tested together in one file; splitting them was the fix for
that layering mistake, not a refactor of convenience.
"""

from __future__ import annotations

import httpx
import pytest

from market_site_client import SiteCapacityClient

_CAPACITY_RESERVATION_ID = "resv-mock-001"


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

        return httpx.Response(404, json={"detail": f"unhandled mock path {path!r}"})


@pytest.mark.asyncio
async def test_reserve_commit_send_no_placement_fields() -> None:
    """The opaque capacity boundary holds from the client side.

    Proves `SiteCapacityClient` never *sends* `resource_id` as a
    required or populated field across reserve/commit -- the same
    invariant the retired cross-service test proved by exercising a real
    server, now proved from the client's own request bodies against a
    mock instead.
    """
    handler = _RecordingHandler()
    transport = httpx.MockTransport(handler)

    capacity = SiteCapacityClient("http://capacity.test", transport=transport)
    reservation = await capacity.reserve(claim={"pool_id": "pool-mock", "gpu_count": 1})
    assert reservation == {"capacity_reservation_id": _CAPACITY_RESERVATION_ID}

    await capacity.commit(
        resource_id=None,
        capacity_reservation_id=_CAPACITY_RESERVATION_ID,
        idempotency_ref="agreement-mock-boundary",
    )

    for sent in handler.requests:
        if sent.content:
            import json

            body = json.loads(sent.content)
            assert body.get("resource_id") in (None, ""), (
                f"{sent.url.path} sent a non-null resource_id: {body}"
            )
