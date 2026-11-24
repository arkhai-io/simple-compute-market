"""The repository's workflow configuration, `.agents/workflow.toml`, and the
checkout's local configuration beside it, `.agents/workflow.local.toml`: what the
change workflow assumes about the repository it runs in, read and checked whole.

A setting is local exactly when developers using the workflow on the same repository
may give it different values: the engineering-guidance pointer, `[models]`, and the
writable sandbox paths a developer adds, which extend the committed ones. Every other
field is committed. Each key has one home, and a key in the wrong file is refused,
naming the file it belongs in; writable sandbox paths alone are declared in both.
The local file is ignored by Git, and may be absent, every local field then missing:
`check config` and `config --json` report them so and succeed, while a step needing
one is refused, naming it and `change-workflow install`, which writes the file.

The committed `[workflow] version` is the range of workflow versions the repository
accepts, comma-separated specifiers (`>=`, `<=`, `>`, `<`, `==`, `!=`, `~=`) over
release numbers. It is required, and read before anything else in the file, so an
engine outside the range refuses, naming its version, the range, and the fix, rather
than reporting a newer workflow's table as unknown, and a committed file declaring no
range is refused whole.

`[guidance] engineering`, the pointer, is required of every step: it names where the
user's engineering guidance is, `{ path = "<directory>" }`, from the checkout's root
or `~`, holding Markdown files, or `{ none = "<reason>" }`. No `load` entry overlaps
the pointer's directory, so nothing is read twice.

Each field configures one operation of a skill or the engine, and a value Git or
the invocation supplies is never one. The workflow defines every table and key; an
adopting repository changes what a field holds and adds none, so an unknown table
or key is a typo or a newer workflow's, and is refused, naming it. Every reader
checks the whole file as it loads it (`load`), so a subcommand never acts on half a
configuration; with no file, every field is absent.

A hook, an evidence kind's command, or the preflight holds one shell command or a
list of them. A command names the values it needs as placeholders the engine
fills in, shell-quoted: `{change}` and `{base}` anywhere but `pre-push`, which has
`{remote}` alone; `{tree}` and `{commit}` in a kind's commands and in
`after-functional-change` and `pre-commit-functional`; `{owed}` only in an
owed kind's `run`, `start`, and `collect`; `{after}` only in a `collect`; `{inputs}`
in a step hook, `before-<step>` or `after-<step>`; and `{kind}` in a review's and a
triage's step hooks. `openspec.command` takes none: the arguments it is run with
follow it. A placeholder is a name in braces not preceded by `$`, so the shell's own
`${VAR}` passes through; any other name in braces, known or not, is refused where it
is used, when the file is checked.

An evidence kind, `[validation.evidence.<kind>]`, is required `always` or when
`owed`; its `evidence` is a pattern over paths from the repository's root holding
exactly one of `{tree}` and `{commit}`, the identity its evidence describes, and
`{owed}` if and only if the kind is owed, so each owed argument's evidence is its
own. The pattern's fixed directory — its leading segments, holding no placeholder
and no glob character — must be one Git ignores, since a file the workflow writes
after implementation must never change the tree its evidence describes. A kind
runs `run`, or `start` then `collect`, may follow another (`after`), may name a
`cleanup`, and names its guide, a non-empty file the steps read to assess its
evidence.

A field is required or optional. A required field's absence refuses only the steps
that need it, naming the field, before anything is launched (`missing`); an
explicit empty value counts as declared, so a repository says "nothing here"
deliberately, but an evidence kind always names a command.

Each step's models, in order of preference, and the orchestrating session's model
are held to the workflow's model policy as they are read: no step names two models
of one vendor, and a model appears only for a step its harness's adapter can run
(`adapters`). No model is forbidden: a repository that never wants one does not list
it.

A review's draft the format check refuses is sent back to the reviewer that wrote
it, for correction, as many times as `review.format-retries` says: once when the
field is absent, never when it is 0.

`[sandbox]` adds to each step's scope, which the engine's baseline and the adapter
of the harness running the step hold (`scope`): `writable.common` paths every step
writes, the review only those outside its checkout, `writable.<step>` paths one step
writes, and `protected` paths
no step writes. A repository only adds: the check refuses a writable path that is or
lies under a protected one, the engine's, any adapter's, or its own; `/tmp` or a
directory holding it, which would hide the private `/tmp` every step writes; and any
writable path for the review.

`config` lists every field and how it resolved, each kind's guide among them, and
each step's resolved scope, every path with its source; `config --json` gives the
same as one object, with the distribution's documents by role and each role the
workflow leaves to an adopting repository with the fields that provide it (`ROLES`),
neither depending on the local file; `check config` reports, and
does not refuse, each local field the checkout lacks, and each engineering section a
shipped skill or the workflow's guidance cites that the guidance beneath the pointer
does not resolve (`sections`); `config load <step>` the
documents a step's skill reads: the engineering guidance beneath the pointer, the
workflow's own guidance, which the distribution ships (`documents`), then
`load.common` and `load.<step>`, each document once.

Contract: openspec/specs/change-workflow/spec.md, CW-f3qk, CW-w8ne, CW-t5hz,
CW-v2dq, CW-l7hn, CW-o6kc, CW-g4oz, CW-t3ev, CW-g1gn, CW-r5qk, CW-k7gd, CW-h3ks,
CW-i2we, CW-n7ra, CW-ebmo, CW-zq4h, CW-w2ld, CW-r8fb, CW-h2zt, CW-f8yy, CW-4pm4,
CW-hu0z, CW-7x0z, CW-c8lw, and CW-ora1.
"""

from __future__ import annotations

import argparse
import glob
import json
import re
import shlex
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, Sequence

from . import documents as distribution
from . import sections
from .common import ORCHESTRATOR, StepError, repository_root
from .graph import STEPS
from .adapters import ADAPTERS, HARNESSES
from .adapters import PROTECTED as ADAPTER_PROTECTED
from .harness import Model
from .records import is_pattern
from .scope import (INSTALLED, PRIVATE_TEMPORARY, PROTECTED, Scope, absolute,
                    hides_temporary, outside_checkout, protected_by, resolve, within)

# The configuration's place in the repository the command acts on, and the
# checkout's local configuration beside it.
CONFIGURATION = Path(".agents/workflow.toml")
LOCAL = Path(".agents/workflow.local.toml")

# The hooks named by when they run. `pre-push` and `post-clone` belong to the
# engine's own push and clone, so no step runs them through `run`.
HOOKS = ("after-functional-change", "pre-commit", "pre-commit-functional", "pre-archive",
         "pre-push", "post-clone", "test-before")
