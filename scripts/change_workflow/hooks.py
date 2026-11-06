"""Running the repository's hooks: `scripts/change-workflow run <hook> <change>`.

A hook is one command or a list (`config`). Each command has its placeholders filled,
each value shell-quoted, and runs with `sh -c` from the repository's root, its
output passed through. A list runs every command in order, whatever an earlier one
reported, and the hook fails when any failed, naming each, so one call reports every
failure. Every hook ends with one closing line the engine writes in a fixed form
(`closing_line`), naming the hook, the commit, the result, and each failed command
with its exit status. An optional hook the configuration does not declare is
skipped, the closing line and the record saying so.

Which steps may run each hook is the engine's hook table (`graph.HOOK_STEPS`). An
unattended run's marker names its step (`harness.UNATTENDED_RUN`), and `run`
refuses a hook its step is not listed for, naming both, before anything runs; with
no marker, as in a session the owner holds, nothing is restricted. A forged marker
is a step breaking its skill, which its deny rules and skill govern.

`run pre-commit` reads its tier from the paths the commit would change, the
worktree's changes against `HEAD` — staged, unstaged, and untracked. When any lies
outside the repository's inert paths, it runs `after-functional-change`, then
`pre-commit-functional`, then `pre-commit`; otherwise `pre-commit` alone. Each is
held to the hook table, so a step that may not make a functional change is refused
one, and a functional commit with no `pre-commit-functional` declared is refused,
naming the field. `pre-commit`'s default checks — the change index, the task list,
the agent skills, and the strict OpenSpec validation of the change, or of every
specification for an archived change — run before its declared commands, each
skipped only when `defaults.disable` names it; `check change <change>` runs them
alone. A `pre-commit`, its defaults included, only reports, so a review may run it
and the worktree is as it was.

`openspec <arguments>` runs the configured OpenSpec command, or `openspec` on the
path, with the arguments shell-quoted after it.

Contract: openspec/specs/change-workflow/spec.md, CW-b2xr, CW-k9vd, CW-u4pc, CW-y6mj,
CW-e1sg, CW-c8lw, CW-v2dq, CW-i2we, and CW-t5hz.
"""

from __future__ import annotations

import shlex
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from . import index, skills, tasks
from .common import UNATTENDED_RUN, Clock, Entry, StepError, utc_now
from .config import (DEFAULT_CHECKS, PLACEHOLDER, PRE_COMMIT_FUNCTIONAL, Configuration,
                     ConfigError, inert, placeholders, require)
from .find import ChangeNotFound, change_directory, is_archived
from .graph import HOOK_STEPS, STEPS
from .records import git_head

# The hooks `run` runs by name.
NAMED =("after-functional-change", "pre-commit", "pre-commit-functional", "pre-archive")
# The prefix of every line the engine writes about a hook, so a reader tells it from
# the commands' own output.
PREFIX = "[change-workflow]"

# Runs a shell command from the repository's root, its output passed through, and
# returns its exit status.
Shell = Callable[[str, Path], int]
# Runs a default check that the engine holds in process, by name, for a change, and
# returns its exit status.
InProcess = Callable[[str, str, Path], int]


class HookError(StepError):
    """A hook cannot be run: refused by the hook table, or missing a value or a
    required field."""


def shell(command: str, root: Path) -> int:
    return subprocess.run(["sh", "-c", command], cwd=root).returncode


def fill(command: str, values: Mapping[str, str]) -> str:
    """`command` with each placeholder replaced by its value, shell-quoted. The
    configuration's check has refused any placeholder unknown where it is used, so a
    placeholder without a value is one this invocation does not supply."""
    def value(name: str) -> str:
        if name not in values:
            raise HookError(f"{{{name}}} has no value in this run")
        return shlex.quote(values[name])

    return PLACEHOLDER.sub(lambda match: value(match.group(1)), command)


def _in_process(check: str, change: str, root: Path) -> int:
    """The default checks the engine holds as its own modules, each printing what it
    finds."""
    try:
        if check == "index":
            return index.main(root)
        if check == "skills":
            return skills.main(root)
        return tasks.main([change], root=root)
    except OSError as exc:
        print(f"ERROR: the {check} check could not read what it checks: {exc}",
              file=sys.stderr)
        return 1


@dataclass
class Invoked:
    """One command a hook ran, or a default check, or a hook skipped: what the run's
    record keeps of it."""

    hook: str
    command: str | None
    exit_status: int | None
    started: str
    seconds: float
    part: str | None = None
    owed: str | None = None
    phase: str | None = None
    check: str | None = None
    skipped: str | None = None

    def entry(self) -> Entry:
        found: Entry = {"hook": self.hook}
        for key in ("part", "owed", "phase", "check", "command", "exit_status", "skipped"):
            if (value := getattr(self, key)) is not None:
                found[key] = value
        return {**found, "started": self.started, "seconds": round(self.seconds, 3)}

    @property
    def failed(self) -> bool:
        return self.exit_status not in (None, 0)

    @property
    def shown(self) -> str:
        return self.command or f"the {self.check} check"


