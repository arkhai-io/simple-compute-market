"""Rule and gate mechanism shared by the compute adapters' mock executors.

Under the provisioning service's mock profile each compute adapter runs its jobs
through a mock of its own. What those mocks share lives here: when→then rules
matched against a job's parameters, pause gates that hold a job until a test
releases it or its run is cancelled, the evaluate-job dry run, and a
framework-free route service each adapter binds under its own ``/test`` prefix.

The mechanism knows nothing about how a job runs or what its output looks like:
rules match an opaque parameter mapping, and ``result_stdout`` is handed back to
the adapter's own mock untouched. A job held at a gate is counted on its rule, so
a test waits for it with ``MockRuleSet.wait_until_held`` (and for its departure
with ``MockRuleSet.wait_until_released``) rather than on elapsed
time, and the rule routes report the count. It serves the compute family only
and is not a foundation kit.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MockRule:
    """One when→then rule.

    A job matches when every ``match`` entry is present in its parameters with an
    equal value; an empty ``match`` matches every job. ``pause_before_result``
    holds a matching job until the rule is resumed. ``fail_with`` makes a matching
    job fail with that message and takes precedence over ``result_stdout``, which
    replaces the mock's default output when set.
    """

    match: dict[str, Any] = field(default_factory=dict)
    pause_before_result: bool = False
    result_stdout: str | None = None
    fail_with: str | None = None
    rule_id: str = ""
    gate: asyncio.Event | None = field(default=None, repr=False)
    #: Jobs currently held at this rule's closed gate.
    waiting: int = field(default=0, repr=False)


class MockRuleSet:
    """The rules of one adapter's mock, evaluated in insertion order."""

    def __init__(self) -> None:
        self._rules: dict[str, MockRule] = {}
        # Set and replaced whenever a job arrives at or leaves a gate, or a rule
        # is removed, so a waiter re-checks its condition rather than polling.
        self._gates_changed = asyncio.Event()

    def add(self, rule: MockRule) -> MockRule:
        if not rule.rule_id:
            rule.rule_id = uuid.uuid4().hex[:8]
        if rule.pause_before_result:
            rule.gate = asyncio.Event()
        self._rules[rule.rule_id] = rule
        return rule

    def delete(self, rule_id: str) -> bool:
        if self._rules.pop(rule_id, None) is None:
            return False
        self._notify_gates_changed()
        return True

    def list(self) -> list[dict[str, Any]]:
        return [
            {
                "rule_id": rule.rule_id,
                "match": rule.match,
                "pause_before_result": rule.pause_before_result,
                "fail_with": rule.fail_with,
                "result_stdout": rule.result_stdout is not None,
                "paused": rule.gate is not None and not rule.gate.is_set(),
                "waiting": rule.waiting,
            }
            for rule in self._rules.values()
        ]

    def resume(self, rule_id: str) -> bool:
        rule = self._rules.get(rule_id)
        if rule is not None and rule.gate is not None:
            rule.gate.set()
            return True
        return False

    def find(self, params: Mapping[str, Any]) -> MockRule | None:
        for rule in self._rules.values():
            if all(params.get(key) == value for key, value in rule.match.items()):
                return rule
        return None

    async def hold(self, rule: MockRule | None) -> None:
        """Wait on a matching rule's gate, if it has one and it is closed.

        A held job is counted on the rule while it waits, which is what
        ``wait_until_held`` and ``list`` observe. A gate already opened passes
        the job through uncounted.
        """

        if rule is None or not rule.pause_before_result or rule.gate is None:
            return
        if rule.gate.is_set():
            return
        rule.waiting += 1
        self._notify_gates_changed()
        try:
            await rule.gate.wait()
        finally:
            rule.waiting -= 1
            self._notify_gates_changed()

    async def wait_until_held(self, rule_id: str, *, count: int = 1) -> int:
        """Return once at least ``count`` jobs are held at ``rule_id``'s gate.

        This is the deterministic signal a test waits on instead of elapsed
        time. It does not bound its own wait: callers wrap it in
        ``asyncio.wait_for`` so a gate never reached fails the test. Raises
        ``LookupError`` if the rule is unknown, has no gate, or is removed while
        waited on, since no job can then arrive at it.
        """

        if count < 1:
            raise ValueError("count must be at least 1")
        while True:
            rule = self._rules.get(rule_id)
            if rule is None or rule.gate is None:
                raise LookupError(f"rule {rule_id!r} has no gate to wait at")
            if rule.waiting >= count:
                return rule.waiting
            await self._gates_changed.wait()

    async def wait_until_released(self, rule_id: str) -> None:
        """Return once no job is held at ``rule_id``'s gate.

        A held job leaves the gate when it is resumed or when its run is
        cancelled; this is the signal a test of either waits on. Callers bound
        it with ``asyncio.wait_for``. Returns at once for a rule that holds
        nothing or no longer exists.
        """

        while True:
            rule = self._rules.get(rule_id)
            if rule is None or rule.waiting == 0:
                return
            await self._gates_changed.wait()

    def _notify_gates_changed(self) -> None:
        # Waking every waiter on the current event and handing later waiters a
        # fresh one keeps notification synchronous, so ``hold`` and ``delete``
        # need no lock and schedule nothing.
        changed, self._gates_changed = self._gates_changed, asyncio.Event()
        changed.set()

    def evaluate(
        self,
        params: Mapping[str, Any],
        *,
        host_id: str,
        host_lookup: Callable[[str], Any],
        required: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        """Report whether a job would run and which rule it would meet.

        The host must be registered, as the job service requires before running
        anything; ``required`` names parameters that must be non-empty. Nothing is
        created or queued.
        """

        errors: list[str] = []
        host_exists = False
        try:
            host_exists = host_lookup(host_id) is not None
            if not host_exists:
                errors.append(
                    f"Host {host_id!r} not found in inventory. "
                    "Register it with POST /api/v1/hosts before settling."
                )
        except Exception as exc:
            errors.append(f"Could not check host inventory: {exc}")
        rule = self.find(params)
        missing = [name for name in required if not params.get(name)]
        errors.extend(f"{name} is required" for name in missing)
        return {
            "params_valid": not errors and bool(host_id),
            "host_exists": host_exists,
            "rule_matched": rule.rule_id if rule is not None else None,
            "would_pause": rule.pause_before_result if rule is not None else False,
            "errors": errors,
        }


class MockRouteError(RuntimeError):
    """HTTP-shaped failure raised without depending on a web framework."""

    def __init__(self, status_code: int, detail: Any) -> None:
        super().__init__(str(detail))
        self.status_code = status_code
        self.detail = detail


class MockRuleRouteService:
    """Add, list, delete, and resume one adapter's mock rules.

    Each adapter binds these into its own router under its own prefix, so a rule
    installed through one adapter's routes never matches another adapter's jobs.
    """

    def __init__(self, rules: Callable[[], MockRuleSet | None]) -> None:
        self._rules = rules

    def _rule_set(self) -> MockRuleSet:
        rule_set = self._rules()
        if rule_set is None:
            raise MockRouteError(
                503, "the mock executor is not active (ACTIVE_PROFILES != mock)"
            )
        return rule_set

    def add(self, body: Mapping[str, Any]) -> dict[str, Any]:
        rule = self._rule_set().add(
            MockRule(
                rule_id=str(body.get("rule_id") or ""),
                match=dict(body.get("match") or {}),
                pause_before_result=bool(body.get("pause_before_result", False)),
                result_stdout=body.get("result_stdout"),
                fail_with=body.get("fail_with"),
            )
        )
        return {"rule_id": rule.rule_id, "status": "added"}

    def list(self) -> list[dict[str, Any]]:
        return self._rule_set().list()

    def delete(self, rule_id: str) -> dict[str, Any]:
        return {"rule_id": rule_id, "deleted": self._rule_set().delete(rule_id)}

    def resume(self, rule_id: str) -> dict[str, Any]:
        if not self._rule_set().resume(rule_id):
            raise MockRouteError(404, f"Rule {rule_id!r} not found or not paused")
        return {"rule_id": rule_id, "resumed": True}


__all__ = [
    "MockRouteError",
    "MockRule",
    "MockRuleRouteService",
    "MockRuleSet",
]
