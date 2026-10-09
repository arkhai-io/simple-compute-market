"""
Integration tests for the system API endpoints.

All calls go through the family client's methods — no route strings in test code.

Coverage:
  - GET /health — fast liveness probe (api, database, job_processor checks only)
  - GET /api/v1/system/status — operator status: storefront checks, watchdog
    state, the contract pin, execution, and the Ansible readiness component,
    composed from the harness's executors as production composes them
  - the convergence and lease-watchdog controls, including the advance refused
    while convergence runs

What is NOT covered here (unit test jurisdiction):
  - the readiness component's playbook, key, and version rules
    (the Ansible distribution's test_readiness.py)
  - status and health check arithmetic (unit/services/test_system_status.py)
  - a control whose worker is not composed (unit/test_system_controller.py)
"""

from __future__ import annotations

from bare_metal_provisioning_adapter.services.mock_output import bare_metal_mock_output
from compute_provisioning_ansible import MockAnsibleRunner
from compute_provisioning_ansible.readiness import (
    ANSIBLE_COMPONENT,
    ANSIBLE_READINESS_KIND,
    AnsibleReadinessDetail,
)
from compute_provisioning_client import ComputeProvisioningError
from compute_provisioning_contracts import (
    COMPUTE_PROVISIONING_CONTRACT_VERSION,
    SUPPORTED_COMPUTE_PROVISIONING_MAJOR_VERSIONS,
    HealthResponse,
    SystemStatusResponse,
)
import pytest
from vm_provisioning_adapter.services.mock_output import vm_mock_output

from compute_provisioning_service import container as _container_module
from compute_provisioning_service.services.system_status import (
    COMPONENT_FAILURE_KIND,
    StatusComponentProvider,
)


class TestHealthEndpoint:
    """GET /health — fast liveness probe via ComputeProvisioningClient.get_health().

    The health endpoint performs only local checks (api, database, job_processor).
    It must never make outbound HTTP calls — that would make it unsuitable as a
    Kubernetes liveness/readiness probe.
    """

    async def test_local_checks_only_and_ok(self, client_and_queue):
        client, _ = client_and_queue
        resp = await client.family.get_health()

        assert isinstance(resp, HealthResponse)
        assert resp.status == "ok"
        assert resp.checks == {"api": "ok", "database": "ok", "job_processor": "ok"}

    async def test_the_versioned_alias_answers_the_same(self, client_and_queue):
        client, _ = client_and_queue

        assert await client.family.get_system_health() == await client.family.get_health()

    async def test_health_carries_no_status_fields(self, client_and_queue):
        """The contract pin and execution are status's, not liveness's."""
        client, _ = client_and_queue
        resp = await client.family.get_health()

        assert set(resp.model_dump()) == {"status", "checks"}


class TestSystemStatus:
    """GET /api/v1/system/status — operator status via get_system_status().

    There is no real storefront here, so the storefront checks report it
    unreachable and the status is degraded; the typed client reads the 503
    body all the same.
    """

    _WATCHDOG_VALUES = {"running", "paused", "disabled"}

    async def test_returns_the_typed_status(self, client_and_queue):
        client, _ = client_and_queue
        resp = await client.family.get_system_status()

        assert isinstance(resp, SystemStatusResponse)
        assert {"storefront", "storefront_auth", "lease_watchdog", "execution"} <= set(
            resp.checks
        )

    async def test_reports_the_contract_pin_and_supported_majors(
        self, client_and_queue
    ):
        """A cutover requires every participant to report the contract major it
        speaks before mutations resume, and there is no other way to ask a
        running service for it."""
        client, _ = client_and_queue
        resp = await client.family.get_system_status()

        assert resp.provisioning_contract_version == COMPUTE_PROVISIONING_CONTRACT_VERSION
        assert sorted(resp.provisioning_contract_supported_majors) == sorted(
            SUPPORTED_COMPUTE_PROVISIONING_MAJOR_VERSIONS
        )
        assert (
            int(resp.provisioning_contract_version.split(".")[0])
            in resp.provisioning_contract_supported_majors
        )

    async def test_watchdog_disabled_in_test_environment(self, client_and_queue):
        """Integration tests set lease_watchdog_enabled=False (conftest
        mock_settings) to prevent background timer cycles."""
        client, _ = client_and_queue
        resp = await client.family.get_system_status()

        assert resp.checks["lease_watchdog"] == "disabled"

    async def test_storefront_checks_reflect_configured_url(self, client_and_queue):
        """storefront_url is configured but unreachable here, so the probe ran
        and failed rather than reporting 'unconfigured'; a failed reachability
        check is repeated as the authentication check."""
        client, _ = client_and_queue
        resp = await client.family.get_system_status()
        value = resp.checks["storefront"]

        assert value in ("unreachable", "timeout") or value.startswith("error:")
        assert resp.checks["storefront_auth"] == value
        assert resp.status == "degraded"

    async def test_status_does_not_include_local_probe_checks(self, client_and_queue):
        client, _ = client_and_queue
        resp = await client.family.get_system_status()

        assert not {"api", "database", "job_processor"} & set(resp.checks)

    async def test_execution_lists_every_composed_offering_mode(self, client_and_queue):
        """The harness composes both bundles over runners that are not the
        mock, so neither mode, nor the deployment, reports mocked execution."""
        client, _ = client_and_queue
        resp = await client.family.get_system_status()

        assert resp.execution.mocked is False
        assert {(e.offering_mode, e.mocked) for e in resp.execution.executors} == {
            ("vm", False),
            ("bare_metal", False),
        }

    async def test_the_ansible_component_reports_every_composed_playbook(
        self, client_and_queue
    ):
        """Bare metal's playbook is reported beside VM's, from the executors
        composed, and a missing playbook degrades execution."""
        client, _ = client_and_queue
        resp = await client.family.get_system_status()
        component = resp.component(ANSIBLE_COMPONENT)

        assert component is not None
        assert (component.detail.kind, component.detail.schema_version) == (
            ANSIBLE_READINESS_KIND,
            1,
        )
        detail = AnsibleReadinessDetail.model_validate(component.detail.payload)
        assert {(p.offering_mode, p.path, p.exists) for p in detail.playbooks} == {
            ("vm", "/fake/playbook.yml", False),
            ("bare_metal", "/fake/bare-metal-node-access.yml", False),
        }
        assert component.ready is False
        assert resp.checks["execution"] == "degraded"

    async def test_status_discloses_no_database_url(self, client_and_queue):
        client, _ = client_and_queue
        resp = await client.family.get_system_status()

        assert "sqlite://" not in resp.model_dump_json()

    async def test_status_and_health_are_independent(self, client_and_queue):
        """Health stays ok while status is degraded by an unreachable storefront."""
        client, _ = client_and_queue

        assert (await client.family.get_health()).status == "ok"
        assert (await client.family.get_system_status()).status == "degraded"


