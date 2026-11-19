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
rewire Git's hooks. A caller may add read-only file mounts of its own, each a source
and the path it is mounted at. The network and the environment are shared, and reads
are open everywhere: the sandbox bounds what a step writes, not what it sees. A Unix
socket on a read-only mount stays connectable, so Docker needs no mount of its own.
The sandbox has its own process namespace and dies with the process that launched it
(`--unshare-pid`, `--die-with-parent`): when the launcher ends, bubblewrap is killed,
and with it, as the namespace's first process, every process the session started,
a command it left running in the background included.

A mount needs something to mount, so before launch each absent writable path is
created as a directory, and each absent protected path inside a writable one as the
empty form of what its harness loads: `{}` for a JSON file, an empty file otherwise,
and a directory where its entry ends in `/`. A protected path created so is mounted
like any other, so it cannot be created during the run either, and stays afterwards.

Before a launch the sandbox is probed: a trivial program run in the namespaces and
under the base mounts every sandbox starts from, though not a scope's own. Where it
cannot run — `bwrap` is not installed, or the kernel refuses it the user namespaces it
needs — `launch` gives the program itself, unconfined, with the probe's reason: the
sandbox guards against a step's mistakes and never stops the workflow (CW-v5ny).
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from .scope import Scope, ScopedPath, within

BWRAP = "bwrap"
# The namespaces and mounts every sandbox starts from, the probe's included.
_BASE = ("--unshare-pid", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc")
_TAIL = ("--die-with-parent", "--")
# What the probe runs: a program that does nothing, present on every system.
_PROBE_PROGRAM = ("true",)

Run = Callable[..., subprocess.CompletedProcess]


@dataclass(frozen=True)
class Launch:
    """The command a run launches, and why it is unconfined, None when the sandbox
    confines it."""

    command: tuple[str, ...]
    unconfined: str | None = None


def _depth(path: ScopedPath) -> tuple[int, str]:
    return len(path.path.parts), str(path.path)


def mounted_protected(scope: Scope) -> list[ScopedPath]:
    """The scope's protected paths that lie inside one of its writable paths, which the
    sandbox mounts read-only."""
    return [guarded for guarded in scope.protected
            if any(within(guarded.path, writable.path) for writable in scope.writable)]


def arguments(scope: Scope, program: Sequence[str],
              binds: Sequence[tuple[Path, Path]] = ()) -> list[str]:
    """`program` inside the scope's sandbox, as a `bwrap` command: the read-only root,
    then each writable path, a directory before any path inside it, so no mount hides
    another; then each protected path inside them, read-only; then the caller's
    read-only `binds`, each a source and where it is mounted."""
    command = [BWRAP, *_BASE]
    for path in sorted(scope.writable, key=_depth):
        command += ["--bind", str(path.path), str(path.path)]
    for path in sorted(mounted_protected(scope), key=_depth):
        command += ["--ro-bind", str(path.path), str(path.path)]
    for source, destination in binds:
        command += ["--ro-bind", str(source), str(destination)]
    return [*command, *_TAIL, *program]


def _empty_form(path: ScopedPath) -> None:
    """Create an absent protected path as the empty form its harness loads."""
    if path.entry.endswith("/"):
        path.path.mkdir(parents=True, exist_ok=True)
        return
    path.path.parent.mkdir(parents=True, exist_ok=True)
    path.path.write_text("{}" if path.path.suffix == ".json" else "", "utf-8")


def prepare(scope: Scope) -> None:
    """Create what the sandbox mounts and does not exist: each absent writable path as
    a directory, and each absent protected path it mounts in its empty form."""
    for path in scope.writable:
        if not path.path.exists():
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


def launch(scope: Scope, program: Sequence[str], *, binds: Sequence[tuple[Path, Path]] = (),
           probing: Callable[[], str | None] = probe) -> Launch:
    """The command that runs `program` in the scope's sandbox, its mounts created; or,
    where the probe finds the sandbox cannot run, `program` itself, unconfined, with
    the probe's reason."""
    if (reason := probing()) is not None:
        return Launch(tuple(program), unconfined=reason)
    prepare(scope)
    return Launch(tuple(arguments(scope, program, binds)))
