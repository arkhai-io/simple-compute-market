#!/usr/bin/env python3
"""Run a change's closing checks as one command, printing only what fails.

A step of an OpenSpec change ends by running the same checks: comment hygiene,
the agent skills, the change's documentation citations and task list, the change
index, and the pinned OpenSpec validator in strict mode. Run as six commands,
each is a tool call that replays the step's whole conversation; run here, they
are one call, and an answer of one line when everything passes. Every check runs
whatever the others report, and each failing check's own output is printed under
its name, so one call says everything that needs fixing.

An archived change has no delta left to validate, so the validator checks every
permanent specification instead, its archive's merges among them.

Usage: `make check-change CHANGE=<change>`.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from find_change import ChangeNotFound, change_directory, is_archived  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
# The validator version openspec/README.md pins, run through whichever package
# runner the machine has.
OPENSPEC = "@fission-ai/openspec@1.14.0"

# Runs a command in a directory and returns its exit status and merged output.
Runner = Callable[[Sequence[str], Path], tuple[int, str]]


def _run(command: Sequence[str], cwd: Path) -> tuple[int, str]:
    done = subprocess.run(list(command), cwd=cwd, stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                          encoding="utf-8", errors="replace")
    return done.returncode, done.stdout


def openspec_command(which: Callable[[str], str | None] = shutil.which) -> list[str]:
    """The pinned validator, through `bunx` where it is installed, else `npx`."""
    return ["bunx", OPENSPEC] if which("bunx") else ["npx", "--yes", OPENSPEC]


def checks(change: str, archived: bool,
           which: Callable[[str], str | None] = shutil.which) -> list[tuple[str, list[str]]]:
    """Each check's name and command, in the order they run."""
    make = ["make", "--no-print-directory"]
    validate = (["validate", "--specs", "--strict"] if archived
                else ["validate", change, "--strict"])
    return [
        ("comment hygiene", [*make, "check-comment-hygiene"]),
        ("agent skills", [*make, "check-agent-skills"]),
        ("documentation citations", [*make, "check-doc-citations", f"CHANGE={change}"]),
        ("task list", [*make, "check-tasks", f"CHANGE={change}"]),
        ("change index", [*make, "check-change-index"]),
        ("openspec validate", [*openspec_command(which), *validate]),
    ]


def run_checks(change: str, *, root: Path = ROOT, runner: Runner = _run,
               which: Callable[[str], str | None] = shutil.which,
               echo: Callable[[str], None] = print) -> int:
    """Run every check, print each failure with its output, and return the exit status."""
    try:
        archived = is_archived(root, change_directory(root, change))
    except ChangeNotFound as exc:
        echo(f"ERROR: {exc}")
        return 1
    planned = checks(change, archived, which)
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
    if len(arguments) != 1 or not arguments[0]:
        print("usage: check_change.py <change>", file=sys.stderr)
        return 2
    return run_checks(arguments[0])


if __name__ == "__main__":
    sys.exit(main())
