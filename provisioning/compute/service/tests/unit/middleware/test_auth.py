"""Unit tests for credential-bound storefront authentication."""

from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from compute_provisioning_service.middleware.auth import (
    LEGACY_STOREFRONT_PRINCIPAL,
    LOCAL_DEVELOPMENT_PRINCIPAL,
    StorefrontAuthMiddleware,
    configured_storefront_principals,
)


def _client(
    admin_key: str | None,
    *,
    principal_keys=None,
) -> TestClient:
    app = FastAPI()
    app.add_middleware(
        StorefrontAuthMiddleware,
        admin_key=admin_key,
        principal_keys=principal_keys,
    )

    @app.get("/api/v1/jobs/")
    def _jobs(request: Request) -> dict:
        return {
            "ok": True,
            "principal": request.state.storefront_principal,
        }

    @app.get("/health")
    def _health() -> dict:
        return {"status": "ok"}

    return TestClient(app)


class TestStorefrontAuthMiddleware:
    @pytest.mark.parametrize("admin_key", ["", None])
    def test_open_development_uses_stable_principal(self, admin_key):
        response = _client(admin_key).get("/api/v1/jobs/")
        assert response.status_code == 200
        assert response.json()["principal"] == LOCAL_DEVELOPMENT_PRINCIPAL

    def test_rejects_missing_key(self):
        assert _client("secret").get("/api/v1/jobs/").status_code == 401

    def test_rejects_wrong_key(self):
        response = _client("secret").get(
            "/api/v1/jobs/",
            headers={"X-Admin-Key": "nope"},
        )
        assert response.status_code == 401

    def test_legacy_key_maps_to_explicit_principal(self):
        response = _client("secret").get(
            "/api/v1/jobs/",
            headers={"X-Admin-Key": "secret", "X-Agent-ID": "spoofed"},
        )
        assert response.status_code == 200
        assert response.json() == {
            "ok": True,
            "principal": LEGACY_STOREFRONT_PRINCIPAL,
        }

    @pytest.mark.parametrize(
        ("secret", "principal"),
        [("seller-a-secret", "seller-a"), ("seller-b-secret", "seller-b")],
    )
    def test_distinct_keys_bind_distinct_principals(self, secret, principal):
        response = _client(
            None,
            principal_keys={
                "seller-a": "seller-a-secret",
                "seller-b": "seller-b-secret",
            },
        ).get(
            "/api/v1/jobs/",
            headers={"X-Admin-Key": secret, "X-Agent-ID": "other"},
        )
        assert response.status_code == 200
        assert response.json()["principal"] == principal

    def test_health_bypasses_gate(self):
        assert _client("secret").get("/health").status_code == 200


def test_principal_configuration_accepts_json_and_rejects_shared_secrets():
    assert configured_storefront_principals(
        admin_key=None,
        principal_keys='{"seller-a":"secret-a"}',
    ) == {"seller-a": "secret-a"}
    with pytest.raises(ValueError, match="distinct secret"):
        configured_storefront_principals(
            admin_key=None,
            principal_keys={"seller-a": "same", "seller-b": "same"},
        )
