"""market_site_client: SiteCapacityAdminClient (request shape, auth
header, error translation) and SiteCapacityClient (wire contract)."""

from __future__ import annotations

import json

import httpx
import pytest

from market_site_client import (
    SiteCapacityAdminClient,
    SiteCapacityAdminClientError,
    SiteCapacityClient,
)
from tests.fake_site import FakeSite


def _client(handler, admin_key: str = "test-admin-key") -> SiteCapacityAdminClient:
    return SiteCapacityAdminClient(
        "http://site-authority:8081",
        admin_key,
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.asyncio
async def test_register_resource_sends_expected_request_shape():
    captured = {}

    def handle(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"resource_id": "r1", "total_units": 8})

    client = _client(handle)
    result = await client.register_resource(
        "r1",
        total_units=8,
        resource_type="compute.gpu",
        pool_id="pool-a",
        attributes={"region": "eu-west"},
    )

    assert captured["method"] == "PUT"
    assert captured["path"] == "/api/v1/capacity/resources/r1"
    assert captured["headers"]["x-admin-key"] == "test-admin-key"
    assert captured["body"] == {
        "total_units": 8,
        "resource_type": "compute.gpu",
        "pool_id": "pool-a",
        "attributes": {"region": "eu-west"},
        "enabled": True,
    }
    assert result == {"resource_id": "r1", "total_units": 8}


@pytest.mark.asyncio
async def test_register_resource_omits_admin_header_when_no_key_configured():
    captured = {}

    def handle(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        return httpx.Response(200, json={})

    client = _client(handle, admin_key="")
    await client.register_resource("r1", total_units=1)

    assert "x-admin-key" not in captured["headers"]


@pytest.mark.asyncio
async def test_register_resource_raises_typed_error_on_http_failure():
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, text="total_units must be >= 0")

    client = _client(handle)
    with pytest.raises(SiteCapacityAdminClientError) as excinfo:
        await client.register_resource("r1", total_units=1)

    assert excinfo.value.status_code == 422
    assert "total_units must be >= 0" in str(excinfo.value)


@pytest.mark.asyncio
async def test_register_resource_raises_typed_error_on_transport_failure():
    def handle(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = _client(handle)
    with pytest.raises(SiteCapacityAdminClientError) as excinfo:
        await client.register_resource("r1", total_units=1)

    assert excinfo.value.status_code is None
    assert "r1" in str(excinfo.value)


@pytest.mark.asyncio
async def test_register_resource_defaults_match_the_server_model():
    """resource_type defaults to "compute.gpu" and enabled defaults to
    True, matching market_site.http_models.ResourceRegisterRequest --
    pinning the one place these two independently-defined shapes must
    stay in sync."""
    captured = {}

    def handle(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={})

    client = _client(handle)
    await client.register_resource("r1", total_units=1)

    assert captured["body"]["resource_type"] == "compute.gpu"
    assert captured["body"]["enabled"] is True


# ---------------------------------------------------------------------------
# SiteCapacityClient: buyer-facing wire contract, exercised against a real
# stateful fake (as opposed to the register-only tests above, which use a
# single-request MockTransport per test).
# ---------------------------------------------------------------------------

@pytest.fixture
def site() -> FakeSite:
    fake = FakeSite()
    fake.add_resource(
        "compute-kvm1-001", 8,
        attributes={"vm_host": "kvm1", "gpu_model": "H200"},
    )
    return fake


@pytest.fixture
def capacity_client(site: FakeSite) -> SiteCapacityClient:
    return SiteCapacityClient(
        "http://site-authority:8081", "test-key", transport=site.transport(),
    )


@pytest.mark.asyncio
async def test_capacity_client_speaks_the_capacity_wire_contract(
    capacity_client: SiteCapacityClient, site: FakeSite,
):
    snapshot = await capacity_client.snapshot()
    assert snapshot[0]["available_units"] == 8

    assert await capacity_client.probe(claim={"gpu_model": "A100"}) is None
    match = await capacity_client.probe(claim={"gpu_model": "H200"})
    assert match["vm_host"] == "kvm1"

    reserved = await capacity_client.reserve(
        claim={"gpu_count": 3}, deal_ref={"escrow_uid": "0xesc"},
    )
    assert reserved["capacity_reservation_id"]
    assert reserved["available_gpu_count"] == 8

    await capacity_client.commit(
        resource_id=reserved["resource_id"],
        capacity_reservation_id=reserved["capacity_reservation_id"],
        lease_start_utc="2099-01-01T00:00:00Z",
        lease_end_utc="2099-01-01 01:00",
        idempotency_ref="0xesc",
    )
    truncated = await capacity_client.truncate_lease(
        capacity_reservation_id=reserved["capacity_reservation_id"], lease_end_utc="2026-06-01 00:00",
    )
    assert truncated["lease_end_utc"] == "2026-06-01 00:00"

    released = await capacity_client.release(
        deal_ref={"escrow_uid": "0xesc"}, failure_reason="provisioning_failed",
    )
    assert released["state"] == "released"
    assert released["failure_reason"] == "provisioning_failed"

    events, latest = await capacity_client.events_after(0)
    assert [e["kind"] for e in events] == [
        "reserved", "committed", "lease_truncated", "released",
    ]
    assert latest == events[-1]["version"]
    # Every call authenticated.
    assert set(site.seen_admin_keys) == {"test-key"}


@pytest.mark.asyncio
async def test_capacity_client_commit_without_capacity_reservation_id_is_an_error(
    capacity_client: SiteCapacityClient,
):
    with pytest.raises(ValueError, match="capacity_reservation_id"):
        await capacity_client.commit(
            resource_id="r", capacity_reservation_id=None, lease_end_utc="2099-01-01 00:00",
        )


@pytest.mark.asyncio
async def test_capacity_client_list_reservations_filters(capacity_client: SiteCapacityClient):
    reserved = await capacity_client.reserve(
        claim={"gpu_count": 1}, deal_ref={"escrow_uid": "0xq"},
    )
    rows = await capacity_client.list_reservations(escrow_uid="0xq")
    assert [a["capacity_reservation_id"] for a in rows] == [reserved["capacity_reservation_id"]]
    assert await capacity_client.list_reservations(state="released") == []
