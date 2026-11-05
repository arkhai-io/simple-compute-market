"""The record of each unattended run in progress in a checkout, and stopping one.

A round view moves the owner's workspace's branch, so it must not open while a
step runs there: a step whose checkout moved under it would describe, commit, or
validate a tree that is not its own. Each run writes one file under
`<git-dir>/change-runs/` as it starts — its process, step, and change — and
removes it once its line is in the workflow log, however the run ends, an
interrupt included.

A run holds an exclusive `flock` on its record for as long as it runs, and a
record counts as a run in progress only while that lock is held. The kernel
releases the lock however the process ends, SIGKILL included, so a record a killed
run left behind reads as stale rather than as a run; and the lock's descriptor is
closed in every program the run executes, so neither a process that has since
taken the run's id nor a child that outlives it passes for the run. The runners
start their processes through `subprocess`, which executes a program in each; a
bare fork would share the descriptor, and the lock with it. `flock`
rather than a POSIX record lock: a record lock belongs to the process, so a reader
in the run's own process would always acquire it, and its closing the file would
release the run's lock.

`stop` signals a run on the owner's word: it checks the lock when it selects the
run and again immediately before it sends SIGTERM, which every run — a step's in
the wrapper, a review's in its runner — turns into its `stopped` line through
`termination_ends_the_run` while its agent or reviewer runs. For the rest of the
time it holds its record, `termination_deferred` holds the signal, so a run is
never killed before its line is written. The two checks and the signal are
separate system calls, so a run ending between the last check and the signal
leaves its id to be signalled; that
reaches another process only if the kernel hands out its whole process-id range in
between, to a process of the same user. No test can make that happen, so nothing
guards it.

The records live in the Git directory, as the round view's own state does, so
they belong to the checkout the run is in and no branch carries them.
"""

from __future__ import annotations

import fcntl
import json
import os
import signal
import subprocess
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from change_workflow.common import Clock, StepError, utc_now

RUNS = "change-runs"


@dataclass(frozen=True)
class Run:
    pid: int
    step: str
    change: str
    started: str
    # The record the run holds; None for a run described without one.
    record: Path | None = None

    def describe(self) -> str:
        return f"{self.step} of {self.change} (process {self.pid}, started {self.started})"


class Terminated(BaseException):
    """The run was told to stop by a signal while it went on."""


# The signals `termination_deferred` has held for the run in progress.
_held: list[str] = []


@contextmanager
def termination_deferred() -> Iterator[None]:
    """Hold SIGTERM for as long as a run holds its record, outside the stretch
    `termination_ends_the_run` covers.

    A signal held before the run's agent or reviewer starts ends the run as it
    would start, so a stop given early still stops it. A signal held after that
    process has ended ends nothing: the run goes on to log the outcome it
    reached. Killing it there would leave no line, and the work it logs — a
    published review, a pushed commit — is done whether or not the line is
    written. A handler rather than SIG_IGN, since an ignored signal stays
    ignored in every program the run executes. Signal handlers can be set only
    on the main thread; elsewhere nothing changes.
    """
    if threading.current_thread() is not threading.main_thread():
        yield
        return

    def hold(signum: int, _frame: Any) -> None:
        _held.append(signal.Signals(signum).name)

    _held.clear()
    previous = signal.getsignal(signal.SIGTERM)
    # Set inside the `try`, so the handler is restored even when a signal that
    # was already pending arrives as it is set.
    try:
        signal.signal(signal.SIGTERM, hold)
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)
        _held.clear()


