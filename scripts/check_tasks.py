#!/usr/bin/env python3
"""Fail if a change's task list has a task under another section's heading.

The sections of a task list are its `## N. Title` headings, and every step that
acts on the list — implementation choosing its section, closeout confirming every
task is checked, the next-step computation routing on which sections are done —
reads them from those headings alone. A heading lost in an edit hands its tasks
to the section before it, and nothing else in the file says so. A task numbered
`N.m` under a heading other than `## N.` is that loss made visible: this check
names each such task and the heading it sits under. Only tasks under a
recognised `## N.` heading are checked, so a list in another format passes.

Run as `make check-tasks CHANGE=<change>` by the skills that act on a task list
before they do; its check, `task_problems`, is also the next-step computation's
own backstop where it routes on sections. Prints each problem with its line and
exits non-zero, or prints OK.

Contract: openspec/specs/change-workflow/spec.md, "The next step is computed from
the files".
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from change_next_step import TASKS_FILE, task_problems  # noqa: E402
from find_change import ChangeNotFound, change_directory  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None, root: Path = ROOT) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    if len(args) != 1 or not args[0]:
        print("usage: check_tasks.py <change>", file=sys.stderr)
        return 2
    try:
        tasks = change_directory(root, args[0]) / TASKS_FILE
    except ChangeNotFound as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if not tasks.is_file():
        print(f"OK: {args[0]} has no task list yet.")
        return 0
    shown = tasks.relative_to(root).as_posix()
    if problems := task_problems(tasks.read_text("utf-8")):
        for problem in problems:
            print(f"{shown}:{problem}")
        print()
        print("FAIL: a task sits under another section's heading; a heading is missing or")
        print("the task is misplaced. Nothing that reads the sections can act on it.")
        return 1
    print(f"OK: every numbered task of {shown} sits under its own section's heading.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