# The hooks around each step a run is logged as, before its session and after it.
STEP_HOOKS = tuple(f"{when}-{step}" for step in STEPS for when in ("before", "after"))
# The steps whose hooks are told which kind of review or triage the run is.
KIND_STEPS = ("review", "triage")
# The default checks of `pre-commit`, run before its declared commands unless
# `defaults.disable` names them.
DEFAULT_CHECKS = ("index", "tasks", "skills", "spec-index", "decisions", "openspec")
# The OpenSpec command when the configuration names none.
DEFAULT_OPENSPEC = "openspec"
# The documents every session reads as it starts, which a step's own add to.
COMMON_DOCUMENTS = "common"
# The inert paths when the configuration declares none: OpenSpec's tree and every
# Markdown file, whose changes alter nothing validation or a code check would prove
# but a test of a document's currency, which the next full run of the suites reads.
DEFAULT_INERT_PATHS = ("openspec/", "**/*.md")
# The send-backs a review's refused draft is given when the configuration names none.
DEFAULT_FORMAT_RETRIES = 1
# The writable paths every step adds, the review only those outside its checkout,
# which a step's own add to.
COMMON_WRITABLE = "common"
# An evidence kind's fields, in the order `config` lists them.
KIND_KEYS = ("required", "evidence", "run", "start", "collect", "after", "cleanup", "guide")
# What an evidence kind may be required as.
ALWAYS, OWED = "always", "owed"
REQUIRED = (ALWAYS, OWED)
# The identities an evidence pattern may key its evidence by.
TREE, COMMIT = "tree", "commit"
_TABLES: dict[str, tuple[str, ...]] = {
    "workflow": ("version",),
    "repository": ("protected-branches", "inert-paths"),
    "hooks": HOOKS + STEP_HOOKS,
    "defaults": ("disable",),
    "openspec": ("command",),
    "load": (COMMON_DOCUMENTS, *STEPS),
    "validation": ("preflight", "evidence"),
    "review": ("format-retries",),
    "sandbox": ("writable", "protected"),
}
# The local configuration's tables and keys: the engineering pointer, the models,
# and the writable sandbox paths a developer adds.
GUIDANCE_ENGINEERING = "guidance.engineering"
_LOCAL_TABLES: dict[str, tuple[str, ...]] = {
    "guidance": ("engineering",),
    "models": (ORCHESTRATOR, *STEPS),
    "sandbox": ("writable",),
}
# The local table of each step's models, whose fields `missing` reports as
# `models.<step>`.
MODELS = "models"
# The comparison operators a version range may use, over release numbers.
_SPECIFIER = re.compile(r"^\s*(~=|==|!=|<=|>=|<|>)\s*(\d+(?:\.\d+)*)\s*$")
_RELEASE = re.compile(r"^(\d+(?:\.\d+)*)")
# The placeholders every command may use, but `pre-push`'s: the guarded push pushes a
# branch, not a change, so it has the remote alone to give.
_EVERYWHERE = frozenset({"change", "base"})
_PRE_PUSH = frozenset({"remote"})
# `test-before` runs one test file at a time, named by `{test}`.
_TEST_BEFORE = _EVERYWHERE | {"test"}
# The worktree a functional hook checks, and a kind's commands gather evidence for,
# by its tree and its commit.
_IDENTITIES = frozenset({TREE, COMMIT})
_FUNCTIONAL = _EVERYWHERE | _IDENTITIES
_FUNCTIONAL_HOOKS = ("after-functional-change", "pre-commit-functional")
# A step hook is given its run's inputs directory; a review's and a triage's also
# the kind of review the run is, or triages.
_STEP_HOOK = _EVERYWHERE | {"inputs"}
_KIND_STEP_HOOK = _STEP_HOOK | {"kind"}
PLACEHOLDERS = frozenset({"change", "base", "remote", "owed", "after", "test", TREE, COMMIT,
                          "inputs", "kind"})
# A name in braces, not the shell's `${…}`.
PLACEHOLDER = re.compile(r"(?<!\$)\{([A-Za-z_][A-Za-z0-9_-]*)\}")
# What a pattern's fixed segment holds none of: a placeholder or a glob character.
_UNFIXED = re.compile(r"[{*?\[\]]")


def placeholders(command: str) -> list[str]:
    """The placeholders `command` names, in order."""
    return PLACEHOLDER.findall(command)


def matches(root: Path, pattern: str) -> list[str]:
    """Every path under `root` matching the filled evidence pattern `pattern`,
    relative to it, in path order."""
    return sorted(glob.glob(pattern, root_dir=root))


def fill(command: str, values: Mapping[str, str]) -> str:
    """`command` with each placeholder replaced by its value, shell-quoted. The
    configuration's check has refused any placeholder unknown where it is used, so a
    placeholder without a value is one this invocation does not supply."""
    def value(name: str) -> str:
        if name not in values:
            raise StepError(f"{{{name}}} has no value in this run")
        return shlex.quote(values[name])

    return PLACEHOLDER.sub(lambda match: value(match.group(1)), command)


def fixed_directory(pattern: str) -> str:
    """The leading directories of `pattern` holding no placeholder and no glob
    character, ending in `/`; empty when its first segment is not fixed."""
    segments = pattern.split("/")[:-1]
    fixed: list[str] = []
    for segment in segments:
        if _UNFIXED.search(segment):
            break
        fixed.append(segment)
    return "/".join(fixed) + "/" if fixed else ""


# Required fields, by the name `missing` reports.
PRE_COMMIT_FUNCTIONAL = "hooks.pre-commit-functional"
EVIDENCE = "validation.evidence"
PROTECTED_BRANCHES = "repository.protected-branches"


class ConfigError(StepError):
    """The configuration is malformed, or lacks a field a step needs."""


@dataclass(frozen=True)
class Kind:
    """An evidence kind: what requires it, the pattern its evidence is found at, how
    it is gathered — `run`, or `start` and `collect` — the kind it follows, what
    archive cleanup runs for it, and the guide its evidence is assessed by."""

    name: str
    required: str
    evidence: str
    guide: str
    run: tuple[str, ...] | None = None
    start: tuple[str, ...] | None = None
    collect: tuple[str, ...] | None = None
    after: str | None = None
    cleanup: tuple[str, ...] | None = None

    @property
    def owed(self) -> bool:
        """Whether the kind is required once per argument complete sections owe."""
        return self.required == OWED

    @property
    def shape(self) -> str:
        return "run" if self.run is not None else "start, collect"

    @property
    def identity(self) -> str:
        """What the kind's evidence describes, as its pattern keys it: the tree, or
        the commit."""
        return TREE if TREE in placeholders(self.evidence) else COMMIT

    @property
    def directory(self) -> str:
        """The pattern's fixed directory, where every attempt of the kind lies."""
        return fixed_directory(self.evidence)


