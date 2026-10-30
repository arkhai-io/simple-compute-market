"""What every part of the workflow tooling shares: the repository, the steps and
review kinds it knows, its error, and its clock."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
CHANGES = Path("openspec/changes")
STEPS = ("design", "plan", "review", "triage", "implement", "validate", "merge",
         "closeout", "archive-cleanup")
KINDS = ("design", "implementation", "pre-closeout", "closeout")
ORCHESTRATOR = "orchestrator"

Clock = Callable[[], datetime]
Entry = dict[str, Any]


class StepError(RuntimeError):
    """The step could not be run or recorded."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
