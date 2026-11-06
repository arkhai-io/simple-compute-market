"""The repository's workflow configuration, `.agents/workflow.toml`: what the change
workflow assumes about the repository it runs in, read and checked whole.

Each field configures one operation of a skill or the engine, and a value Git or
the invocation supplies is never one. The workflow defines every table and key; an
adopting repository changes what a field holds and adds none, so an unknown table
or key is a typo or a newer workflow's, and is refused, naming it. Every reader
checks the whole file as it loads it (`load`), as the step table's loader refuses
a malformed table, so a subcommand never acts on half a configuration; with no
file, every field is absent.

A hook, a validation part's command, or the preflight holds one shell command or a
list of them. A command names the values it needs as placeholders the engine
fills in, shell-quoted: `{change}` and `{base}` anywhere but `pre-push`, which has
`{remote}` alone, `{owed}` only in an owed part's `run`, `start`, and `collect`, and
`{after}` only in a `collect`. `openspec.command` takes none: the arguments it is
run with follow it. A placeholder is a name in braces not preceded by `$`, so the
shell's own `${VAR}` passes through; any other name in braces, known or not, is
refused where it is used, when the file is checked.

A field is required or optional. A required field's absence refuses only the steps
that need it, naming the field, before anything is launched (`missing`); an
explicit empty value counts as declared, so a repository says "nothing here"
deliberately, but a validation part always names a command.

Each step's models, in order of preference, and the orchestrating session's model
are held to the workflow's model policy as they are read: no step names two models
of one vendor, and only the review names a Codex model. No model is forbidden: a
repository that never wants one does not list it.

`config` lists every field and how it resolved, `config load <step>` the documents
a step's skill reads, and `config parts <change>` validation's plan for the change.

Contract: openspec/specs/change-workflow/spec.md, CW-f3qk, CW-w8ne, CW-t5hz,
CW-v2dq, CW-l7hn, CW-o6kc, CW-g4oz, CW-i2we, CW-n7ra, CW-ebmo, CW-zq4h, and CW-w2ld.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from .common import ORCHESTRATOR, StepError, repository_root
from .graph import STEPS
from .steps import HARNESSES, Model

# The configuration's place in the repository the command acts on.
CONFIGURATION = Path(".agents/workflow.toml")

# The hooks named by when they run. `pre-push` and `post-clone` belong to the
# engine's own push and clone, so no step runs them through `run`.
HOOKS = ("after-functional-change", "pre-commit", "pre-commit-functional", "pre-archive",
         "pre-push", "post-clone")
# The default checks of `pre-commit`, run before its declared commands unless
# `defaults.disable` names them.
DEFAULT_CHECKS = ("index", "tasks", "skills", "openspec")
# The OpenSpec command when the configuration names none.
DEFAULT_OPENSPEC = "openspec"
# The documents every session reads as it starts, which a step's own add to.
COMMON_DOCUMENTS = "common"
_PART_KEYS = ("run", "start", "collect", "owed", "after", "evidence", "cleanup")
_TABLES: dict[str, tuple[str, ...]] = {
    "repository": ("protected-branches", "inert-paths"),
    "hooks": HOOKS,
    "defaults": ("disable",),
    "openspec": ("command",),
    "load": (COMMON_DOCUMENTS, *STEPS),
    "models": (ORCHESTRATOR, *STEPS),
    "validation": ("preflight", "parts"),
}
# The placeholders every command may use, but `pre-push`'s: the guarded push pushes a
# branch, not a change, so it has the remote alone to give.
_EVERYWHERE = frozenset({"change", "base"})
_PRE_PUSH = frozenset({"remote"})
PLACEHOLDERS = frozenset({"change", "base", "remote", "owed", "after"})
# A name in braces, not the shell's `${…}`.
PLACEHOLDER = re.compile(r"(?<!\$)\{([A-Za-z_][A-Za-z0-9_-]*)\}")


def placeholders(command: str) -> list[str]:
    """The placeholders `command` names, in order."""
    return PLACEHOLDER.findall(command)


def fill(command: str, values: Mapping[str, str]) -> str:
    """`command` with each placeholder replaced by its value, shell-quoted. The
    configuration's check has refused any placeholder unknown where it is used, so a
    placeholder without a value is one this invocation does not supply."""
    def value(name: str) -> str:
        if name not in values:
            raise StepError(f"{{{name}}} has no value in this run")
        return shlex.quote(values[name])

    return PLACEHOLDER.sub(lambda match: value(match.group(1)), command)


# Required fields, by the name `missing` reports.
PRE_COMMIT_FUNCTIONAL = "hooks.pre-commit-functional"
PARTS = "validation.parts"
PROTECTED_BRANCHES = "repository.protected-branches"


class ConfigError(StepError):
    """The configuration is malformed, or lacks a field a step needs."""


@dataclass(frozen=True)
class Part:
    """A validation part: `run`, or `start` and `collect`; whether it is owed once
    per `Owed by validation:` line; the part it follows; where its evidence goes;
    and what archive cleanup runs for it."""

    name: str
    run: tuple[str, ...] | None = None
    start: tuple[str, ...] | None = None
    collect: tuple[str, ...] | None = None
    owed: bool = False
    after: str | None = None
    evidence: str | None = None
    cleanup: tuple[str, ...] | None = None

    @property
    def shape(self) -> str:
        return "run" if self.run is not None else "start, collect"


@dataclass(frozen=True)
class Configuration:
    """The configuration as checked. A field the file does not declare is None, or
    missing from its mapping; `exists` says whether there is a file at all."""

    path: Path
    exists: bool = False
    protected_branches: tuple[str, ...] | None = None
    inert_paths: tuple[str, ...] | None = None
    hooks: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    # Each disabled default check and its reason.
    disabled: Mapping[str, str] = field(default_factory=dict)
    openspec: str | None = None
    load: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    models: Mapping[str, Any] = field(default_factory=dict)
    preflight: tuple[str, ...] | None = None
    parts: tuple[Part, ...] | None = None

    def hook(self, name: str) -> tuple[str, ...] | None:
        """The hook's commands, or None when it is not declared."""
        return self.hooks.get(name)

    def part(self, name: str) -> Part:
        for part in self.parts or ():
            if part.name == name:
                return part
        declared = ", ".join(part.name for part in self.parts or ()) or "none"
        raise ConfigError(f"{self.shown} declares no validation part {name!r}; its parts: "
                          f"{declared}")

    def openspec_command(self) -> str:
        return self.openspec if self.openspec is not None else DEFAULT_OPENSPEC

    def documents(self, step: str) -> list[str]:
        """The documents a step's skill reads: `load.common`, then `load.<step>`,
        each once."""
        return list(dict.fromkeys((*self.load.get(COMMON_DOCUMENTS, ()),
                                   *self.load.get(step, ()))))

    def step_models(self, step: str) -> tuple[Model, ...]:
        """The models a step's unattended runs use, in order of preference; refused,
        naming the field, when the configuration names none."""
        require(self, f"models.{step}", needed_by=f"an unattended {step} run")
        return tuple(Model(entry["harness"], entry["model"], entry.get("effort"))
                     for entry in self.models[step])

    def orchestrator_model(self) -> Model:
        """The orchestrating session's model and effort; refused, naming the field,
        when the configuration names none."""
        require(self, f"models.{ORCHESTRATOR}", needed_by="the orchestrating session")
        entry = self.models[ORCHESTRATOR]
        return Model("claude", entry["model"], entry.get("effort"))

    def evidence(self) -> list[str]:
        """Every declared part's evidence directory, each once, in declaration order."""
        return list(dict.fromkeys(part.evidence for part in self.parts or ()
                                  if part.evidence is not None))

    @property
    def shown(self) -> str:
        return CONFIGURATION.as_posix()