@dataclass(frozen=True)
class Configuration:
    """The configuration as checked. A field the file does not declare is None, or
    missing from its mapping; `exists` says whether there is a file at all."""

    path: Path
    exists: bool = False
    # The local configuration's path, and whether there is a file.
    local: Path | None = None
    local_exists: bool = False
    # `[workflow] version`, as declared.
    version_range: str | None = None
    # `[guidance] engineering`: the pointer, or None while the local file lacks it.
    engineering: Engineering | None = None
    protected_branches: tuple[str, ...] | None = None
    inert_paths: tuple[str, ...] | None = None
    hooks: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    # Each disabled default check and its reason.
    disabled: Mapping[str, str] = field(default_factory=dict)
    openspec: str | None = None
    load: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    models: Mapping[str, Any] = field(default_factory=dict)
    preflight: tuple[str, ...] | None = None
    kinds: tuple[Kind, ...] | None = None
    format_retries: int | None = None
    # `[sandbox]`: the writable paths `writable.common` and each `writable.<step>`
    # declares, by their key, and the protected paths.
    sandbox_writable: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    sandbox_protected: tuple[str, ...] | None = None

    def repository_writable(self, step: str, root: Path | None = None,
                            home: Path | None = None) -> tuple[str, ...]:
        """The writable paths the repository adds to a step's scope in the checkout at
        `root`: `writable.common`, then the step's own. The review takes only the
        common paths outside its checkout, such as a tool's cache in the home
        directory, since every file it reviews stays read-only; with no `root`, none."""
        common = self.sandbox_writable.get(COMMON_WRITABLE, ())
        if step == "review":
            common = () if root is None else tuple(
                entry for entry in common
                if outside_checkout(entry, root, Path.home() if home is None else home))
        return tuple(dict.fromkeys((*common, *self.sandbox_writable.get(step, ()))))

    def scope(self, step: str, root: Path, harness: str | None = None,
              **launch: Any) -> Scope:
        """A step's scope in the checkout at `root`, with the paths of the adapter of
        `harness` — by default the harness of the step's first model, and no adapter's
        where the configuration names none — and the repository's additions and inert
        paths; `launch` gives what a run adds, its grants, and where its home
        directory is."""
        if harness is None and self.models.get(step):
            harness = self.models[step][0]["harness"]
        adapter = ADAPTERS.get(harness) if harness else None
        if adapter is not None:
            launch = {"adapter_writable": adapter.state, "adapter_files": adapter.state_files,
                      "adapter_protected": adapter.protected, **launch}
        return resolve(step, root, inert_paths=self.repository_inert_paths(),
                       writable=self.repository_writable(step, root, launch.get("home")),
                       protected=self.sandbox_protected or (), **launch)

    def hook(self, name: str) -> tuple[str, ...] | None:
        """The hook's commands, or None when it is not declared."""
        return self.hooks.get(name)

    def kind(self, name: str) -> Kind:
        for kind in self.kinds or ():
            if kind.name == name:
                return kind
        declared = ", ".join(kind.name for kind in self.kinds or ()) or "none"
        raise ConfigError(f"{self.shown} declares no evidence kind {name!r}; its kinds: "
                          f"{declared}")

    def review_format_retries(self) -> int:
        """How many times a review's draft the format check refuses is sent back to
        its reviewer for correction."""
        return DEFAULT_FORMAT_RETRIES if self.format_retries is None else self.format_retries

    def repository_inert_paths(self) -> tuple[str, ...]:
        """The repository's inert paths: its declaration, which replaces the default
        even when empty, or the workflow's default where it declares none."""
        return DEFAULT_INERT_PATHS if self.inert_paths is None else self.inert_paths

    def openspec_command(self) -> str:
        return self.openspec if self.openspec is not None else DEFAULT_OPENSPEC

    def documents(self, step: str, root: Path) -> list[str]:
        """The documents a step's skill reads, relative to the repository at `root`
        where they lie in it and whole otherwise, lower layer first: the Markdown
        files beneath the engineering pointer, those of the workflow's guidance, then
        `load.common` and `load.<step>`, each document once. A `load` entry ending in
        `/` names a directory and stands for the Markdown files beneath it
        (`directory_documents`); any other entry names one file and is given as it
        is, whether or not the file exists. Refused, naming the pointer and
        `change-workflow install`, while the local configuration lacks the pointer: a
        session reading the list then would miss the guidance it points at."""
        require(self, GUIDANCE_ENGINEERING, needed_by="the documents a session reads")
        found: list[str] = []
        if self.engineering is not None and self.engineering.path is not None:
            found.extend(_markdown(self.engineering.path, root))
        found.extend(_markdown(distribution.path(distribution.GUIDANCE), root))
        for entry in (*self.load.get(COMMON_DOCUMENTS, ()), *self.load.get(step, ())):
            found.extend(directory_documents(root, entry) if entry.endswith("/") else (entry,))
        return list(dict.fromkeys(found))

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
        """Every declared kind's fixed evidence directory, each once, in declaration
        order."""
        return list(dict.fromkeys(kind.directory for kind in self.kinds or ()))

    @property
    def shown(self) -> str:
        return CONFIGURATION.as_posix()


@dataclass(frozen=True)
class Engineering:
    """The engineering-guidance pointer: the directory it names, as declared and
    resolved, or the reason the repository applies none."""

    entry: str | None = None
    path: Path | None = None
    none: str | None = None

    def shown(self) -> dict[str, str]:
        """As `config --json` gives it: `{"path": <the directory>}` or `{"none":
        <the reason>}`."""
        return {"path": str(self.path)} if self.path is not None else {"none": self.none or ""}


def _markdown(directory: Path, root: Path) -> list[str]:
    """The Markdown files beneath `directory`, in sorted path order, each relative to
    `root` where it lies there and whole otherwise."""
    files = sorted(path for path in directory.rglob("*.md") if path.is_file())
    return [path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path)
            for path in files]


def directory_documents(root: Path, entry: str) -> list[str]:
    """The Markdown files beneath the directory `entry` names, recursively, relative to
    `root`, in sorted path order.

    Refused, naming the entry, when the directory is missing, is a file, cannot be
    read, or holds no Markdown file: a session given a directory that names nothing
    would read none of the guidance it was meant to and never know, where a literal
    entry's missing file is at least named to it."""
    directory = root / entry
    if not directory.is_dir():
        found = "is a file" if directory.exists() else "does not exist"
        raise ConfigError(f"load names the directory {entry}, which {found}")

    def unreadable(error: OSError) -> None:
        raise ConfigError(f"load names the directory {entry}, which cannot be read: {error}")

    files = sorted(PurePosixPath((parent / name).relative_to(root).as_posix())
                   for parent, _, names in directory.walk(on_error=unreadable)
                   for name in names if name.endswith(".md"))
    if not files:
        raise ConfigError(f"load names the directory {entry}, which holds no Markdown file")
    return [file.as_posix() for file in files]


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


