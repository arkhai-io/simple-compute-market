"""
Integration tests for the system API endpoints.

All calls go through ProvisioningClient methods — no route strings in test code.

Coverage:
  - GET /health — fast liveness probe (api, database, job_processor checks only)
  - GET /api/v1/system/status — full diagnostic status (storefront checks, watchdog state)
  - GET /api/v1/system/ansible/readiness — Ansible config diagnostics

What is NOT covered here (unit test jurisdiction):
  - Filesystem checks for SSH key paths
  - ansible --version subprocess output parsing
  - AnsibleReadinessResponse field validation edge cases
  - get_status() HTTP logic — covered by SystemService unit tests
"""

from __future__ import annotations

import pytest

class TestHealthEndpoint:
    """GET /health — fast liveness probe via ProvisioningClient.get_health().

    The health endpoint performs only local checks (api, database, job_processor).
    It must never make outbound HTTP calls — that would make it unsuitable as a
    Kubernetes liveness/readiness probe.
    """

    async def test_returns_status_and_checks(self, client_and_queue):
        """Response always contains 'status' and 'checks' keys."""
        client, _ = client_and_queue
        resp = await client.get_health()
        assert isinstance(resp, dict), f"Expected dict, got {type(resp)}"
        assert "status" in resp, f"Missing 'status' in health response: {resp}"
        assert "checks" in resp, f"Missing 'checks' in health response: {resp}"

    async def test_local_checks_present(self, client_and_queue):
        """Health response includes api, database, and job_processor checks."""
        client, _ = client_and_queue
        resp = await client.get_health()
        checks = resp.get("checks", {})
        assert "api" in checks, f"Missing 'api' check: {checks}"
        assert "database" in checks, f"Missing 'database' check: {checks}"
        assert "job_processor" in checks, f"Missing 'job_processor' check: {checks}"

    async def test_api_check_is_ok(self, client_and_queue):
        """checks.api is always 'ok' when the service is reachable."""
        client, _ = client_and_queue
        resp = await client.get_health()
        assert resp["checks"].get("api") == "ok"

    async def test_database_check_is_ok(self, client_and_queue):
        """checks.database is 'ok' against the in-memory test DB."""
        client, _ = client_and_queue
        resp = await client.get_health()
        assert resp["checks"].get("database") == "ok", (
            f"Database check failed: {resp['checks'].get('database')}"
        )

    async def test_no_storefront_checks_in_health(self, client_and_queue):
        """Health endpoint must NOT include storefront or lease_watchdog checks.

        These are outbound/heavyweight checks that belong in /api/v1/system/status,
        not the fast liveness probe.
        """
        client, _ = client_and_queue
        resp = await client.get_health()
        checks = resp.get("checks", {})
        assert "storefront" not in checks, (
            "storefront check must not appear in /health — it makes an outbound "
            "HTTP call which would make the liveness probe fail during storefront restarts."
        )
        assert "storefront_auth" not in checks, (
            "storefront_auth check must not appear in /health."
        )
        assert "lease_watchdog" not in checks, (
            "lease_watchdog check must not appear in /health."
        )


