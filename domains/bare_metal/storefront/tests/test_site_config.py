from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from arkhai_bare_metal_storefront.runtime import build_runtime_from_environment
from arkhai_bare_metal_storefront.server import build_bare_metal_storefront_app
from arkhai_bare_metal_storefront.site_config import (
    SiteConfigurationError,
    parse_trusted_site_bindings,
)


def _payload() -> str:
    return json.dumps([
        {
            "site_id": "site-east",
            "authority_url": "https://east.internal.example/api/",
            "admin_key": "east-secret",
        },
        {
            "site_id": "site-west",
            "authority_url": "http://west.internal.example:8085",
            "admin_key": "west-secret",
        },
    ])


def test_bindings_are_stable_immutable_and_site_indexed() -> None:
    bindings = parse_trusted_site_bindings(_payload())

    assert tuple(bindings.by_site_id) == ("site-east", "site-west")
    assert bindings.by_site_id["site-east"].authority_url == (
        "https://east.internal.example/api"
    )
    with pytest.raises((AttributeError, TypeError)):
        bindings.by_site_id["site-east"] = bindings.bindings[1]  # type: ignore[index]


@pytest.mark.parametrize(
    "payload",
    [
        "not-json",
        "{}",
        '[{"site_id":"bad id","authority_url":"https://site","admin_key":"x"}]',
        '[{"site_id":"site","authority_url":"file:///tmp/site","admin_key":"x"}]',
        '[{"site_id":"site","authority_url":"https://user:pass@site","admin_key":"x"}]',
        '[{"site_id":"site","authority_url":"https://site?key=value","admin_key":"x"}]',
        '[{"site_id":"site","authority_url":"https://site","admin_key":""}]',
        (
            '[{"site_id":"site","authority_url":"https://one","admin_key":"x"},'
            '{"site_id":"site","authority_url":"https://two","admin_key":"y"}]'
        ),
    ],
)
def test_invalid_or_ambiguous_binding_fails_closed(payload: str) -> None:
    with pytest.raises(SiteConfigurationError):
        parse_trusted_site_bindings(payload)


def test_environment_composition_validates_and_diagnostics_redact_secrets(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("BARE_METAL_STOREFRONT_SITES_JSON", _payload())
    monkeypatch.setenv("BARE_METAL_STOREFRONT_ADMIN_KEY", "operator-secret")
    monkeypatch.setenv(
        "BARE_METAL_STOREFRONT_DB_PATH",
        str(tmp_path / "storefront.db"),
    )
    runtime = build_runtime_from_environment()
    app = build_bare_metal_storefront_app(runtime=runtime)

    with TestClient(app) as client:
        forbidden = client.get("/api/v1/system/sites")
        response = client.get(
            "/api/v1/system/sites",
            headers={"X-Admin-Key": "operator-secret"},
        )

    assert forbidden.status_code == 403
    assert response.json() == {
        "sites": [
            {
                "site_id": "site-east",
                "authority_configured": True,
                "credential_configured": True,
            },
            {
                "site_id": "site-west",
                "authority_configured": True,
                "credential_configured": True,
            },
        ],
        "count": 2,
    }
    serialized = response.text
    assert "east-secret" not in serialized
    assert "west-secret" not in serialized
    assert "internal.example" not in serialized


def test_environment_composition_rejects_invalid_config(monkeypatch) -> None:
    monkeypatch.setenv(
        "BARE_METAL_STOREFRONT_SITES_JSON",
        '[{"site_id":"site-1","authority_url":"https://site-1"}]',
    )

    with pytest.raises(SiteConfigurationError, match="admin_key"):
        build_runtime_from_environment()
