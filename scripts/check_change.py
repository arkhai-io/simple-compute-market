#!/usr/bin/env python3
"""Run this repository's own closing checks of a change as one command, printing
only what fails.

The change workflow's `pre-commit` hook runs the workflow's default checks of a
change — the change index, its task list, the agent skills, and the strict OpenSpec
validation — and then this repository's command for the hook, which is this one:
comment hygiene, the change's documentation citations, the indexed capabilities'
specifications against their indexes with the change's deltas counted, and the
written rules the change's own work must keep — each design decision's destination,
no history wording in the comments it adds, one version step per package it bumps,
a reason for each import it adds inside a function, and a capability index listing
every capability. Run as separate commands, each is a tool call that replays the
step's whole conversation; run here, they are one call, and an answer of one line
when everything passes. Every check runs whatever the others report, and each
failing check's own output is printed under its name, so one call says everything
that needs fixing.

The checks of what the change adds read its diff from the merge-base with the
branch it lands on: `--base` when given, as the hook gives it, else the landing
branch the change's clone recorded, which `scripts/change-workflow find --json`
prints as `base`. A change with neither is refused, naming `--base`, since a
guessed branch would read another diff.

Usage: `make check-repository CHANGE=<change> [CHANGE_BASE=<branch>]`; `make
check-change` runs the whole hook, defaults included.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Callable, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from workflow_command import WorkflowRefused, found_change  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

# Runs a command in a directory and returns its exit status and merged output.
Runner = Callable[[Sequence[str], Path], tuple[int, str]]


def _run(command: Sequence[str], cwd: Path) -> tuple[int, str]:
    done = subprocess.run(list(command), cwd=cwd, stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                          encoding="utf-8", errors="replace")
    return done.returncode, done.stdout


def checks(change: str, base: str) -> list[tuple[str, list[str]]]:
    """Each check's name and command, in the order they run."""
    make = ["make", "--no-print-directory"]
    lands_on = f"CHANGE_BASE={base}"
    return [
        ("comment hygiene", [*make, "check-comment-hygiene"]),
        ("documentation citations", [*make, "check-doc-citations", f"CHANGE={change}"]),
        ("specification index", [*make, "check-spec-index", f"CHANGE={change}"]),
        ("decision destinations", [*make, "check-decision-destinations", f"CHANGE={change}"]),
        ("history wording", [*make, "check-history-wording", lands_on]),
        ("version bumps", [*make, "check-version-bumps", lands_on]),
        ("local imports", [*make, "check-local-imports", lands_on]),
        ("capability index", [*make, "check-capability-index"]),
    ]


def run_checks(change: str, *, root: Path = ROOT, runner: Runner = _run,
               echo: Callable[[str], None] = print, base: str | None = None) -> int:
    """Run every check, print each failure with its output, and return the exit status."""
    try:
        found = found_change(root, change)
    except WorkflowRefused as exc:
        echo(f"ERROR: {exc}")
        return 1
    lands_on = base or found.get("base")
    if not isinstance(lands_on, str) or not lands_on:
        echo(f"ERROR: {change} records no branch it lands on; give it with --base <branch> "
             "(CHANGE_BASE=<branch>)")
        return 1
    planned = checks(change, lands_on)
    failed = []
    for name, command in planned:
        status, output = runner(command, root)
        if status != 0:
            failed.append(name)
            echo(f"FAILED: {name} ({' '.join(command)}), exit {status}")
            echo(output.rstrip("\n"))
    if failed:
        echo(f"FAILED: {len(failed)} of {len(planned)} checks of {change}: "
             + ", ".join(failed))
        return 1
    echo(f"OK: every check of {change} passed: " + ", ".join(name for name, _ in planned))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    base = None
    if len(arguments) == 3 and arguments[1] == "--base" and arguments[2]:
        base = arguments[2]
        arguments = arguments[:1]
    if len(arguments) != 1 or not arguments[0]:
        print("usage: check_change.py <change> [--base <branch>]", file=sys.stderr)
        return 2
    return run_checks(arguments[0], base=base)


if __name__ == "__main__":
    sys.exit(main())
