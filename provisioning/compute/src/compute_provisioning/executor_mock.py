"""Rule and gate mechanism shared by the compute adapters' mock executors.

Under the provisioning service's mock profile each compute adapter runs its jobs
through a mock executor of its own. What those mocks share lives here: when→then
rules matched against a job's parameters, pause gates that hold a job until a test
releases it, job-done notification, the evaluate-job dry run, and a
framework-free route service each adapter binds under its own ``/test`` prefix.

The mechanism knows nothing about how a job runs or what its output looks like:
rules match an opaque parameter mapping, and ``result_stdout`` is handed back to
the adapter's own mock untouched. It serves the compute family only and is not a
foundation kit.
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


class MockRuleSet:
    """The rules of one adapter's mock, evaluated in insertion order."""

    def __init__(self) -> None:
        self._rules: dict[str, MockRule] = {}
        self._job_done_events: dict[str, asyncio.Event] = {}

    def add(self, rule: MockRule) -> MockRule:
        if not rule.rule_id:
            rule.rule_id = uuid.uuid4().hex[:8]
        if rule.pause_before_result:
            rule.gate = asyncio.Event()
        self._rules[rule.rule_id] = rule
        return rule

    def delete(self, rule_id: str) -> bool:
        return self._rules.pop(rule_id, None) is not None

    def list(self) -> list[dict[str, Any]]:
        return [
            {
                "rule_id": rule.rule_id,
                "match": rule.match,
                "pause_before_result": rule.pause_before_result,
                "fail_with": rule.fail_with,
                "result_stdout": rule.result_stdout is not None,
                "paused": rule.gate is not None and not rule.gate.is_set(),
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
        """Wait on a matching rule's gate, if it has one."""

        if rule is not None and rule.pause_before_result and rule.gate is not None:
            await rule.gate.wait()

    def notify_job_done(self, job_id: str) -> None:
        event = self._job_done_events.get(job_id)
        if event is not None:
            event.set()

    def job_done_event(self, job_id: str) -> asyncio.Event:
        if job_id not in self._job_done_events:
            self._job_done_events[job_id] = asyncio.Event()
        return self._job_done_events[job_id]

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
