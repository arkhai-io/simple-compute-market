"""The change workflow's engine as this repository's own scripts reach it.

A repository reaches the engine only through its command, `scripts/change-workflow`,
never by importing the `change_workflow` package beside it: the command's
subcommands, exit statuses, and structured outputs are what the engine keeps
stable, while its modules may change under any of them. A script here therefore
runs the command as a process, in the checkout it asks about, since the command
acts on the Git repository containing its working directory, and reads only the
structured output a program may rely on — `find --json`'s object and `clone
where`'s path — with the command's own reason when it refuses.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Sequence

# The command beside this file; it acts on the working directory it is given.
COMMAND = Path(__file__).resolve().parent / "change-workflow"


class WorkflowRefused(Exception):
    """The command refused, for the reason it gave, or could not be run."""


def run(arguments: Sequence[str], cwd: Path,
        command: Path = COMMAND) -> subprocess.CompletedProcess[str]:
    """`command` run with `arguments` in `cwd`, its output captured."""
    try:
        return subprocess.run([str(command), *arguments], cwd=cwd, stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace")
    except OSError as exc:
        raise WorkflowRefused(f"cannot run {command}: {exc}") from exc


def _refused(done: subprocess.CompletedProcess[str],
             arguments: Sequence[str]) -> WorkflowRefused:
    reason = done.stderr.strip().removeprefix("ERROR: ").strip()
    return WorkflowRefused(reason or f"change-workflow {' '.join(arguments)} exited "
                                     f"{done.returncode}")


def found_change(root: Path, change: str, command: Path = COMMAND) -> dict[str, object]:
    """The change called `change` in the checkout at `root`, as `find --json` prints it:
    its `name`, its `directory` relative to the checkout, whether it is `archived`,
    and its `records` directory in this checkout, or None where it holds none."""
    arguments = ["find", "--json", change]
    done = run(arguments, root, command)
    if done.returncode != 0:
        raise _refused(done, arguments)
    try:
        found = json.loads(done.stdout)
    except json.JSONDecodeError as exc:
        raise WorkflowRefused(f"change-workflow {' '.join(arguments)} printed no JSON "
                              f"object: {exc}") from exc
    if not isinstance(found, dict):
        raise WorkflowRefused(f"change-workflow {' '.join(arguments)} printed no JSON object")
    return found


def clone_where(checkout: Path, change: str, command: Path = COMMAND) -> Path | None:
    """The usable clone of `change`, looked for from `checkout`; None where no clone
    directory exists and the change is worked in place.

    Refused, with the command's reason, for a change that does not exist and for a
    clone directory that is unusable — not a clone of the workspace, its branch not
    checked out, or its bootstrap not succeeded — so neither is taken for a change
    worked in place.
    """
    arguments = ["clone", "where", change]
    done = run(arguments, checkout, command)
    if done.returncode != 0:
        raise _refused(done, arguments)
    found = done.stdout.strip()
    return Path(found) if found else None
