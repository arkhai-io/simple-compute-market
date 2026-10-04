"""
Unit tests for AnsibleJobService's submissions and retry policy.

Covers: the route key and host a VM job is submitted under, and the retry
policy read from settings. Orchestration methods (submit, list_jobs,
_process_job, etc.) delegate to the DB and queue — they are exercised in
integration tests; how the VM codec interprets parameters and output is
covered in test_vm_codec.py.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from arkhai_bare_metal import (
    BARE_METAL_ACCESS_ACTIONS,
    NODE_RECLAIM_ACCESS_ACTION,
)
from compute_provisioning import JobExecutorTable, UnsupportedExecutorActionError
from vm_provisioning_adapter.bundle import VM_JOB_ACTIONS
from bare_metal_provisioning_adapter.codec import BareMetalAnsibleCodec
from compute_provisioning_ansible import AnsibleJobExecutor
from vm_provisioning_adapter.codec import VmAnsibleCodec
from vm_provisioning_adapter.models.jobs_model import VmJobParams
from vm_provisioning_adapter.services.job_service import AnsibleJobService, retry_policy_from


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


def _make_service(*, host_service=None, **settings_overrides) -> AnsibleJobService:
    """A job service over ``_executors``, which ``svc._engine_executors`` exposes."""
    settings = MagicMock()
    settings.default_host_id = "kvm1"
    settings.default_max_retries = 3
    settings.retry_backoff_initial_seconds = 60
    settings.retry_backoff_multiplier = 2.0
    settings.retry_backoff_max_seconds = 3600
    settings.additional_non_retryable_errors = [
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

    executors = _executors(settings)
    service = AnsibleJobService(
        settings=settings,
        session_factory=MagicMock(),
        executors=executors,
        host_service=host_service if host_service is not None else MagicMock(),
    )
    service._engine_executors = executors
    return service


def _executors(settings, runner=None):
    runner = runner if runner is not None else MagicMock()
    vm = AnsibleJobExecutor(
        runner, VmAnsibleCodec(), settings.resolved_playbook_path, timeout_seconds=30,
    )
    bare_metal = AnsibleJobExecutor(
        runner,
        BareMetalAnsibleCodec(),
        settings.resolved_bare_metal_playbook_path,
        timeout_seconds=30,
    )
    table = JobExecutorTable()
    for action in VM_JOB_ACTIONS:
        table.register("vm", action, vm)
    for action in BARE_METAL_ACCESS_ACTIONS:
        table.register("bare_metal", action, bare_metal)
    table.freeze()
    return table


class _RecordingEngine:
    def __init__(self) -> None:
        self.submitted: list[dict] = []

    async def submit(self, **fields):
        self.submitted.append(fields)
        return None


def _submitted(svc, params: VmJobParams) -> dict:
    import asyncio

    engine = _RecordingEngine()
    svc._engine = engine
    asyncio.run(svc.submit(params, job_queue=object()))
    return engine.submitted[0]


class TestSubmission:
    """A job is submitted under its offering mode, action, and host."""

    def test_vm_actions_use_the_vm_registration(self):
        svc = _make_service()
        params = VmJobParams(host_id="kvm1", vm_action="create", offering_mode="vm")

        fields = _submitted(svc, params)

        assert (fields["offering_mode"], fields["action"], fields["host_id"]) == (
            "vm", "create", "kvm1",
        )
        assert svc._engine_executors.resolve("vm", "create").playbook_path == Path(
            "/playbooks/vm-operations.yaml"
        )

    def test_bare_metal_actions_use_the_bare_metal_registration(self):
        svc = _make_service()

        assert svc._engine_executors.resolve(
            "bare_metal", NODE_RECLAIM_ACCESS_ACTION
        ).playbook_path == Path("/playbooks/node-access.yaml")

    def test_executor_action_takes_precedence_over_vm_action(self):
        svc = _make_service()
        params = VmJobParams(
            host_id="kvm1",
            vm_action="vm_remove",
            offering_mode="vm",
            executor_action="destroy",
        )

        assert _submitted(svc, params)["action"] == "destroy"

    def test_an_unregistered_mode_and_action_is_refused(self):
        svc = _make_service()

        with pytest.raises(UnsupportedExecutorActionError):
            svc._engine_executors.resolve("bare_metal", "create")

    def test_a_job_naming_no_host_runs_against_its_target_or_the_default(self):
        svc = _make_service()

        targeted = VmJobParams(
            host_id=None, vm_action="create", offering_mode="vm", executor_target="kvm9"
        )
        untargeted = VmJobParams(host_id=None, vm_action="create", offering_mode="vm")

        assert _submitted(svc, targeted)["host_id"] == "kvm9"
        assert _submitted(svc, untargeted)["host_id"] == "kvm1"

    def test_its_parameters_are_stored_as_submitted(self):
        import dataclasses

        svc = _make_service()
        params = VmJobParams(host_id="kvm1", vm_action="create", offering_mode="vm")

        assert _submitted(svc, params)["params"] == dataclasses.asdict(params)


# ---------------------------------------------------------------------------
# retry_policy_from
# ---------------------------------------------------------------------------


class TestRetryPolicyFromSettings:
    def _policy(self, **overrides):
        return retry_policy_from(_make_service(**overrides)._settings)

    def test_delays_grow_by_the_multiplier(self):
        policy = self._policy(retry_backoff_initial_seconds=60, retry_backoff_multiplier=2.0)
        assert [policy.delay_seconds(n) for n in range(3)] == [60, 120, 240]

    def test_capped_at_max(self):
        policy = self._policy(
            retry_backoff_initial_seconds=60,
            retry_backoff_multiplier=2.0,
            retry_backoff_max_seconds=200,
        )
        assert policy.delay_seconds(2) == 200

    def test_the_default_retry_count_is_the_deployment_s(self):
        assert self._policy(default_max_retries=5).default_max_retries == 5


def test_the_host_registry_is_required():
    """The registry is a job's only inventory source, so it cannot be omitted."""
    with pytest.raises(TypeError):
        AnsibleJobService(
            settings=MagicMock(),
            session_factory=MagicMock(),
            executors=MagicMock(),
        )
