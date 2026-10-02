"""Mock implementation of AnsibleService for use in the provisioning service's
'mock' ACTIVE_PROFILE.

Activated when ACTIVE_PROFILES includes 'mock'.  Returns deterministic
fake results with no subprocess invocations, no SSH, and no filesystem I/O
beyond reading the configured inventory path.

The mock is the provisioning service's responsibility, not the agent's.
Agents always call the provisioning service HTTP API; whether that service
runs real Ansible or this mock is a deployment concern controlled by the
ACTIVE_PROFILES environment variable on the provisioning service container.

Control hooks (constructor parameters)
---------------------------------------
``provision_result`` — dict returned as the parsed result for any create job.
``should_fail``      — if True, ``wait_for_playbook`` raises AnsibleError.
``fail_message``     — error string used when should_fail is True.

These are set once at construction.  For docker-compose e2e tests that need
to toggle failure mode, run two separate provisioning-service containers
configured with different profiles.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional
from unittest.mock import MagicMock

from compute_provisioning.jobs.executor_mock import MockRule, MockRuleSet
from compute_provisioning_ansible.runner import (
    AnsibleError,
    AnsibleResult,
    AnsibleRun,
    ConnectivityResult,
    MaterializedInventory,
)
from vm_provisioning_adapter.models.jobs_model import AnsibleJobParams, AnsibleRunResult

if TYPE_CHECKING:
    from vm_provisioning_adapter.models.system_model import EvaluateJobResponse

logger = logging.getLogger(__name__)

_FAKE_STDOUT = """\
PLAY [Mock Provision] *********************************************************

TASK [debug] ******************************************************************
ok: [kvm1] => {
    "vm_creation_data": {
        "action": "create",
        "vm_name": "mock-vm",
        "status": "running",
        "host": "kvm1",
        "timestamp": "2025-01-01T00:00:00Z",
        "tenant_user": "mockuser",
        "external_ssh_port": "2222",
        "vm_ip_internal": "192.168.122.2",
        "authentication": {
            "tenant": {
                "password": "mock-tenant-password",
                "key_type": "generated",
                "ssh_commands": {
                    "internal": "ssh -i key mockuser@192.168.122.2",
                    "external": "ssh -i key -p 2222 mockuser@127.0.0.1"
                }
            },
            "root": {
                "password": "mock-root-password",
                "ssh_commands": {"internal": "ssh root@192.168.122.2"},
                "ssh_key_path_host": "/root/.ssh/mock-vm_root_ed25519"
            }
        }
    }
}
"""


class MockAnsibleService:
    """Drop-in replacement for AnsibleService that performs no I/O.

    Implements the same interface as AnsibleService so AnsibleJobService
    can use it without modification.
    """

    def __init__(
        self,
        settings,
        *,
        provision_result: Optional[str] = None,
        should_fail: bool = False,
        fail_message: str = "mock failure",
    ) -> None:
        self._settings = settings
        self._stdout = provision_result or _FAKE_STDOUT
        self._should_fail = should_fail
        self._fail_message = fail_message

    # ------------------------------------------------------------------
    # Playbook interface — mirrors AnsibleService exactly
    # ------------------------------------------------------------------

    def build_vars_file(self, params: AnsibleJobParams) -> Path:
        """Return a dummy path — no file is written."""
        return Path(f"/tmp/mock_vars_{params.vm_action}.yml")

    def reserved_var_keys(self, params: AnsibleJobParams) -> frozenset[str]:
        """Mirror the production renderer's protected variable namespace."""
        from vm_provisioning_adapter.services.ansible_service import AnsibleService

        real = AnsibleService.__new__(AnsibleService)
        real._settings = self._settings
        return real.reserved_var_keys(params)

    def start_playbook(
        self,
        playbook_path: Path,
        inventory_path: Path,
        extra_vars_path: Path,
        limit: str,
        extra_cli_vars: dict | None = None,
    ) -> AnsibleRun:
        """Return a fake AnsibleRun handle with a mock process."""
        mock_proc = MagicMock()
        mock_proc.pid = 0
        mock_proc.poll.return_value = 0
        return AnsibleRun(
            process=mock_proc,
            process_id=0,
            vars_path=extra_vars_path,
        )

    def default_stdout(self, run: AnsibleRun) -> str:
        """The output a run produces when no rule replaces it.

        A subclass renders it per run from the job's params, which the job
        service attaches to the run handle as ``_params``.
        """
        return self._stdout

    async def wait_for_playbook(
        self,
        run: AnsibleRun,
        timeout_seconds: int,
        log_callback: Optional[Callable] = None,
    ) -> AnsibleResult:
        """Return a fake result immediately (no subprocess, no wait)."""
        return await self._complete(run, self.default_stdout(run), log_callback)

    async def _complete(
        self,
        run: AnsibleRun,
        stdout: str,
        log_callback: Optional[Callable] = None,
    ) -> AnsibleResult:
        await asyncio.sleep(0)  # yield to event loop

        if self._should_fail:
            raise AnsibleError(self._fail_message, stdout="", stderr=self._fail_message)

        if log_callback:
            try:
                await asyncio.to_thread(log_callback, stdout, "")
            except Exception:
                pass

        return AnsibleResult(
            stdout=stdout,
            stderr="",
            process_id=0,
        )

    def parse_playbook_result(
        self,
        result: AnsibleResult,
        params: AnsibleJobParams,
        tenant_address: str | None = None,
    ) -> AnsibleRunResult:
        """Delegate to real parsing logic — only subprocess boundary is mocked."""
        from vm_provisioning_adapter.services.ansible_service import AnsibleService

        real = AnsibleService.__new__(AnsibleService)
        real._settings = self._settings
        return real.parse_playbook_result(result, params, tenant_address=tenant_address)

    # ------------------------------------------------------------------
    # Connectivity check
    # ------------------------------------------------------------------

    async def check_connectivity_with_inventory(
        self, host: str, inventory_path
    ) -> ConnectivityResult:
        """Always reports reachable in mock mode (ignores inventory_path)."""
        await asyncio.sleep(0)
        return ConnectivityResult(
            host=host,
            reachable=True,
            detail="mock: connectivity check always succeeds",
        )

    def write_inventory(self, hosts: list) -> MaterializedInventory:
        """A minimal inventory of the caller's own in mock mode; Ansible never runs."""
        descriptor, name = tempfile.mkstemp(prefix="mock_inventory_", suffix=".ini")
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write("[kvm_hosts]\n")
        return MaterializedInventory(path=Path(name))


