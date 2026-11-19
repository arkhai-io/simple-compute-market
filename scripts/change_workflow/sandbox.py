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

Over each of the system's two Git executables, the one on `PATH` and the one in
Git's exec path, the sandbox mounts the engine's `git` (`sandbox_git`), which
refuses every push of the run but the guarded push's, and mounts the system's Git
where only the engine's names it (CW-j4cs). The engine's `git` is mounted as a short
shell program running that module with the Python that runs the engine, from the
engine's own directory, which a program mounted at `/usr/bin/git` could not find by
its own path. Bubblewrap copies the program in from a descriptor as the sandbox
starts and gives the copy its mode, so it needs no executable file on disk; the module
it runs is read from the engine's directory as each command runs. The process started
from a `Launch` inherits its descriptors (`fds`), which the launcher may close once
that process has started.

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
sandbox guards against a step's mistakes and never stops the workflow (CW-v5ny).
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

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
    it; and the descriptors the command reads as it starts, which the process started
    from it inherits (`pass_fds`), and which leaving the `with` block closes, any time
    once that process has started."""

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


def mounted_protected(scope: Scope) -> list[ScopedPath]:
    """The scope's protected paths that lie inside one of its writable paths, which the
    sandbox mounts read-only."""
    return [guarded for guarded in scope.protected
            if any(within(guarded.path, writable.path) for writable in scope.writable)]


def arguments(scope: Scope, program: Sequence[str], *, git: Sequence[int]) -> list[str]:
    """`program` inside the scope's sandbox, as a `bwrap` command: the read-only root,
    then each writable path, a directory before any path inside it, so no mount hides
    another; then each protected path inside them, read-only; then the system's Git
    where the engine's `git` finds it, and the engine's `git`, read from the
    descriptors `git`, one for each of the system's Git executables, over each.

    Bubblewrap reads a mount's source from outside the sandbox, so the system's Git
    is the one it mounts at `REAL_GIT` whatever is mounted over it after."""
    command = [BWRAP, *_BASE]
    for path in sorted(scope.writable, key=_depth):
        command += ["--bind", str(path.path), str(path.path)]
    for path in sorted(mounted_protected(scope), key=_depth):
        command += ["--ro-bind", str(path.path), str(path.path)]
    command += ["--ro-bind", GIT_EXECUTABLES[0], str(REAL_GIT)]
    for fd, executable in zip(git, GIT_EXECUTABLES, strict=True):
        command += ["--perms", "0755", "--ro-bind-data", str(fd), executable]
    return [*command, *_TAIL, *program]


def _readable(data: bytes) -> int:
    """A descriptor reading `data` from its start, in memory."""
    fd = os.memfd_create("change-workflow-git")
    os.write(fd, data)
    os.lseek(fd, 0, os.SEEK_SET)
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
    path it mounts in its empty form."""
    for path in scope.writable:
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
           probing: Callable[[], str | None] = probe) -> Launch:
    """The command that runs `program` in the scope's sandbox, its mounts created and
    the engine's `git` open for it to read; or, where the probe finds the sandbox
    cannot run, `program` itself, unconfined, with the probe's reason."""
    if (reason := probing()) is not None:
        return Launch(tuple(program), unconfined=reason)
    prepare(scope)
    program_text = git_program()
    # One descriptor for each mount: bubblewrap reads each to its end.
    fds = tuple(_readable(program_text) for _ in GIT_EXECUTABLES)
    return Launch(tuple(arguments(scope, program, git=fds)), fds=fds)
