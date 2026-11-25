"""The change workflow's engine as this repository's own scripts reach it.

The workflow is installed as a tool, `arkhai-change-workflow`, and a repository
reaches its engine only through its command, `change-workflow` on the path, never
by importing its package: the command's subcommands, exit statuses, and structured
outputs are what the engine keeps stable, while its modules may change under any of
them. A script here therefore runs the command as a process, in the checkout it
asks about, since the command acts on the Git repository containing its working
directory, and reads only the structured output a program may rely on — `find
--json`'s object, `check spec-index --json`'s, `config --json`'s, and `clone
where`'s path — with the command's own reason when it refuses. Where the command is
not installed, each call is refused, saying it cannot be run.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Sequence

# The installed command, found on the path; it acts on the working directory it is
# given.
COMMAND = "change-workflow"


class WorkflowRefused(Exception):
    """The command refused, for the reason it gave, or could not be run."""


def run(arguments: Sequence[str], cwd: Path,
        command: str | Path = COMMAND) -> subprocess.CompletedProcess[str]:
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


def found_change(root: Path, change: str,
                 command: str | Path = COMMAND) -> dict[str, object]:
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


def created_specifications(root: Path, change: str,
                           command: str | Path = COMMAND) -> frozenset[str]:
    """The specification paths the deltas of `change` create, as `check spec-index
    --json` prints them in `created`. The index check's own result is not this
    caller's concern: a failing check prints its object all the same, exiting 1,
    while a refusal prints none, its reason on standard error."""
    arguments = ["check", "spec-index", change, "--json"]
    done = run(arguments, root, command)
    try:
        reported = json.loads(done.stdout)
    except json.JSONDecodeError:
        raise _refused(done, arguments) from None
    created = reported.get("created") if isinstance(reported, dict) else None
    if not isinstance(created, list) or not all(isinstance(path, str) for path in created):
        raise WorkflowRefused(f"change-workflow {' '.join(arguments)} printed no `created` "
                              "list of paths")
    return frozenset(created)


def installed_guidance(root: Path, command: str | Path = COMMAND) -> Path:
    """The directory of the installed workflow's own guidance, as `config --json`
    names it in `workflow.guidance`, run in the checkout at `root`."""
    arguments = ["config", "--json"]
    done = run(arguments, root, command)
    if done.returncode != 0:
        raise _refused(done, arguments)
    try:
        shown = json.loads(done.stdout)
    except json.JSONDecodeError as exc:
        raise WorkflowRefused(f"change-workflow {' '.join(arguments)} printed no JSON "
                              f"object: {exc}") from exc
    workflow = shown.get("workflow") if isinstance(shown, dict) else None
    guidance = workflow.get("guidance") if isinstance(workflow, dict) else None
    if not isinstance(guidance, str) or not guidance:
        raise WorkflowRefused(f"change-workflow {' '.join(arguments)} printed no "
                              "`workflow.guidance` path")
    return Path(guidance)


def clone_where(checkout: Path, change: str,
                command: str | Path = COMMAND) -> Path | None:
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
