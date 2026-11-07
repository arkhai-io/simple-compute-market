"""What every part of the workflow tooling shares: the repository it acts on, the
format of a change's record set, the marker of an unattended run, its error, and its
clock. The steps and review
kinds it knows are the graph's (`graph.STEPS`, `graph.KINDS`)."""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

CHANGES = Path("openspec/changes")
ORCHESTRATOR = "orchestrator"
# The format of a change's record set: the workflow log's lines and the outcomes
# and decisions they hold, the records' layout and names, the fields read from
# records, and, where a log exists, the ledger's lines. Every log line carries it,
# and so do `next`'s and `find --json`'s outputs and the outcome schema's `$id`; it
# moves when any of them changes incompatibly, with a command converting the older.
FORMAT = 2
# Set in the environment of every unattended run, to the name of the run's step, so
# a command the run starts can tell it is inside one, and which: the wrapper records
# that run's outcome, so a step's own recording of it would write it twice, and
# `run` gives a step only the hooks the engine's hook table lists for it. Any
# non-empty value marks a run unattended. The marker is internal: no repository or
# runner reads it.
UNATTENDED_RUN = "CHANGE_WORKFLOW_UNATTENDED"
# Where Claude Code gives every command it starts the id of its session. The
# variable is not documented, so a run where it is unset is refused rather than
# recorded without a session, and `record --session` gives the id instead; what a
# command invoked outside any session is kept for no line.
SESSION_ID = "CLAUDE_CODE_SESSION_ID"

Clock = Callable[[], datetime]
Entry = dict[str, Any]


class StepError(RuntimeError):
    """The step could not be run or recorded."""


class NotInRepository(StepError):
    """The command runs in a directory no Git repository contains."""


def repository_root(directory: Path | None = None) -> Path:
    """The top level of the Git repository containing `directory`, the working
    directory by default: the repository every command acts on. A command finds it
    as it starts; a part not handed a repository, a step table, or a schema finds
    it again from the same working directory, and so the same one.

    The engine acts on the repository it is run in, never on the one its own files
    sit in, so a change's clone and the owner's workspace each act on themselves.
    Outside any repository it refuses, naming the directory, before anything is
    read or written.
    """
    where = Path.cwd() if directory is None else directory
    try:
        found = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=where,
                               capture_output=True, text=True, check=False)
    except OSError as exc:
        raise NotInRepository(f"cannot look for a Git repository at {where}: {exc}") from exc
    if found.returncode != 0 or not found.stdout.strip():
        raise NotInRepository(f"{where} is not inside a Git repository")
    return Path(found.stdout.strip())


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