class TestSystemStatus:
    """GET /api/v1/system/status — full diagnostic status via get_system_status().

    This endpoint includes outbound storefront connectivity checks and watchdog
    state. In the integration test environment there is no real storefront, so
    the storefront checks will reflect that (unreachable or unconfigured).

    Tests assert structure and value domain — not specific connectivity outcomes,
    which depend on the deployment environment.
    """

    _STOREFRONT_VALUES = {"ok", "unreachable", "timeout", "unconfigured"}
    _AUTH_VALUES = {"ok", "unauthorized", "unconfigured", "unreachable", "timeout"}
    _WATCHDOG_VALUES = {"running", "paused", "disabled"}

    async def test_returns_status_and_checks(self, client_and_queue):
        """Response always contains 'status' and 'checks' keys."""
        client, _ = client_and_queue
        resp = await client.get_system_status()
        assert isinstance(resp, dict), f"Expected dict, got {type(resp)}"
        assert "status" in resp, f"Missing 'status' in status response: {resp}"
        assert "checks" in resp, f"Missing 'checks' in status response: {resp}"

    async def test_storefront_check_is_present(self, client_and_queue):
        """checks.storefront is present in the diagnostic status."""
        client, _ = client_and_queue
        resp = await client.get_system_status()
        checks = resp.get("checks", {})
        assert "storefront" in checks, (
            f"Missing 'storefront' check in /api/v1/system/status: {checks}"
        )

    async def test_storefront_auth_check_is_present(self, client_and_queue):
        """checks.storefront_auth is present in the diagnostic status."""
        client, _ = client_and_queue
        resp = await client.get_system_status()
        checks = resp.get("checks", {})
        assert "storefront_auth" in checks, (
            f"Missing 'storefront_auth' check in /api/v1/system/status: {checks}"
        )

    async def test_lease_watchdog_check_is_present(self, client_and_queue):
        """checks.lease_watchdog is present in the diagnostic status."""
        client, _ = client_and_queue
        resp = await client.get_system_status()
        checks = resp.get("checks", {})
        assert "lease_watchdog" in checks, (
            f"Missing 'lease_watchdog' check in /api/v1/system/status: {checks}"
        )

    async def test_storefront_check_has_valid_value(self, client_and_queue):
        """checks.storefront value is one of the documented domain values."""
        client, _ = client_and_queue
        resp = await client.get_system_status()
        value = resp["checks"].get("storefront", "")
        # Also allow http_N responses
        assert (
            value in self._STOREFRONT_VALUES
            or (isinstance(value, str) and value.startswith("http_"))
            or (isinstance(value, str) and value.startswith("error:"))
        ), (
            f"checks.storefront={value!r} is not a documented value. "
            f"Expected one of {self._STOREFRONT_VALUES} or http_N / error:*"
        )

    async def test_storefront_auth_check_has_valid_value(self, client_and_queue):
        """checks.storefront_auth value is one of the documented domain values."""
        client, _ = client_and_queue
        resp = await client.get_system_status()
        value = resp["checks"].get("storefront_auth", "")
        assert (
            value in self._AUTH_VALUES
            or (isinstance(value, str) and value.startswith("http_"))
            or (isinstance(value, str) and value.startswith("error:"))
        ), (
            f"checks.storefront_auth={value!r} is not a documented value. "
            f"Expected one of {self._AUTH_VALUES} or http_N / error:*"
        )

    async def test_lease_watchdog_check_has_valid_value(self, client_and_queue):
        """checks.lease_watchdog value is one of: running, paused, disabled."""
        client, _ = client_and_queue
        resp = await client.get_system_status()
        value = resp["checks"].get("lease_watchdog", "")
        assert value in self._WATCHDOG_VALUES, (
            f"checks.lease_watchdog={value!r} is not a documented value. "
            f"Expected one of {self._WATCHDOG_VALUES}"
        )

    async def test_watchdog_disabled_in_test_environment(self, client_and_queue):
        """Watchdog reports 'disabled' when lease_watchdog_enabled=False in test settings.

        Integration tests set lease_watchdog_enabled=False (conftest mock_settings)
        to prevent background timer cycles. The status endpoint reflects this.
        """
        client, _ = client_and_queue
        resp = await client.get_system_status()
        assert resp["checks"].get("lease_watchdog") == "disabled", (
            f"Expected lease_watchdog='disabled' in test environment "
            f"(lease_watchdog_enabled=False in mock_settings), "
            f"got {resp['checks'].get('lease_watchdog')!r}"
        )

    async def test_storefront_checks_reflect_configured_url(self, client_and_queue):
        """When storefront_url is configured but not reachable, storefront='unreachable'.

        The test conftest sets storefront_url='http://test-storefront:8001' — a URL
        that is configured but not reachable in the test environment. This confirms
        the connectivity probe actually runs (rather than returning 'unconfigured').
        """
        client, _ = client_and_queue
        resp = await client.get_system_status()
        storefront_val = resp["checks"].get("storefront")
        # URL is configured, so must not be 'unconfigured'
        assert storefront_val != "unconfigured", (
            f"Expected storefront check to attempt a connection since storefront_url "
            f"is set in mock_settings, but got 'unconfigured'. "
            f"Check that mock_settings.storefront_url is non-empty in conftest."
        )
        # Must be unreachable (no real storefront in test env)
        assert storefront_val in ("unreachable", "timeout") or (
            isinstance(storefront_val, str) and storefront_val.startswith("error:")
        ), (
            f"Expected storefront check to be unreachable/timeout in test env, "
            f"got {storefront_val!r}"
        )

    async def test_status_does_not_include_local_probe_checks(self, client_and_queue):
        """The status endpoint does not duplicate /health's local checks.

        api, database, and job_processor are liveness-probe concerns belonging
        to /health. The status endpoint focuses on connectivity diagnostics.
        """
        client, _ = client_and_queue
        resp = await client.get_system_status()
        checks = resp.get("checks", {})
        assert "api" not in checks, (
            "checks.api should not appear in /api/v1/system/status — it belongs in /health."
        )
        assert "database" not in checks, (
            "checks.database should not appear in /api/v1/system/status — it belongs in /health."
        )

    async def test_status_and_health_are_independent(self, client_and_queue):
        """Both endpoints return independently — status degraded doesn't affect health.

        The health endpoint must return 200/ok even when the status endpoint
        reports storefront connectivity issues.
        """
        client, _ = client_and_queue
        health = await client.get_health()
        status = await client.get_system_status()

        # Health should be ok (local checks pass in test env)
        assert health.get("status") == "ok", (
            f"Expected health=ok but got {health.get('status')!r}. "
            f"Local checks should always pass: {health.get('checks')}"
        )
        # Status may be degraded (storefront unreachable) — that's expected
        assert "status" in status



