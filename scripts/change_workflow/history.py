"""Copy a cleaned-up change's history from its clone into the owner's workspace.

A change worked in its own clone keeps its history there: its records under
`reviews/` — reviews, triage, the owner's notes, the workflow log, transcripts —
and the validation evidence they name, under the fixed directory of each evidence
kind's pattern the workflow configuration declares. None of it is tracked,
so no merge carries it, and removing the clone would lose it. Archive cleanup
copies it, as its last act, to the same paths in the owner's workspace, where
sessions working other changes find it (`find --records`); removing the
clone copies it again first.

The copy is a synchronization, safe to repeat. A file the workspace lacks is
copied; one with the same contents is left alone; one whose contents are a prefix
of the clone's is extended to the clone's, since the workflow log and a run's
transcript only grow, and archive cleanup's own outcome, the orchestrating
session's lines, and another round on the pull request are written after the first
copy. Any other difference is refused, naming the file, and the workspace's file is
never overwritten: it holds something the clone does not, and which is meant is the
owner's call. Only regular files are copied. Nothing rebuildable is: only
`reviews/` and the evidence its records name, never a wheelhouse, an environment,
or a zip of logs.

The evidence a change's records name is, under each evidence directory, each path
they cite — a directory, or the directory holding a cited file — and the evidence of
each validation record's tree (`**Tree:**`) and commit (`**Commit:**`), each by its
full object name. A kind keyed by that identity says what that is, by its pattern:
what matches it, the identity filled in and any other placeholder matching anything.
A matching directory is copied itself, and a matching file with the directory
holding it — an attempt, with its logs — when that directory holds that kind's
evidence alone, and alone otherwise. So evidence keyed by a whole directory, a file,
or a name embedding the identity is found alike, and nothing outside what matches,
or the directories holding it, is copied. A directory a kind's
pattern reaches before its identity's segment holds every identity's evidence, so it
is never copied whole: a cited file in it is copied alone, and a cited directory
that is one is not copied, the evidence of the trees and commits the records name
found in it by their patterns instead; a directory another kind's pattern also
reaches holds that kind's evidence too, so a match in it is copied alone. Transcripts
are not read for it: they cite whatever a session read, another clone's evidence
included. Named evidence the clone does not hold is reported, not refused: a cited
path absent, and a tree or commit no kind's pattern finds, each pattern as filled.

Contract: openspec/specs/change-workflow/spec.md, CW-hak6 and CW-rf50.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Sequence

from . import config
from .common import StepError, repository_root
from .find import REVIEWS, ChangeNotFound, change_directory, is_archived, workspace_of

# A validation record's commit and tree, each its full object name.
_IDENTITY = re.compile(r"^- \*\*(Commit|Tree):\*\*\s*`?([0-9a-f]{40})\b", re.M)


class HistoryError(RuntimeError):
    """The change has no history to copy from this clone."""


@dataclass
class Synced:
    """What one synchronization did, each path relative to the clone and the workspace."""

    copied: list[str] = field(default_factory=list)
    extended: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    # Each a path and why it was not copied.
    refused: list[str] = field(default_factory=list)
    # Evidence the records name that the clone does not hold.
    absent: list[str] = field(default_factory=list)


def _cited(directory: Path) -> re.Pattern[str]:
    """A citation of a path under `directory`, the path below it taken: segments of
    names, attempts, and files, never `.` or `..`, nor the full stop ending a
    sentence."""
    segment = r"[0-9A-Za-z](?:[0-9A-Za-z_.-]*[0-9A-Za-z_-])?"
    return re.compile(re.escape(directory.as_posix()) + rf"((?:/{segment})+)/?"
                      r"(?![0-9A-Za-z_-]|\.[0-9A-Za-z_-])")


def named_evidence(reviews: Path, evidence: Sequence[str]
                   ) -> tuple[list[Path], list[tuple[str, str]]]:
    """What the records in `reviews` name under the evidence directories `evidence`,
    relative to the checkout: each cited path, and each validated tree and commit, as
    its identity — `tree` or `commit` — and its full object name, whose evidence the
    records do not locate."""
    directories = [Path(entry.rstrip("/")) for entry in evidence]
    cited: set[Path] = set()
    keys: set[tuple[str, str]] = set()
    for record in sorted(reviews.iterdir()):
        if not record.is_file():
            continue
        text = record.read_text("utf-8", errors="replace")
        for directory in directories:
            cited.update(Path(directory.as_posix() + below)
                         for below in _cited(directory).findall(text))
        keys.update((label.lower(), key) for label, key in _IDENTITY.findall(text))
    return sorted(cited), sorted(keys)


def _identity_segment(segments: Sequence[str]) -> int:
    """The index of the segment holding a pattern's identity, which the
    configuration's check requires it to hold."""
    return next(index for index, segment in enumerate(segments)
                if {config.TREE, config.COMMIT} & set(config.placeholders(segment)))