def _count(where: str, value: Any) -> int:
    """A whole number, zero or more; TOML's `true` is no number here."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ConfigError(f"{where} must be a whole number, zero or more; got {value!r}")
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
    fallback. A model is named only for a step its harness's adapter can run.
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
        for harness in harnesses:
            if key in STEPS and not ADAPTERS[harness].runs(key):
                raise ConfigError(f"{where} names a {harness} model for the {key} step, "
                                  f"which the {harness} adapter cannot run; it runs only: "
                                  + ", ".join(sorted(ADAPTERS[harness].steps)))
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


# Of the directories given, relative to the root, those Git does not ignore there.
Unignored = Callable[[Path, Sequence[str]], list[str]]


def git_unignored(root: Path, directories: Sequence[str]) -> list[str]:
    """Of `directories`, those Git does not ignore in the checkout at `root`. Outside
    a Git checkout nothing is tracked, so nothing a pattern names can change a tree,
    and none is reported."""
    if not directories:
        return []
    try:
        found = subprocess.run(["git", "check-ignore", "--", *directories], cwd=root,
                               capture_output=True, text=True)
        # Git exits 0 when it ignores any of them and 1 when it ignores none; any
        # other status is a failure, which outside a checkout is no failure at all.
        checkout = found.returncode in (0, 1) or subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"], cwd=root,
            capture_output=True).returncode == 0
    except OSError as exc:
        raise ConfigError(f"cannot run git to check the evidence directories: {exc}") from exc
    if not checkout:
        return []
    if found.returncode not in (0, 1):
        raise ConfigError(f"git check-ignore failed on the evidence directories: "
                          f"{found.stderr.strip()}")
    ignored = set(found.stdout.splitlines())
    return [directory for directory in directories if directory not in ignored]


def _pattern(where: str, value: Any, owed: bool) -> str:
    """An evidence pattern: a relative path holding exactly one of `{tree}` and
    `{commit}`, `{owed}` if and only if its kind is owed, and no other placeholder,
    below a fixed directory."""
    pattern = _string(where, value)
    named = placeholders(pattern)
    allowed = _IDENTITIES | ({OWED} if owed else set())
    for name in named:
        if name not in allowed:
            raise ConfigError(f"{where} names {{{name}}}, which is not available there; "
                              "available: " + ", ".join(f"{{{p}}}" for p in sorted(allowed)))
    identities = [name for name in (TREE, COMMIT) if name in named]
    if len(identities) != 1:
        raise ConfigError(f"{where} must hold exactly one of {{tree}} and {{commit}}, the "
                          "identity its evidence describes; it holds "
                          + (" and ".join(f"{{{name}}}" for name in identities) or "neither"))
    if owed and OWED not in named:
        raise ConfigError(f"{where} must hold {{owed}}, so that each owed argument's evidence "
                          "is found apart from another's")
    if pattern.startswith("/") or ".." in pattern.split("/"):
        raise ConfigError(f"{where} must be a path from the repository's root, with no `..`; "
                          f"got {pattern!r}")
    if not fixed_directory(pattern):
        raise ConfigError(f"{where} must begin with a fixed directory, holding no placeholder "
                          "and no glob character, which Git ignores")
    return pattern


def _guide(where: str, value: Any, root: Path) -> str:
    """A kind's guide: a file from the repository's root, holding something to read."""
    guide = _string(where, value)
    path = root / guide
    if Path(guide).is_absolute() or ".." in Path(guide).parts:
        raise ConfigError(f"{where} must be a path from the repository's root, with no `..`; "
                          f"got {guide!r}")
    try:
        text = path.read_text("utf-8")
    except FileNotFoundError:
        raise ConfigError(f"{where} names {guide}, which does not exist") from None
    except (IsADirectoryError, NotADirectoryError):
        raise ConfigError(f"{where} names {guide}, which is no file") from None
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"{where} names {guide}, which cannot be read: {exc}") from exc
    if not text.strip():
        raise ConfigError(f"{where} names {guide}, which is empty; validation assesses the "
                          "kind's evidence from its guide")
    return guide


def _kinds(value: Any, root: Path, unignored: Unignored) -> tuple[Kind, ...]:
    if not isinstance(value, dict):
        raise ConfigError(f"{EVIDENCE} must be a table of evidence kinds; got {value!r}")
    kinds: list[Kind] = []
    for name, declared in value.items():
        where = f"{EVIDENCE}.{name}"
        table = _table(where, declared, KIND_KEYS)
        required = table.get("required")
        if required not in REQUIRED:
            raise ConfigError(f"{where}.required must be one of {', '.join(REQUIRED)}; got "
                              f"{required!r}")
        owed = required == OWED
        running = _EVERYWHERE | _IDENTITIES | ({OWED} if owed else set())
        shapes = [key for key in ("run", "start") if key in table]
        if len(shapes) != 1 or ("start" in table) != ("collect" in table):
            raise ConfigError(f"{where} declares `run`, or `start` and `collect`, and not "
                              "both shapes; it declares "
                              + (", ".join(k for k in ("run", "start", "collect") if k in table)
                                 or "neither"))
        commands = {key: _commands(f"{where}.{key}", table[key],
                                   running | ({"after"} if key == "collect" else set()))
                    for key in ("run", "start", "collect") if key in table}
        # A hook's empty list says "nothing here"; a kind that runs nothing would
        # gather no evidence, and a `start` running nothing prints no marker.
        if empty := [key for key, value in commands.items() if not value]:
            raise ConfigError(f"{where}.{empty[0]} must name a command; a kind runs one or "
                              "more")
        if "evidence" not in table:
            raise ConfigError(f"{where}.evidence is required: the pattern its evidence is "
                              "found at")
        evidence = _pattern(f"{where}.evidence", table["evidence"], owed)
        after = _string(f"{where}.after", table["after"]) if "after" in table else None
        cleanup = (_commands(f"{where}.cleanup", table["cleanup"], _EVERYWHERE | _IDENTITIES)
                   if "cleanup" in table else None)
        if "guide" not in table:
            raise ConfigError(f"{where}.guide is required: validation assesses the kind's "
                              "evidence from its guide")
        guide = _guide(f"{where}.guide", table["guide"], root)
        kinds.append(Kind(name, required=required, evidence=evidence, guide=guide,
                          run=commands.get("run"), start=commands.get("start"),
                          collect=commands.get("collect"), after=after, cleanup=cleanup))
    # Validation starts every `start` kind before any `run` kind, and runs the `run`
    # kinds in declaration order, so an `after` it could not keep — a kind declared
    # later, which also rules out every cycle, or a started kind following a `run`
    # kind — is refused here rather than left for a run to improvise around.
    declared = {kind.name: index for index, kind in enumerate(kinds)}
    for index, kind in enumerate(kinds):
        if kind.after is None:
            continue
        where = f"{EVIDENCE}.{kind.name}.after"
        if kind.after not in declared or kind.after == kind.name:
            raise ConfigError(f"{where} names {kind.after!r}, which is no other declared kind")
        if declared[kind.after] > index:
            raise ConfigError(f"{where} names {kind.after!r}, which is declared after it; a "
                              "kind follows only a kind declared before it")
        if kind.start is not None and kinds[declared[kind.after]].run is not None:
            raise ConfigError(f"{where} names {kind.after!r}, a `run` kind, but every "
                              "`start` is dispatched before any `run` kind runs")
    # Every file the workflow writes after implementation is ignored by Git, so it
    # never changes the tree the evidence describes.
    directories = list(dict.fromkeys(kind.directory for kind in kinds))
    if outside := unignored(root, directories):
        first = next(kind for kind in kinds if kind.directory == outside[0])
        raise ConfigError(f"{EVIDENCE}.{first.name}.evidence lies under {outside[0]}, which "
                          "Git does not ignore; evidence written there would change the tree "
                          "it describes")
    return tuple(kinds)


def _sandbox(table: dict[str, Any], root: Path, home: Path,
             also_protected: Sequence[str] = ()
             ) -> tuple[dict[str, tuple[str, ...]], tuple[str, ...] | None]:
    """`[sandbox]`'s writable paths by key and its protected paths, refused naming the
    field: a key that is neither `common` nor a step; `writable.review`, since the
    review writes nothing it reviews; a pattern outside the checkout, since a pattern
    is matched against the checkout's files; a protected pattern, since a protected
    path is mounted read-only whole; `/tmp` or a directory holding it, which would
    hide the private `/tmp` every step writes, though a path under it is admitted;
    and a writable path that is or lies under a protected one, the engine's or the repository's, which the
    sandbox could not honour; the protected paths are the engine's, every adapter's,
    whichever harness runs the step, and the repository's. A writable directory
    containing a protected path is admitted: the protected path stays read-only inside
    it. `also_protected` adds the paths another file protects, as the committed
    configuration's do for the local one's writable paths."""
    protected = (_strings("sandbox.protected", table["protected"])
                 if "protected" in table else None)
    for entry in protected or ():
        if is_pattern(entry):
            raise ConfigError(f"sandbox.protected names {entry}, a pattern; a protected path "
                              "is named whole")
    declared = table.get("writable", {})
    if not isinstance(declared, dict):
        raise ConfigError("sandbox.writable must be a table of path lists, keyed by "
                          f"{COMMON_WRITABLE} or a step; got {declared!r}")
    writable: dict[str, tuple[str, ...]] = {}
    for key, value in declared.items():
        where = f"sandbox.writable.{key}"
        if key == "review":
            raise ConfigError(f"{where} is refused: the review writes nothing it reviews, so "
                              "no repository widens its scope")
        if key != COMMON_WRITABLE and key not in STEPS:
            raise ConfigError(f"{where} names no step; sandbox.writable takes "
                              f"{COMMON_WRITABLE} or one of: "
                              + ", ".join(step for step in STEPS if step != "review"))
        entries = _strings(where, value)
        for entry in entries:
            if is_pattern(entry) and entry.startswith(("~", "/")):
                raise ConfigError(f"{where} names {entry}, a pattern outside the checkout; "
                                  "only a path from the checkout's root may be a pattern")
            if hides_temporary(entry, root, home):
                raise ConfigError(f"{where} names {entry}, which is or holds the host's "
                                  "temporary directory; every step writes a private "
                                  f"{PRIVATE_TEMPORARY} of its own, which it would hide")
            if guarded := protected_by(entry, root, home,
                                       (*PROTECTED, *INSTALLED, *ADAPTER_PROTECTED,
                                        *(protected or ()), *also_protected)):
                raise ConfigError(f"{where} names {entry}, which is or lies under the "
                                  f"protected path {guarded}")
        writable[key] = entries
    return writable, protected


def _hook_placeholders(name: str) -> frozenset[str]:
    """The placeholders the hook `name` may use."""
    if name == "pre-push":
        return _PRE_PUSH
    if name == "test-before":
        return _TEST_BEFORE
    if name in _FUNCTIONAL_HOOKS:
        return _FUNCTIONAL
    if name in STEP_HOOKS:
        return _KIND_STEP_HOOK if name.split("-", 1)[1] in KIND_STEPS else _STEP_HOOK
    return _EVERYWHERE


def _hooks(table: dict[str, Any]) -> dict[str, tuple[str, ...]]:
    return {name: _commands(f"hooks.{name}", value, _hook_placeholders(name))
            for name, value in table.items()}


def _hooks_table(value: Any) -> dict[str, Any]:
    """The hooks table, a step hook's misspelt or unknown step named as such."""
    if isinstance(value, dict):
        for key in value:
            if key not in _TABLES["hooks"] and key.startswith(("before-", "after-")):
                raise ConfigError(f"hooks.{key} names no step; a step hook is before- or "
                                  "after- one of: " + ", ".join(STEPS))
    return _table("hooks", value, _TABLES["hooks"])


