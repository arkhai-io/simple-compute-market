"""A step's scope for one run: the paths its sandbox lets it write, and the paths it
keeps read-only inside them, each named by the source it came from.

A step writes only its scope (CW-m8wq). The scope of one run is resolved as the run
starts, from four sources:

- the engine: the step's baseline (`graph.STEP_DEFINITIONS`), design's holding each
  prerequisite's proposal worktree registered in its checkout (CW-k8dn), and the
  paths protected
  in every scope (`PROTECTED`) — the workflow's configuration, so no step changes
  what its own hooks run; Git's configuration, which says where Git finds its hooks;
  and the system's two Git executables, so no step replaces the Git its pushes go
  through (CW-r6kd, CW-j4cs);
- the adapter of the harness that runs the step: the state its harness writes and the
  settings files it loads, which the caller passes in (`adapters`);
- the repository: its configuration's `[sandbox]`, `writable.common` for every step
  but the review, `writable.<step>` for one, and `protected` (CW-h2zt);
- a grant: a path the owner gives one run (CW-tl5v).

An entry is a path from the checkout's root, a path from the home directory where it
begins with `~`, or an absolute path. An entry under `.git/` names a path in the
checkout's Git directory as Git resolves it, so a linked worktree's Git directory, and
the common directory its commits write, resolve as a clone's do. A relative entry
holding a glob character is a pattern, matched against the checkout's files as Git
lists them, tracked or untracked but not ignored, as an inert path is matched
(`records.inert`): a file inside an environment Git ignores is no match.

Every step writes a private `/tmp` of its own (`PRIVATE_TEMPORARY`), which the sandbox
makes fresh for the run, owned by the owner and open to no one else, in place of the
host's: the baseline's temporary entry names it, and resolves to no host path. A path
under the host's `/tmp` that the scope writes besides — a grant, the review's drafts
directory — is mounted at its own path inside it, so it names the same file on both
sides. `/tmp` itself, or a directory holding it, is refused as a writable entry or a
grant (`hides_temporary`): mounting the host's there would hide the private one.

A scope is made of directories, never a single writable file: a tool replaces a file
by writing another and renaming it over the first, which a file bound on its own
refuses. So a file entry, and each file a pattern matches, makes its directory
writable. A writable path absent as the run starts is marked to be created as a
directory before launch, since a mount needs something to mount. The one exception
is a state file an adapter names, which is mounted alone, since its directory is the
home directory, which no step writes whole: it can be written in place, though not
replaced by rename. A protected path
stays read-only inside any writable directory that contains it, so a path is refused
only where it is, or lies under, a protected one; the configuration's check and a
grant's both ask `protected_by`, so the two cannot disagree.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable, Sequence

from .common import StepError
from .graph import INERT_PATHS, PROPOSAL_SUFFIX, PROPOSALS, STEP_DEFINITIONS, TEMPORARY
from .records import inert, is_pattern

# Where each path of a scope came from.
ENGINE, ADAPTER, REPOSITORY, GRANT = "engine", "adapter", "repository", "grant"
# Where the sandbox mounts the engine's own `git`: the executable on `PATH`, and the one
# in Git's exec path, which Git puts first on `PATH` for its scripted commands.
GIT_EXECUTABLES = ("/usr/bin/git", "/usr/lib/git-core/git")
# The paths no step writes, whatever its scope.
PROTECTED = (".agents/workflow.toml", ".git/config", *GIT_EXECUTABLES)
# Where every step's private temporary directory sits inside its sandbox.
PRIVATE_TEMPORARY = Path("/tmp")
_GIT = ".git"


class ScopeError(StepError):
    """A grant a scope cannot hold: a pattern, `/tmp` or a directory holding it, or a
    protected path."""


@dataclass(frozen=True)
class ScopedPath:
    """One path of a scope, absolute, with its source and the entry it resolved from;
    `create` when it is absent, to be created before launch, as a directory unless it
    is a file mounted `alone`; `private` for the step's own `/tmp`, which the sandbox
    makes rather than mounts from the host."""

    path: Path
    source: str
    entry: str
    create: bool = False
    alone: bool = False
    private: bool = False

    def shown(self) -> dict[str, Any]:
        return {"path": str(self.path), "source": self.source, "entry": self.entry,
                **({"absent": True} if self.create else {}),
                **({"file": True} if self.alone else {}),
                **({"private": True} if self.private else {})}


@dataclass(frozen=True)
class Scope:
    """A step's scope for one run: what it writes, and what stays read-only inside."""

    step: str
    writable: tuple[ScopedPath, ...]
    protected: tuple[ScopedPath, ...]

    def shown(self) -> dict[str, Any]:
        return {"writable": [path.shown() for path in self.writable],
                "protected": [path.shown() for path in self.protected]}

    def writing(self, path: Path, source: str) -> Scope:
        """This scope with `path`, an existing directory, writable too, from `source`."""
        return replace(self, writable=_unique((*self.writable,
                                               ScopedPath(path, source, str(path)))))


