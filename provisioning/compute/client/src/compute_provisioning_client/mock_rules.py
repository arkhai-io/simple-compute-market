"""Typed clients for the compute family's mock routes, wherever a domain mounts them.

The rule and evaluate-job routes are the family's mock mechanism, which each
compute domain mounts under its own prefix. These clients wrap any transport
offering ``authenticated_request`` -- the family's async or sync client -- and,
given the domain's ``MockRouteMount``, sign each request from the declaration
the mount yields for that route. ``MockRuleClient`` wraps an async transport
and ``SyncMockRuleClient`` a sync one, with identical method signatures.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from compute_provisioning_contracts import (
    MockJobEvaluation,
    MockRouteMount,
    MockRuleAdded,
    MockRuleCreate,
    MockRuleDeleted,
    MockRuleResumed,
    MockRuleView,
)
from market_identity import EMPTY_BODY


class _Transport(Protocol):
    def authenticated_request(self, method: str, path: str, *args: Any, **kwargs: Any) -> Any: ...


@dataclass(frozen=True)
class _Call:
    action: str
    method: str
    path: str
    body: Any
    parse: Callable[[Any], Any]

    def arguments(self, mount: MockRouteMount) -> tuple[tuple, dict[str, Any]]:
        return (self.method, self.path, self.body), {"route": mount.declaration(self.action)}


def _rule_views(payload: Any) -> list[MockRuleView]:
    return [MockRuleView.model_validate(rule) for rule in payload]


def _add_rule(mount: MockRouteMount, rule: MockRuleCreate) -> _Call:
    return _Call("rule_add", "POST", mount.rules_path(), rule, MockRuleAdded.model_validate)


def _list_rules(mount: MockRouteMount) -> _Call:
    return _Call("rules_list", "GET", mount.rules_path(), EMPTY_BODY, _rule_views)


def _delete_rule(mount: MockRouteMount, rule_id: str) -> _Call:
    return _Call(
        "rule_delete", "DELETE", mount.rule_path(rule_id), EMPTY_BODY, MockRuleDeleted.model_validate
    )


def _resume_rule(mount: MockRouteMount, rule_id: str) -> _Call:
    return _Call(
        "rule_resume", "POST", mount.rule_resume_path(rule_id), {}, MockRuleResumed.model_validate
    )


def _evaluate_job(mount: MockRouteMount, job: Mapping[str, Any]) -> _Call:
    return _Call(
        "job_evaluate", "POST", mount.evaluate_path(), dict(job), MockJobEvaluation.model_validate
    )


class MockRuleClient:
    """One domain's mock routes over an async signing transport.

    ``evaluate_job`` takes the job as the mounting domain describes it, since a
    job's parameters are that domain's; its answer is the family's.
    """

    def __init__(self, transport: _Transport, mount: MockRouteMount) -> None:
        self._transport = transport
        self._mount = mount

    async def _run(self, call: _Call) -> Any:
        args, kwargs = call.arguments(self._mount)
        return call.parse(await self._transport.authenticated_request(*args, **kwargs))

    async def add_rule(self, rule: MockRuleCreate) -> MockRuleAdded:
        return await self._run(_add_rule(self._mount, rule))

    async def list_rules(self) -> list[MockRuleView]:
        return await self._run(_list_rules(self._mount))

    async def delete_rule(self, rule_id: str) -> MockRuleDeleted:
        return await self._run(_delete_rule(self._mount, rule_id))

    async def resume_rule(self, rule_id: str) -> MockRuleResumed:
        return await self._run(_resume_rule(self._mount, rule_id))

    async def evaluate_job(self, job: Mapping[str, Any]) -> MockJobEvaluation:
        return await self._run(_evaluate_job(self._mount, job))


class SyncMockRuleClient:
    """One domain's mock routes over a sync signing transport."""

    def __init__(self, transport: _Transport, mount: MockRouteMount) -> None:
        self._transport = transport
        self._mount = mount

    def _run(self, call: _Call) -> Any:
        args, kwargs = call.arguments(self._mount)
        return call.parse(self._transport.authenticated_request(*args, **kwargs))

    def add_rule(self, rule: MockRuleCreate) -> MockRuleAdded:
        return self._run(_add_rule(self._mount, rule))

    def list_rules(self) -> list[MockRuleView]:
        return self._run(_list_rules(self._mount))

    def delete_rule(self, rule_id: str) -> MockRuleDeleted:
        return self._run(_delete_rule(self._mount, rule_id))

    def resume_rule(self, rule_id: str) -> MockRuleResumed:
        return self._run(_resume_rule(self._mount, rule_id))

    def evaluate_job(self, job: Mapping[str, Any]) -> MockJobEvaluation:
        return self._run(_evaluate_job(self._mount, job))


__all__ = ["MockRuleClient", "SyncMockRuleClient"]
