"""What every part of the workflow tooling shares: the repository it acts on, its
error, and its clock. The steps and review kinds it knows are the graph's
(`graph.STEPS`, `graph.KINDS`)."""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

CHANGES = Path("openspec/changes")
ORCHESTRATOR = "orchestrator"

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