def _commands(where: str, value: Any, available: frozenset[str]) -> tuple[str, ...]:
    """A command field's commands: one string or a list of them, each checked for
    placeholders unknown or unavailable at `where`."""
    commands = [value] if isinstance(value, str) else value
    if not isinstance(commands, list) or not all(isinstance(c, str) and c.strip()
                                                 for c in commands):
        raise ConfigError(f"{where} must be a command or a list of commands, each a "
                          f"non-empty string; got {value!r}")
    for command in commands:
        for name in placeholders(command):
            if name not in PLACEHOLDERS:
                raise ConfigError(f"{where} names {{{name}}}, which is no placeholder the "
                                  "workflow fills; known: "
                                  + ", ".join(f"{{{p}}}" for p in sorted(PLACEHOLDERS)))
            if name not in available:
                raise ConfigError(f"{where} names {{{name}}}, which is not available there; "
                                  "available: "
                                  + ", ".join(f"{{{p}}}" for p in sorted(available)))
    return tuple(commands)


def _strings(where: str, value: Any) -> tuple[str, ...]:
    """A list of non-empty strings; an empty list is a deliberate "none"."""
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise ConfigError(f"{where} must be a list of non-empty strings; got {value!r}")
    return tuple(value)


def _string(where: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{where} must be a non-empty string; got {value!r}")
    return value


def _table(where: str, value: Any, keys: Sequence[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"{where} must be a table; got {value!r}")
    for key in value:
        if key not in keys:
            raise ConfigError(f"{where}.{key} is no field the workflow defines; "
                              f"{where} takes " + ", ".join(keys))
    return value


def _model(where: str, entry: Any, *, harness: bool) -> dict[str, Any]:
    keys = ("harness", "model", "effort") if harness else ("model", "effort")
    entry = _table(where, entry, keys)
    _string(f"{where}.model", entry.get("model"))
    if "effort" in entry:
        _string(f"{where}.effort", entry["effort"])
    if harness and entry.get("harness") not in HARNESSES:
        raise ConfigError(f"{where}.harness must be one of {', '.join(HARNESSES)}; got "
                          f"{entry.get('harness')!r}")
    return dict(entry)


def _models(table: dict[str, Any]) -> dict[str, Any]:
    """Each step's models, in order of preference, refusing what the workflow's model
    policy forbids, naming the step.

    A harness is one vendor's, so two entries of one harness are two models of one
    vendor: an outage or a usage limit takes both down, and the second is no
    fallback. Codex runs only the review, the one step its read-only sandbox can
    hold to its limits; a writing sandbox cannot refuse a commit or a relock.
    """
    models: dict[str, Any] = {}
    for key, value in table.items():
        where = f"models.{key}"
        if key == ORCHESTRATOR:
            models[key] = _model(where, value, harness=False)
            continue
        if not isinstance(value, list) or not value:
            raise ConfigError(f"{where} must be a list of one or more models; got {value!r}")
        entries = [_model(f"{where}[{index}]", entry, harness=True)
                   for index, entry in enumerate(value)]
        harnesses = [entry["harness"] for entry in entries]
        if len(set(harnesses)) != len(harnesses):
            raise ConfigError(f"{where} names two models of one vendor for the {key} step, "
                              "which an outage or a usage limit takes down together")
        if "codex" in harnesses and key != "review":
            raise ConfigError(f"{where} names a Codex model for the {key} step; Codex runs "
                              "only the review")
        models[key] = entries
    return models


def _disabled(value: Any) -> dict[str, str]:
    if not isinstance(value, list):
        raise ConfigError(f"defaults.disable must be a list; got {value!r}")
    disabled: dict[str, str] = {}
    for index, entry in enumerate(value):
        where = f"defaults.disable[{index}]"
        if not isinstance(entry, dict) or set(entry) != {"check", "reason"}:
            raise ConfigError(f"{where} must be a table naming a check and a reason, "
                              f"{{ check = \"…\", reason = \"…\" }}; got {entry!r}")
        check = entry["check"]
        if check not in DEFAULT_CHECKS:
            raise ConfigError(f"{where} names {check!r}, which is no default check; the "
                              "default checks: " + ", ".join(DEFAULT_CHECKS))
        if not isinstance(entry["reason"], str) or not entry["reason"].strip():
            raise ConfigError(f"{where} turns off {check} without a reason; a default check "
                              "is turned off only with one")
        disabled[check] = entry["reason"]
    return disabled


def _parts(value: Any) -> tuple[Part, ...]:
    if not isinstance(value, dict):
        raise ConfigError(f"validation.parts must be a table of parts; got {value!r}")
    parts: list[Part] = []
    for name, declared in value.items():
        where = f"validation.parts.{name}"
        if name == "preflight":
            raise ConfigError(f"{where}: `preflight` names validation's preflight, so no part "
                              "takes the name")
        table = _table(where, declared, _PART_KEYS)
        owed = table.get("owed", False)
        if not isinstance(owed, bool):
            raise ConfigError(f"{where}.owed must be true or false; got {owed!r}")
        running = _EVERYWHERE | ({"owed"} if owed else set())
        shapes = [key for key in ("run", "start") if key in table]
        if len(shapes) != 1 or ("start" in table) != ("collect" in table):
            raise ConfigError(f"{where} declares `run`, or `start` and `collect`, and not "
                              "both shapes; it declares "
                              + (", ".join(k for k in ("run", "start", "collect") if k in table)
                                 or "neither"))
        commands = {key: _commands(f"{where}.{key}", table[key],
                                   running | ({"after"} if key == "collect" else set()))
                    for key in ("run", "start", "collect") if key in table}
        # A hook's empty list says "nothing here"; a part that runs nothing would
        # pass without evidence, and a `start` running nothing prints no marker.
        if empty := [key for key, value in commands.items() if not value]:
            raise ConfigError(f"{where}.{empty[0]} must name a command; a part runs one or "
                              "more")
        after = _string(f"{where}.after", table["after"]) if "after" in table else None
        evidence = _string(f"{where}.evidence", table["evidence"]) if "evidence" in table \
            else None
        cleanup = (_commands(f"{where}.cleanup", table["cleanup"], _EVERYWHERE)
                   if "cleanup" in table else None)
        parts.append(Part(name, run=commands.get("run"), start=commands.get("start"),
                          collect=commands.get("collect"), owed=owed, after=after,
                          evidence=evidence, cleanup=cleanup))
    # Validation runs the parts in declaration order, every dispatch before any long
    # part, so an `after` it could not keep — a part declared later, which also
    # rules out every cycle, or a long part followed by a dispatch — is refused
    # here rather than left for an unattended run to improvise around.
    declared = {part.name: index for index, part in enumerate(parts)}
    for index, part in enumerate(parts):
        if part.after is None:
            continue
        where = f"validation.parts.{part.name}.after"
        if part.after not in declared or part.after == part.name:
            raise ConfigError(f"{where} names {part.after!r}, which is no other declared part")
        if declared[part.after] > index:
            raise ConfigError(f"{where} names {part.after!r}, which is declared after it; a "
                              "part follows only a part declared before it")
        if part.start is not None and parts[declared[part.after]].run is not None:
            raise ConfigError(f"{where} names {part.after!r}, a `run` part, but every "
                              "`start` is dispatched before any `run` part runs")
    return tuple(parts)


def check(text: str, path: Path) -> Configuration:
    """The configuration `text` holds, checked whole; refused, naming the field, on
    an unknown table or key, a wrong type, or a placeholder unknown or unavailable
    where it is used."""
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{CONFIGURATION.as_posix()} is not TOML: {exc}") from exc
    for name in raw:
        if name not in _TABLES:
            raise ConfigError(f"{name} is no table the workflow defines; its tables: "
                              + ", ".join(_TABLES))
    tables = {name: _table(name, raw[name], keys) for name, keys in _TABLES.items()
              if name in raw}
    repository = tables.get("repository", {})
    hooks_table = tables.get("hooks", {})
    hooks = {name: _commands(f"hooks.{name}", value,
                             _PRE_PUSH if name == "pre-push" else _EVERYWHERE)
             for name, value in hooks_table.items()}
    validation = tables.get("validation", {})
    load = {key: _strings(f"load.{key}", value)
            for key, value in tables.get("load", {}).items()}
    return Configuration(
        path=path, exists=True,
        protected_branches=(_strings(PROTECTED_BRANCHES, repository["protected-branches"])
                            if "protected-branches" in repository else None),
        inert_paths=(_strings("repository.inert-paths", repository["inert-paths"])
                     if "inert-paths" in repository else None),
        hooks=hooks,
        disabled=_disabled(tables["defaults"]["disable"])
        if "disable" in tables.get("defaults", {}) else {},
        openspec=(_commands("openspec.command",
                            _string("openspec.command", tables["openspec"]["command"]),
                            frozenset())[0]
                  if "command" in tables.get("openspec", {}) else None),
        load=load,
        models=_models(tables.get("models", {})),
        preflight=(_commands("validation.preflight", validation["preflight"], _EVERYWHERE)
                   if "preflight" in validation else None),
        parts=_parts(validation["parts"]) if "parts" in validation else None,
    )


def load(root: Path) -> Configuration:
    """The configuration of the repository at `root`, checked whole; every field
    absent when the file does not exist."""
    path = root / CONFIGURATION
    try:
        text = path.read_text("utf-8")
    except FileNotFoundError:
        return Configuration(path=path)
    except OSError as exc:
        raise ConfigError(f"cannot read {CONFIGURATION.as_posix()}: {exc}") from exc
    return check(text, path)


def missing(configuration: Configuration, *fields: str) -> list[str]:
    """Of the required `fields`, those the configuration does not declare. An
    explicit empty value is declared."""
    absent = []
    for name in fields:
        if name == PRE_COMMIT_FUNCTIONAL:
            present = configuration.hook("pre-commit-functional") is not None
        elif name == PARTS:
            present = bool(configuration.parts)
        elif name == PROTECTED_BRANCHES:
            present = configuration.protected_branches is not None
        elif name.startswith("models."):
            present = name.removeprefix("models.") in configuration.models
        else:
            raise ConfigError(f"{name} is no required field")
        if not present:
            absent.append(name)
    return absent


# The name `start` gives the orchestrating session, which is no step of the graph.
ORCHESTRATOR_STEP = "orchestrate"

# The required fields `start` checks for each step: every step but the review, which
# writes nothing, pushes, so it needs the protected branches; implementation, triage,
# and the merge make functional commits, so they need the functional checks;
# validation runs the declared parts.
STEP_NEEDS: dict[str, tuple[str, ...]] = {
    step: (PROTECTED_BRANCHES,) for step in STEPS if step != "review"}
STEP_NEEDS.update({
    "implement": (PROTECTED_BRANCHES, PRE_COMMIT_FUNCTIONAL),
    "triage": (PROTECTED_BRANCHES, PRE_COMMIT_FUNCTIONAL),
    "merge": (PROTECTED_BRANCHES, PRE_COMMIT_FUNCTIONAL),
    "validate": (PROTECTED_BRANCHES, PARTS),
})


def require(configuration: Configuration, *fields: str, needed_by: str) -> None:
    """Refuse, naming each field, when a required field `needed_by` needs is absent."""
    if absent := missing(configuration, *fields):
        raise ConfigError(f"{needed_by} needs {', '.join(absent)}, which "
                          f"{configuration.shown} does not declare"
                          + ("" if configuration.exists else " (there is no such file)")
                          + "; an empty value declares it deliberately")


def require_for_step(configuration: Configuration, step: str, *,
                     unattended: bool = False) -> None:
    """Refuse a step whose required fields are absent, before anything is launched:
    an unattended run also needs its step's models, and the orchestrating session
    needs its own."""
    if step == ORCHESTRATOR_STEP:
        require(configuration, f"models.{ORCHESTRATOR}", needed_by="the orchestrating session")
        return
    require(configuration, *STEP_NEEDS.get(step, ()),
            *((f"models.{step}",) if unattended else ()), needed_by=step)


# Resolution: every field and how it resolved.

DECLARED, DEFAULT, DISABLED, ABSENT = "declared", "default", "disabled", "absent"
# What each default check runs, as `config` shows it.
_DEFAULT_SHOWN = {
    "index": "scripts/change-workflow check index",
    "tasks": "scripts/change-workflow check tasks <change>",
    "skills": "scripts/change-workflow check skills",
    "openspec": "{openspec} validate <change> --strict, or validate --specs --strict for an "
                "archived change",
}


def resolution(configuration: Configuration) -> list[dict[str, Any]]:
    """Every field the workflow defines and how it resolved — declared, default,
    disabled, or absent — with what it resolves to: a command field's commands, any
    other field's value."""
    fields: list[dict[str, Any]] = []

    def add(name: str, status: str, value: Any = None, **more: Any) -> None:
        fields.append({"field": name, "status": status,
                       **({"value": value} if value is not None else {}), **more})

    for key, value in (("protected-branches", configuration.protected_branches),
                       ("inert-paths", configuration.inert_paths)):
        add(f"repository.{key}", ABSENT if value is None else DECLARED,
            None if value is None else list(value))
    for hook in HOOKS:
        commands = configuration.hook(hook)
        add(f"hooks.{hook}", ABSENT if commands is None else DECLARED,
            None if commands is None else list(commands))
    for check_ in DEFAULT_CHECKS:
        if check_ in configuration.disabled:
            add(f"defaults.{check_}", DISABLED, reason=configuration.disabled[check_])
        else:
            add(f"defaults.{check_}", DEFAULT, _DEFAULT_SHOWN[check_].format(
                openspec=configuration.openspec_command()))
    add("openspec.command", DEFAULT if configuration.openspec is None else DECLARED,
        configuration.openspec_command())
    for key in _TABLES["load"]:
        documents = configuration.load.get(key)
        add(f"load.{key}", ABSENT if documents is None else DECLARED,
            None if documents is None else list(documents))
    for key in _TABLES["models"]:
        models = configuration.models.get(key)
        add(f"models.{key}", ABSENT if models is None else DECLARED, models)
    add("validation.preflight", ABSENT if configuration.preflight is None else DECLARED,
        None if configuration.preflight is None else list(configuration.preflight))
    if not configuration.parts:
        add(PARTS, ABSENT)
    for part in configuration.parts or ():
        for key in _PART_KEYS:
            value = getattr(part, key)
            if key == "owed":
                add(f"{PARTS}.{part.name}.owed", DECLARED if value else DEFAULT, value)
            else:
                add(f"{PARTS}.{part.name}.{key}", ABSENT if value is None else DECLARED,
                    list(value) if isinstance(value, tuple) else value)
    return fields


def _shown_value(value: Any) -> str:
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return "; ".join(value) if value else "(empty)"
    return json.dumps(value, ensure_ascii=False)


def resolution_lines(configuration: Configuration) -> list[str]:
    lines = [f"{configuration.shown}: " + ("read" if configuration.exists
                                           else "no such file; every field is absent")]
    for entry in resolution(configuration):
        detail = (f"— {entry['reason']}" if "reason" in entry
                  else _shown_value(entry["value"]) if "value" in entry else "")
        lines.append(f"{entry['field']:<44} {entry['status']:<9} {detail}".rstrip())
    return lines


# Validation's plan for a change.

@dataclass(frozen=True)
class PlannedRun:
    """One run of a part in validation's plan: an owed part's names the workflow it
    is owed for and the sections owing it, or is `not owed`."""

    part: Part
    owed: str | None = None
    sections: tuple[str, ...] = ()
    not_owed: bool = False

    @property
    def name(self) -> str:
        return f"{self.part.name} {self.owed}" if self.owed else self.part.name

    def entry(self) -> dict[str, Any]:
        return {"name": self.name, "part": self.part.name, "owed": self.owed,
                "not_owed": self.not_owed, "sections": list(self.sections),
                "shape": "run" if self.part.run is not None else "start-collect",
                "after": self.part.after, "evidence": self.part.evidence}


def plan(configuration: Configuration, owed: Sequence[tuple[str, str]]) -> list[PlannedRun]:
    """Each run of a part, in declaration order: an owed part once per workflow the
    complete sections owe (`owed`, each a section and a workflow), or once as not
    owed. Two lines owing one workflow are one run, owed by both sections, since a
    run is named by its workflow."""
    require(configuration, PARTS, needed_by="validation")
    by_workflow: dict[str, list[str]] = {}
    for section, workflow in owed:
        by_workflow.setdefault(workflow, [])
        if section not in by_workflow[workflow]:
            by_workflow[workflow].append(section)
    runs: list[PlannedRun] = []
    for part in configuration.parts or ():
        if not part.owed:
            runs.append(PlannedRun(part))
        elif not by_workflow:
            runs.append(PlannedRun(part, not_owed=True))
        else:
            runs.extend(PlannedRun(part, workflow, tuple(sections))
                        for workflow, sections in by_workflow.items())
    return runs


def plan_lines(configuration: Configuration, runs: Sequence[PlannedRun]) -> list[str]:
    preflight = "; ".join(configuration.preflight) if configuration.preflight else "none"
    lines = [f"{'preflight':<20} {preflight}"]
    for run in runs:
        if run.not_owed:
            lines.append(f"{run.name:<20} not owed")
            continue
        shape = run.part.shape + (f"   after {run.part.after}" if run.part.after else "")
        owing = (f"owed by section{'s' if len(run.sections) > 1 else ''} "
                 + ", ".join(run.sections)) if run.owed else ""
        evidence = f"evidence {run.part.evidence}" if run.part.evidence else ""
        lines.append("   ".join(text for text in (f"{run.name:<20} {shape:<17}", owing,
                                                   evidence) if text).rstrip())
    return lines


def plan_json(configuration: Configuration, runs: Sequence[PlannedRun]) -> str:
    return json.dumps({"preflight": list(configuration.preflight)
                       if configuration.preflight is not None else None,
                       "runs": [run.entry() for run in runs]}, ensure_ascii=False)


def main(argv: Sequence[str] | None = None, root: Path | None = None) -> int:
    """`config [--json]`, `config load <step>` or `config load common`, and `check
    config`, as `cli` hands them on; `config parts`, which reads a change's task
    list, is `cli`'s."""
    parser = argparse.ArgumentParser(prog="change-workflow config")
    parser.add_argument("action", choices=("show", "load", "check"))
    parser.add_argument("step", nargs="?", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    # `common` names no step: it is for a session no step of the graph runs, such
    # as the orchestrating session, which reads `load.common` alone.
    if args.action == "load" and args.step not in (*STEPS, COMMON_DOCUMENTS):
        print(f"usage: config load <step>, a step of: {', '.join(STEPS)}, or "
              f"{COMMON_DOCUMENTS}", file=sys.stderr)
        return 2
    try:
        configuration = load(repository_root() if root is None else root)
    except StepError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if args.action == "check":
        print(f"OK: {configuration.shown} "
              + ("passes its check." if configuration.exists
                 else "does not exist; every field is absent."))
    elif args.action == "load":
        for document in configuration.documents(args.step):
            print(document)
    elif args.json:
        print(json.dumps({"file": configuration.shown, "exists": configuration.exists,
                          "fields": resolution(configuration)}, ensure_ascii=False))
    else:
        print("\n".join(resolution_lines(configuration)))
    return 0
