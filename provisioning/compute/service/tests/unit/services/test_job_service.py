"""
Unit tests for AnsibleJobService's routing and retry arithmetic.

Covers: which executor a job's stored parameters select, and retry delays.
Orchestration methods (submit, list_jobs, _process_job, etc.) delegate to
the DB and queue — they are exercised in integration tests; how an executor
interprets parameters and output is covered in test_ansible_job_executor.py.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from arkhai_bare_metal import (
    BARE_METAL_ACCESS_ACTIONS,
    NODE_GRANT_ACCESS_ACTION,
    NODE_RECLAIM_ACCESS_ACTION,
)
from compute_provisioning import JobExecutorTable, UnsupportedExecutorActionError
from vm_provisioning_adapter.bundle import VM_JOB_ACTIONS
from vm_provisioning_adapter.models.jobs_model import AnsibleJobParams
from vm_provisioning_adapter.services.ansible_job_executor import AnsibleJobExecutor
from vm_provisioning_adapter.services.job_service import AnsibleJobService


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


def _make_service(*, host_service=None, **settings_overrides) -> AnsibleJobService:
    settings = MagicMock()
    settings.default_host_id = "kvm1"
    settings.default_max_retries = 3
    settings.retry_backoff_initial_seconds = 60
    settings.retry_backoff_multiplier = 2.0
    settings.retry_backoff_max_seconds = 3600
    settings.non_retryable_errors = [
        "Invalid SSH key",
        "VM target not found",
        "Permission denied",
        "Authentication failed",
        "UNREACHABLE",
        "Domain not found",
    ]
    settings.resolved_playbook_path = Path("/playbooks/vm-operations.yaml")
    settings.resolved_bare_metal_playbook_path = Path("/playbooks/node-access.yaml")
    for k, v in settings_overrides.items():
        setattr(settings, k, v)

    return AnsibleJobService(
        settings=settings,
        session_factory=MagicMock(),
        executors=_executors(settings),
        host_service=host_service if host_service is not None else MagicMock(),
    )


def _executors(settings, runner=None):
    runner = runner if runner is not None else MagicMock()
    vm = AnsibleJobExecutor(runner, settings.resolved_playbook_path, settings=settings)
    bare_metal = AnsibleJobExecutor(
        runner, settings.resolved_bare_metal_playbook_path, settings=settings
    )
    table = JobExecutorTable()
    for action in VM_JOB_ACTIONS:
        table.register("vm", action, vm)
    for action in BARE_METAL_ACCESS_ACTIONS:
        table.register("bare_metal", action, bare_metal)
    table.freeze()
    return table


# ---------------------------------------------------------------------------
# _build_params
# ---------------------------------------------------------------------------


class TestExecutorSelection:
    """A job's stored parameters name its offering mode, action, and host."""

    def _resolved(self, svc, params: AnsibleJobParams):
        import dataclasses

        offering_mode, action, host_id = svc._route(dataclasses.asdict(params))
        return svc._executors.resolve(offering_mode, action), action, host_id

    def test_vm_actions_use_the_vm_registration(self):
        svc = _make_service()
        executor, action, host_id = self._resolved(
            svc, AnsibleJobParams(host_id="kvm1", vm_action="create", offering_mode="vm")
        )

        assert executor._playbook_path == Path("/playbooks/vm-operations.yaml")
        assert (action, host_id) == ("create", "kvm1")

    def test_bare_metal_actions_use_the_bare_metal_registration(self):
        svc = _make_service()
        executor, _, _ = self._resolved(
            svc,
            AnsibleJobParams(
                host_id="bm-node-1",
                vm_action=NODE_RECLAIM_ACCESS_ACTION,
                offering_mode="bare_metal",
            ),
        )

        assert executor._playbook_path == Path("/playbooks/node-access.yaml")

    def test_executor_action_takes_precedence_over_vm_action(self):
        svc = _make_service()
        executor, action, _ = self._resolved(
            svc,
            AnsibleJobParams(
                host_id="bm-node-1",
                vm_action="create",
                offering_mode="bare_metal",
                executor_action=NODE_GRANT_ACCESS_ACTION,
            ),
        )

        assert action == NODE_GRANT_ACCESS_ACTION
        assert executor._playbook_path == Path("/playbooks/node-access.yaml")

    def test_an_unregistered_mode_and_action_is_refused(self):
        svc = _make_service()

        with pytest.raises(UnsupportedExecutorActionError):
            self._resolved(
                svc,
                AnsibleJobParams(
                    host_id="bm-node-1", vm_action="create", offering_mode="bare_metal"
                ),
            )

    def test_a_job_naming_no_host_runs_against_its_target_or_the_default(self):
        svc = _make_service()

        assert svc._route({"offering_mode": "vm", "executor_target": "kvm9"})[2] == "kvm9"
        assert svc._route({"offering_mode": "vm"})[2] == "kvm1"


# ---------------------------------------------------------------------------
# _calculate_retry_delay
# ---------------------------------------------------------------------------


class TestCalculateRetryDelay:
    def test_first_retry_uses_initial_seconds(self):
        svc = _make_service(retry_backoff_initial_seconds=60, retry_backoff_multiplier=2.0)
        assert svc._calculate_retry_delay(0) == 60

    def test_second_retry_doubles(self):
        svc = _make_service(retry_backoff_initial_seconds=60, retry_backoff_multiplier=2.0)
        assert svc._calculate_retry_delay(1) == 120

    def test_third_retry_quadruples(self):
        svc = _make_service(retry_backoff_initial_seconds=60, retry_backoff_multiplier=2.0)
        assert svc._calculate_retry_delay(2) == 240

    def test_capped_at_max(self):
        svc = _make_service(
            retry_backoff_initial_seconds=60,
            retry_backoff_multiplier=2.0,
            retry_backoff_max_seconds=200,
        )
        assert svc._calculate_retry_delay(2) == 200

    def test_returns_int(self):
        svc = _make_service()
        assert isinstance(svc._calculate_retry_delay(0), int)


def test_the_host_registry_is_required():
    """The registry is a job's only inventory source, so it cannot be omitted."""
    with pytest.raises(TypeError):
        AnsibleJobService(
            settings=MagicMock(),
            session_factory=MagicMock(),
            executors=MagicMock(),
        )
