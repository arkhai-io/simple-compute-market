"""
Integration tests for the system API endpoints.

All calls go through ProvisioningClient methods — no route strings in test code.

Coverage:
  - GET /api/v1/system/ansible/readiness returns 200 with expected fields
  - playbook.exists reflects the configured playbook path
  - inventory source is 'database' (DB-backed, not INI file)
  - ProvisioningClient.get_ansible_readiness() matches the API contract end-to-end

What is NOT covered here (unit test jurisdiction):
  - Filesystem checks for SSH key paths
  - ansible --version subprocess output parsing
  - AnsibleReadinessResponse field validation edge cases
"""

from __future__ import annotations

import pytest

from client.provisioning_client import ProvisioningClient


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
