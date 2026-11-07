"""Route contracts and wire models of the compute family's mock mechanism.

Under the provisioning service's mock profile each compute adapter runs its
jobs through a mock built on the family's rule and gate mechanism, and mounts
that mechanism's rule and evaluate-job routes under a prefix of its own, so a
rule installed through one adapter never matches another adapter's jobs. The
routes are the family's wherever they are mounted, so their declarations come
from one template: a ``MockRouteMount`` names where a domain mounts them and
yields their declarations, for the provisioning service's route table and for
the family's mock-rule client to sign from.

A job's parameters are the domain's, so a rule's ``match`` and an evaluated
job are opaque mappings here; only the rule's own fields and the dry run's
report are the family's.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

# A prefix is literal path segments with no regular-expression metacharacter,
# so it enters the declarations' patterns unescaped and they match exactly the
# paths a client builds from it.
_PREFIX = re.compile(r"(/[A-Za-z0-9_-]+)+")
_OPERATION_PREFIX = re.compile(r"[a-z][a-z0-9_]*")

_RULES = "/mock-rules"
_EVALUATE = "/evaluate-job"
_RULE_ID = r"(?P<rule_id>[^/]+)"
# Every mock route is the administrator's: it reshapes or holds jobs the
# service runs for every caller.
_ROLES = ("admin",)


@dataclass(frozen=True, slots=True)
class MockRouteMount:
    """Where one compute domain mounts the family's mock routes.

    ``prefix`` is the path the domain's routes sit under, such as ``/test``,
    and ``operation_prefix`` begins each route's signed operation name, such as
    ``provisioning_test``. Two domains mounting the mechanism state different
    values of both, which keeps their paths and operations apart.
    """

    prefix: str
    operation_prefix: str

    def __post_init__(self) -> None:
        if not _PREFIX.fullmatch(self.prefix):
            raise ValueError(
                f"mock route prefix {self.prefix!r} must be one or more literal "
                "path segments, starting with '/' and not ending with one"
            )
        if not _OPERATION_PREFIX.fullmatch(self.operation_prefix):
            raise ValueError(
                f"mock route operation prefix {self.operation_prefix!r} must be "
                "lower-case letters, digits, and underscores, starting with a letter"
            )

    def route_declarations(self) -> tuple[dict[str, Any], ...]:
        """The mount's five route declarations, in the order they resolve.

        Rule add, rules list, rule delete, rule resume, and job evaluate. No two
        of them can match one request, so the order decides nothing.
        """

        rules = f"{self.prefix}{_RULES}"
        return (
            {
                "method": "POST",
                "path": rules,
                "operation": self.operation("rule_add"),
                "roles": _ROLES,
            },
            {
                "method": "GET",
                "path": rules,
                "operation": self.operation("rules_list"),
                "roles": _ROLES,
            },
            {
                "method": "DELETE",
                "path": f"{rules}/{_RULE_ID}",
                "operation": self.operation("rule_delete"),
                "roles": _ROLES,
                "path_resource": "rule_id",
            },
            {
                "method": "POST",
                "path": f"{rules}/{_RULE_ID}/resume",
                "operation": self.operation("rule_resume"),
                "roles": _ROLES,
                "path_resource": "rule_id",
            },
            {
                "method": "POST",
                "path": f"{self.prefix}{_EVALUATE}",
                "operation": self.operation("job_evaluate"),
                "roles": _ROLES,
            },
        )

    def operation(self, action: str) -> str:
        """The signed operation name of one of the mount's routes."""

        return f"{self.operation_prefix}_{action}"

    def declaration(self, action: str) -> dict[str, Any]:
        """The declaration of the mount's route for ``action``, such as ``rule_add``."""

        operation = self.operation(action)
        for declaration in self.route_declarations():
            if declaration["operation"] == operation:
                return declaration
        raise KeyError(action)

    def rules_path(self) -> str:
        return f"{self.prefix}{_RULES}"

    def rule_path(self, rule_id: str) -> str:
        return f"{self.prefix}{_RULES}/{rule_id}"

    def rule_resume_path(self, rule_id: str) -> str:
        return f"{self.prefix}{_RULES}/{rule_id}/resume"

    def evaluate_path(self) -> str:
        return f"{self.prefix}{_EVALUATE}"


class MockRuleCreate(BaseModel):
    """A when→then rule to install.

    A job matches when every ``match`` entry is present in its parameters with
    an equal value; an empty ``match`` matches every job. ``pause_before_result``
    holds a matching job until the rule is resumed. ``fail_with`` makes a
    matching job fail with that message and takes precedence over
    ``result_stdout``, which replaces the mock's default output. An empty
    ``rule_id`` is assigned by the service.
    """

    rule_id: str = ""
    match: dict[str, Any] = Field(default_factory=dict)
    pause_before_result: bool = False
    result_stdout: str | None = None
    fail_with: str | None = None


class MockRuleAdded(BaseModel):
    rule_id: str
    status: str = Field(description="'added'")


class MockRuleView(BaseModel):
    """An installed rule, as listed in evaluation order."""

    rule_id: str
    match: dict[str, Any]
    pause_before_result: bool
    fail_with: str | None = None
    #: Whether the rule replaces the mock's output; the output itself is not
    #: returned.
    result_stdout: bool
    #: Whether the rule's gate is closed.
    paused: bool
    #: Jobs held at the rule's gate now.
    waiting: int


class MockRuleDeleted(BaseModel):
    rule_id: str
    #: False when no such rule was installed.
    deleted: bool


class MockRuleResumed(BaseModel):
    rule_id: str
    resumed: bool


class MockJobEvaluation(BaseModel):
    """Whether a job would run, and which rule it would meet; nothing is created."""

    params_valid: bool
    host_exists: bool
    rule_matched: str | None = None
    would_pause: bool = False
    errors: list[str] = Field(default_factory=list)


__all__ = [
    "MockJobEvaluation",
    "MockRouteMount",
    "MockRuleAdded",
    "MockRuleCreate",
    "MockRuleDeleted",
    "MockRuleResumed",
    "MockRuleView",
]