def identity_glob(pattern: str, key: str) -> str:
    """An evidence pattern, `{tree}` or `{commit}` filled with `key`, and any other
    placeholder matching anything: the evidence of the tree or commit `key`."""
    return config.PLACEHOLDER.sub(
        lambda match: key if match.group(1) in (config.TREE, config.COMMIT) else "*",
        pattern)


def _shared(pattern: str) -> list[str]:
    """The segments of an evidence pattern before its identity's, each a glob, its
    placeholders matching anything: the directories they match hold the evidence of
    every tree or commit."""
    segments = pattern.split("/")
    return [config.PLACEHOLDER.sub("*", segment)
            for segment in segments[:_identity_segment(segments)]]


def _directories(pattern: str) -> list[str]:
    """The segments of an evidence pattern but its last, each a glob, its
    placeholders matching anything: the directories its evidence lies in."""
    return [config.PLACEHOLDER.sub("*", segment) for segment in pattern.split("/")[:-1]]


def _reaches(path: Path, globs: Sequence[str]) -> bool:
    """Whether `path` is one of the directories `globs` match, or lies above one."""
    parts = path.parts
    return len(parts) <= len(globs) and all(map(fnmatchcase, parts, globs))


def _history(clone: Path, change: str) -> tuple[list[Path], list[Path]]:
    """What of the change's history the clone holds, relative to it — its records,
    then the evidence they name, each a directory or a file — and the named evidence
    it does not, as the clone's configuration declares its kinds."""
    try:
        directory = change_directory(clone, change)
    except ChangeNotFound as exc:
        raise HistoryError(str(exc)) from exc
    if not is_archived(clone, directory):
        raise HistoryError(f"change {change!r} is not archived in {clone}; its history is "
                           "copied once closeout has archived it")
    reviews = directory / REVIEWS
    if not reviews.is_dir():
        raise HistoryError(f"{reviews.relative_to(clone)} does not exist in {clone}")
    try:
        configuration = config.load(clone)
    except StepError as exc:
        raise HistoryError(str(exc)) from exc
    kinds = configuration.kinds or ()
    cited, keys = named_evidence(reviews, configuration.evidence())
    shared = [_shared(kind.evidence) for kind in kinds]
    directories = [_directories(kind.evidence) for kind in kinds]

    def whole(path: Path) -> bool:
        """Whether `path` may be copied whole: no kind's pattern reaches it before
        its identity's segment, where it would bring every identity's evidence."""
        return not any(_reaches(path, globs) for globs in shared)

    def owned(path: Path, index: int) -> bool:
        """Whether `path`, a directory holding evidence of the kind at `index`, holds
        that kind's alone, so it may be copied whole: it is whole, and no other
        kind's pattern reaches it."""
        return whole(path) and not any(_reaches(path, globs)
                                       for other, globs in enumerate(directories)
                                       if other != index)

    # A cited file is copied with the directory holding it, unless that directory
    # holds every identity's evidence; then it is copied alone.
    cited = sorted({path.parent if (clone / path).is_file() and whole(path.parent) else path
                    for path in cited})
    held = [path for path in cited
            if (clone / path).is_file() or ((clone / path).exists() and whole(path))]
    absent = [path for path in cited if not (clone / path).exists()]
    for identity, key in keys:
        # A tree's evidence lies only where a kind keyed by the tree puts it, and a
        # commit's where one keyed by the commit does. A file matching a kind's
        # pattern is copied with the directory holding it — an attempt, with its
        # logs — when that directory holds that kind's evidence alone, and alone
        # otherwise; a matching directory is copied itself.
        globs: list[str] = []
        found: list[Path] = []
        for index, kind in enumerate(kinds):
            if kind.identity != identity:
                continue
            globs.append(glob := identity_glob(kind.evidence, key))
            # Matched as the presence check matches it, so the two agree on what a
            # pattern finds.
            for match in map(Path, config.matches(clone, glob)):
                widen = (clone / match).is_file() and owned(match.parent, index)
                found.append(match.parent if widen else match)
        found = list(dict.fromkeys(found))
        held += [path for path in found if path not in held]
        if not found:
            absent += [Path(glob) for glob in dict.fromkeys(globs) if Path(glob) not in absent]
    # What lies inside a directory copied is copied with it, once.
    held = [path for path in held if not any(other in path.parents for other in held)]
    return [reviews.relative_to(clone), *sorted(held)], sorted(absent)


