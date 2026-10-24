"""What each run cost.

Every run's line records what it cost (`cost`): for a Claude run its own dollars,
turns, duration, and tokens, the dollars marked `usd_partial` when they cannot be
told from its session's other turns; for a Codex review the tokens it reports.
`cost` also keeps `session_usd` and `entries`, the session's running total and its
conversation file's turns when the run ended, which the session's next run is
measured against; they are not the run's cost. A resumed session's line also
records the gap since its last turn (`gap_s`) and whether its first model call
read the prompt cache (`cache_hit`); `scripts/change_cost.py` reports them.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from change_workflow.common import STEPS, Entry
from change_workflow.log import read_log
from change_workflow.stream import read_transcript


def run_cost(results: Sequence[dict[str, Any]], before: float | None) -> Entry:
    """What a Claude run cost, from its turns' `result` events.

    The fields differ in kind: a session's `total_cost_usd` is its running total,
    so the run's own dollars are the last result's total less `before`, the total
    when the run began; its token counts, turns, and duration are the run's own,
    so they are summed over its results — a background task finishing can wake
    the session for a second turn with its own result. `session_usd` keeps the
    running total for the session's next run to difference against.
    """
    usage = [r["usage"] for r in results if isinstance(r.get("usage"), dict)]

    def total(key: str) -> int:
        return sum(int(u.get(key) or 0) for u in usage)

    cost: Entry = {
        "turns": sum(int(r.get("num_turns") or 0) for r in results),
        "duration_s": round(sum(float(r.get("duration_ms") or 0) for r in results) / 1000, 1),
        "input": total("input_tokens"), "output": total("output_tokens"),
        "cache_read": total("cache_read_input_tokens"),
        "cache_write": total("cache_creation_input_tokens")}
    totals = [r["total_cost_usd"] for r in results
              if isinstance(r.get("total_cost_usd"), (int, float))]
    if totals:
        cost["usd"] = round(totals[-1] - (before or 0.0), 6)
        cost["session_usd"] = totals[-1]
    return cost


_CODEX_TOKENS = re.compile(r"^tokens used\s*\n\s*([\d,]+)\s*$", re.M)


def codex_cost(transcript: Path) -> Entry:
    """The tokens a Codex review reports, summed over the attempts its transcript
    holds, since a retried attempt's tokens were spent too."""
    text = transcript.read_text("utf-8", "replace") if transcript.is_file() else ""
    counts = _CODEX_TOKENS.findall(text)
    return {"tokens": sum(int(count.replace(",", "")) for count in counts)} if counts else {}


def pi_cost(transcript: Path) -> Entry:
    """The dollars and tokens a pi review's assistant messages report, summed over
    the attempts its transcript holds."""
    usd, tokens, seen = 0.0, 0, False
    text = transcript.read_text("utf-8", "replace") if transcript.is_file() else ""
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        message = event.get("message") if isinstance(event, dict) else None
        if (event.get("type") != "message_end" or not isinstance(message, dict)
                or message.get("role") != "assistant"):
            continue
        usage = message.get("usage") or {}
        seen = True
        tokens += int(usage.get("totalTokens") or 0)
        usd += float((usage.get("cost") or {}).get("total") or 0)
    return {"usd": round(usd, 6), "tokens": tokens} if seen else {}


@dataclass(frozen=True)
class Conversation:
    """What Claude Code's own record of a session says: how many turns it holds,
    and when the last of them was."""

    entries: int
    last: datetime | None


def conversation_file(root: Path, session: str) -> Path:
    """Where Claude Code keeps a session started in `root`: its project directory is
    the path with every character but a letter or digit made a dash."""
    project = re.sub(r"[^A-Za-z0-9]", "-", str(root.resolve()))
    return Path.home() / ".claude" / "projects" / project / f"{session}.jsonl"


def read_conversation(path: Path) -> Conversation | None:
    """The turns of a session's conversation file and the time of its last entry."""
    if not path.is_file():
        return None
    entries, last = 0, None
    for line in path.read_text("utf-8", "replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") in ("user", "assistant"):
            entries += 1
        if isinstance(event.get("timestamp"), str):
            try:
                last = datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00"))
            except ValueError:
                pass
    return Conversation(entries, last)