def _home_relative(entry: str) -> bool:
    return entry == "~" or entry.startswith("~/")


def absolute(entry: str, root: Path, home: Path) -> Path:
    """`entry` as an absolute path, read lexically: from `home` where it begins with
    `~`, as it is where it is absolute, and from `root` otherwise."""
    if _home_relative(entry):
        path = home / entry[2:]
    elif entry.startswith("/"):
        path = Path(entry)
    else:
        path = root / entry
    return Path(os.path.normpath(path))


def within(path: Path, ancestor: Path) -> bool:
    """Whether `path` is `ancestor` or lies under it."""
    return path == ancestor or ancestor in path.parents


def fixed_part(entry: str) -> str:
    """An entry's leading segments holding no glob character: the entry itself where it
    is no pattern, and empty, the checkout's root, where its first segment is one."""
    if not is_pattern(entry):
        return entry
    fixed: list[str] = []
    for segment in entry.split("/"):
        if is_pattern(segment):
            break
        fixed.append(segment)
    return "/".join(fixed)


def hides_temporary(entry: str, root: Path, home: Path) -> bool:
    """Whether `entry`, as a writable path, would mount the host's `/tmp` over the
    step's private one: it is `/tmp` or a directory holding it, as it is written or
    where its links lead."""
    path = absolute(entry, root, home)
    return any(within(PRIVATE_TEMPORARY, found) for found in (path, path.resolve()))


def grant_paths(values: Sequence[str]) -> list[tuple[str, str]]:
    """Each path a run's grants name, with the value that named it: each value split on
    `;`, each part trimmed, and empty parts dropped."""
    return [(value, part.strip()) for value in values for part in value.split(";")
            if part.strip()]


class _Checkout:
    """The checkout a scope is resolved in: its root, the home directory, and what Git
    says of it, asked once each."""

    def __init__(self, root: Path, home: Path) -> None:
        self.root, self.home = root, home
        self._files: list[str] | None = None
        self._paths: dict[str, list[Path]] = {}

    def _git(self, *args: str) -> str | None:
        """What Git prints; None where it fails, as outside a Git checkout."""
        try:
            found = subprocess.run(["git", *args], cwd=self.root, capture_output=True,
                                   text=True)
        except OSError as exc:
            raise ScopeError(f"cannot run git to resolve a step's scope: {exc}") from exc
        return found.stdout if found.returncode == 0 else None

    def paths(self, entry: str) -> list[Path]:
        """The absolute paths an entry that is no pattern names. Outside a Git checkout
        an entry under `.git/` is read as any other path from the root."""
        if entry not in self._paths:
            self._paths[entry] = self._resolved(entry)
        return self._paths[entry]

    def protecting(self, entry: str, protected: Iterable[str]) -> str | None:
        """The first of the `protected` entries that `entry` is or lies under, or None.
        A pattern is judged by its fixed part, the directory its matches lie under."""
        paths = self.paths(fixed_part(entry))
        return next((guarded for guarded in protected
                     if any(within(path, ancestor) for path in paths
                            for ancestor in self.paths(guarded))), None)

    def _resolved(self, entry: str) -> list[Path]:
        parts = Path(entry).parts
        if _home_relative(entry) or entry.startswith("/") or not parts or parts[0] != _GIT:
            return [absolute(entry, self.root, self.home)]
        rest = "/".join(parts[1:])
        if rest:
            found = self._git("rev-parse", "--git-path", rest)
            named = [found.strip()] if found else []
        else:
            # The Git directory itself: the checkout's own, and the common directory a
            # linked worktree's commits write their objects and references to.
            found = self._git("rev-parse", "--absolute-git-dir", "--git-common-dir")
            named = found.split() if found else []
        if not named:
            return [absolute(entry, self.root, self.home)]
        return list(dict.fromkeys(Path(os.path.normpath(self.root / path)) for path in named))

    def proposals(self) -> list[Path]:
        """Each worktree registered in the checkout whose directory sits beside it,
        named `<prerequisite>-proposal`; none outside a Git checkout."""
        found = self._git("worktree", "list", "--porcelain") or ""
        paths = [Path(line.removeprefix("worktree ")) for line in found.splitlines()
                 if line.startswith("worktree ")]
        root = Path(os.path.normpath(self.root))
        return [path for path in paths
                if path != root and path.parent == root.parent
                and path.name.endswith(PROPOSAL_SUFFIX) and path.name != PROPOSAL_SUFFIX]

    def files(self) -> list[str]:
        """The checkout's files as Git lists them, tracked or untracked but not ignored,
        from its root; none outside a Git checkout."""
        if self._files is None:
            found = self._git("ls-files", "-z", "--cached", "--others", "--exclude-standard")
            self._files = [path for path in (found or "").split("\0") if path]
        return self._files

    def writable(self, entry: str, source: str) -> list[ScopedPath]:
        """The directories a writable entry mounts: a directory as it is, created when
        absent; a file's directory; and a pattern's each match's directory."""
        if is_pattern(entry) and not (_home_relative(entry) or entry.startswith("/")):
            directories = dict.fromkeys(
                (self.root / path).parent for path in self.files()
                if inert(path, (entry,)) and (self.root / path).is_file())
            return [ScopedPath(Path(os.path.normpath(directory)), source, entry)
                    for directory in directories]
        return [ScopedPath(path.parent, source, entry) if path.is_file()
                else ScopedPath(path, source, entry, create=not path.exists())
                for path in self.paths(entry)]


