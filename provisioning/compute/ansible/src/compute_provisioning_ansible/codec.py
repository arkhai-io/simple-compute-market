"""What a domain contributes to run its jobs as Ansible playbooks.

``AnsibleJobExecutor`` owns the mechanics every Ansible job shares: rendering
the variables file and the inventory, running the playbook, redacting what it
reports, and classifying transport failures. A domain contributes an
``AnsibleJobCodec`` for everything that is its own: how a job's opaque
parameters become playbook variables, which inventory group its playbooks
target, what a playbook's output means as a result and credentials, which of
its own failures are not worth retrying, and which fields its playbooks print
that are secret.

A codec is a pure translation over its domain's parameter model, which the
job authority stores without reading. A third domain contributes a codec and
a playbook; nothing here changes.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from compute_provisioning_contracts import CredentialEnvelope, ResultEnvelope
from compute_provisioning.jobs import JobRun

from .runner import AnsibleResult, InventoryTarget


@dataclass(frozen=True)
class AnsibleJobPlan:
    """How one attempt at a job runs, as its codec prepared it.

    ``variables`` are the job's own playbook variables and are authoritative;
    ``extra_variables`` are operator-supplied ones (a pool's configuration, for
    example), which may add variables but never replace one of the job's own.
    ``limit`` restricts the run to the host the job names. ``playbook_path``,
    when set, replaces the executor's playbook for this job.
    """

    variables: Mapping[str, Any]
    limit: str
    extra_variables: Mapping[str, Any] = field(default_factory=dict)
    playbook_path: Path | None = None


@dataclass(frozen=True)
class AnsibleJobInterpretation:
    """What a successful playbook run produced, in the job authority's terms."""

    result: ResultEnvelope | None
    credentials: tuple[CredentialEnvelope, ...] = ()


class AnsibleJobCodec(Protocol):
    """A domain's translation between its jobs and its playbooks."""

    #: The inventory group the domain's playbooks target.
    inventory_group: str

    #: Fields the domain's playbooks may print whose values are secret, beyond
    #: the ones every playbook's output is scrubbed of.
    secret_fields: frozenset[str]

    def prepare(self, run: JobRun) -> AnsibleJobPlan:
        """Variables, limit, and playbook for one attempt at ``run``'s job.

        Called immediately before the playbook starts, so a value resolved
        here (a credential the job references, say) is current for every
        attempt, retries included. Raising refuses the attempt as a failure
        the executor did not anticipate, which is never retried.
        """

    def interpret(
        self, run: JobRun, host: InventoryTarget, output: AnsibleResult
    ) -> AnsibleJobInterpretation:
        """The result and credentials a successful run's output reports."""

    def is_retryable(self, message: str) -> bool:
        """Whether a failure reported as ``message`` could succeed if run again.

        Answers only for the domain's own failures; transport failures and
        operator-configured patterns are classified by the executor.
        """


def matches_any(message: str, patterns: tuple[str, ...] | frozenset[str]) -> bool:
    """Whether ``message`` contains one of ``patterns``, ignoring case."""
    lowered = message.lower()
    return any(pattern.lower() in lowered for pattern in patterns)


def render_extra_vars(
    variables: Mapping[str, Any], extra_variables: Mapping[str, Any] = {}
) -> str:
    """The extra-vars YAML document for a plan's variables.

    Each value is written as JSON, which is YAML, so a string is always a
    string whatever it contains. A job's own variables are authoritative: an
    extra variable with the same name is a configuration error, refused here
    rather than silently overriding the job.
    """
    colliding = sorted(set(variables) & set(extra_variables))
    if colliding:
        raise ValueError(
            "extra variables collide with the job's own variables: "
            + ", ".join(colliding)
        )
    lines = [f"{name}: {json.dumps(value)}" for name, value in variables.items()]
    lines.extend(
        f"{name}: {json.dumps(extra_variables[name])}" for name in sorted(extra_variables)
    )
    return "\n".join(lines) + "\n"


def write_extra_vars(plan: AnsibleJobPlan) -> Path:
    """Write a plan's variables to a new owner-only file and return its path.

    The file may hold credentials a job resolved, so it never exists with wider
    permissions; the caller removes it when the run ends.
    """
    content = render_extra_vars(plan.variables, plan.extra_variables)
    path = Path(tempfile.gettempdir()) / f"ansible_vars_{uuid.uuid4().hex}.yml"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path


__all__ = [
    "AnsibleJobCodec",
    "AnsibleJobInterpretation",
    "AnsibleJobPlan",
    "matches_any",
    "render_extra_vars",
    "write_extra_vars",
]
