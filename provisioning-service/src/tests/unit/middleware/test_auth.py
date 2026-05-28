"""Unit tests for StorefrontAuthMiddleware — the shared X-Admin-Key gate.

The provisioning service is an internal dependency of one storefront. The
gate enforces only "this request came from my storefront": both sides hold
the operator's admin key, presented as ``X-Admin-Key``. An empty key opens
the gate (local dev); ``/health`` and docs routes are always open.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from middleware.auth import StorefrontAuthMiddleware


def _client(admin_key: str | None) -> TestClient:
    app = FastAPI()
    app.add_middleware(StorefrontAuthMiddleware, admin_key=admin_key)

    @app.get("/api/v1/jobs/")
    def _jobs() -> dict:
        return {"ok": True}

    @app.get("/health")
    def _health() -> dict:
        return {"status": "ok"}

    return TestClient(app)


class TestStorefrontAuthMiddleware:
    @pytest.mark.parametrize("admin_key", ["", None])
    def test_open_when_no_key_configured(self, admin_key):
        assert _client(admin_key).get("/api/v1/jobs/").status_code == 200

    def test_rejects_missing_key(self):
        assert _client("secret").get("/api/v1/jobs/").status_code == 401

    def test_rejects_wrong_key(self):
        resp = _client("secret").get("/api/v1/jobs/", headers={"X-Admin-Key": "nope"})
        assert resp.status_code == 401

    def test_accepts_correct_key(self):
        resp = _client("secret").get("/api/v1/jobs/", headers={"X-Admin-Key": "secret"})
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    def test_health_bypasses_gate(self):
        assert _client("secret").get("/health").status_code == 200
