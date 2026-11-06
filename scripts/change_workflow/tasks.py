"""Fail if a change's task list has a task under another section's heading.

The sections of a task list are its `## N. Title` headings, and every step that
acts on the list — implementation choosing its section, closeout confirming every
task is checked, the next-step computation routing on which sections are done —
reads them from those headings alone. A heading lost in an edit hands its tasks
to the section before it, and nothing else in the file says so. A task numbered
`N.m` under a heading other than `## N.` is that loss made visible: this check
names each such task and the heading it sits under. Only tasks under a
recognised `## N.` heading are checked, so a list in another format passes.

Run as `scripts/change-workflow check tasks <change>` (`make check-tasks`) by the
skills that act on a task list before they do; its check, `task_problems`, is also
the next-step computation's own backstop where it routes on sections. Prints each
problem with its line on standard error and exits 1, or prints OK.

`owed_lines` reads the evidence a task list's complete sections owe validation:
each `Owed by validation:` line names, first in backticks, the CI workflow whose
run only a push produces. A line under a section with an unchecked task owes
nothing yet, since validation judges a section only once it is complete.

Contract: openspec/specs/change-workflow/spec.md, CW-4rqr, CW-5r7l, and CW-g4oz.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from .common import StepError, repository_root
from .find import ChangeNotFound, change_directory
from .next_step import TASKS_FILE, read_sections, section_heading, task_problems

# An owed line, in a task's text or the section's notes, and its workflow.
_OWED = re.compile(r"^\s*(?:- )?Owed by validation:\s*`(?P<workflow>[^`]+)`")


def owed_lines(tasks: Path) -> list[tuple[str, str]]:
    """Each `Owed by validation:` line of a complete section of the task list at
    `tasks`, as its section's id and its workflow, in the list's order; none when
    there is no list."""
    if not tasks.is_file():
        return []
    complete = {section.id for section in read_sections(tasks) if section.complete}
    owed: list[tuple[str, str]] = []
    section: str | None = None
    for line in tasks.read_text("utf-8").splitlines():
        if (heading := section_heading(line)) is not None:
            section = heading
        elif line.startswith("## "):
            section = None
        elif section in complete and (match := _OWED.match(line)):
            owed.append((section, match["workflow"]))
    return owed


def main(argv: list[str] | None = None, root: Path | None = None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    if len(args) != 1 or not args[0]:
        print("usage: check tasks <change>", file=sys.stderr)
        return 2
    try:
        root = repository_root() if root is None else root
    except StepError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    try:
        tasks = change_directory(root, args[0]) / TASKS_FILE
    except ChangeNotFound as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if not tasks.is_file():
        print(f"OK: {args[0]} has no task list yet.")
        return 0
    shown = tasks.relative_to(root).as_posix()
    if problems := task_problems(tasks.read_text("utf-8")):
        for problem in problems:
            print(f"{shown}:{problem}", file=sys.stderr)
        print(file=sys.stderr)
        print("FAIL: a task sits under another section's heading; a heading is missing or\n"
              "the task is misplaced. Nothing that reads the sections can act on it.",
              file=sys.stderr)
        return 1
    print(f"OK: every numbered task of {shown} sits under its own section's heading.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
