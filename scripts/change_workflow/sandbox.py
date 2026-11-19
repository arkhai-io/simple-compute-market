"""The engine's sandbox: a step's scope rendered as a bubblewrap command around any
program, so the harness's file tools, its shell, and every process they start are
confined alike (CW-x3pf).

The root filesystem is mounted read-only; `/dev` and `/proc` are the sandbox's own;
each writable path of the scope is bound read-write over the root; and each protected
path that lies inside a writable one is bound read-only over that, so writing it fails
however wide the directory holding it (CW-r6kd). A protected path outside
every writable path is read-only already, under the root, so it needs no mount of
its own. Writing to a protected file fails as a read-only file system, and replacing
it by renaming another file over it fails busy, since the target is a mount point: so
`git config`, which writes a lock file and renames it over `.git/config`, cannot
rewire Git's hooks. The network and the environment are shared, and reads
are open everywhere: the sandbox bounds what a step writes, not what it sees. A Unix
socket on a read-only mount stays connectable, so Docker needs no mount of its own.
The sandbox has its own process namespace and dies with the process that launched it
(`--unshare-pid`, `--die-with-parent`): when the launcher ends, bubblewrap is killed,
and with it, as the namespace's first process, every process the session started,
a command it left running in the background included.

Bubblewrap cannot mount over a symlink: it fails to start at one whose target it
cannot reach from inside the sandbox it is building, as an absolute target is. So
each writable and protected path is mounted where its symlinks lead, and a write
through the link reaches the mount. A protected settings file that a clone links to
the owner's workspace, outside the clone's scope, is then read-only under the root
and needs no mount. The link itself is no mount: inside a writable directory, a step
can remove it or rename a file over it, and the file it leaves there is not
protected.

Over each of the system's two Git executables, the one on `PATH` and the one in
Git's exec path, the sandbox mounts the engine's `git` (`sandbox_git`), which
refuses every push of the run but the guarded push's, and mounts the system's Git
where only the engine's names it (CW-j4cs). The engine's `git` is mounted as a short
shell program running that module with the Python that runs the engine, from the
engine's own directory, which a program mounted at `/usr/bin/git` could not find by
its own path. Bubblewrap copies the program in from a descriptor as the sandbox
starts and gives the copy its mode, so it needs no executable file on disk; the module
it runs is read from the engine's directory as each command runs. The process started
from a `Launch` inherits its descriptors (`fds`), which are inheritable, so a runner
that keeps its descriptors open across the start, as each adapter's does, passes them
on, and which the launcher may close once that process has started.

A sandbox started inside the engine's sandbox, as a step's suite starts one, finds
an engine's `git` already over the system's two, mounted from a file bubblewrap
removed once it was mounted, so no mount over it can be made. There the sandbox keeps
the `git` it finds, which refuses pushes alike, and mounts the system's Git at
`REAL_GIT` again from where the enclosing sandbox put it.

A mount needs something to mount, so before launch each absent writable path is
created as a directory, and each absent file an adapter's state mounts alone, and
each absent protected path inside a writable one, as the empty form of what its
harness loads: `{}` for a JSON file, an empty file otherwise,
and a directory where its entry ends in `/`. A protected path created so is mounted
like any other, so it cannot be created during the run either, and stays afterwards.

Before a launch the sandbox is probed: a trivial program run in the namespaces and
under the base mounts every sandbox starts from, though not a scope's own. Where it
cannot run — `bwrap` is not installed, or the kernel refuses it the user namespaces it
needs — `launch` gives the program itself, unconfined, with the probe's reason: the
sandbox guards against a step's mistakes and never stops the workflow (CW-v5ny). A
program that is not installed fails inside the sandbox as bubblewrap's own error
(`missing`), not as the launch's.

`Confinement` holds the three a runner of steps uses — the probe, the creation of a
scope's mounts, and the launch — so a test may stand in for the sandbox.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .sandbox_git import REAL_GIT
from .scope import GIT_EXECUTABLES, Scope, ScopedPath, within

BWRAP = "bwrap"
# The namespaces and mounts every sandbox starts from, the probe's included.
_BASE = ("--unshare-pid", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc")
_TAIL = ("--die-with-parent", "--")
# What the probe runs: a program that does nothing, present on every system.
_PROBE_PROGRAM = ("true",)
# The directory holding the engine's package, from which its `git` imports it.
_ENGINE = Path(__file__).resolve().parent.parent
# What the engine's `git` runs: its module, imported from the engine's directory,
# which the program passes first, then the name it was run by and Git's arguments.
# `-I` keeps the environment's Python settings and the working directory out of what
# is imported.
_GIT_ENTRY = ("import sys; sys.path.insert(0, sys.argv.pop(1)); "
              "from change_workflow.sandbox_git import main; "
              "sys.exit(main(sys.argv[2:], sys.argv[1]))")

Run = Callable[..., subprocess.CompletedProcess]


@dataclass(frozen=True)
class Launch:
    """The command a run launches; why it is unconfined, None when the sandbox confines
    it; and the descriptors the command reads as it starts, inheritable, which the
    process started from it keeps when its runner leaves descriptors open, or names
    in `pass_fds`, and which leaving the `with` block closes, any time once that
    process has started."""

    command: tuple[str, ...]
    unconfined: str | None = None
    fds: tuple[int, ...] = ()

    def close(self) -> None:
        for fd in self.fds:
            os.close(fd)

    def __enter__(self) -> Launch:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


def git_program(python: str = sys.executable, engine: Path = _ENGINE) -> bytes:
    """The engine's `git` as the sandbox mounts it: a shell program running the
    engine's `git` module with `python`, from `engine`, the directory holding the
    package, given the name the program was run by and Git's command line."""
    return (f"#!/bin/sh\nexec {shlex.quote(python)} -I -c {shlex.quote(_GIT_ENTRY)} "
            f"{shlex.quote(str(engine))} \"$0\" \"$@\"\n").encode()


