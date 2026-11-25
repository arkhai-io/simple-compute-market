"""Running the repository's hooks: `change-workflow run <hook> <change>`.

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
is a step working around its skill, outside what the table guards against; the
checks after a run hold what matters, such as validation's tree.

`run pre-commit` reads its tier from the paths the commit would change, the
worktree's changes against `HEAD` — staged, unstaged, and untracked. When any lies
outside the repository's inert paths, it runs `after-functional-change`, then
`pre-commit-functional`, then `pre-commit`; otherwise `pre-commit` alone. Each is
held to the hook table, so a step that may not make a functional change is refused
one, and a functional commit with no `pre-commit-functional` declared is refused,
naming the field. `pre-commit`'s default checks — the change index, the task list,
the agent skills, the specification indexes with the change's deltas counted, each
decision's destination, and the strict OpenSpec validation of the change, or of every
specification for an archived change — run before its declared commands, each
skipped only when `defaults.disable` names it; `check change <change>` runs them
alone. A `pre-commit`, its defaults included, only reports, so a review may run it
and the worktree is as it was. `after-functional-change` and `pre-commit-functional`
may name `{tree}`, the worktree's tree as the hook starts, and `{commit}`, `HEAD`'s,
so a functional check can leave evidence for the tree it checks.

A kind's `start` is a dispatch that returns at once, promising its last line of
standard output is the marker its `collect` waits past: the engine keeps that
marker in the checkout's Git directory (`start`, `keep_marker`, `kept_marker`), for
the tree or commit the kind's evidence describes, the kind, and an owed argument
(`marker_key`). The gathering (`gather`) runs a kind's commands through this
runner. `run cleanup <change>` runs every kind's cleanup in declaration order, as
one list.

Whatever ran is kept, naming its change, for the line of the session it ran in
(`keep`), the session named by `CLAUDE_CODE_SESSION_ID`: the wrapper adds it to an
unattended run's line as `invoked`, the review to a Claude review's, and `record`
to an interactive run's. Outside a session nothing is kept.

Contract: openspec/specs/change-workflow/spec.md, CW-b2xr, CW-k9vd, CW-u4pc, CW-y6mj,
CW-e1sg, CW-c8lw, CW-v2dq, CW-i2we, CW-t5hz, CW-x9bt, CW-ikmm, and CW-q5fy.
"""

from __future__ import annotations

import fcntl
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from . import decisions, index, skills, spec_index, tasks
from .common import SESSION_ID, UNATTENDED_RUN, Clock, Entry, StepError, utc_now
from .config import (COMMIT, DEFAULT_CHECKS, PRE_COMMIT_FUNCTIONAL, TREE, Configuration, fill,
                     placeholders, require)
from .evidence import worktree_tree
from .find import ChangeNotFound, change_directory, is_archived
from .graph import HOOK_STEPS, STEPS
from .records import git_head, inert
from .running import git_state, invocations_directory, keep_invocations

