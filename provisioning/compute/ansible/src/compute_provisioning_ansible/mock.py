"""A stand-in for the Ansible runner, for the provisioning service's mock profile.

``MockAnsibleRunner`` replaces only the playbook's execution: an
``AnsibleJobExecutor`` over it still prepares the job through the domain's
codec, renders the variables and the inventory from the registered host, and
has the codec interpret the output, which here is produced with no subprocess
and no SSH.

What a run produces is decided by the compute mock mechanism's rules
(``compute_provisioning.jobs.executor_mock``): the first rule whose ``match`` is
a subset of the job's stored parameters may hold the run at a gate, fail it, or
replace its output. With no rule, the run succeeds with the output the domain
contributes as ``default_output``, rendered from the job and the host it runs
against, so the codec reads the same fields from it that a real playbook
prints. Each domain composes its own runner, so a rule installed for one
domain never matches another domain's jobs.

Whether the provisioning service runs real Ansible or this mock is a deployment
concern of the service's ``ACTIVE_PROFILES``; callers of the service's API
cannot tell.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from compute_provisioning.jobs.executor_mock import MockRule, MockRuleSet

from compute_provisioning_contracts import ConnectivityResult

from .runner import (
    AnsibleError,
    AnsibleResult,
    AnsibleRun,
    InventoryTarget,
    MaterializedInventory,
)


@dataclass(frozen=True)
class MockPlaybook:
    """What a domain's default output is rendered from: one mocked run."""

    #: The job's stored parameters, as the job authority holds them.
    parameters: Mapping[str, Any]
    #: The host the run is limited to, as its inventory names it.
    limit: str
    #: The hosts in the run's inventory, by host id.
    hosts: Mapping[str, InventoryTarget] = field(default_factory=dict)

    @property
    def host(self) -> InventoryTarget | None:
        """The registered host the run is limited to, if its inventory has it."""
        return self.hosts.get(self.limit)


#: Renders a run's output when no rule replaces it.
DefaultOutput = Callable[[MockPlaybook], str]


class _NoProcess:
    """Stands in for a playbook process that never existed."""

    pid = 0

    @staticmethod
    def poll() -> int:
        return 0


@dataclass
class _MockRun(AnsibleRun):
    playbook: MockPlaybook | None = None
    run_id: str = ""


