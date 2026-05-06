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
``host_ip``          — value returned by ``lookup_host_ip`` for any host.

These are set once at construction.  For docker-compose e2e tests that need
to toggle failure mode, run two separate provisioning-service containers
configured with different profiles.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock

from models.ansible import ConnectivityResult, InventoryHost, InventoryResponse
from models.jobs_model import AnsibleJobParams, AnsibleRunResult
from services.ansible_service import AnsibleError, AnsibleResult, AnsibleRun

logger = logging.getLogger(__name__)

_FAKE_STDOUT = """\
PLAY [Mock Provision] *********************************************************

TASK [debug] ******************************************************************
ok: [ww1] => {
    "vm_creation_data": {
        "action": "create",
        "vm_name": "mock-vm",
        "status": "running",
        "host": "ww1",
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
        host_ip: str = "127.0.0.1",
    ) -> None:
        self._settings = settings
        self._stdout = provision_result or _FAKE_STDOUT
        self._should_fail = should_fail
        self._fail_message = fail_message
        self._host_ip = host_ip

    # ------------------------------------------------------------------
    # Playbook interface — mirrors AnsibleService exactly
    # ------------------------------------------------------------------

    def build_vars_file(self, params: AnsibleJobParams) -> Path:
        """Return a dummy path — no file is written."""
        return Path(f"/tmp/mock_vars_{params.vm_action}.yml")

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

    async def wait_for_playbook(
        self,
        run: AnsibleRun,
        timeout_seconds: int,
        log_callback: Optional[Callable] = None,
    ) -> AnsibleResult:
        """Return a fake result immediately (no subprocess, no wait)."""
        await asyncio.sleep(0)  # yield to event loop

        if self._should_fail:
            raise AnsibleError(self._fail_message, stdout="", stderr=self._fail_message)

        if log_callback:
            try:
                await asyncio.to_thread(log_callback, self._stdout, "")
            except Exception:
                pass

        return AnsibleResult(
            stdout=self._stdout,
            stderr="",
            process_id=0,
        )

    def parse_playbook_result(
        self, result: AnsibleResult, params: AnsibleJobParams
    ) -> AnsibleRunResult:
        """Delegate to real parsing logic — only subprocess boundary is mocked."""
        from services.ansible_service import AnsibleService
        real = AnsibleService.__new__(AnsibleService)
        real._settings = self._settings
        return real.parse_playbook_result(result, params)

    # ------------------------------------------------------------------
    # Inventory interface
    # ------------------------------------------------------------------

    def parse_inventory(self, search: str | None = None) -> list[InventoryHost]:
        """Return a single fake host entry."""
        hosts = [
            InventoryHost(
                name="ww1",
                ansible_host=self._host_ip,
                vars={"ansible_ssh_private_key_file": "~/.ssh/id_ed25519"},
            )
        ]
        if search:
            hosts = [h for h in hosts if search.lower() in h.name.lower()]
        return hosts

    def get_inventory(self, search: str | None = None) -> InventoryResponse:
        return InventoryResponse(
            inventory_path=str(getattr(self._settings, "resolved_inventory_path", "/mock/hosts")),
            hosts=self.parse_inventory(search=search),
        )

    def lookup_host_ip(self, vm_host: str) -> Optional[str]:
        return self._host_ip

    # ------------------------------------------------------------------
    # Connectivity check
    # ------------------------------------------------------------------

    async def check_connectivity(self, host: str) -> ConnectivityResult:
        """Always reports reachable in mock mode."""
        await asyncio.sleep(0)
        return ConnectivityResult(
            host=host,
            reachable=True,
            detail="mock: connectivity check always succeeds",
        )

    async def check_connectivity_with_inventory(self, host: str, inventory_path) -> ConnectivityResult:
        """Always reports reachable in mock mode (ignores inventory_path)."""
        await asyncio.sleep(0)
        return ConnectivityResult(
            host=host,
            reachable=True,
            detail="mock: connectivity check always succeeds",
        )

    def write_inventory(self, hosts: list) -> "Path":
        """Return a minimal temp file in mock mode; Ansible is never called."""
        import tempfile
        from pathlib import Path
        p = Path(tempfile.gettempdir()) / "mock_inventory.ini"
        p.write_text("[kvm_hosts]\n", encoding="utf-8")
        return p


# ---------------------------------------------------------------------------
# ProgrammableMockAnsibleService — when→then rule-based mock
# ---------------------------------------------------------------------------


from dataclasses import dataclass, field as dc_field
from typing import Optional as _Optional


@dataclass
class MockRule:
    """A single when→then mock rule.

    ``match`` is a dict of ``AnsibleJobParams`` field names → expected values.
    A job matches this rule when **all** match entries are present and equal
    in the job params.  An empty ``match`` dict matches every job (catch-all).

    ``pause_before_result`` — if True, ``wait_for_playbook`` blocks on an
    ``asyncio.Event`` until ``resume_rule`` is called on the test controller.
    This lets tests assert on mid-flight job state without polling loops.

    ``result_stdout`` — Ansible stdout to return on success.  If None, falls
    back to the class-level ``_FAKE_STDOUT``.

    ``fail_with`` — if set, ``wait_for_playbook`` raises ``AnsibleError`` with
    this message instead of returning a result.  Takes precedence over
    ``result_stdout``.

    ``rule_id`` — caller-chosen identifier used to resume and delete rules.
    """

    match: dict = dc_field(default_factory=dict)
    pause_before_result: bool = False
    result_stdout: _Optional[str] = None
    fail_with: _Optional[str] = None
    rule_id: str = ""

    # Internal gate — created in ProgrammableMockAnsibleService.add_rule
    _gate: _Optional[asyncio.Event] = dc_field(default=None, repr=False)


class ProgrammableMockAnsibleService(MockAnsibleService):
    """Drop-in replacement for MockAnsibleService with when→then rule support.

    Activated when ``mock`` is in ``ACTIVE_PROFILES`` (same condition as
    ``MockAnsibleService``).  The test controller mounts at ``/test/*`` and
    provides the HTTP API for configuring rules and waiting for jobs.

    Rule matching
    -------------
    Rules are evaluated in insertion order; the first rule whose ``match``
    dict is a subset of the incoming ``AnsibleJobParams`` dict wins.
    A rule with ``match={}`` is a catch-all.  If no rule matches, behaviour
    falls through to the base ``MockAnsibleService`` (instant success with
    ``_FAKE_STDOUT``).

    Thread safety
    -------------
    Rules are stored in a plain ``dict`` keyed by ``rule_id``.  Mutation
    (add/delete) happens on the asyncio event loop via the test controller
    endpoints — no locking needed.
    """

    def __init__(self, settings, **kwargs) -> None:
        super().__init__(settings, **kwargs)
        self._rules: dict[str, MockRule] = {}
        # job_id → asyncio.Event; set when the job reaches a terminal state
        self._job_done_events: dict[str, asyncio.Event] = {}

    # ------------------------------------------------------------------
    # Rule management (called by test controller)
    # ------------------------------------------------------------------

    def add_rule(self, rule: MockRule) -> None:
        if not rule.rule_id:
            import uuid as _uuid
            rule.rule_id = str(_uuid.uuid4())[:8]
        if rule.pause_before_result:
            rule._gate = asyncio.Event()
        self._rules[rule.rule_id] = rule

    def delete_rule(self, rule_id: str) -> bool:
        return self._rules.pop(rule_id, None) is not None

    def list_rules(self) -> list[dict]:
        return [
            {
                "rule_id": r.rule_id,
                "match": r.match,
                "pause_before_result": r.pause_before_result,
                "fail_with": r.fail_with,
                "result_stdout": r.result_stdout is not None,
                "paused": r._gate is not None and not r._gate.is_set(),
            }
            for r in self._rules.values()
        ]

    def resume_rule(self, rule_id: str) -> bool:
        rule = self._rules.get(rule_id)
        if rule and rule._gate:
            rule._gate.set()
            return True
        return False

    def notify_job_done(self, job_id: str) -> None:
        """Called by wait_for_playbook when a job completes — fires wait_for_job."""
        evt = self._job_done_events.get(job_id)
        if evt:
            evt.set()

    def get_or_create_job_event(self, job_id: str) -> asyncio.Event:
        if job_id not in self._job_done_events:
            self._job_done_events[job_id] = asyncio.Event()
        return self._job_done_events[job_id]

    # ------------------------------------------------------------------
    # Rule lookup
    # ------------------------------------------------------------------

    def _find_rule(self, params: "AnsibleJobParams") -> _Optional[MockRule]:
        import dataclasses as _dc
        params_dict = _dc.asdict(params)
        for rule in self._rules.values():
            if all(params_dict.get(k) == v for k, v in rule.match.items()):
                return rule
        return None

    def evaluate_job(
        self,
        params: "AnsibleJobParams",
        host_service: "Any",
    ) -> "EvaluateJobResponse":
        """Dry-run: check whether a job would be accepted and which rule would match.

        Args:
            params:       AnsibleJobParams describing the hypothetical job.
            host_service: HostService instance used to verify host existence.

        Returns EvaluateJobResponse with params_valid, host_exists,
        rule_matched (rule_id or None), would_pause, and any errors.
        No job is created or queued.
        """
        from models.system_model import EvaluateJobResponse

        errors: list[str] = []
        host_exists = False

        # Check host exists in inventory
        try:
            host = host_service.get_host(params.vm_host)
            host_exists = host is not None
            if not host_exists:
                errors.append(
                    f"Host {params.vm_host!r} not found in inventory. "
                    "Register it with POST /api/v1/hosts before settling."
                )
        except Exception as exc:
            errors.append(f"Could not check host inventory: {exc}")

        # Check mock rule matching
        rule = self._find_rule(params)
        rule_matched = rule.rule_id if rule is not None else None
        would_pause = rule.pause_before_result if rule is not None else False

        params_valid = len(errors) == 0 and bool(params.vm_host) and bool(params.vm_action)

        return EvaluateJobResponse(
            params_valid=params_valid,
            host_exists=host_exists,
            rule_matched=rule_matched,
            would_pause=would_pause,
            errors=errors,
        )

    # ------------------------------------------------------------------
    # AnsibleService interface override
    # ------------------------------------------------------------------

    def start_playbook(self, playbook_path, inventory_path, extra_vars_path,
                       limit, extra_cli_vars=None) -> "AnsibleRun":
        # Store the job_id from extra_vars_path stem for event notification.
        # The vars file is named after the job_id by build_vars_file.
        return super().start_playbook(
            playbook_path, inventory_path, extra_vars_path, limit, extra_cli_vars
        )

    async def wait_for_playbook(self, run: "AnsibleRun", timeout_seconds: int,
                                log_callback=None) -> "AnsibleResult":
        """Apply the first matching rule, then either pause, fail, or succeed."""
        # Recover the params from the vars file path — it holds the AnsibleJobParams
        # serialised by build_vars_file.  For rule matching we read the params back.
        # We inject params via a side-channel set in start_playbook_with_params.
        params = getattr(run, "_params", None)
        rule = self._find_rule(params) if params is not None else None

        if rule:
            if rule.pause_before_result and rule._gate:
                await rule._gate.wait()
            if rule.fail_with:
                from services.ansible_service import AnsibleError
                raise AnsibleError(rule.fail_with, stdout="", stderr=rule.fail_with)
            if rule.result_stdout:
                original_stdout = self._stdout
                self._stdout = rule.result_stdout
                result = await super().wait_for_playbook(run, timeout_seconds, log_callback)
                self._stdout = original_stdout
                return result

        result = await super().wait_for_playbook(run, timeout_seconds, log_callback)
        return result
