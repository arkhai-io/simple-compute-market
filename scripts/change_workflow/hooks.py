"""Running the repository's hooks: `scripts/change-workflow run <hook> <change>`.

A hook is one command or a list (`config`). Each command has its placeholders filled,
each value shell-quoted, and runs with `sh -c` from the repository's root, without
the recursion state of any make that started the session (`command_environment`),
its output passed through. A list runs every command in order, whatever an earlier one
reported, and the hook fails when any failed, naming each, so one call reports every
failure. Every hook ends with one closing line the engine writes in a fixed form
(`closing_line`), naming the hook, the commit, the result, and each failed command
with its exit status. An optional hook the configuration does not declare is
skipped, the closing line and the record saying so.

Which steps may run each hook is the engine's hook table (`graph.HOOK_STEPS`). An
unattended run's marker names its step (`common.UNATTENDED_RUN`), and `run`
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

`run validation <change> preflight` runs the preflight, and `run validation <change>
<part> run|start|collect` a part's command, an owed part's with `--owed <workflow>`,
the workflow its run is for, which any other part refuses. A `start` is a dispatch
that returns at once, promising its last line of standard output is the marker its
`collect` waits past: the engine keeps that marker in the checkout's Git directory,
for the commit, the part, and the owed workflow, so owed runs dispatched side by
side never share one, and a retried `start` replaces it, so a collect always waits
past the newest dispatch. It fills the collect's `{after}` from it; with none kept
the collect refuses, naming the start to run. Each part ends with the closing line,
which also names the part's evidence directory. `run cleanup <change>` runs every
part's cleanup in declaration order, as one list.

Whatever ran is kept, naming its change, for the line of the session it ran in
(`keep`), the session named by `CLAUDE_CODE_SESSION_ID`: the wrapper adds it to an
unattended run's line as `invoked`, the review to a Claude review's, and `record`
to an interactive run's. Outside a session nothing is kept.

Contract: openspec/specs/change-workflow/spec.md, CW-b2xr, CW-k9vd, CW-u4pc, CW-y6mj,
CW-e1sg, CW-c8lw, CW-v2dq, CW-i2we, CW-t5hz, CW-g4oz, CW-x9bt, CW-zkhs, CW-ikmm, and
CW-q5fy.
"""

from __future__ import annotations

import fcntl
import json
import os
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from . import index, skills, tasks
from .common import SESSION_ID, UNATTENDED_RUN, Clock, Entry, StepError, utc_now
from .config import (DEFAULT_CHECKS, PRE_COMMIT_FUNCTIONAL, Configuration, fill, placeholders,
                     require)
from .find import ChangeNotFound, change_directory, is_archived
from .graph import HOOK_STEPS, STEPS
from .records import git_head, inert
from .running import git_state, invocations_directory, keep_invocations

# The hooks `run` runs by name.
NAMED = ("after-functional-change", "pre-commit", "pre-commit-functional", "pre-archive")
# Validation's preflight and parts, `run validation <change> …`, and every part's
# cleanup, `run cleanup <change>`.
VALIDATION, CLEANUP, PREFLIGHT = "validation", "cleanup", "preflight"
PHASES = ("run", "start", "collect")
# The prefix of every line the engine writes about a hook, so a reader tells it from
# the commands' own output.
PREFIX = "[change-workflow]"
# Where a checkout keeps each change's started parts' markers, under its Git
# directory.
MARKERS = "change-validation"

# Runs a shell command from the repository's root, its output passed through, and
# returns its exit status.
Shell = Callable[[str, Path], int]
# Runs a shell command as `Shell` does, and also returns the last non-empty line of
# its standard output: a `start`'s marker.
Capture = Callable[[str, Path], tuple[int, str | None]]
# Runs a default check that the engine holds in process, by name, for a change, and
# returns its exit status.
InProcess = Callable[[str, str, Path], int]


class HookError(StepError):
    """A hook cannot be run: refused by the hook table, or missing a value or a
    required field."""


# What a make passes the commands it runs so that a make among them acts as its
# sub-make. A session started by a make target inherits them, and a declared
# `make …` would then print its "Leaving directory" line after a `start`'s marker,
# which must be its last line.
_MAKE_RECURSION = ("MAKELEVEL", "MAKEFLAGS", "MFLAGS", "MAKEOVERRIDES")


