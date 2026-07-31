"""lookup_key_record: constructs and uses CreditsServiceClient directly."""

from __future__ import annotations

import httpx
import pytest

from apicredits_storefront.services import keys_lookup
from domains.apicredits.settlement.credits_client import CreditsServiceClient


@pytest.mark.asyncio
async def test_lookup_key_record_uses_the_typed_client(monkeypatch):
    captured = {}

    def handle(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["headers"] = dict(request.headers)
        return httpx.Response(200, json={"key_id": "k1", "status": "active"})

    from apicredits_storefront.utils import config

    monkeypatch.setattr(config, "credits_service_url", lambda: "http://credits-service:8082")
    monkeypatch.setattr(config, "credits_admin_key", lambda: "test-admin-key")

    real_init = CreditsServiceClient.__init__

    def patched_init(self, service_url, admin_key="", **kwargs):
        real_init(self, service_url, admin_key, transport=httpx.MockTransport(handle))

    monkeypatch.setattr(CreditsServiceClient, "__init__", patched_init)

    result = await keys_lookup.lookup_key_record("k1")

    assert captured["path"] == "/api/v1/keys/k1"
    assert captured["headers"]["x-admin-key"] == "test-admin-key"
    assert result == {"key_id": "k1", "status": "active"}


@pytest.mark.asyncio
async def test_lookup_key_record_returns_none_for_unknown_key(monkeypatch):
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    from apicredits_storefront.utils import config

    monkeypatch.setattr(config, "credits_service_url", lambda: "http://credits-service:8082")
    monkeypatch.setattr(config, "credits_admin_key", lambda: "")

    real_init = CreditsServiceClient.__init__

    def patched_init(self, service_url, admin_key="", **kwargs):
        real_init(self, service_url, admin_key, transport=httpx.MockTransport(handle))

    monkeypatch.setattr(CreditsServiceClient, "__init__", patched_init)

    assert await keys_lookup.lookup_key_record("missing") is None