Specifier = tuple[str, tuple[int, ...]]


def version_range(where: str, value: Any) -> list[Specifier]:
    """A version range's specifiers, each an operator and the release numbers it
    compares with; refused, naming the field, unless every comma-separated part is
    one of the operators the range admits followed by release numbers."""
    text = _string(where, value)
    specifiers: list[Specifier] = []
    for part in text.split(","):
        match = _SPECIFIER.match(part)
        if match is None:
            raise ConfigError(f"{where} must be comma-separated version specifiers, each one "
                              "of >=, <=, >, <, ==, !=, or ~= followed by release numbers "
                              f"such as 0.1; got {part.strip()!r} in {text!r}")
        operator, release = match.groups()
        numbers = tuple(int(number) for number in release.split("."))
        if operator == "~=" and len(numbers) < 2:
            raise ConfigError(f"{where} names ~={release}, and ~= compares with two release "
                              "numbers or more, such as ~=0.1")
        specifiers.append((operator, numbers))
    return specifiers


def _padded(numbers: tuple[int, ...], width: int) -> tuple[int, ...]:
    return numbers + (0,) * (width - len(numbers))


def _holds(operator: str, version: tuple[int, ...], final: bool,
           release: tuple[int, ...]) -> bool:
    """Whether a version, its release numbers and whether it is a final release, meets
    one specifier. A version with anything after its release numbers, a pre-release
    or a development release, sorts before its release, as PEP 440 orders them."""
    width = max(len(version), len(release))
    have, want = (_padded(version, width), final), (_padded(release, width), True)
    if operator == "~=":
        # `~=0.4.1` is `>=0.4.1` within the `0.4` series: the release less its last
        # number is a prefix the version keeps.
        prefix = release[:-1]
        return have >= want and _padded(version, len(prefix))[:len(prefix)] == prefix
    return {"==": have == want, "!=": have != want, "<=": have <= want,
            ">=": have >= want, "<": have < want, ">": have > want}[operator]


def admits(specifiers: Sequence[Specifier], version: str) -> bool:
    """Whether `version`, by the release numbers it begins with, meets every
    specifier; one with nothing it begins with as release numbers meets none."""
    match = _RELEASE.match(version)
    if match is None:
        return False
    numbers = tuple(int(number) for number in match.group(1).split("."))
    final = match.end() == len(version)
    return all(_holds(operator, numbers, final, release) for operator, release in specifiers)


def _accepted(raw: dict[str, Any], installed: Callable[[], str]) -> str | None:
    """The range `[workflow] version` declares, checked against the installed
    version before anything else in the file is read; None when it declares none.
    Refused, naming the installed version, the range, and the fix, when the version
    lies outside it: whatever else the file holds may be a later version's."""
    declared = raw.get("workflow")
    if not isinstance(declared, dict) or "version" not in declared:
        return None
    accepted = declared["version"]
    specifiers = version_range("workflow.version", accepted)
    running = installed()
    if not admits(specifiers, running):
        raise ConfigError(f"the installed workflow is {running}, outside the range "
                          f"{accepted} that {CONFIGURATION.as_posix()} accepts "
                          "(workflow.version): install a version the range admits and run "
                          "`change-workflow install`, or change the range")
    return accepted