def _depth(path: ScopedPath) -> tuple[int, str]:
    return len(path.path.parts), str(path.path)


def _followed(path: ScopedPath) -> ScopedPath:
    """`path` where a mount of it lands: every symlink on it followed, as far as the
    paths it leads to exist."""
    real = path.path.resolve()
    return path if real == path.path else replace(path, path=real)


def mounted_writable(scope: Scope) -> list[ScopedPath]:
    """The scope's writable paths as the sandbox mounts them, each where its symlinks
    lead."""
    return [_followed(writable) for writable in scope.writable]


def mounted_protected(scope: Scope) -> list[ScopedPath]:
    """The scope's protected paths, each where its symlinks lead, that lie inside one
    of its writable paths, which the sandbox mounts read-only."""
    writable = mounted_writable(scope)
    mounted: dict[Path, ScopedPath] = {}
    for guarded in map(_followed, scope.protected):
        if any(within(guarded.path, open_.path) for open_ in writable):
            mounted.setdefault(guarded.path, guarded)
    return list(mounted.values())


def arguments(scope: Scope, program: Sequence[str], *, git: Sequence[int]) -> list[str]:
    """`program` inside the scope's sandbox, as a `bwrap` command: the read-only root,
    then each writable path, a directory before any path inside it, so no mount hides
    another; then each protected path inside them, read-only; then the system's Git
    where the engine's `git` finds it, and the engine's `git`, read from the
    descriptors `git`, one for each of the system's Git executables, over each. With
    no descriptors, inside the engine's sandbox (`nested`), the engine's `git` already
    over them is kept, and the system's Git is mounted from `REAL_GIT`.

    Bubblewrap reads a mount's source from outside the sandbox, so the system's Git
    is the one it mounts at `REAL_GIT` whatever is mounted over it after."""
    command = [BWRAP, *_BASE]
    for path in sorted(mounted_writable(scope), key=_depth):
        command += ["--bind", str(path.path), str(path.path)]
    for path in sorted(mounted_protected(scope), key=_depth):
        command += ["--ro-bind", str(path.path), str(path.path)]
    command += ["--ro-bind", GIT_EXECUTABLES[0] if git else str(REAL_GIT), str(REAL_GIT)]
    for fd, executable in zip(git, GIT_EXECUTABLES if git else (), strict=True):
        command += ["--perms", "0755", "--ro-bind-data", str(fd), executable]
    return [*command, *_TAIL, *program]


def nested() -> bool:
    """Whether this process runs inside the engine's sandbox, where the system's Git
    sits at `REAL_GIT`, a path only the sandbox makes."""
    return REAL_GIT.exists()


def _readable(data: bytes) -> int:
    """An inheritable descriptor reading `data` from its start, in memory."""
    fd = os.memfd_create("change-workflow-git")
    os.write(fd, data)
    os.lseek(fd, 0, os.SEEK_SET)
    os.set_inheritable(fd, True)
    return fd


