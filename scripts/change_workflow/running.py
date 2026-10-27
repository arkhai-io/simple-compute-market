"""The record of each unattended run in progress in a checkout.

A round view moves the owner's workspace's branch, so it must not open while a
step runs there: a step whose checkout moved under it would describe, commit, or
validate a tree that is not its own. Each run writes one file under
`<git-dir>/change-runs/` as it starts — its process, step, and change — and
removes it once its line is in the workflow log, however the run ends, an
interrupt included. A record whose process is no longer alive is a run killed
before it could remove it, and counts as none; one whose process id another
process has since taken reads as a run in progress, which errs toward refusing.

The records live in the Git directory, as the round view's own state does, so
they belong to the checkout the run is in and no branch carries them.
"""

from __future__ import annotations

import json
import os
import subprocess
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timezone
from pathlib import Path
from typing import Callable, Iterator

from change_workflow.common import Clock, utc_now

RUNS = "change-runs"


@dataclass(frozen=True)
class Run:
    pid: int
    step: str
    change: str
    started: str

    def describe(self) -> str:
        return f"{self.step} of {self.change} (process {self.pid}, started {self.started})"


def runs_directory(root: Path) -> Path | None:
    """Where a checkout's runs are recorded; None outside a Git checkout, which no
    round view can move."""
    result = subprocess.run(["git", "rev-parse", "--git-path", RUNS], cwd=root,
                            capture_output=True, text=True)
    if result.returncode != 0:
        return None
    path = Path(result.stdout.strip())
    return path if path.is_absolute() else root / path


@contextmanager
def recorded_run(directory: Path | None, step: str, change: str, *,
                 clock: Clock = utc_now, pid: int | None = None) -> Iterator[None]:
    """Record a run in `directory` for as long as the block runs."""
    if directory is None:
        yield
        return
    pid = os.getpid() if pid is None else pid
    directory.mkdir(parents=True, exist_ok=True)
    name = f"{pid}-{uuid.uuid4().hex}"
    record = directory / f"{name}.json"
    started = clock().astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    # Written aside and renamed, so a reader never finds the record half-written
    # and takes it for no run.
    partial = directory / f"{name}.partial"
    partial.write_text(json.dumps({"pid": pid, "step": step, "change": change,
                                   "started": started}), "utf-8")
    partial.replace(record)
    try:
        yield
    finally:
        record.unlink(missing_ok=True)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def live_runs(directory: Path | None, alive: Callable[[int], bool] = _alive) -> list[Run]:
    """The runs recorded in `directory` whose process is alive."""
    if directory is None or not directory.is_dir():
        return []
    runs = []
    for path in sorted(directory.glob("*.json")):
        try:
            entry = json.loads(path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        pid = entry.get("pid") if isinstance(entry, dict) else None
        if isinstance(pid, int) and not isinstance(pid, bool) and alive(pid):
            runs.append(Run(pid, str(entry.get("step")), str(entry.get("change")),
                            str(entry.get("started"))))
    return runs


def runs_in_progress(root: Path, alive: Callable[[int], bool] = _alive) -> list[Run]:
    """The runs in progress in the checkout at `root`."""
    return live_runs(runs_directory(root), alive)