@contextmanager
def termination_ends_the_run() -> Iterator[None]:
    """Turn SIGTERM into `Terminated` while a run's agent or reviewer runs.

    A process killed by SIGTERM's default action writes nothing, and a log whose
    last line is a run's question cannot tell a run still going from one that
    died. Raised in the run, the signal ends it as any interruption does: the
    runner stops the process it started, and the run is logged
    `stopped`, naming the signal. A signal `termination_deferred` held before
    this began is raised as it begins. SIGKILL cannot be caught, so a run killed
    that way still leaves no line. Signal handlers can be set only on the main
    thread; elsewhere nothing changes.
    """
    if threading.current_thread() is not threading.main_thread():
        yield
        return

    def stop(signum: int, _frame: Any) -> None:
        raise Terminated(f"received {signal.Signals(signum).name}")

    previous = signal.getsignal(signal.SIGTERM)
    try:
        signal.signal(signal.SIGTERM, stop)
        if _held:
            raise Terminated(f"received {_held[0]}")
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


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
                 clock: Clock = utc_now) -> Iterator[None]:
    """Record a run in `directory`, holding its lock, for as long as the block runs."""
    if directory is None:
        yield
        return
    pid = os.getpid()
    directory.mkdir(parents=True, exist_ok=True)
    name = f"{pid}-{uuid.uuid4().hex}"
    record = directory / f"{name}.json"
    started = clock().astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    # Written aside, locked, and then renamed, so a reader never finds the record
    # half-written or unlocked and takes it for no run. Python opens files
    # non-inheritable, so no program the run executes keeps the descriptor.
    partial = directory / f"{name}.partial"
    with partial.open("w", encoding="utf-8") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        held.write(json.dumps({"pid": pid, "step": step, "change": change,
                               "started": started}))
        held.flush()
        partial.replace(record)
        try:
            yield
        finally:
            record.unlink(missing_ok=True)


def _read(path: Path) -> tuple[Run, bool] | None:
    """The run `path` records and whether its lock is held; None for a record gone
    or unreadable."""
    try:
        handle = path.open("r", encoding="utf-8")
    except OSError:
        return None
    with handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            held = True
        else:
            # Released as the file closes.
            held = False
        try:
            entry = json.loads(handle.read())
        except (OSError, json.JSONDecodeError):
            return None
    pid = entry.get("pid") if isinstance(entry, dict) else None
    if not isinstance(pid, int) or isinstance(pid, bool):
        return None
    return Run(pid, str(entry.get("step")), str(entry.get("change")),
               str(entry.get("started")), path), held


def _records(directory: Path | None) -> list[tuple[Run, bool]]:
    if directory is None or not directory.is_dir():
        return []
    return [found for path in sorted(directory.glob("*.json"))
            if (found := _read(path)) is not None]


def live_runs(directory: Path | None) -> list[Run]:
    """The runs recorded in `directory` whose lock is held."""
    return [run for run, held in _records(directory) if held]


def runs_in_progress(root: Path) -> list[Run]:
    """The runs in progress in the checkout at `root`."""
    return live_runs(runs_directory(root))


def select_run(directory: Path | None, change: str, step: str | None = None) -> Run:
    """The one run in progress of `change` in `directory`, of `step` when named.

    Refused when none is, naming a record whose lock no run holds as stale, and
    when two are and no step tells them apart.
    """
    found = [(run, held) for run, held in _records(directory)
             if run.change == change and (step is None or run.step == step)]
    live = [run for run, held in found if held]
    of = f"{step} of {change}" if step else change
    if not live:
        stale = [run for run, held in found if not held]
        if stale:
            raise StepError(f"no run of {of} is in progress: the record of "
                            + "; ".join(f"{run.describe()} at {run.record}" for run in stale)
                            + " is stale, its run no longer holding it; nothing was signalled")
        raise StepError(f"no run of {of} is in progress; nothing was signalled")
    if len(live) > 1:
        raise StepError(f"{len(live)} runs of {of} are in progress: "
                        + "; ".join(run.describe() for run in live)
                        + "; name the one to stop with --step. Nothing was signalled")
    return live[0]


def signal_run(run: Run, send: Callable[[int, int], None] = os.kill) -> None:
    """Send SIGTERM to `run`, once its lock is checked again to be held."""
    found = _read(run.record) if run.record is not None else None
    if found is None or not found[1] or found[0].pid != run.pid:
        raise StepError(f"{run.describe()} ended before it could be stopped; nothing was "
                        "signalled")
    try:
        send(run.pid, signal.SIGTERM)
    except ProcessLookupError as exc:
        raise StepError(f"{run.describe()} ended before it could be stopped") from exc


def stop(directory: Path | None, change: str, step: str | None = None,
         send: Callable[[int, int], None] = os.kill) -> Run:
    """Stop the run in progress of `change`, of `step` when named, and return it."""
    run = select_run(directory, change, step)
    signal_run(run, send)
    return run