def _unique(paths: Iterable[ScopedPath]) -> tuple[ScopedPath, ...]:
    """Each path once, from the first source that gave it."""
    seen: dict[Path, ScopedPath] = {}
    for path in paths:
        seen.setdefault(path.path, path)
    return tuple(seen.values())


def protected_by(entry: str, root: Path, home: Path, protected: Iterable[str]) -> str | None:
    """The first of the `protected` entries that `entry` is or lies under, in the
    checkout at `root`, or None; the configuration's check and a grant's ask it alike."""
    return _Checkout(root, home).protecting(entry, protected)


def granted(values: Sequence[str], checkout: _Checkout,
            protected: Sequence[str]) -> list[ScopedPath]:
    """The writable directories a run's grants give, refused, naming the value, where
    one names a pattern, `/tmp` or a directory holding it (`hides_temporary`), or a path
    that is or lies under one of the `protected` entries. A grant answers a gap with the
    narrowest path, so it names a path and never a pattern; a directory containing a
    protected path is granted, the protected path staying read-only inside it; a path
    under `/tmp` is granted, mounted at its own path inside the private one."""
    paths: list[ScopedPath] = []
    for value, part in grant_paths(values):
        if is_pattern(part):
            raise ScopeError(f"the grant {value!r} names {part}, a pattern; a grant names "
                             "a path")
        if hides_temporary(part, checkout.root, checkout.home):
            raise ScopeError(f"the grant {value!r} names {part}, which is or holds the "
                             "host's temporary directory; every step writes a private "
                             f"{PRIVATE_TEMPORARY} of its own, which it would hide")
        if guarded := checkout.protecting(part, protected):
            raise ScopeError(f"the grant {value!r} names {part}, which is or lies under the "
                             f"protected path {guarded}")
        paths.extend(checkout.writable(part, GRANT))
    return paths


def resolve(step: str, root: Path, *, inert_paths: Sequence[str],
            writable: Sequence[str] = (), protected: Sequence[str] = (),
            adapter_writable: Sequence[str] = (), adapter_files: Sequence[str] = (),
            adapter_protected: Sequence[str] = (), grants: Sequence[str] = (),
            home: Path | None = None) -> Scope:
    """The scope of one run of `step` in the checkout at `root`, as absolute paths:
    its baseline, its temporary entry the private `/tmp`; the adapter's state — its
    directories, and its files mounted alone — and protected paths; the repository's
    writable paths for the step and its protected ones; and the run's grants, each
    grant refused before anything launches where the scope cannot hold it
    (`granted`). `inert_paths` are the repository's,
    which closeout's baseline names."""
    definition = STEP_DEFINITIONS[step]
    checkout = _Checkout(root, Path.home() if home is None else home)
    sources = ((ENGINE, PROTECTED), (ADAPTER, adapter_protected), (REPOSITORY, protected))
    guarded = _unique([ScopedPath(path, source, entry) for source, entries in sources
                       for entry in entries for path in checkout.paths(entry)])
    paths: list[ScopedPath] = []
    for entry in definition.baseline:
        if entry == TEMPORARY:
            paths.append(ScopedPath(PRIVATE_TEMPORARY, ENGINE, entry, private=True))
        elif entry == PROPOSALS:
            paths.extend(ScopedPath(path, ENGINE, entry) for path in checkout.proposals())
        elif entry == INERT_PATHS:
            paths.extend(path for inert_path in inert_paths
                         for path in checkout.writable(inert_path, ENGINE))
        else:
            paths.extend(checkout.writable(entry, ENGINE))
    paths.extend(ScopedPath(path, ADAPTER, entry, create=not path.exists(), alone=True)
                 for entry in adapter_files for path in checkout.paths(entry))
    for source, entries in ((ADAPTER, adapter_writable), (REPOSITORY, writable)):
        paths.extend(path for entry in entries for path in checkout.writable(entry, source))
    every_protected = [entry for _, entries in sources for entry in entries]
    paths.extend(granted(grants, checkout, every_protected))
    return Scope(step, _unique(paths), guarded)