def _engineering(value: Any, root: Path, home: Path) -> Engineering:
    """The engineering-guidance pointer: exactly one of `path`, a directory from the
    checkout's root or `~` holding Markdown files, or `none`, a reason."""
    where = GUIDANCE_ENGINEERING
    if not isinstance(value, dict) or len(value) != 1 or not set(value) <= {"path", "none"}:
        raise ConfigError(f"{where} must be a table holding exactly one of path, the "
                          "directory of the engineering guidance, or none, the reason the "
                          f"repository applies none; got {value!r}")
    if "none" in value:
        if not isinstance(value["none"], str) or not value["none"].strip():
            raise ConfigError(f"{where} declares none without a reason; a repository applies "
                              "no engineering guidance only with one")
        return Engineering(none=value["none"])
    entry = _string(f"{where}.path", value["path"])
    if entry.startswith("/"):
        raise ConfigError(f"{where}.path must be a directory from the checkout's root or "
                          f"from `~`; got {entry!r}")
    directory = absolute(entry, root, home)
    if not directory.is_dir():
        found = "is a file" if directory.exists() else "does not exist"
        raise ConfigError(f"{where} names {entry}, which {found}")
    if not any(path.is_file() for path in directory.rglob("*.md")):
        raise ConfigError(f"{where} names {entry}, which holds no Markdown file")
    return Engineering(entry=entry, path=directory)


def _overlapping(load: Mapping[str, tuple[str, ...]], engineering: Engineering | None,
                 root: Path) -> None:
    """Refuse a `load` entry that is the pointer's directory, lies beneath it, or is a
    directory holding it: each document beneath the pointer is read once, from it."""
    if engineering is None or engineering.path is None:
        return
    for key, entries in load.items():
        for entry in entries:
            path = absolute(entry, root, root)
            if within(path, engineering.path) or (entry.endswith("/")
                                                  and within(engineering.path, path)):
                raise ConfigError(f"load.{key} names {entry}, which overlaps the directory "
                                  f"{engineering.entry} that {GUIDANCE_ENGINEERING} points at; "
                                  "the documents beneath the pointer are read from it alone")


def _local_tables(text: str) -> dict[str, dict[str, Any]]:
    """The local configuration's tables, each key one the local file holds; a table
    or key the committed configuration holds is refused, naming that file."""
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{LOCAL.as_posix()} is not TOML: {exc}") from exc
    for name in raw:
        if name in _LOCAL_TABLES:
            continue
        if name in _TABLES:
            raise ConfigError(f"{LOCAL.as_posix()} declares [{name}], which belongs in "
                              f"{CONFIGURATION.as_posix()}")
        raise ConfigError(f"{name} is no table the workflow defines; "
                          f"{LOCAL.as_posix()}'s tables: " + ", ".join(_LOCAL_TABLES))
    if isinstance(raw.get("sandbox"), dict) and "protected" in raw["sandbox"]:
        raise ConfigError(f"{LOCAL.as_posix()} declares sandbox.protected, which belongs in "
                          f"{CONFIGURATION.as_posix()}: a developer adds writable paths alone")
    return {name: _table(name, raw[name], keys) for name, keys in _LOCAL_TABLES.items()
            if name in raw}


def check(text: str, path: Path, *, root: Path | None = None,
          unignored: Unignored = git_unignored, home: Path | None = None,
          local: str | None = None, committed: bool = True,
          installed: Callable[[], str] = distribution.version) -> Configuration:
    """The configuration `text` holds, checked whole; refused, naming the field, on
    an unknown table or key, a wrong type, a placeholder unknown or unavailable
    where it is used, an evidence pattern under a directory Git does not ignore, a
    guide missing or empty, or a `[sandbox]` path its check refuses (`_sandbox`).
    Paths are read from `root`, the repository's, which is the configuration's own by
    default, and `~` from `home`, the user's by default.

    `local` is the local configuration's text, None when there is no local file; its
    models join the committed ones, a step's declared in one file alone, and its
    writable paths extend the committed ones. The range is checked against
    `installed`, the engine's version, before anything else, and is refused absent
    unless `committed` is false: no committed file exists, and `text` is empty."""
    if root is None:
        depth = len(CONFIGURATION.parts)
        root = path.parents[depth - 1] if len(path.parents) >= depth else path.parent
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{CONFIGURATION.as_posix()} is not TOML: {exc}") from exc
    accepted = _accepted(raw, installed)
    if accepted is None and committed:
        raise ConfigError(f"{CONFIGURATION.as_posix()} declares no workflow.version, the range "
                          "of workflow versions the repository accepts, such as "
                          "version = \">=0.1, <0.2\" under [workflow]")
    for name in raw:
        if name in _TABLES:
            continue
        if name in _LOCAL_TABLES:
            raise ConfigError(f"{CONFIGURATION.as_posix()} declares [{name}], which belongs in "
                              f"{LOCAL.as_posix()}, the checkout's own settings that "
                              "developers may give different values")
        raise ConfigError(f"{name} is no table the workflow defines; its tables: "
                          + ", ".join(_TABLES))
    tables = {name: (_hooks_table(raw[name]) if name == "hooks"
                     else _table(name, raw[name], keys))
              for name, keys in _TABLES.items() if name in raw}
    repository = tables.get("repository", {})
    hooks = _hooks(tables.get("hooks", {}))
    validation = tables.get("validation", {})
    load = {key: _strings(f"load.{key}", value)
            for key, value in tables.get("load", {}).items()}
    home = Path.home() if home is None else home
    sandbox_writable, sandbox_protected = _sandbox(tables.get("sandbox", {}), root, home)
    models: dict[str, Any] = {}
    engineering = None
    if local is not None:
        local_tables = _local_tables(local)
        guidance = local_tables.get("guidance", {})
        if "engineering" in guidance:
            engineering = _engineering(guidance["engineering"], root, home)
        models = dict(local_tables.get("models", {}))
        local_writable, _ = _sandbox(local_tables.get("sandbox", {}), root, home,
                                     also_protected=sandbox_protected or ())
        sandbox_writable = {key: tuple(dict.fromkeys((*sandbox_writable.get(key, ()),
                                                      *local_writable.get(key, ()))))
                            for key in (*sandbox_writable, *local_writable)}
    _overlapping(load, engineering, root)
    return Configuration(
        path=path, exists=True, local=root / LOCAL, local_exists=local is not None,
        version_range=accepted, engineering=engineering,
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
        models=_models(models),
        preflight=(_commands("validation.preflight", validation["preflight"], _EVERYWHERE)
                   if "preflight" in validation else None),
        kinds=(_kinds(validation["evidence"], root, unignored) if "evidence" in validation
               else None),
        format_retries=(_count("review.format-retries", tables["review"]["format-retries"])
                        if "format-retries" in tables.get("review", {}) else None),
        sandbox_writable=sandbox_writable, sandbox_protected=sandbox_protected,
    )