def _session_lines(log: Sequence[Entry], session: str) -> list[Entry]:
    """The logged runs of a session, oldest first."""
    return [entry for entry in log if entry.get("session") == session
            and entry.get("step") in STEPS]


def _logged_total(lines: Sequence[Entry]) -> float | None:
    """The session's running total as its latest run that recorded one left it."""
    for entry in reversed(lines):
        cost = entry.get("cost")
        if isinstance(cost, dict) and isinstance(cost.get("session_usd"), (int, float)):
            return float(cost["session_usd"])
    return None


def measured_before(log: Sequence[Entry], session: str, conversation: Conversation | None,
                    started: datetime) -> Entry:
    """What a resumed session's run is measured against, read before it starts: the
    session's running total as logged, whether this run's dollars can be told from
    its other turns, and when its last turn was."""
    lines = _session_lines(log, session)
    last = lines[-1] if lines else None
    logged = last.get("cost") if last else None
    partial = (
        # The session's last run left no total: it crashed before a result, or ran
        # before costs were recorded, so its dollars are in this run's.
        not isinstance(logged, dict) or "session_usd" not in logged
        # The session gained turns the wrapper did not run, such as the owner's own
        # after taking it over.
        or (conversation is not None and isinstance(logged.get("entries"), int)
            and conversation.entries > logged["entries"]))
    turn = conversation.last if conversation and conversation.last else (
        datetime.fromisoformat(last["at"].replace("Z", "+00:00"))
        if last and isinstance(last.get("at"), str) else None)
    return {"usd": _logged_total(lines), "partial": partial, "turn": turn,
            "started": started,
            "entries": conversation.entries if conversation is not None else None}


def measured_cost(results: Sequence[dict[str, Any]], first_usage: dict[str, Any] | None,
                  before: Entry, conversation: Conversation | None) -> Entry:
    """A run's line fields for its cost: `cost`, and for a resumed session the gap
    since its last turn and whether its first model call read the prompt cache.

    `cost` also keeps two figures for the session's next run, not this run's cost:
    `session_usd`, the session's running total, and `entries`, the turns its
    conversation file held when this run ended. A run that reached no model leaves
    the running total as it found it, when its conversation file shows it added
    nothing, so the next run is not taken for one after a crash.
    """
    cost = run_cost(results, before.get("usd"))
    if before.get("partial") and "usd" in cost:
        cost["usd_partial"] = True
    if conversation is not None:
        cost["entries"] = conversation.entries
    if ("session_usd" not in cost and isinstance(before.get("usd"), (int, float))
            and not before.get("partial") and conversation is not None
            and conversation.entries == before.get("entries")):
        cost["session_usd"] = before["usd"]
    fields: Entry = {"cost": cost}
    if before:
        if before.get("turn") is not None:
            fields["gap_s"] = round((before["started"] - before["turn"]).total_seconds())
        if first_usage is not None:
            fields["cache_hit"] = int(first_usage.get("cache_read_input_tokens") or 0) > 0
    return fields


def review_cost(transcript: Path, log: Path, session: str | None, harness: str | None,
                started: datetime) -> Entry:
    """What a review's run cost, read from its transcript: the tokens Codex
    reports, a pi run's dollars and tokens, or a Claude run's cost as a step's is
    measured, against the total its session's last logged review left when it
    continues one. A bb thread's run records none: bb reports no cost to its
    caller."""
    if harness == "pi":
        cost = pi_cost(transcript)
        return {"cost": cost} if cost else {}
    if harness == "bb":
        return {}
    if harness != "claude":
        cost = codex_cost(transcript)
        return {"cost": cost} if cost else {}
    stream = read_transcript(transcript)
    entries = read_log(log)
    # A review continuing a Claude reviewer is measured as a resumed step is, from
    # the log alone: its conversation file already holds this run's own turns.
    before = (measured_before(entries, session, None, started)
              if session and _session_lines(entries, session) else {})
    return measured_cost(stream.results, stream.first_usage, before, None)