def closing_line(name: str, invoked: Sequence[Invoked], commit: str | None) -> str:
    """The line the engine ends a hook with: `<prefix> <name> at <commit>: passed`,
    or `failed:` and each failed command with its exit status; a hook with nothing
    to run says it was skipped, and why."""
    where = f"{PREFIX} {name} at {commit or 'no commit'}"
    if invoked and all(i.skipped for i in invoked):
        return f"{where}: skipped, {invoked[0].skipped}"
    failed = [i for i in invoked if i.failed]
    if not failed:
        return f"{where}: passed"
    return f"{where}: failed: " + "; ".join(f"{i.shown} (exit {i.exit_status})" for i in failed)


@dataclass
class Hooks:
    """Runs a repository's hooks for one change, through injected seams."""

    root: Path
    configuration: Configuration
    environ: Mapping[str, str]
    shell: Shell = shell
    in_process: InProcess = _in_process
    clock: Clock = utc_now
    timer: Callable[[], float] = time.monotonic
    head: Callable[[Path], str | None] = git_head
    echo: Callable[[str], None] = lambda shown: print(shown, flush=True)
    # Every command, check, and skipped hook this invocation ran, in order.
    invoked: list[Invoked] = field(default_factory=list)

    @property
    def step(self) -> str | None:
        """The step of the unattended run this invocation is part of; None outside
        one."""
        return self.environ.get(UNATTENDED_RUN) or None

    def allow(self, hook: str) -> None:
        """Refuse `hook` when the unattended run's step is not listed for it."""
        step = self.step
        if step is None:
            return
        if step not in STEPS:
            raise HookError(f"{UNATTENDED_RUN} names {step!r}, which is no step of the "
                            "workflow; no hook is run")
        if step not in HOOK_STEPS[hook]:
            raise HookError(f"the {step} step may not run {hook}; the steps that may: "
                            + ", ".join(sorted(HOOK_STEPS[hook])))

    def values(self, change: str, base: str | None, **more: str) -> dict[str, str]:
        return {"change": change, **({"base": base} if base is not None else {}), **more}

    def needs(self, commands: Sequence[str], values: Mapping[str, str], where: str) -> None:
        """Refuse, before anything runs, a command naming a value this run lacks."""
        for command in commands:
            for name in placeholders(command):
                if name not in values:
                    flag = {"base": "--base <branch>"}.get(name, name)
                    raise HookError(f"{where} names {{{name}}}, which this run was not "
                                    f"given; give it with {flag}")

    def run_commands(self, hook: str, commands: Sequence[str], values: Mapping[str, str],
                     **labels: str | None) -> list[Invoked]:
        """Run each of `commands`, filled, in order, whatever an earlier one reported."""
        ran = []
        for command in commands:
            resolved = fill(command, values)
            self.echo(f"+ {resolved}")
            ran.append(self._timed(lambda: self.shell(resolved, self.root), hook=hook,
                                   command=resolved, **labels))
        return ran

    def _timed(self, call: Callable[[], int], **fields: Any) -> Invoked:
        started = self.clock().strftime("%Y-%m-%dT%H:%M:%SZ")
        begun = self.timer()
        status = call()
        invoked = Invoked(started=started, seconds=self.timer() - begun, exit_status=status,
                          **fields)
        self.invoked.append(invoked)
        return invoked

    def skip(self, hook: str, why: str, **labels: str | None) -> list[Invoked]:
        skipped = Invoked(hook=hook, command=None, exit_status=None,
                          started=self.clock().strftime("%Y-%m-%dT%H:%M:%SZ"), seconds=0.0,
                          skipped=why, **labels)
        self.invoked.append(skipped)
        return [skipped]

    def finish(self, name: str, ran: Sequence[Invoked]) -> bool:
        """Write the hook's closing line, and say whether it passed."""
        self.echo(closing_line(name, ran, self.head(self.root)))
        return not any(i.failed for i in ran)

    # The named hooks.

    def defaults(self, change: str) -> list[Invoked]:
        """`pre-commit`'s default checks, each but those `defaults.disable` names."""
        ran = []
        for check in DEFAULT_CHECKS:
            if check in self.configuration.disabled:
                self.echo(f"{PREFIX} default check {check}: disabled — "
                          f"{self.configuration.disabled[check]}")
                continue
            if check == "openspec":
                ran += self.run_commands("pre-commit", [self.openspec_validation(change)], {},
                                         check=check)
            else:
                self.echo(f"+ the {check} check")
                ran.append(self._timed(lambda c=check: self.in_process(c, change, self.root),
                                       hook="pre-commit", command=None, check=check))
        return ran

    def openspec_validation(self, change: str) -> str:
        """The strict validation of the change, or of every specification once it is
        archived and has no delta left."""
        try:
            archived = is_archived(self.root, change_directory(self.root, change))
        except ChangeNotFound as exc:
            raise HookError(str(exc)) from exc
        arguments = (["validate", "--specs", "--strict"] if archived
                     else ["validate", change, "--strict"])
        return openspec_command(self.configuration, arguments)

    def hook(self, name: str, change: str, base: str | None) -> list[Invoked]:
        """One named hook: `pre-commit` its defaults and then its commands; any
        other its commands, or skipped, saying so, when it is not declared."""
        commands = self.configuration.hook(name)
        values = self.values(change, base)
        if commands is not None:
            self.needs(commands, values, f"hooks.{name}")
        ran = self.defaults(change) if name == "pre-commit" else []
        if commands is None:
            if name == "pre-commit-functional":
                require(self.configuration, PRE_COMMIT_FUNCTIONAL, needed_by="a functional commit")
            if ran:
                self.echo(f"{PREFIX} hooks.{name}: not declared; the default checks alone")
            return ran + self.skip(name, "not declared")
        return ran + self.run_commands(name, commands, values)

    def pre_commit(self, change: str, base: str | None, changed: Sequence[str]) -> bool:
        """The hooks a commit of `changed` runs: the functional tier when any path
        lies outside the inert paths, `pre-commit` alone otherwise."""
        functional = [path for path in changed
                      if not inert(path, self.configuration.inert_paths)]
        tier = (["after-functional-change", "pre-commit-functional", "pre-commit"]
                if functional else ["pre-commit"])
        if functional:
            # Said first, so a step refused the functional tier learns which path
            # put it there.
            self.echo(f"{PREFIX} pre-commit: {len(functional)} changed path"
                      f"{'' if len(functional) == 1 else 's'} outside the inert paths, "
                      f"{functional[0]} first: running {', '.join(tier)}")
        for name in tier:
            self.allow(name)
        if functional:
            require(self.configuration, PRE_COMMIT_FUNCTIONAL,
                    needed_by=f"a commit changing {functional[0]}, outside the inert paths,")
        for name in tier:
            commands = self.configuration.hook(name)
            if commands is not None:
                self.needs(commands, self.values(change, base), f"hooks.{name}")
        passed = [self.finish(name, self.hook(name, change, base)) for name in tier]
        return all(passed)

    def named(self, name: str, change: str, base: str | None,
              changed: Callable[[], Sequence[str]]) -> bool:
        """`run <name> <change>`, held to the hook table."""
        if name == "pre-commit":
            return self.pre_commit(change, base, changed())
        self.allow(name)
        return self.finish(name, self.hook(name, change, base))

    def check_change(self, change: str) -> bool:
        """The default checks alone, as `check change` runs them."""
        return self.finish("default checks", self.defaults(change))