class TestComponentFailure:
    """A readiness component that fails is reported, not raised."""

    async def test_a_raising_component_degrades_status_through_the_route(
        self, client_and_queue, monkeypatch
    ):
        client, _ = client_and_queue
        composed = _container_module.resolved_system_status_service

        def raising():
            raise RuntimeError("component exploded")

        monkeypatch.setattr(
            composed,
            "_components",
            (*composed._components, StatusComponentProvider("exploding", raising)),
        )

        resp = await client.family.get_system_status()

        failed = resp.component("exploding")
        assert failed is not None and failed.ready is False
        assert failed.detail.kind == COMPONENT_FAILURE_KIND
        assert resp.component(ANSIBLE_COMPONENT) is not None
        assert resp.checks["execution"] == "degraded"


class TestWorkerControls:
    """The convergence and lease-watchdog controls bind the composed workers."""

    async def test_advance_is_refused_while_convergence_runs(self, client_and_queue):
        client, _ = client_and_queue

        with pytest.raises(ComputeProvisioningError) as raised:
            await client.family.advance_fulfillment_convergence_cycle()

        assert raised.value.status_code == 409

    async def test_a_paused_convergence_advances_then_resumes(self, client_and_queue):
        client, _ = client_and_queue

        assert await client.family.pause_fulfillment_convergence() == {"paused": True}
        try:
            advanced = await client.family.advance_fulfillment_convergence_cycle()
            ran = await client.family.run_fulfillment_convergence_cycle()
        finally:
            assert await client.family.resume_fulfillment_convergence() == {"paused": False}

        assert isinstance(advanced, dict) and isinstance(ran, dict)

    async def test_the_lease_watchdog_pauses_and_still_checks(self, client_and_queue):
        client, _ = client_and_queue

        assert await client.family.pause_lease_watchdog() == {"paused": True}
        try:
            cycle = await client.family.check_leases()
        finally:
            assert await client.family.resume_lease_watchdog() == {"paused": False}

        assert cycle["checked"] == 0


class TestMockedExecution:
    """With every composed executor the mock, the deployment reports mocked
    execution and the Ansible component is ready without Ansible or playbooks."""

    @pytest.fixture
    def fake_ansible(self):
        return MockAnsibleRunner(default_output=vm_mock_output)

    @pytest.fixture
    def bare_metal_runner(self):
        return MockAnsibleRunner(default_output=bare_metal_mock_output)

    async def test_every_executor_mocked(self, client_and_queue):
        client, _ = client_and_queue
        resp = await client.family.get_system_status()

        assert resp.execution.mocked is True
        assert all(executor.mocked for executor in resp.execution.executors)
        assert resp.component(ANSIBLE_COMPONENT).ready is True
        assert resp.checks["execution"] == "ok"


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