class MockAnsibleRunner:
    """The runner's playbook, inventory, and connectivity surface, with rules.

    ``rules`` is the domain's own rule set; the service's test routes manage it.
    """

    def __init__(self, default_output: DefaultOutput) -> None:
        self._default_output = default_output
        self.rules = MockRuleSet()
        # Hosts of each inventory this runner wrote and has not yet run.
        self._inventories: dict[Path, dict[str, InventoryTarget]] = {}
        # Runs started and not yet finished, by run id: the task waiting on
        # each one's rule, once it waits, so ``cancel`` can end that wait.
        self._waits: dict[str, asyncio.Task | None] = {}
        self._cancelled: set[str] = set()

    # ------------------------------------------------------------------
    # Rules
    # ------------------------------------------------------------------

    def add_rule(self, rule: MockRule) -> None:
        self.rules.add(rule)

    def delete_rule(self, rule_id: str) -> bool:
        return self.rules.delete(rule_id)

    def list_rules(self) -> list[dict]:
        return self.rules.list()

    def resume_rule(self, rule_id: str) -> bool:
        return self.rules.resume(rule_id)

    # ------------------------------------------------------------------
    # Runner surface
    # ------------------------------------------------------------------

    def write_inventory(self, hosts: list, *, group: str) -> MaterializedInventory:
        """An inventory naming the group and no host; Ansible never reads it.

        The hosts are kept for the run that uses the inventory, so its output
        can name the registered host's address.
        """
        descriptor, name = tempfile.mkstemp(prefix="mock_inventory_", suffix=".ini")
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(f"[{group}]\n")
        path = Path(name)
        self._inventories[path] = {
            str(host.host_id): host for host in hosts if getattr(host, "host_id", None)
        }
        return MaterializedInventory(path=path)

    def start_playbook(
        self,
        playbook_path: Path,
        inventory_path: Path,
        extra_vars_path: Path,
        limit: str,
        extra_cli_vars: dict | None = None,
        job_parameters: Mapping[str, Any] | None = None,
    ) -> AnsibleRun:
        run_id = uuid.uuid4().hex
        self._waits[run_id] = None
        return _MockRun(
            run_id=run_id,
            process=_NoProcess(),  # type: ignore[arg-type]
            process_id=0,
            vars_path=extra_vars_path,
            job_parameters=job_parameters,
            playbook=MockPlaybook(
                parameters=dict(job_parameters or {}),
                limit=limit,
                hosts=self._inventories.pop(Path(inventory_path), {}),
            ),
        )

    @staticmethod
    def execution_handle(run: AnsibleRun) -> dict[str, Any]:
        """A mocked run is named by its run id; it has no process to signal."""
        return {"mock_run": getattr(run, "run_id", "")}

    async def cancel(self, handle: Mapping[str, Any]) -> None:
        """End the named run as a cancelled playbook, wherever it is.

        A run held at a gate leaves it without a resume, so its job's
        processing ends and the gate's held count drops; a run not yet waiting
        ends as soon as it would. A run already finished is left alone.
        """
        run_id = str(handle.get("mock_run", ""))
        if run_id not in self._waits:
            return
        self._cancelled.add(run_id)
        waiting = self._waits[run_id]
        if waiting is not None:
            waiting.cancel()

    async def wait_for_playbook(
        self,
        run: AnsibleRun,
        timeout_seconds: int,
        log_callback: Callable[[str, str], None] | None = None,
        redact: Callable[[str], str] | None = None,
    ) -> AnsibleResult:
        """Apply the first matching rule, then hold, fail, or succeed.

        A run that carries no job parameters matches no rule. A run cancelled
        before or while it is held fails as a stopped playbook would.
        """
        run_id = getattr(run, "run_id", "")
        try:
            parameters = run.job_parameters
            rule = self.rules.find(dict(parameters)) if parameters is not None else None
            await self._hold(run_id, rule)
        finally:
            self._waits.pop(run_id, None)
            self._cancelled.discard(run_id)
        if rule is not None and rule.fail_with:
            raise AnsibleError(rule.fail_with, stdout="", stderr=rule.fail_with)
        if rule is not None and rule.result_stdout:
            stdout = rule.result_stdout
        else:
            playbook = getattr(run, "playbook", None) or MockPlaybook(
                parameters=dict(parameters or {}), limit=""
            )
            stdout = self._default_output(playbook)
        if log_callback is not None:
            await asyncio.to_thread(log_callback, stdout, "")
        return AnsibleResult(stdout=stdout, stderr="", process_id=run.process_id)

    async def _hold(self, run_id: str, rule: MockRule | None) -> None:
        cancelled = AnsibleError("Playbook cancelled", stdout="", stderr="")
        if run_id in self._cancelled:
            raise cancelled
        waiting = asyncio.ensure_future(self.rules.hold(rule))
        if run_id in self._waits:
            self._waits[run_id] = waiting
        try:
            await asyncio.shield(waiting)
        except asyncio.CancelledError:
            if run_id in self._cancelled and waiting.cancelled():
                raise cancelled from None
            # The job's own processing was cancelled: take the wait with it.
            waiting.cancel()
            raise
        if waiting.cancelled():
            raise cancelled

    async def check_connectivity_with_inventory(
        self, host: str, inventory_path: Path
    ) -> ConnectivityResult:
        """Every registered host is reachable under the mock."""
        self._inventories.pop(Path(inventory_path), None)
        return ConnectivityResult(
            host=host, reachable=True, detail="mock: connectivity check always succeeds"
        )


__all__ = ["DefaultOutput", "MockAnsibleRunner", "MockPlaybook"]
