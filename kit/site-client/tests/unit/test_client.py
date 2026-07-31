"""SiteCapacityAdminClient: request shape, auth header, and error translation."""

from __future__ import annotations

import json

import httpx
import pytest

from market_site_client import SiteCapacityAdminClient, SiteCapacityAdminClientError


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