class TestAnsibleReadiness:
    """GET /api/v1/system/ansible/readiness via ProvisioningClient."""

    async def test_returns_200_with_expected_top_level_fields(self, client_and_queue):
        """Endpoint returns a dict with the documented top-level keys."""
        client, _ = client_and_queue
        resp = await client.get_ansible_readiness()
        assert isinstance(resp, dict)
        assert "playbook" in resp, f"Missing 'playbook' key in response: {resp}"
        assert "inventory" in resp, f"Missing 'inventory' key in response: {resp}"
        assert "ssh_keys" in resp, f"Missing 'ssh_keys' key in response: {resp}"
        # ansible_version may be None when ansible is not on PATH (expected in test env)
        assert "ansible_version" in resp, f"Missing 'ansible_version' key in response: {resp}"

    async def test_playbook_has_exists_field(self, client_and_queue):
        """playbook sub-object always has an 'exists' boolean field."""
        client, _ = client_and_queue
        resp = await client.get_ansible_readiness()
        playbook = resp.get("playbook", {})
        assert isinstance(playbook, dict), f"Expected playbook to be a dict, got: {playbook!r}"
        assert "exists" in playbook, f"Missing 'exists' in playbook: {playbook}"
        assert isinstance(playbook["exists"], bool)

    async def test_playbook_has_path_field(self, client_and_queue):
        """playbook sub-object always has a 'path' string field."""
        client, _ = client_and_queue
        resp = await client.get_ansible_readiness()
        playbook = resp.get("playbook", {})
        assert "path" in playbook, f"Missing 'path' in playbook: {playbook}"
        assert isinstance(playbook["path"], str)

    async def test_inventory_source_is_database(self, client_and_queue):
        """Inventory is sourced from the DB (not an INI file on disk)."""
        client, _ = client_and_queue
        resp = await client.get_ansible_readiness()
        inventory = resp.get("inventory", {})
        assert isinstance(inventory, dict), f"Expected inventory dict, got: {inventory!r}"
        assert inventory.get("source") == "database", (
            f"Expected inventory source='database', got {inventory.get('source')!r}. "
            "Integration tests use DB-backed inventory — not INI files."
        )

    async def test_inventory_has_host_count(self, client_and_queue):
        """inventory.host_count reflects enabled hosts in the DB (0 on fresh DB)."""
        client, _ = client_and_queue
        resp = await client.get_ansible_readiness()
        inventory = resp.get("inventory", {})
        host_count = inventory.get("host_count")
        # May be None if HostService isn't wired, or 0 on a fresh DB — both valid
        assert host_count is None or isinstance(host_count, int), (
            f"Expected host_count to be int or None, got {host_count!r}"
        )

    async def test_ssh_keys_is_list(self, client_and_queue):
        """ssh_keys is always a list (empty on fresh DB with no hosts)."""
        client, _ = client_and_queue
        resp = await client.get_ansible_readiness()
        ssh_keys = resp.get("ssh_keys")
        assert isinstance(ssh_keys, list), (
            f"Expected ssh_keys to be a list, got {ssh_keys!r}"
        )

    async def test_endpoint_always_returns_200(self, client_and_queue):
        """Readiness endpoint returns 200 even when ansible is not configured.

        The endpoint is diagnostic — it reports state rather than asserting
        health. Only /health returns 503 on degraded state.
        """
        client, _ = client_and_queue
        # If this raises ProvisioningError the status was not 200
        resp = await client.get_ansible_readiness()
        assert resp is not None