def _files(clone: Path, tops: Sequence[Path]) -> list[Path]:
    files: list[Path] = []
    for top in tops:
        if not (clone / top).is_dir() or (clone / top).is_symlink():
            # A file is copied itself, and a link listed, so it is refused and named.
            files.append(top)
            continue
        for directory, subdirectories, names in os.walk(clone / top):
            subdirectories.sort()
            # A link to a directory is not walked into; it is listed, so it is refused
            # and named rather than passed over.
            links = [name for name in subdirectories if (Path(directory) / name).is_symlink()]
            files += [(Path(directory) / name).relative_to(clone)
                      for name in sorted(names + links)]
    return files


def history_files(clone: Path, change: str) -> list[Path]:
    """Every file of the change's history in the clone, relative to it."""
    return _files(clone, _history(clone, change)[0])


def _regular(path: Path) -> bool:
    return path.is_file() and not path.is_symlink()


def _copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    # Copied aside and renamed, so a session reading the workspace's history never
    # finds a half-copied file.
    aside = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    shutil.copy2(source, aside)
    aside.replace(target)


def sync(clone: Path, workspace: Path, change: str) -> Synced:
    """Copy the change's history from `clone` into `workspace`, at the same paths."""
    tops, absent = _history(clone, change)
    synced = Synced(absent=[path.as_posix() for path in absent])
    for relative in _files(clone, tops):
        name, source, target = relative.as_posix(), clone / relative, workspace / relative
        if not _regular(source):
            synced.refused.append(f"{name}: not a regular file in the clone")
            continue
        try:
            if not target.exists() and not target.is_symlink():
                _copy(source, target)
                synced.copied.append(name)
                continue
            if not _regular(target):
                synced.refused.append(f"{name}: not a regular file in the workspace")
                continue
            ours, theirs = source.read_bytes(), target.read_bytes()
            if ours == theirs:
                synced.unchanged.append(name)
            elif ours.startswith(theirs):
                with target.open("ab") as stream:
                    stream.write(ours[len(theirs):])
                synced.extended.append(name)
            else:
                synced.refused.append(f"{name}: the workspace's copy differs from the "
                                      "clone's, other than by the clone's having grown it")
        except OSError as exc:
            synced.refused.append(f"{name}: {exc}")
    return synced


def differences(clone: Path, workspace: Path, change: str) -> list[str]:
    """Every file of the change's history in the clone that the workspace does not
    hold with the same contents, each with what is wrong."""
    found = []
    for relative in history_files(clone, change):
        source, target = clone / relative, workspace / relative
        if not _regular(source):
            found.append(f"{relative.as_posix()}: not a regular file in the clone")
        elif not target.exists() and not target.is_symlink():
            found.append(f"{relative.as_posix()}: not in the workspace")
        elif not _regular(target) or target.read_bytes() != source.read_bytes():
            found.append(f"{relative.as_posix()}: the workspace's copy differs")
    return found


def report(synced: Synced, workspace: Path) -> str:
    lines = [f"Into {workspace}: {len(synced.copied)} file(s) copied, "
             f"{len(synced.extended)} extended, {len(synced.unchanged)} already there."]
    lines += [f"  extended {name}" for name in synced.extended]
    if synced.absent:
        lines.append("Named by the records but not in this clone, so not copied: "
                     + ", ".join(synced.absent))
    if synced.refused:
        lines.append("Refused, the workspace's file left as it is:")
        lines += [f"  {line}" for line in synced.refused]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None, root: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    actions = parser.add_subparsers(dest="action", required=True)
    syncing = actions.add_parser("sync", help="copy the change's history into the workspace")
    syncing.add_argument("change")
    args = parser.parse_args(argv)
    try:
        root = repository_root() if root is None else root
    except StepError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    workspace = workspace_of(root)
    if workspace is None:
        print(f"ERROR: {root} is not a change's clone: no `workspace` remote names the "
              "owner's workspace to copy its history into", file=sys.stderr)
        return 1
    try:
        synced = sync(root, workspace, args.change)
    except HistoryError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(report(synced, workspace))
    for refused in synced.refused:
        print(f"ERROR: not copied, the workspace's file left as it is: {refused}",
              file=sys.stderr)
    return 1 if synced.refused else 0


if __name__ == "__main__":
    sys.exit(main())
