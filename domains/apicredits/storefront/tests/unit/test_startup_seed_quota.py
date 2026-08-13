"""_register_seed_quota: delegates to the typed capacity-administration
client rather than constructing its own HTTP request.
"""

from __future__ import annotations

import json

import httpx
import pytest

from apicredits_storefront import startup


@pytest.mark.asyncio
async def test_register_seed_quota_sends_expected_request_via_the_typed_client(monkeypatch):
    captured = {}

    def handle(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"resource_id": "demo-quota"})

    monkeypatch.setattr(
        startup, "_capacity_authority_url", lambda: "http://credits-service:8082",
    )
    monkeypatch.setattr(
        startup.config, "credits_admin_key", lambda: "test-admin-key",
    )

    import market_site_client
    real_client_cls = market_site_client.SiteCapacityAdminClient

    def _client_with_test_transport(base_url, admin_key="", **kwargs):
        return real_client_cls(
            base_url, admin_key, transport=httpx.MockTransport(handle),
        )

    monkeypatch.setattr(
        market_site_client, "SiteCapacityAdminClient", _client_with_test_transport,
    )

    await startup._register_seed_quota(resource_id="demo-quota", total_units=100)

    assert captured["path"] == "/api/v1/capacity/resources/demo-quota"
    assert captured["headers"]["x-admin-key"] == "test-admin-key"
    assert captured["body"]["total_units"] == 100
    assert captured["body"]["resource_type"] == "api_credits"


@pytest.mark.asyncio
async def test_register_seed_quota_raises_runtime_error_on_client_failure(monkeypatch):
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="ledger unavailable")

    monkeypatch.setattr(
        startup, "_capacity_authority_url", lambda: "http://credits-service:8082",
    )
    monkeypatch.setattr(startup.config, "credits_admin_key", lambda: "")

    import market_site_client
    real_client_cls = market_site_client.SiteCapacityAdminClient

    def _client_with_test_transport(base_url, admin_key="", **kwargs):
        return real_client_cls(
            base_url, admin_key, transport=httpx.MockTransport(handle),
        )

    monkeypatch.setattr(
        market_site_client, "SiteCapacityAdminClient", _client_with_test_transport,
    )

    with pytest.raises(RuntimeError, match="demo-quota"):
        await startup._register_seed_quota(resource_id="demo-quota", total_units=100)