def _empty_form(path: ScopedPath) -> None:
    """Create an absent file the sandbox mounts on its own as the empty form its
    harness loads."""
    if path.entry.endswith("/"):
        path.path.mkdir(parents=True, exist_ok=True)
        return
    path.path.parent.mkdir(parents=True, exist_ok=True)
    path.path.write_text("{}" if path.path.suffix == ".json" else "", "utf-8")


def prepare(scope: Scope) -> None:
    """Create what the sandbox mounts and does not exist: each absent writable path as
    a directory, or, a file mounted alone, in its empty form; and each absent protected
    path it mounts in its empty form, each where its symlinks lead."""
    for path in mounted_writable(scope):
        if path.path.exists():
            continue
        if path.alone:
            _empty_form(path)
        else:
            path.path.mkdir(parents=True, exist_ok=True)
    for path in mounted_protected(scope):
        if not path.path.exists():
            _empty_form(path)


def probe(run: Run = subprocess.run) -> str | None:
    """Why the sandbox cannot run on this machine, or None when it can: a trivial
    program run under the mounts every sandbox starts from."""
    try:
        found = run([BWRAP, *_BASE, *_TAIL, *_PROBE_PROGRAM], capture_output=True, text=True)
    except FileNotFoundError:
        return f"{BWRAP} is not installed"
    except OSError as exc:
        return f"{BWRAP} cannot be run: {exc}"
    if found.returncode != 0:
        detail = (found.stderr or "").strip() or f"exit {found.returncode}"
        return f"{BWRAP} cannot run here: {detail}"
    return None


def launch(scope: Scope, program: Sequence[str], *,
           probing: Callable[[], str | None] = probe,
           inside: Callable[[], bool] = nested) -> Launch:
    """The command that runs `program` in the scope's sandbox, its mounts created and
    the engine's `git` open for it to read, unless `inside` finds the engine's sandbox
    around this process; or, where the probe finds the sandbox cannot run, `program`
    itself, unconfined, with the probe's reason."""
    if (reason := probing()) is not None:
        return Launch(tuple(program), unconfined=reason)
    prepare(scope)
    program_text = git_program()
    # One descriptor for each mount: bubblewrap reads each to its end.
    fds = () if inside() else tuple(_readable(program_text) for _ in GIT_EXECUTABLES)
    return Launch(tuple(arguments(scope, program, git=fds)), fds=fds)


def missing(said: str, program: Sequence[str]) -> bool:
    """Whether `said`, a confined run's output, holds bubblewrap's own line saying it
    could not start `program`, which is not installed. Only a line bubblewrap begins
    counts: the rest of a run's output may quote such a line from a file it read."""
    failed = f"{BWRAP}: execvp {program[0]}: No such file or directory"
    return any(line.strip() == failed for line in said.splitlines())


@dataclass(frozen=True)
class Confinement:
    """The sandbox a runner of steps confines each run in: why it cannot run, or None
    (`probe`); the creation of what a scope mounts, before the state a session starts
    from is recorded (`prepare`); and the command a run launches (`launch`)."""

    probe: Callable[[], str | None] = probe
    prepare: Callable[[Scope], None] = prepare
    launch: Callable[..., Launch] = launch


BUBBLEWRAP = Confinement()


@dataclass(frozen=True)
class Confined:
    """How one run is confined: why the sandbox cannot run, None when it confines the
    run; and the run's scope for each harness its models name."""

    unconfined: str | None
    scopes: Mapping[str, Scope]

    def launch(self, confinement: Confinement, harness: str,
               program: Sequence[str]) -> Launch:
        """The command that runs `program`, on `harness`, as this run is confined."""
        return confinement.launch(self.scopes[harness], program,
                                  probing=lambda: self.unconfined)

    def prepare(self, confinement: Confinement) -> None:
        """Create what each of the run's scopes mounts and does not exist, unless the
        run is unconfined, when nothing is mounted."""
        if self.unconfined is None:
            for found in self.scopes.values():
                confinement.prepare(found)


def confine(confinement: Confinement, harnesses: Sequence[str],
            resolve: Callable[[str], Scope], step: str) -> Confined:
    """How a run of `step` on models of `harnesses` is confined: its scope resolved
    for each harness by `resolve`, which refuses a grant the scope cannot hold, before
    anything launches, whether or not the sandbox can run; then the sandbox probed
    once, and, where it cannot run, the run unconfined, said as a warning."""
    scopes = {harness: resolve(harness) for harness in dict.fromkeys(harnesses)}
    if (reason := confinement.probe()) is not None:
        print(f"WARNING: the sandbox cannot run, so this {step} run is unconfined: {reason}",
              file=sys.stderr)
    return Confined(reason, scopes)
