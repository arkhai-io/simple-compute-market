#!/usr/bin/env python3
"""Fail if code outside openspec/ names a change, a task, or a change document.

A mechanical sweep for the "Python comments and docstrings" rule in `AGENTS.md`:
comments describe the current system, not the history of the change that
produced it. Two scans, each a line search over the tree from the repository
root, skipping the directories that hold no code of ours:

- change-history references — a `POOLS-<n>` change ID, a section or task
  number, or the file name of a change document (its task list, design, or
  proposal) — in `.py`, `.yml`, and `.yaml` files outside `openspec/`;
- the name of any OpenSpec change directory, active or archived (its date
  prefix dropped), in `.py`, `.toml`, `.yml`, and `.yaml` files outside
  `openspec/`, `docs/`, and `.claude/`. `docs/` is exempt because naming the
  change that owns a gap is the roadmap's job.

This catches the reliably mechanical subset of the rule, not the fuzzier
"references the review that introduced the code" cases, which still need a
human or LLM read. It deliberately does not match a bare "tombstone": that word
has a legitimate, unrelated meaning (a soft-delete marker row) in this codebase,
and a pattern cannot tell the two apart; the tombstone convention stays a
judgement-call check.

One line is exempt from the first scan: the definition of `TASKS_FILE` in
`scripts/change_next_step.py`, which reads a change's task list and so must name
the file once. Any other mention in that script is still caught. This script and
its test are scanned like any other file, so neither spells out what the first
scan looks for: the pattern is written as a pattern, and the test builds its
samples at run time.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

HISTORY_PATTERN = re.compile(
    r"POOLS-[0-9]+|[Ss]ection [0-9]+\.[0-9]+|[Ss]ection [0-9]+(\s|:|$)|[Tt]ask [0-9]+\.[0-9]+"
    r"|\btasks\.md\b|\bdesign\.md\b|\bproposal\.md\b")
HISTORY_SUFFIXES = (".py", ".yml", ".yaml")
HISTORY_EXCLUDED_DIRS = frozenset(
    {"openspec", ".git", "__pycache__", ".venv", ".dist", "node_modules", "build"})
#: The one exempt line: the file name's definition in the script that reads it.
EXEMPT = ("scripts/change_next_step.py", re.compile(r'^TASKS_FILE = "[^"]*"$'))

NAME_SUFFIXES = (".py", ".toml", ".yml", ".yaml")
NAME_EXCLUDED_DIRS = HISTORY_EXCLUDED_DIRS | {"docs", ".claude"}
_DATED = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}-")


def _files(root: Path, suffixes: tuple[str, ...], excluded: frozenset[str]) -> list[Path]:
    """Every file under `root` with one of `suffixes`, skipping `excluded`
    directories at any depth, in a stable order."""
    found: list[Path] = []
    for directory, subdirectories, names in os.walk(root):
        subdirectories[:] = sorted(d for d in subdirectories if d not in excluded)
        for name in sorted(names):
            if name.endswith(suffixes):
                found.append(Path(directory) / name)
    return found


def _lines(path: Path) -> list[str]:
    try:
        return path.read_text("utf-8", errors="replace").splitlines()
    except OSError:
        return []


def _shown(root: Path, path: Path, number: int, line: str) -> str:
    return f"./{path.relative_to(root).as_posix()}:{number}:{line}"


def change_history_matches(root: Path = ROOT) -> list[str]:
    """Every line outside openspec/ that names a change ID, a task, or a change
    document, as `./path:line:text`, the exempt line left out."""
    matches: list[str] = []
    for path in _files(root, HISTORY_SUFFIXES, HISTORY_EXCLUDED_DIRS):
        exempt = path.relative_to(root).as_posix() == EXEMPT[0]
        for number, line in enumerate(_lines(path), start=1):
            if HISTORY_PATTERN.search(line) and not (exempt and EXEMPT[1].match(line)):
                matches.append(_shown(root, path, number, line))
    return matches


def change_names(root: Path = ROOT) -> list[str]:
    """Every OpenSpec change name: the active directories and the archived ones
    with their date prefix dropped. A name containing `archive` is skipped, the
    archive directory itself among them."""
    changes = root / "openspec" / "changes"
    names: set[str] = set()
    if changes.is_dir():
        for entry in changes.iterdir():
            if entry.is_dir() and "archive" not in entry.name:
                names.add(entry.name)
    archive = changes / "archive"
    if archive.is_dir():
        for entry in archive.iterdir():
            if entry.is_dir():
                names.add(_DATED.sub("", entry.name))
    return sorted(name for name in names if name)


def change_name_matches(root: Path = ROOT) -> list[str]:
    """Every line of code that contains a change's name, as `./path:line:text`."""
    names = change_names(root)
    if not names:
        return []
    matches: list[str] = []
    for path in _files(root, NAME_SUFFIXES, NAME_EXCLUDED_DIRS):
        for number, line in enumerate(_lines(path), start=1):
            if any(name in line for name in names):
                matches.append(_shown(root, path, number, line))
    return matches


def main(root: Path = ROOT) -> int:
    print("Scanning for change-ID and task-number references outside openspec/...")
    if matches := change_history_matches(root):
        print("\n".join(matches))
        print()
        print("FAIL: found change-history references outside openspec/. See AGENTS.md's")
        print("'Python comments and docstrings' section -- comments must describe the")
        print("current system, not the history of the change that produced it.")
        return 1
    print("OK: no change-ID/task-number references found outside openspec/.")
    print("Scanning for OpenSpec change directory names in code...")
    if matches := change_name_matches(root):
        print("\n".join(matches))
        print()
        print("FAIL: code names an OpenSpec change. A comment must describe the")
        print("current system, not the change that produced it or the change that")
        print("will alter it next -- a reader of the code cannot see either, and")
        print("the name goes stale the moment the change is archived.")
        print("docs/ is exempt: the roadmap's job is to name the change owning a gap.")
        return 1
    print("OK: no OpenSpec change names found in code.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