def _read(path: Path, shown: Path) -> str | None:
    try:
        return path.read_text("utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ConfigError(f"cannot read {shown.as_posix()}: {exc}") from exc


def load(root: Path, unignored: Unignored = git_unignored, home: Path | None = None,
         installed: Callable[[], str] = distribution.version) -> Configuration:
    """The configuration of the repository at `root` with its checkout's local one,
    checked whole; every committed field absent when there is no committed file, and
    every local field when there is no local one."""
    path = root / CONFIGURATION
    text = _read(path, CONFIGURATION)
    # An empty local file is the sandbox's empty form of an absent protected file,
    # holding no setting, and is read as no local file, as the installer writes it.
    local = _read(root / LOCAL, LOCAL) or None
    if text is None and local is None:
        return Configuration(path=path, local=root / LOCAL)
    checked = check(text or "", path, root=root, unignored=unignored, home=home, local=local,
                    committed=text is not None, installed=installed)
    return checked if text is not None else replace(checked, exists=False)


def missing(configuration: Configuration, *fields: str) -> list[str]:
    """Of the required `fields`, those the configuration does not declare. An
    explicit empty value is declared."""
    absent = []
    for name in fields:
        if name == PRE_COMMIT_FUNCTIONAL:
            present = configuration.hook("pre-commit-functional") is not None
        elif name == EVIDENCE:
            present = bool(configuration.kinds)
        elif name == PROTECTED_BRANCHES:
            present = configuration.protected_branches is not None
        elif name.startswith("models."):
            present = name.removeprefix("models.") in configuration.models
        elif name == GUIDANCE_ENGINEERING:
            present = configuration.engineering is not None
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
# validation assesses the declared evidence kinds.
STEP_NEEDS: dict[str, tuple[str, ...]] = {
    step: (PROTECTED_BRANCHES,) for step in STEPS if step != "review"}
STEP_NEEDS.update({
    "implement": (PROTECTED_BRANCHES, PRE_COMMIT_FUNCTIONAL),
    "triage": (PROTECTED_BRANCHES, PRE_COMMIT_FUNCTIONAL),
    "merge": (PROTECTED_BRANCHES, PRE_COMMIT_FUNCTIONAL),
    "validate": (PROTECTED_BRANCHES, EVIDENCE),
})


def is_local(name: str) -> bool:
    """Whether the required field `name` is one the local configuration declares."""
    return name == GUIDANCE_ENGINEERING or name.startswith(f"{MODELS}.")


def require(configuration: Configuration, *fields: str, needed_by: str) -> None:
    """Refuse, naming each field and the file it belongs in, when a required field
    `needed_by` needs is absent; a local field's names `change-workflow install`,
    which writes the local file where a checkout has none."""
    absent = missing(configuration, *fields)
    if not absent:
        return
    committed = [name for name in absent if not is_local(name)]
    local = [name for name in absent if is_local(name)]
    parts = []
    if committed:
        parts.append(f"{', '.join(committed)}, which {configuration.shown} does not declare"
                     + ("" if configuration.exists else " (there is no such file)")
                     + "; an empty value declares it deliberately")
    if local:
        parts.append(f"{', '.join(local)}, which {LOCAL.as_posix()} does not declare"
                     + ("" if configuration.local_exists else " (there is no such file)")
                     + ": run `change-workflow install` to write it where the checkout has "
                       "none, or declare them there")
    raise ConfigError(f"{needed_by} needs " + "; and ".join(parts))


def require_for_step(configuration: Configuration, step: str, *,
                     unattended: bool = False) -> None:
    """Refuse a step whose required fields are absent, before anything is launched:
    every session needs the engineering pointer, whose guidance its skill reads
    first; an unattended run also needs its step's models, and the orchestrating
    session its own."""
    if step == ORCHESTRATOR_STEP:
        require(configuration, GUIDANCE_ENGINEERING, f"models.{ORCHESTRATOR}",
                needed_by="the orchestrating session")
        return
    require(configuration, *STEP_NEEDS.get(step, ()), GUIDANCE_ENGINEERING,
            *((f"models.{step}",) if unattended else ()), needed_by=step)


# Resolution: every field and how it resolved.

DECLARED, DEFAULT, DISABLED, ABSENT = "declared", "default", "disabled", "absent"
# A required local field the local configuration lacks; an optional field is absent.
MISSING = "missing"


@dataclass(frozen=True)
class Role:
    """A role the workflow leaves to an adopting repository: what it does, and the
    configuration fields that provide it, none where Git, the invocation, a
    convention the workflow fixes, or the repository's `Makefile` does. A field
    written with a placeholder, `load.<step>`, names that key for every step."""

    name: str
    fields: tuple[str, ...] = ()

    def shown(self) -> dict[str, Any]:
        return {"role": self.name, "fields": list(self.fields)}


# Every role the workflow leaves to an adopting repository, in the order its
# companion's table states them, which a repository's statement of how it fills each
# reads from `config --json`.
ROLES = (
    Role("Local validation of a commit: the repository's own checks and suites against "
         "the commit, built from it",
         (EVIDENCE, "validation.preflight", "hooks.pre-commit-functional")),
    Role("Validation in a deployed environment: the change's services built and run as "
         "the repository deploys them", (EVIDENCE,)),
    Role("The end-to-end pipeline: a run whose head is the commit, its logs fetched",
         (EVIDENCE,)),
    Role("CI evidence only a push produces: the workflows validation may dispatch, from a "
         "fixed list", (EVIDENCE,)),
    Role("Removing a change's validation resources, and recording what they used, at "
         "archive cleanup", (EVIDENCE,)),
    Role("The repository's tests and environments: the suites, locks, builds, and "
         "environment refreshes a change's work runs",
         ("hooks.after-functional-change", "hooks.pre-commit-functional",
          f"sandbox.writable.{COMMON_WRITABLE}", "sandbox.writable.<step>")),
    Role("The packaging check before closeout",
         ("hooks.pre-commit-functional", "hooks.pre-archive")),
    Role("The closing checks a step ends with", ("hooks.pre-commit", "defaults.disable")),
    Role("The change index at a known path"),
    Role("The guidance documents every step reads",
         (GUIDANCE_ENGINEERING, f"load.{COMMON_DOCUMENTS}", "load.<step>")),
    Role("Where specifications and documentation live", ("repository.inert-paths",)),
    Role("Protected branches the guarded push refuses", ("repository.protected-branches",)),
    Role("A pre-push check the guarded push runs over what it would send, where the "
         "repository provides one", ("hooks.pre-push",)),
    Role("The remote a change's branch is pushed to, its upstream's, from which the "
         "pipeline runs"),
    Role("The branch a change lands on, merged before closeout and reviewed against"),
    Role("The clone's bootstrap: one command that readies a fresh clone",
         ("hooks.post-clone",)),
    Role("The make fragment's targets, included by the repository's `Makefile`"),
)


# What each default check runs, as `config` shows it.
_DEFAULT_SHOWN = {
    "index": "change-workflow check index",
    "tasks": "change-workflow check tasks <change>",
    "skills": "change-workflow check skills",
    "spec-index": "change-workflow check spec-index <change>",
    "decisions": "change-workflow check decisions <change>",
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

    add("workflow.version", ABSENT if configuration.version_range is None else DECLARED,
        configuration.version_range)
    engineering = configuration.engineering
    add(GUIDANCE_ENGINEERING, MISSING if engineering is None else DECLARED,
        None if engineering is None else engineering.shown())
    branches = configuration.protected_branches
    add("repository.protected-branches", ABSENT if branches is None else DECLARED,
        None if branches is None else list(branches))
    add("repository.inert-paths", DEFAULT if configuration.inert_paths is None else DECLARED,
        list(configuration.repository_inert_paths()))
    for hook in HOOKS + STEP_HOOKS:
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
    for key in _LOCAL_TABLES[MODELS]:
        models = configuration.models.get(key)
        add(f"models.{key}", MISSING if models is None else DECLARED, models)
    add("validation.preflight", ABSENT if configuration.preflight is None else DECLARED,
        None if configuration.preflight is None else list(configuration.preflight))
    add("review.format-retries", DEFAULT if configuration.format_retries is None else DECLARED,
        configuration.review_format_retries())
    for key in (COMMON_WRITABLE, *(step for step in STEPS if step != "review")):
        paths = configuration.sandbox_writable.get(key)
        add(f"sandbox.writable.{key}", ABSENT if paths is None else DECLARED,
            None if paths is None else list(paths))
    add("sandbox.protected", ABSENT if configuration.sandbox_protected is None else DECLARED,
        None if configuration.sandbox_protected is None else list(configuration.sandbox_protected))
    if not configuration.kinds:
        add(EVIDENCE, ABSENT)
    for kind in configuration.kinds or ():
        for key in KIND_KEYS:
            value = getattr(kind, key)
            add(f"{EVIDENCE}.{kind.name}.{key}", ABSENT if value is None else DECLARED,
                list(value) if isinstance(value, tuple) else value)
    return fields


def _shown_value(value: Any) -> str:
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return "; ".join(value) if value else "(empty)"
    return json.dumps(value, ensure_ascii=False)


def scopes(configuration: Configuration, root: Path) -> dict[str, Scope]:
    """Each step's scope in the checkout at `root` as a run of it on its first model
    would start now, with that model's adapter's paths, before any grant adds its
    own."""
    return {step: configuration.scope(step, root) for step in STEPS}


def _shown_path(path: Path, root: Path) -> str:
    """A scope's path as `config` lists it: from the checkout's root where it lies there,
    from `~` where it lies in the home directory, and whole otherwise."""
    for base, prefix in ((root, ""), (Path.home(), "~/")):
        if path == base:
            return prefix or "."
        if base in path.parents:
            return prefix + path.relative_to(base).as_posix()
    return str(path)


def resolution_lines(configuration: Configuration, resolved: Mapping[str, Scope],
                     root: Path) -> list[str]:
    """`config`'s listing: every field and how it resolved, then each step's scope in
    `resolved`, its paths shown from the checkout at `root`."""
    lines = [f"{configuration.shown}: " + ("read" if configuration.exists
                                           else "no such file; every field is absent"),
             f"{LOCAL.as_posix()}: " + ("read" if configuration.local_exists
                                       else "no such file; every local field is missing")]
    for entry in resolution(configuration):
        detail = (f"— {entry['reason']}" if "reason" in entry
                  else _shown_value(entry["value"]) if "value" in entry else "")
        lines.append(f"{entry['field']:<44} {entry['status']:<9} {detail}".rstrip())
    for step, scope in resolved.items():
        for kind, paths in (("writable", scope.writable), ("protected", scope.protected)):
            for path in paths:
                shown = _shown_path(path.path, root)
                note = (" (private)" if path.private else "") + (" (absent)" if path.create
                                                                 else "")
                lines.append(f"{f'scope.{step}.{kind}':<44} {path.source:<9} {shown}{note}")
    return lines


def cited_sections(configuration: Configuration,
                   shipped: distribution.Distribution) -> list[str]:
    """`check config`'s report of the engineering sections the `shipped` skills and
    workflow guidance cite that the guidance beneath the pointer does not resolve:
    each no file heads, and each several sections head, naming the files. A report,
    never a refusal: a user's guidance is held to no repository's headings. Nothing
    while the pointer names no directory."""
    engineering = configuration.engineering
    if engineering is None or engineering.path is None:
        return []
    texts = {name: (source / "SKILL.md").read_text("utf-8")
             for name, source in shipped.skills().items()}
    guidance = shipped.path(distribution.GUIDANCE)
    texts.update({f"the workflow guidance's {path.relative_to(guidance).as_posix()}":
                  path.read_text("utf-8") for path in sorted(guidance.rglob("*.md"))})
    citing = sections.citing(texts, sections.ENGINEERING)
    lines = []
    for name, files in sections.unresolved(citing, sections.heads(engineering.path)).items():
        by = ", ".join(sorted(citing[name]))
        if files:
            lines.append(f'AMBIGUOUS: the engineering guidance\'s section "{name}", which '
                         f"{by} cites, heads a section in each of "
                         + ", ".join(f"{engineering.entry.rstrip('/')}/{path.as_posix()}"
                                     for path in files)
                         + ", so the citation names none of them")
        else:
            lines.append(f'UNRESOLVED: the engineering guidance\'s section "{name}", which '
                         f"{by} cites, heads no file beneath {engineering.entry}")
    return lines


def main(argv: Sequence[str] | None = None, root: Path | None = None) -> int:
    """`config [--json]`, `config load <step>` or `config load common`, and `check
    config`, as `cli` hands them on."""
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
        root = repository_root() if root is None else root
        configuration = load(root)
        # A directory entry is resolved here, before anything is printed, so a
        # refused one prints no partial list.
        documents = configuration.documents(args.step, root) if args.action == "load" else []
        resolved = scopes(configuration, root) if args.action == "show" else {}
    except StepError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if args.action == "check":
        print(f"OK: {configuration.shown} "
              + ("passes its check." if configuration.exists
                 else "does not exist; every field is absent."))
        # A local field's absence is reported, not refused: a checkout with no local
        # file, CI's among them, checks every committed field all the same.
        if absent := [entry["field"] for entry in resolution(configuration)
                      if entry["status"] == MISSING]:
            print(f"MISSING: {LOCAL.as_posix()} "
                  + ("does not declare " if configuration.local_exists
                     else "does not exist, so lacks ")
                  + ", ".join(absent) + "; a step needing one refuses until "
                  "`change-workflow install` writes the file or they are declared there.")
        for line in cited_sections(configuration, distribution.RUNNING):
            print(line)
    elif args.action == "load":
        for document in documents:
            print(document)
    elif args.json:
        engineering = configuration.engineering
        print(json.dumps({"file": configuration.shown, "exists": configuration.exists,
                          "local": {"file": LOCAL.as_posix(),
                                    "exists": configuration.local_exists},
                          "fields": resolution(configuration),
                          "guidance": {"engineering": None if engineering is None
                                       else engineering.shown()},
                          "scopes": {step: scope.shown() for step, scope in resolved.items()},
                          "workflow": distribution.RUNNING.described(),
                          "roles": [role.shown() for role in ROLES]},
                         ensure_ascii=False))
    else:
        print("\n".join(resolution_lines(configuration, resolved, root)))
    return 0