class TestEvaluateJob:
    """POST /test/evaluate-job — dry-run job evaluation via AsyncProvisioningTestClient."""

    async def test_returns_expected_fields(self, test_client):
        """Endpoint returns a dict with params_valid, host_exists, rule_matched, would_pause, errors."""
        resp = await test_client.evaluate_job(
            "non-existent-host",
            vm_target="eval-target",
            vm_action="create",
        )
        assert isinstance(resp, dict)
        assert "params_valid" in resp
        assert "host_exists" in resp
        assert "rule_matched" in resp
        assert "would_pause" in resp
        assert "errors" in resp

    async def test_unknown_host_returns_host_exists_false(self, test_client):
        """Host not in inventory → host_exists=False, errors mentions inventory."""
        resp = await test_client.evaluate_job(
            "definitely-not-a-real-host",
            vm_action="create",
        )
        assert resp.get("host_exists") is False
        assert resp.get("params_valid") is False
        errors = resp.get("errors", [])
        assert any("host" in e.lower() or "inventory" in e.lower() for e in errors), (
            f"Expected an error mentioning host/inventory, got: {errors}"
        )

    async def test_no_armed_rule_returns_rule_matched_none(self, test_client):
        """When no mock rules are armed, rule_matched=None and would_pause=False."""
        resp = await test_client.evaluate_job("some-host", vm_action="create")
        assert resp.get("rule_matched") is None
        assert resp.get("would_pause") is False

    async def test_armed_rule_is_reflected(self, test_client):
        """After arming a mock rule, evaluate_job returns rule_matched and would_pause."""
        rule_id = "eval-job-test-rule"
        await test_client.add_mock_rule(
            rule_id=rule_id,
            match={"vm_action": "create"},
            pause_before_result=True,
        )
        try:
            resp = await test_client.evaluate_job("any-host", vm_action="create")
            assert resp.get("rule_matched") == rule_id, (
                f"Expected rule_matched={rule_id!r}, got {resp.get('rule_matched')!r}"
            )
            assert resp.get("would_pause") is True
        finally:
            await test_client.delete_mock_rule(rule_id)
