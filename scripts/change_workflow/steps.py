"""The step table: each step's skill and the permission rules an unattended run of it
is held to, and what a model a step runs on is.

The table is `.claude/change-steps.toml`, the workflow's policy. Each step's rules
are its own plus `common`'s. The models each step runs on, and the orchestrating
session's, are the repository's preference, which its workflow configuration names
(`config`), so the loader refuses a row's `models` and an `[orchestrator]` table,
naming the field that holds them, rather than leave a value nothing reads.

Contract: openspec/specs/change-workflow/spec.md, CW-qu42.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .common import ORCHESTRATOR, Entry, StepError, repository_root
from .graph import STEPS

# The table's place in the repository the command acts on.
STEP_TABLE = Path(".claude/change-steps.toml")
HARNESSES = ("claude", "codex")


@dataclass(frozen=True)
class Model:
    """One model a step may run on: its harness, its name, and its effort."""

    harness: str
    model: str
    effort: str | None = None

    def entry(self) -> Entry:
        """The model as a log line records it."""
        return {"harness": self.harness, "model": self.model,
                **({"effort": self.effort} if self.effort else {})}


@dataclass(frozen=True)
class StepRules:
    """A step's skill and the permission rules an unattended run of it is held to."""

    skill: str
    allow: tuple[str, ...]
    deny: tuple[str, ...]
    # The step whose last session this step resumes, rather than starting fresh.
    resume_from: str | None = None


def _read_table(path: Path | None) -> tuple[Path, dict[str, Any]]:
    path = repository_root() / STEP_TABLE if path is None else path
    try:
        table = tomllib.loads(path.read_text("utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise StepError(f"cannot read the step table {path}: {exc}") from exc
    if ORCHESTRATOR in table:
        raise StepError(f"{path} has an [{ORCHESTRATOR}] table; the orchestrating session's "
                        f"model is the workflow configuration's models.{ORCHESTRATOR}")
    if unknown := set(table) - {"common", "steps"}:
        raise StepError(f"{path} has unknown tables: {', '.join(sorted(unknown))}")
    return path, table


def load_steps(path: Path | None = None) -> dict[str, StepRules]:
    """Each step's rules, `common`'s added to its own, from the table at `path`, or
    the repository's own."""
    path, table = _read_table(path)
    common = table.get("common", {})
    if set(common) - {"allow", "deny"}:
        raise StepError(f"{path}'s common row takes only allow and deny")
    steps = {}
    for name, row in table.get("steps", {}).items():
        if name not in STEPS:
            raise StepError(f"{path} names an unknown step {name!r}")
        if "models" in row:
            raise StepError(f"{path}'s {name} row names models; a step's models are the "
                            f"workflow configuration's models.{name}")
        if "skill" not in row or set(row) - {"skill", "allow", "deny", "resume_from"}:
            raise StepError(f"{path}'s {name} row needs a skill, and takes only skill, allow, "
                            "deny, and resume_from")
        steps[name] = StepRules(
            skill=row["skill"],
            allow=(*_rules(path, common, "allow"), *_rules(path, row, "allow")),
            deny=(*_rules(path, common, "deny"), *_rules(path, row, "deny")),
            resume_from=row.get("resume_from"))
    for name, rules in steps.items():
        if rules.resume_from is not None and rules.resume_from not in steps:
            raise StepError(f"{path}'s {name} row resumes {rules.resume_from!r}, which has "
                            "no row")
    return steps


def _rules(path: Path, row: dict[str, Any], key: str) -> tuple[str, ...]:
    # A string here would be spread into characters, silently dropping its rule.
    rules = row.get(key, [])
    if not isinstance(rules, list) or not all(isinstance(rule, str) and rule for rule in rules):
        raise StepError(f"{path}: {key} must be a list of rules")
    return tuple(rules)