# ---------------------------------------------------------------------------
# ProgrammableMockAnsibleService — when→then rule-based mock
# ---------------------------------------------------------------------------


class ProgrammableMockAnsibleService(MockAnsibleService):
    """``MockAnsibleService`` with when→then rules.

    Rules, gates, and job-done notification come from the compute mock mechanism
    (``compute_provisioning.jobs.executor_mock``); this class supplies the Ansible
    surface the job service calls and the adapter's default output. Each adapter
    constructs its own instance, so a rule installed for one adapter never matches
    another adapter's jobs.

    The first rule whose ``match`` is a subset of the job's ``AnsibleJobParams``
    wins. With no matching rule a job succeeds with the default output.
    """

    def __init__(self, settings, **kwargs) -> None:
        super().__init__(settings, **kwargs)
        self.rules = MockRuleSet()

    # ------------------------------------------------------------------
    # Rule management (called by the test controller)
    # ------------------------------------------------------------------

    def add_rule(self, rule: MockRule) -> None:
        self.rules.add(rule)

    def delete_rule(self, rule_id: str) -> bool:
        return self.rules.delete(rule_id)

    def list_rules(self) -> list[dict]:
        return self.rules.list()

    def resume_rule(self, rule_id: str) -> bool:
        return self.rules.resume(rule_id)

    def evaluate_job(
        self,
        params: "AnsibleJobParams",
        host_service: "Any",
    ) -> "EvaluateJobResponse":
        """Dry-run: whether a job would be accepted and which rule it would meet.

        No job is created or queued.
        """
        from vm_provisioning_adapter.models.system_model import EvaluateJobResponse

        report = self.rules.evaluate(
            dataclasses.asdict(params),
            host_id=params.host_id,
            host_lookup=host_service.get_host,
            required=("vm_action",),
        )
        return EvaluateJobResponse(**report)

    # ------------------------------------------------------------------
    # AnsibleService interface override
    # ------------------------------------------------------------------

    async def wait_for_playbook(
        self, run: "AnsibleRun", timeout_seconds: int, log_callback=None
    ) -> "AnsibleResult":
        """Apply the first matching rule, then pause, fail, or succeed.

        The job service attaches the job's params to the run handle as
        ``_params``; a run without them matches no rule.
        """
        params = getattr(run, "_params", None)
        rule = (
            self.rules.find(dataclasses.asdict(params)) if params is not None else None
        )
        await self.rules.hold(rule)
        if rule is not None and rule.fail_with:
            raise AnsibleError(rule.fail_with, stdout="", stderr=rule.fail_with)
        stdout = (
            rule.result_stdout
            if rule is not None and rule.result_stdout
            else self.default_stdout(run)
        )
        return await self._complete(run, stdout, log_callback)