def command_environment(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """The environment a hook's or a part's command runs in: the caller's, without
    make's recursion state, so the command runs as a fresh invocation from the
    repository's root. A variable given to the outer make on its command line stays,
    since make exports it, but as an environment variable: a Makefile's `?=` takes
    it, while a plain `=` or `:=` assignment overrides it."""
    return {key: value for key, value in (os.environ if environ is None else environ).items()
            if key not in _MAKE_RECURSION}


def shell(command: str, root: Path) -> int:
    return subprocess.run(["sh", "-c", command], cwd=root, env=command_environment()).returncode


def capture(command: str, root: Path) -> tuple[int, str | None]:
    """Run `command` as `shell` does, passing each line of its standard output
    through as it arrives, and return its status and its last non-empty line."""
    process = subprocess.Popen(["sh", "-c", command], cwd=root, stdout=subprocess.PIPE,
                               text=True, encoding="utf-8", errors="replace",
                               env=command_environment())
    assert process.stdout is not None
    last = None
    for line in process.stdout:
        sys.stdout.write(line)
        sys.stdout.flush()
        if line.strip():
            last = line.strip()
    return process.wait(), last


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


def closing_line(name: str, invoked: Sequence[Invoked], commit: str | None,
                 evidence: str | None = None, part: bool = False) -> str:
    """The line the engine ends a hook or a part with, whatever its commands
    printed: `<prefix> <name> at <commit>: passed, exit 0`, or `failed, exit <n>:`
    and each failed command with its exit status, `<n>` the first's; a hook with
    nothing to run says it was skipped, and why. A part's line ends `; evidence
    <directory>`, or `none`."""
    where = f"{PREFIX} {name} at {commit or 'no commit'}"
    failed = [i for i in invoked if i.failed]
    if invoked and all(i.skipped for i in invoked):
        result = f"skipped, {invoked[0].skipped}"
    elif not failed:
        result = "passed, exit 0"
    else:
        result = f"failed, exit {failed[0].exit_status}: " + "; ".join(
            f"{i.shown} (exit {i.exit_status})" for i in failed)
    return f"{where}: {result}" + (f"; evidence {evidence or 'none'}" if part else "")


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
    capture: Capture = capture
    # Where the change's started parts' markers are kept, and where a session's
    # invocations wait for its line; None outside a Git checkout.
    markers: Callable[[Path], Path | None] = lambda root: git_state(root, MARKERS)
    invocations: Callable[[Path], Path | None] = invocations_directory
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
                    flag = {"base": "--base <branch>"}.get(name)
                    raise HookError(f"{where} names {{{name}}}, which this run was not given"
                                    + (f"; give it with {flag}" if flag else ""))

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

    def engine_hook(self, name: str, values: Mapping[str, str]) -> bool:
        """A hook the engine runs itself, as the guarded push runs `pre-push`, held
        to no step's listing: its commands with `values`, or skipped, saying so,
        when it is not declared."""
        commands = self.configuration.hook(name)
        if commands is None:
            return self.finish(name, self.skip(name, "not declared"))
        self.needs(commands, values, f"hooks.{name}")
        return self.finish(name, self.run_commands(name, commands, values))

    def check_change(self, change: str) -> bool:
        """The default checks alone, as `check change` runs them."""
        return self.finish("default checks", self.defaults(change))

    # Validation's preflight and parts, and their cleanup.

    def validation(self, change: str, base: str | None, part_name: str,
                   phase: str | None = None, owed: str | None = None) -> bool:
        """`run validation <change> preflight`, or a part's `run`, `start`, or
        `collect`, held to the hook table. An owed part takes the workflow it is
        owed for, and any other refuses one. A `start`'s last line of standard
        output is kept as its marker, for the commit, the part, and the workflow,
        replacing any kept before; the matching `collect` fills `{after}` with it,
        and refuses with none kept."""
        self.allow(VALIDATION)
        commit = self.head(self.root)
        if commit is None:
            raise HookError("validation reads the commit at HEAD, and none could be read")
        if part_name == PREFLIGHT:
            if phase is not None or owed is not None:
                raise HookError("the preflight takes no phase and no --owed")
            name = f"{VALIDATION} {PREFLIGHT}"
            commands = self.configuration.preflight
            values = self.values(change, base)
            if commands is None:
                return self.finish(name, self.skip(VALIDATION, "not declared",
                                                   phase=PREFLIGHT))
            self.needs(commands, values, "validation.preflight")
            return self.finish(name, self.run_commands(VALIDATION, commands, values,
                                                       phase=PREFLIGHT))
        part = self.configuration.part(part_name)
        if phase not in PHASES:
            raise HookError(f"a part is run with one of {', '.join(PHASES)}; got {phase!r}")
        if (phase == "run") != (part.run is not None):
            raise HookError(f"validation.parts.{part.name} declares {part.shape}, so it is "
                            f"run with {' or '.join(part.shape.split(', '))}, not {phase}")
        if part.owed and owed is None:
            raise HookError(f"validation.parts.{part.name} is owed: give the workflow its run "
                            "is for with --owed <workflow>")
        if owed is not None and not part.owed:
            raise HookError(f"validation.parts.{part.name} is not owed, so it takes no --owed")
        values = self.values(change, base, **({"owed": owed} if owed is not None else {}))
        key = _marker_key(commit, part.name, owed)
        if phase == "collect":
            after = self._kept(change).get(key)
            if after is None:
                raise HookError(f"no start of {part.name}{f' for {owed}' if owed else ''} at "
                                f"{commit} has kept a marker; run `scripts/change-workflow "
                                f"run validation {change} {part.name} start"
                                f"{f' --owed {owed}' if owed else ''}` first")
            values["after"] = after
        commands = getattr(part, phase)
        self.needs(commands, values, f"validation.parts.{part.name}.{phase}")
        labels = {"part": part.name, "owed": owed, "phase": phase}
        if phase == "start":
            ran, marker = self._start(commands, values, labels)
            self._keep_marker(change, key, marker if not any(i.failed for i in ran) else None)
        else:
            ran = self.run_commands(VALIDATION, commands, values, **labels)
        name = " ".join([VALIDATION, part.name, *([owed] if owed else []), phase])
        self.echo(closing_line(name, ran, commit, part.evidence, part=True))
        return not any(i.failed for i in ran)

    def _start(self, commands: Sequence[str], values: Mapping[str, str],
               labels: Mapping[str, str | None]) -> tuple[list[Invoked], str | None]:
        """Run a `start`'s commands, and return them and the last line its last
        command printed."""
        ran, marker = [], None
        for command in commands:
            resolved = fill(command, values)
            self.echo(f"+ {resolved}")
            printed: list[str | None] = []

            def call(resolved: str = resolved) -> int:
                status, last = self.capture(resolved, self.root)
                printed.append(last)
                return status

            ran.append(self._timed(call, hook=VALIDATION, command=resolved, **labels))
            marker = printed[0]
        return ran, marker

    def _markers_file(self, change: str) -> Path:
        directory = self.markers(self.root)
        if directory is None:
            raise HookError(f"{self.root} is no Git checkout, so no start's marker can be kept")
        return directory / f"{change}.json"

    def _kept(self, change: str) -> dict[str, str]:
        path = self._markers_file(change)
        try:
            with path.open("r", encoding="utf-8") as kept:
                fcntl.flock(kept, fcntl.LOCK_SH)
                return json.loads(kept.read() or "{}")
        except FileNotFoundError:
            return {}

    def _keep_marker(self, change: str, key: str, marker: str | None) -> None:
        """Keep `marker` for `key`, replacing any kept before; a start that failed,
        or printed nothing, keeps none, so its collect refuses."""
        path = self._markers_file(change)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Owed runs are started side by side, so the file is locked from reading it
        # to writing it back.
        with path.open("a+", encoding="utf-8") as kept:
            fcntl.flock(kept, fcntl.LOCK_EX)
            kept.seek(0)
            markers = json.loads(kept.read() or "{}")
            if marker is None:
                markers.pop(key, None)
            else:
                markers[key] = marker
            kept.seek(0)
            kept.truncate()
            kept.write(json.dumps(markers, ensure_ascii=False, indent=1, sort_keys=True))

    def cleanup(self, change: str, base: str | None) -> bool:
        """`run cleanup <change>`: every part's cleanup, in declaration order, as one
        list, each command run whatever an earlier one reported."""
        self.allow(CLEANUP)
        parts = [part for part in self.configuration.parts or () if part.cleanup]
        values = self.values(change, base)
        for part in parts:
            self.needs(part.cleanup or (), values, f"validation.parts.{part.name}.cleanup")
        if not parts:
            return self.finish(CLEANUP, self.skip(CLEANUP, "no part declares a cleanup"))
        ran = [invoked for part in parts
               for invoked in self.run_commands(CLEANUP, part.cleanup or (), values,
                                                part=part.name, phase=CLEANUP)]
        return self.finish(CLEANUP, ran)

    def keep(self, change: str) -> None:
        """Keep what this invocation ran for `change`, for the line of the session
        it is part of. Keeping it is the record's, never the hook's: a failure to
        keep it is said, and changes neither the hook's result nor its exit."""
        try:
            keep_invocations(self.invocations(self.root), self.environ.get(SESSION_ID),
                             [{"change": change, **invoked.entry()}
                              for invoked in self.invoked])
        except (OSError, StepError) as exc:
            print(f"WARNING: what this run invoked could not be kept for its session's "
                  f"line: {exc}", file=sys.stderr)


def _marker_key(commit: str, part: str, owed: str | None) -> str:
    return " ".join([commit, part, *([owed] if owed else [])])


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
         environ: Mapping[str, str], base: str | None = None, part: str | None = None,
         phase: str | None = None, owed: str | None = None,
         hooks: Hooks | None = None) -> int:
    """`run <hook> <change>`, `run validation <change> preflight|<part> <phase>`, or
    `run cleanup <change>`: 0 when it passed, 1 when it failed or was refused, its
    reason on standard error. What ran is kept for the session's line, however it
    ended."""
    runner = hooks or Hooks(root, configuration, environ)
    try:
        change_directory(root, change)
        if hook == VALIDATION:
            passed = runner.validation(change, base, part or "", phase, owed)
        elif hook == CLEANUP:
            passed = runner.cleanup(change, base)
        else:
            passed = runner.named(hook, change, base, lambda: worktree_changes(root))
    except (ChangeNotFound, StepError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        runner.keep(change)
    return 0 if passed else 1
