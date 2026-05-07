"""Append-only logs for buyer runs.

A pure buyer (`market buy`) doesn't run a server, so it has no SQLite
DB to write structured stage events into. Instead each invocation
opens a JSONL file under the XDG state dir and appends one line per
event. Format:

    {"ts": "2026-04-27T18:30:00+00:00",
     "run_id": "<uuid>",
     "event": "negotiation_terminated",
     ...}

One file per run, keyed by run_id, so:
- The CLI can list past runs by listing the directory.
- Recovery: re-running with `--resume <run_id>` (future) reads the
  file, finds the last completed step, and retries from there.
- Inspection: ordinary `cat`/`tail`/`jq` work without our CLI.

Location: ``$XDG_STATE_HOME/arkhai/buy-runs/<run_id>.jsonl``,
defaulting to ``~/.local/state/arkhai/buy-runs/`` when XDG is unset.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def runs_dir() -> Path:
    """Return the directory holding per-run JSONL log files.

    Honors ``XDG_STATE_HOME`` when set, otherwise falls back to
    ``~/.local/state``.
    """
    xdg = os.environ.get("XDG_STATE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "state"
    return base / "arkhai" / "buy-runs"


def _new_run_id() -> str:
    return uuid.uuid4().hex


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunLog:
    """Per-run append-only event log.

    Construct via ``RunLog.start(...)`` to create a fresh run, or
    ``RunLog.open(run_id)`` to append more events to an existing run.

    All event records share the schema::

        {"ts": <iso8601>, "run_id": <id>, "event": <name>, **fields}
    """

    def __init__(self, run_id: str, path: Path) -> None:
        self.run_id = run_id
        self.path = path

    @classmethod
    def start(cls, **input_fields: Any) -> "RunLog":
        """Begin a new run. Creates the JSONL file and writes the
        opening ``run_started`` event with the given input fields."""
        run_id = _new_run_id()
        path = runs_dir() / f"{run_id}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        log = cls(run_id, path)
        log.event("run_started", **input_fields)
        return log

    @classmethod
    def open(cls, run_id: str) -> "RunLog":
        """Re-open an existing run by id. Appends to the existing file."""
        return cls(run_id, runs_dir() / f"{run_id}.jsonl")

    def event(self, event: str, **fields: Any) -> None:
        """Append one event line to the log."""
        record = {
            "ts": _now_iso(),
            "run_id": self.run_id,
            "event": event,
            **fields,
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")

    def end(self, status: str, **fields: Any) -> None:
        """Append the closing ``run_ended`` event."""
        self.event("run_ended", status=status, **fields)


# ---------------------------------------------------------------------------
# Read-side helpers (used by `market logs`)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    path: Path
    started_at: str | None
    last_event: str | None
    last_event_ts: str | None
    last_status: str | None  # set when the run emitted run_ended


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    # Skip malformed lines rather than blow up — recovery
                    # paths still need to read what's salvageable.
                    continue
    except FileNotFoundError:
        return []
    return out


def read_run(run_id: str) -> list[dict[str, Any]]:
    """Return all events for a given run, in append order."""
    return _read_jsonl(runs_dir() / f"{run_id}.jsonl")


def list_runs() -> list[RunSummary]:
    """Return summaries for every run in the runs directory, newest
    first by file mtime."""
    d = runs_dir()
    if not d.exists():
        return []
    files: Iterable[Path] = sorted(
        d.glob("*.jsonl"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    out: list[RunSummary] = []
    for p in files:
        events = _read_jsonl(p)
        if not events:
            continue
        first = events[0]
        last = events[-1]
        last_status: str | None = None
        if last.get("event") == "run_ended":
            last_status = last.get("status")
        out.append(RunSummary(
            run_id=p.stem,
            path=p,
            started_at=first.get("ts"),
            last_event=last.get("event"),
            last_event_ts=last.get("ts"),
            last_status=last_status,
        ))
    return out


def last_successful_step(run_id: str) -> dict[str, Any] | None:
    """Return the last event that completed without an error field set.

    Used by the recovery path: the caller can read this and decide
    where to resume from. ``None`` if the run has no clean successful
    events recorded.
    """
    events = read_run(run_id)
    for ev in reversed(events):
        if ev.get("error"):
            continue
        if ev.get("event") in ("run_started", "run_ended"):
            continue
        return ev
    return None
