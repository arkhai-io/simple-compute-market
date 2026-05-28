"""
Smoke tests for the deployed provisioning service.

Scope (per Architecture.md — Smoke Tests jurisdiction):
  - The service is reachable and healthy
  - The host registry API responds correctly
  - Ansible readiness endpoint returns structured diagnostics
  - Auth enforcement is tested only when the shared admin key is configured
    (the storefront presents it as X-Admin-Key)

These tests are stateless and idempotent. They do not submit Ansible jobs
or modify persistent state (other than a transient test-host registration
that is cleaned up in the same test).

Run against a deployed stack::

    pytest -m provisioning_smoke

Required config (via ACTIVE_PROFILES + mounted config file, or env var override):
  provisioning:
    api_url: "http://<host>:<port>"
  seller:
    admin_api_key: "<shared secret, matches the provisioning storefront_admin_key>"
"""

from __future__ import annotations

import logging

import httpx
import pytest

from src.settings import settings

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _provisioning_settings() -> dict:
    try:
        return dict(settings.get("provisioning", {}))
    except Exception:
        return {}


def _api_url() -> str:
    url = _provisioning_settings().get("api_url", "")
    if not url:
        pytest.fail(
            "provisioning.api_url is not configured.\n"
            "Set it via your active config profile or "
            "ARKHAI_PROVISIONING__API_URL env var."
        )
    return url.rstrip("/")


def _admin_key() -> str:
    """The shared secret the storefront presents to provisioning as X-Admin-Key.

    Configured under the seller section because it is the operator's single
    ``admin_api_key`` — the same key the storefront's own /admin/* routes use.
    """
    try:
        return str(dict(settings.get("seller", {})).get("admin_api_key", "") or "")
    except Exception:
        return ""


def _client() -> httpx.Client:
    return httpx.Client(base_url=_api_url(), timeout=15.0)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.provisioning
class TestProvisioningSmoke:

    def test_health_returns_ok(self):
        """GET /health → 200 with status field present."""
        with _client() as client:
            resp = client.get("/health")
        assert resp.status_code == 200, f"Health check failed: {resp.text}"
        data = resp.json()
        assert "status" in data, f"Missing status field: {data}"
        assert data["status"] in ("ok", "degraded"), f"Unexpected status: {data['status']}"
        log.info("Health: %s", data)

    def test_ansible_readiness_returns_structured_response(self):
        """GET /api/v1/system/ansible/readiness → 200 with inventory and playbook fields."""
        with _client() as client:
            resp = client.get("/api/v1/system/ansible/readiness")
        assert resp.status_code == 200, f"Readiness check failed: {resp.text}"
        data = resp.json()
        assert "inventory" in data, f"Missing inventory field: {data}"
        assert "playbook" in data, f"Missing playbook field: {data}"
        assert "ssh_keys" in data, f"Missing ssh_keys field: {data}"
        inv = data["inventory"]
        assert "source" in inv
        assert "host_count" in inv
        log.info(
            "Readiness: ansible_version=%s, host_count=%s",
            data.get("ansible_version"),
            inv.get("host_count"),
        )

    def test_list_hosts_returns_200(self):
        """GET /api/v1/hosts/ → 200 with a hosts list."""
        with _client() as client:
            resp = client.get("/api/v1/hosts/")
        assert resp.status_code == 200, f"List hosts failed: {resp.text}"
        data = resp.json()
        assert "hosts" in data, f"Missing hosts field: {data}"
        log.info("Registered hosts: %d", len(data["hosts"]))

    def test_connectivity_check_on_first_host_if_available(self):
        """If any hosts are registered, GET /hosts/{name}/connectivity returns a result."""
        with _client() as client:
            list_resp = client.get("/api/v1/hosts/")
        assert list_resp.status_code == 200
        hosts = list_resp.json().get("hosts", [])
        if not hosts:
            pytest.skip("No hosts registered — skipping connectivity check")

        first = hosts[0]["name"]
        with _client() as client:
            resp = client.get(f"/api/v1/hosts/{first}/connectivity")
        assert resp.status_code == 200, f"Connectivity check failed: {resp.text}"
        data = resp.json()
        assert "reachable" in data, f"Missing reachable field: {data}"
        log.info("Connectivity for %s: reachable=%s", first, data["reachable"])

    def test_host_crud_round_trip(self):
        """Register → GET → disable → re-enable → cleanup a transient test host.

        Idempotent against a persistent DB: if smoke-test-host already exists
        from a prior run (disable left the row in place), we update it rather
        than attempting a duplicate INSERT.
        """
        test_host = {
            "name": "smoke-test-host",
            "kvm_host": "192.0.2.1",   # TEST-NET — never routes
            "ssh_user": "ubuntu",
            "ssh_key_type": "path",
            "ssh_key_value": "/home/appuser/.ssh/id_ed25519",
            "gpu_count": 0,
            "enabled": True,
        }
        with _client() as client:
            # Upsert: try to register; if the host already exists (409) from a
            # prior test run, update it instead so the test is idempotent.
            reg = client.post("/api/v1/hosts/", json=test_host)
            if reg.status_code == 409:
                log.info("smoke-test-host already exists — updating instead of inserting")
                reg = client.put("/api/v1/hosts/smoke-test-host", json={
                    "kvm_host": test_host["kvm_host"],
                    "ssh_user": test_host["ssh_user"],
                })
                assert reg.status_code == 200, f"Update failed: {reg.text}"
                # Re-enable in case it was left disabled
                client.post("/api/v1/hosts/smoke-test-host/enable")
            else:
                assert reg.status_code == 201, f"Register failed: {reg.text}"
            assert reg.json()["name"] == "smoke-test-host"
            assert "ssh_key_value" not in reg.json(), "ssh_key_value must never be returned"

            # GET
            get = client.get("/api/v1/hosts/smoke-test-host")
            assert get.status_code == 200
            assert get.json()["kvm_host"] == "192.0.2.1"

            # Disable
            dis = client.post("/api/v1/hosts/smoke-test-host/disable")
            assert dis.status_code == 200
            assert dis.json()["enabled"] is False

            # Confirm excluded from default list
            lst = client.get("/api/v1/hosts/")
            names = [h["name"] for h in lst.json()["hosts"]]
            assert "smoke-test-host" not in names

            # Re-enable
            ena = client.post("/api/v1/hosts/smoke-test-host/enable")
            assert ena.status_code == 200
            assert ena.json()["enabled"] is True

            # Cleanup — disable (no hard delete)
            client.post("/api/v1/hosts/smoke-test-host/disable")

        log.info("Host CRUD round-trip passed")

    def test_auth_enforcement_when_enabled(self):
        """POST /api/v1/hosts/{host}/vms/ without X-Admin-Key → 401 when a key is set.

        Stays within smoke-test scope: it never submits a real job. The gate
        rejects the request before the body reaches the controller.
        """
        if not _admin_key():
            pytest.skip("No admin key configured on this deployment — skipping 401 check")
        with _client() as client:
            resp = client.post(
                "/api/v1/hosts/kvm1/vms/",
                json={"vm_target": "smoke-test-vm"},
                # Intentionally no X-Admin-Key header
            )
        assert resp.status_code == 401, (
            f"Expected 401 without admin key, got {resp.status_code}: {resp.text}"
        )
        log.info("Auth enforcement confirmed: 401 without X-Admin-Key")
