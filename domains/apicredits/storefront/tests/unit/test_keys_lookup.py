"""lookup_key_record reads through the one authority client the storefront composes."""

from __future__ import annotations

import httpx
import pytest

from apicredits_storefront.services import credits_service_client, keys_lookup
from arkhai_api_client import ADMIN_KEY_HEADER, AuthorityClient
from arkhai_apicredits.label import API_CREDITS_LABEL


def _compose(monkeypatch, handler, admin_key: str = "test-admin-key") -> None:
    monkeypatch.setattr(
        credits_service_client,
        "_client",
        AuthorityClient(
            "http://credits-service:8082",
            admin_key,
            label=API_CREDITS_LABEL,
            transport=httpx.MockTransport(handler),
        ),
    )


@pytest.mark.asyncio
async def test_lookup_key_record_uses_the_composed_client(monkeypatch):
    captured = {}

    def handle(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["headers"] = dict(request.headers)
        return httpx.Response(200, json={"key_id": "k1", "status": "active"})

    _compose(monkeypatch, handle)

    result = await keys_lookup.lookup_key_record("k1")

    assert captured["path"] == "/api/v1/keys/k1"
    assert captured["headers"][ADMIN_KEY_HEADER.lower()] == "test-admin-key"
    assert result == {"key_id": "k1", "status": "active"}


@pytest.mark.asyncio
async def test_lookup_key_record_returns_none_for_unknown_key(monkeypatch):
    _compose(monkeypatch, lambda request: httpx.Response(404), admin_key="")

    assert await keys_lookup.lookup_key_record("missing") is None


def test_the_composition_builds_one_client_from_configuration(monkeypatch):
    from apicredits_storefront.utils import config

    monkeypatch.setattr(credits_service_client, "_client", None)
    monkeypatch.setattr(config, "credits_service_url", lambda: "http://credits-service:8082")
    monkeypatch.setattr(config, "credits_admin_key", lambda: "test-admin-key")
    monkeypatch.setattr(config, "credits_expected_authorities", lambda: None)

    client = credits_service_client.get_credits_service_client()

    assert isinstance(client, AuthorityClient)
    assert client.signing_enabled is False
    assert credits_service_client.get_credits_service_client() is client