def worktree_changes(root: Path) -> list[str]:
    """Every path the worktree changes against `HEAD`: staged, unstaged, and
    untracked, a rename's both sides."""
    found = subprocess.run(["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
                           cwd=root, capture_output=True, text=True)
    if found.returncode != 0:
        raise HookError(f"git status failed: {found.stderr.strip()}")
    paths: list[str] = []
    fields = found.stdout.split("\0")
    position = 0
    while position < len(fields):
        entry = fields[position]
        position += 1
        if len(entry) < 4:
            continue
        paths.append(entry[3:])
        # A rename or copy names its original path in the field after it.
        if "R" in entry[:2] or "C" in entry[:2]:
            paths.append(fields[position])
            position += 1
    return paths


def openspec_command(configuration: Configuration, arguments: Sequence[str]) -> str:
    """The configured OpenSpec command with `arguments`, each shell-quoted."""
    return " ".join([configuration.openspec_command(), *map(shlex.quote, arguments)])


def run_openspec(configuration: Configuration, arguments: Sequence[str], root: Path,
                 run: Shell = shell) -> int:
    """`openspec <arguments>`: the configured command run from the root, 0 when it
    passed and 1 when it did not."""
    return 0 if run(openspec_command(configuration, arguments), root) == 0 else 1


def main(hook: str, change: str, *, root: Path, configuration: Configuration,
         environ: Mapping[str, str], base: str | None = None,
         hooks: Hooks | None = None) -> int:
    """`run <hook> <change>`: 0 when the hook passed, 1 when it failed or was refused,
    its reason on standard error."""
    runner = hooks or Hooks(root, configuration, environ)
    try:
        change_directory(root, change)
        passed = runner.named(hook, change, base, lambda: worktree_changes(root))
    except (ChangeNotFound, ConfigError, HookError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0 if passed else 1
