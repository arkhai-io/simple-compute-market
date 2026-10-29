#!/usr/bin/env python3
"""Copy a cleaned-up change's history from its clone into the owner's workspace.

A change worked in its own clone keeps its history there: its records under
`reviews/` — reviews, triage, the owner's notes, the workflow log, transcripts —
and the validation evidence they name under `.snapshot/`. None of it is tracked,
so no merge carries it, and removing the clone would lose it. Archive cleanup
copies it, as its last act, to the same paths in the owner's workspace, where
sessions working other changes find it (`find_change.py --records`); removing the
clone copies it again first.

The copy is a synchronization, safe to repeat. A file the workspace lacks is
copied; one with the same contents is left alone; one whose contents are a prefix
of the clone's is extended to the clone's, since the workflow log and a run's
transcript only grow, and archive cleanup's own outcome, the orchestrating
session's lines, and another round on the pull request are written after the first
copy. Any other difference is refused, naming the file, and the workspace's file is
never overwritten: it holds something the clone does not, and which is meant is the
owner's call. Only regular files are copied. Nothing rebuildable is: only
`reviews/` and the evidence directories its records name, never a wheelhouse, an
environment, or a zip of logs.

The evidence a change's records name is each `.snapshot/validation/<commit>/` and
`.snapshot/e2e-logs/<run>/` they cite, the evidence of each validation record's
commit (`**Commit:**`, kept under its first twelve characters), and each record's
pipeline run (`**Pipeline:** run <id>`). Transcripts are not read for it: they
cite whatever a session read, another clone's evidence included. Named evidence
the clone does not hold is reported, not refused.

Contract: openspec/specs/change-workflow/spec.md, "Each change is worked in its
own clone".
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from find_change import (REVIEWS, ChangeNotFound, change_directory, is_archived,
                         workspace_of)

ROOT = Path(__file__).resolve().parents[1]
VALIDATION = Path(".snapshot/validation")
E2E_LOGS = Path(".snapshot/e2e-logs")
_CITED_VALIDATION = re.compile(r"\.snapshot/validation/([0-9a-f]{7,40})(?![0-9A-Za-z])")
_CITED_RUN = re.compile(r"\.snapshot/e2e-logs/([0-9]+)(?![0-9A-Za-z])")
_VALIDATED_COMMIT = re.compile(r"^- \*\*Commit:\*\*\s*([0-9a-f]{12,40})\b", re.M)
_PIPELINE_RUN = re.compile(r"^- \*\*Pipeline:\*\*\s*run\s+([0-9]+)\b", re.M)
# validate_slice.py keeps a commit's evidence under its first twelve characters.
_SHORT_COMMIT = 12


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


def named_evidence(reviews: Path) -> list[Path]:
    """The evidence directories the records in `reviews` name, relative to the checkout."""
    named: set[Path] = set()
    for record in sorted(reviews.iterdir()):
        if not record.is_file():
            continue
        text = record.read_text("utf-8", errors="replace")
        named.update(VALIDATION / commit for commit in _CITED_VALIDATION.findall(text))
        named.update(VALIDATION / commit[:_SHORT_COMMIT]
                     for commit in _VALIDATED_COMMIT.findall(text))
        named.update(E2E_LOGS / run
                     for run in _CITED_RUN.findall(text) + _PIPELINE_RUN.findall(text))
    return sorted(named)


def _history(clone: Path, change: str) -> tuple[list[Path], list[Path]]:
    """The directories of the change's history the clone holds, relative to it —
    its records, then the evidence they name — and the named evidence it does not."""
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
    named = named_evidence(reviews)
    held = [path for path in named if (clone / path).is_dir()]
    absent = [path for path in named if not (clone / path).is_dir()]
    return [reviews.relative_to(clone), *held], absent


def _files(clone: Path, tops: Sequence[Path]) -> list[Path]:
    files: list[Path] = []
    for top in tops:
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


def main(argv: Sequence[str] | None = None, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    actions = parser.add_subparsers(dest="action", required=True)
    syncing = actions.add_parser("sync", help="copy the change's history into the workspace")
    syncing.add_argument("change")
    args = parser.parse_args(argv)
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
    return 1 if synced.refused else 0


if __name__ == "__main__":
    sys.exit(main())
