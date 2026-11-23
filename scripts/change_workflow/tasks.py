"""Fail if a change's task list has a task under another section's heading.

The sections of a task list are its `## N. Title` headings, and every step that
acts on the list — implementation choosing its section, closeout confirming every
task is checked, the next-step computation routing on which sections are done —
reads them from those headings alone. A heading lost in an edit hands its tasks
to the section before it, and nothing else in the file says so. A task numbered
`N.m` under a heading other than `## N.` is that loss made visible: this check
names each such task and the heading it sits under. Only tasks under a
recognised `## N.` heading are checked, so a list in another format passes.
The closeout section is known by its exact title, `Closeout`, alone, so a list
with sections also fails where none is titled so, where more than one is, or where
a section follows it.

Run as `change-workflow check tasks <change>` (`make check-tasks`) by the
skills that act on a task list before they do; its check, `task_problems`, is also
the next-step computation's own backstop where it routes on sections. Prints each
problem with its line on standard error and exits 1, or prints OK.

`owed_lines` reads the evidence a task list's sections owe validation, evidence only
a push produces. Each owed line names the evidence kind it owes and an argument,
`Owed by validation (<kind> <argument>):`, the argument one safe path segment —
non-empty, neither `.` nor `..`, holding no `/`, whitespace, or glob character — so
no argument's evidence lies in another's directory. A line naming no kind, `Owed by
validation:`, owes the one kind the configuration declares owed, its argument the
first word in backticks. Any other line is refused, naming its section: a line
naming no argument, an unsafe argument, a kind that is not owed, or no kind where
none or several are owed. Only a complete section's lines owe anything, since
validation judges a section only once it is complete (`complete`); `check tasks`
reports a refused line in any section.

Contract: openspec/specs/change-workflow/spec.md, CW-4rqr, CW-5r7l, CW-g4oz, CW-r5qk,
and CW-5h8e.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from . import config
from .common import StepError, repository_root
from .find import ChangeNotFound, change_directory
from .next_step import (TASKS_FILE, closeout_problems, read_sections, section_heading,
                        task_problems)

# An owed line, in a task's text or the section's notes, and what follows its words.
_OWED = re.compile(r"^\s*(?:- )?Owed by validation\b(?P<rest>.*)$")
# The line naming its kind and argument, `(<kind> <argument>):`.
_NAMED = re.compile(r"^\s*\((?P<kind>[^\s()]*)\s*(?P<argument>[^()]*)\)\s*:")
# The line naming no kind, `:` and its argument, the first word in backticks.
_UNNAMED = re.compile(r"^\s*:[^`]*(?:`(?P<argument>[^`]*)`)?")
# What an argument may not hold: a path separator, whitespace, or a glob character.
_UNSAFE = re.compile(r"[/\s*?\[\]]")


@dataclass(frozen=True)
class Owed:
    """One owed line: its section, its line number, and the kind and argument it
    owes, or why it was refused."""

    section: str
    line: int
    kind: str | None = None
    argument: str | None = None
    refusal: str | None = None


def argument_problem(argument: str) -> str | None:
    """Why `argument` is not one safe path segment, or None when it is."""
    if not argument:
        return "names no argument"
    if argument in (".", ".."):
        return f"names {argument!r}, which is no argument but a directory"
    if _UNSAFE.search(argument):
        return f"names {argument!r}, which holds a `/`, whitespace, or a glob character"
    return None


def read_owed(text: str, owed_kinds: Sequence[str], complete: Sequence[str] | None = None
              ) -> list[Owed]:
    """Each owed line of the task list `text`, in order, read against the kinds the
    configuration declares owed; only the sections `complete` names, or every
    section when it is None."""
    found: list[Owed] = []
    section: str | None = None
    for number, line in enumerate(text.splitlines(), start=1):
        if (heading := section_heading(line)) is not None:
            section = heading
            continue
        if line.startswith("## "):
            section = None
            continue
        if section is None or (complete is not None and section not in complete):
            continue
        if (match := _OWED.match(line)) is None:
            continue
        found.append(_owed(section, number, match["rest"], owed_kinds))
    return found


def _owed(section: str, number: int, rest: str, owed_kinds: Sequence[str]) -> Owed:
    kind: str | None = None

    def refused(why: str) -> Owed:
        return Owed(section, number, kind, refusal=f"section {section}'s owed line {why}")

    if (named := _NAMED.match(rest)) is not None:
        argument = named["argument"].strip()
        if not named["kind"]:
            return refused("names no kind in its parentheses")
        # A line is reported under the kind it names only when that kind is owed, so
        # a refused line never reads as another requirement of a kind owed always.
        if named["kind"] not in owed_kinds:
            return refused(f"names {named['kind']!r}, which is no evidence kind the "
                           "configuration declares owed; owed: "
                           + (", ".join(owed_kinds) or "none"))
        kind = named["kind"]
    elif (unnamed := _UNNAMED.match(rest)) is not None:
        if len(owed_kinds) != 1:
            return refused("names no kind, and the configuration declares "
                           + ("no kind owed" if not owed_kinds else
                              "several kinds owed: " + ", ".join(owed_kinds))
                           + "; name one as `Owed by validation (<kind> <argument>):`")
        kind = owed_kinds[0]
        if unnamed["argument"] is None:
            return refused("names no argument in backticks")
        argument = unnamed["argument"].strip()
    else:
        return refused("is neither `Owed by validation (<kind> <argument>):` nor `Owed by "
                       "validation:` followed by its argument in backticks")
    if problem := argument_problem(argument):
        return refused(problem)
    return Owed(section, number, kind, argument)


def owed_kinds(configuration: config.Configuration) -> tuple[str, ...]:
    """The names of the kinds the configuration declares owed."""
    return tuple(kind.name for kind in configuration.kinds or () if kind.owed)


def complete(tasks: Path) -> list[str]:
    """The ids of the task list's complete sections."""
    return [section.id for section in read_sections(tasks) if section.complete]


def owed_lines(tasks: Path, owed: Sequence[str]) -> list[Owed]:
    """Each owed line of a complete section of the task list at `tasks`, read against
    the kinds `owed`, in the list's order; none when there is no list."""
    if not tasks.is_file():
        return []
    return read_owed(tasks.read_text("utf-8"), owed, complete(tasks))


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
    text = tasks.read_text("utf-8")
    if problems := task_problems(text) + closeout_problems(text):
        for problem in problems:
            print(f"{shown}:{problem}", file=sys.stderr)
        print(file=sys.stderr)
        print("FAIL: a task sits under another section's heading, or the closeout section,\n"
              "titled `Closeout`, is missing, repeated, or not the last. Nothing that reads\n"
              "the sections can act on it.", file=sys.stderr)
        return 1
    try:
        owed = owed_kinds(config.load(root))
    except StepError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if refused := [line for line in read_owed(text, owed) if line.refusal]:
        for line in refused:
            print(f"{shown}:{line.line}: {line.refusal}", file=sys.stderr)
        print(file=sys.stderr)
        print("FAIL: an owed line names no evidence kind the configuration owes, or no safe\n"
              "argument, so validation cannot tell what it owes.", file=sys.stderr)
        return 1
    print(f"OK: every numbered task of {shown} sits under its own section's heading, "
          "its closeout section is its last, and every owed line names an owed kind and "
          "an argument.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