# The hooks `run` runs by name.
NAMED = ("after-functional-change", "pre-commit", "pre-commit-functional", "pre-archive")
# The hooks whose commands may name the worktree's tree and `HEAD`'s commit.
FUNCTIONAL_HOOKS = ("after-functional-change", "pre-commit-functional")
# Every kind's cleanup, `run cleanup <change>`.
CLEANUP = "cleanup"
TEST_BEFORE = "test-before"
# The prefix of every line the engine writes about a hook, so a reader tells it from
# the commands' own output.
PREFIX = "[change-workflow]"
# Where a checkout keeps each change's started kinds' markers, under its Git
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
    """The environment a hook's or a kind's command runs in: the caller's, without
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
        if check == "spec-index":
            return spec_index.main([change], root=root)
        if check == "decisions":
            return decisions.main([change], root=root)
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
    kind: str | None = None
    owed: str | None = None
    phase: str | None = None
    check: str | None = None
    skipped: str | None = None
    # Why a waived kind was gathered: its waiver lapsed.
    lapsed: str | None = None

    def entry(self) -> Entry:
        found: Entry = {"hook": self.hook}
        for key in ("kind", "owed", "phase", "lapsed", "check", "command", "exit_status",
                    "skipped"):
            if (value := getattr(self, key)) is not None:
                found[key] = value
        return {**found, "started": self.started, "seconds": round(self.seconds, 3)}

    @property
    def failed(self) -> bool:
        return self.exit_status not in (None, 0)

    @property
    def shown(self) -> str:
        return self.command or f"the {self.check} check"


def result(invoked: Sequence[Invoked]) -> str:
    """What `invoked` came to: `passed, exit 0`, or `failed, exit <n>:` and each failed
    command with its exit status, `<n>` the first's; nothing run but skipped,
    `skipped, <why>`."""
    failed = [i for i in invoked if i.failed]
    if invoked and all(i.skipped for i in invoked):
        return f"skipped, {invoked[0].skipped}"
    if not failed:
        return "passed, exit 0"
    return f"failed, exit {failed[0].exit_status}: " + "; ".join(
        f"{i.shown} (exit {i.exit_status})" for i in failed)


def closing_line(name: str, invoked: Sequence[Invoked], commit: str | None) -> str:
    """The line the engine ends a hook with, whatever its commands printed:
    `<prefix> <name> at <commit>: <result>`."""
    return f"{PREFIX} {name} at {commit or 'no commit'}: {result(invoked)}"


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
    # The tree of the worktree as it stands, which a functional hook checks.
    tree: Callable[[Path], str] = worktree_tree
    echo: Callable[[str], None] = lambda shown: print(shown, flush=True)
    capture: Capture = capture
    # Where the change's started kinds' markers are kept, and where a session's
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

    def identities(self, commands: Sequence[str]) -> dict[str, str]:
        """The worktree's tree and `HEAD`'s commit, each only where one of `commands`
        names it, since the tree is written through Git as the worktree stands now."""
        named = {name for command in commands for name in placeholders(command)}
        found: dict[str, str] = {}
        if TREE in named:
            found[TREE] = self.tree(self.root)
        if COMMIT in named and (commit := self.head(self.root)) is not None:
            found[COMMIT] = commit
        return found

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
        other its commands, or skipped, saying so, when it is not declared. A
        functional hook's `{tree}` is the worktree's as the hook starts, after any
        hook before it changed it, so it names the tree the hook checks."""
        commands = self.configuration.hook(name)
        values = self.values(change, base)
        if commands is not None:
            if name in FUNCTIONAL_HOOKS:
                values.update(self.identities(commands))
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
                      if not inert(path, self.configuration.repository_inert_paths())]
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
                # The identities are read as each hook starts; here only that a
                # functional hook may name them.
                given = dict.fromkeys((TREE, COMMIT), "") if name in FUNCTIONAL_HOOKS else {}
                self.needs(commands, self.values(change, base, **given), f"hooks.{name}")
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

    def test_before(self, change: str, base: str | None, commit: str | None,
                    tests: Sequence[str]) -> bool:
        """`run test-before <change> --test <path>…`: each test file as `HEAD` holds
        it, run against the code at `commit`, in a detached worktree of its own that
        is removed however the run ends, so the change's worktree is never touched.
        A test that fails there and passes at `HEAD` shows the change made it pass.
        It passes when every test ran, whatever the tests found: what each found is
        its own line."""
        self.allow(TEST_BEFORE)
        commands = self.configuration.hook(TEST_BEFORE)
        if not commands:
            raise HookError("hooks.test-before is not declared, so no test can be run "
                            "against an earlier commit")
        if not commit:
            raise HookError("test-before runs against a commit: give it with --at <commit>; "
                            "with no round recorded there is no round base to default to")
        if not tests:
            raise HookError("test-before names the test files it runs, with --test <path>")
        for test in tests:
            if not (self.root / test).is_file() or Path(test).is_absolute() \
                    or ".." in Path(test).parts:
                raise HookError(f"{test} is no file of this checkout")
        values = self.values(change, base, test=tests[0])
        self.needs(commands, values, f"hooks.{TEST_BEFORE}")
        scratch = Path(tempfile.mkdtemp(prefix="change-workflow-test-before-"))
        tree = scratch / "tree"
        added = subprocess.run(["git", "-C", str(self.root), "worktree", "add", "--detach",
                                "--quiet", str(tree), commit], capture_output=True, text=True)
        try:
            if added.returncode != 0:
                raise HookError(f"no worktree at {commit}: {added.stderr.strip()}")
            for test in tests:
                (tree / test).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(self.root / test, tree / test)
            for test in tests:
                filled = {**values, "test": test}
                ran = [self._timed(lambda command=fill(c, filled): self.shell(command, tree),
                                   hook=TEST_BEFORE, command=fill(c, filled))
                       for c in commands]
                self.echo(closing_line(f"{TEST_BEFORE} {test}", ran, commit))
        finally:
            subprocess.run(["git", "-C", str(self.root), "worktree", "remove", "--force",
                            str(tree)], capture_output=True)
            shutil.rmtree(scratch, ignore_errors=True)
        return True

    def start(self, hook: str, commands: Sequence[str], values: Mapping[str, str],
              labels: Mapping[str, str | None]) -> tuple[list[Invoked], str | None]:
        """Run a `start`'s commands, and return them and the last line its last
        command printed: the marker its `collect` waits past."""
        ran, marker = [], None
        for command in commands:
            resolved = fill(command, values)
            self.echo(f"+ {resolved}")
            printed: list[str | None] = []

            def call(resolved: str = resolved) -> int:
                status, last = self.capture(resolved, self.root)
                printed.append(last)
                return status

            ran.append(self._timed(call, hook=hook, command=resolved, **labels))
            marker = printed[0]
        return ran, marker

    def _markers_file(self, change: str) -> Path:
        directory = self.markers(self.root)
        if directory is None:
            raise HookError(f"{self.root} is no Git checkout, so no start's marker can be kept")
        return directory / f"{change}.json"

    def kept_marker(self, change: str, key: str) -> str | None:
        """The marker kept for `key`, or None."""
        return self._kept(change).get(key)

    def _kept(self, change: str) -> dict[str, str]:
        path = self._markers_file(change)
        try:
            with path.open("r", encoding="utf-8") as kept:
                fcntl.flock(kept, fcntl.LOCK_SH)
                return json.loads(kept.read() or "{}")
        except FileNotFoundError:
            return {}

    def keep_marker(self, change: str, key: str, marker: str | None) -> None:
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
        """`run cleanup <change>`: every kind's cleanup, in declaration order, as one
        list, each command run whatever an earlier one reported; `{tree}` and
        `{commit}` are the checkout's as the cleanup starts."""
        self.allow(CLEANUP)
        kinds = [kind for kind in self.configuration.kinds or () if kind.cleanup]
        values = self.values(change, base, **self.identities(
            [command for kind in kinds for command in kind.cleanup or ()]))
        for kind in kinds:
            self.needs(kind.cleanup or (), values, f"validation.evidence.{kind.name}.cleanup")
        if not kinds:
            return self.finish(CLEANUP, self.skip(CLEANUP, "no kind declares a cleanup"))
        ran = [invoked for kind in kinds
               for invoked in self.run_commands(CLEANUP, kind.cleanup or (), values,
                                                kind=kind.name, phase=CLEANUP)]
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


def marker_key(identity: str, kind: str, owed: str | None) -> str:
    """A start's marker is kept for the tree or commit its kind's evidence describes,
    the kind, and an owed kind's argument, so owed runs started side by side never
    share one and a later start of the same key replaces it."""
    return " ".join([identity, kind, *([owed] if owed else [])])


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
         commit: str | None = None, tests: Sequence[str] = (),
         hooks: Hooks | None = None) -> int:
    """`run <hook> <change>`, `run cleanup <change>`, or `run test-before <change>`:
    0 when it passed, 1 when it failed or was refused, its reason on standard error.
    What ran is kept for the session's line, however it ended."""
    runner = hooks or Hooks(root, configuration, environ)
    try:
        change_directory(root, change)
        if hook == CLEANUP:
            passed = runner.cleanup(change, base)
        elif hook == TEST_BEFORE:
            passed = runner.test_before(change, base, commit, tests)
        else:
            passed = runner.named(hook, change, base, lambda: worktree_changes(root))
    except (ChangeNotFound, StepError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        runner.keep(change)
    return 0 if passed else 1
