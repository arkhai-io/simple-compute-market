"""A Claude Code run's event stream: its transcript, its progress, and its denials.

Every line a run prints is kept in its transcript, `reviews/transcripts/NN-<step>.jsonl`,
events or not, with a progress file of its tool calls beside it. The stream is read
for the run's session, its results, and every tool call it was denied: each denial
as the harness lists it, with the harness's reason for it, gathered over every turn
of the run, since a background task finishing can wake a session for another turn
after its first `result` event. A line's denials are always this record, never the
step's own account of them.

Both files stay open from the run's first line to its end. Closeout archives the
change it runs for, which renames the change's directory, `reviews/` with it, while
the run is still writing; an open file moves with its directory, where a path
opened again for each line would name a directory that no longer exists.
"""

from __future__ import annotations

import json
from datetime import timezone
from pathlib import Path
from typing import Any, Callable, TextIO

from change_workflow.common import Clock, utc_now


def tool_summary(tool: dict[str, Any]) -> str:
    return call_summary(tool.get("input"))


def call_summary(given: Any) -> str:
    """One line for a tool call's input: the field that says what it did."""
    given = given if isinstance(given, dict) else {}
    for key in ("command", "file_path", "path", "pattern", "skill", "description", "prompt"):
        if isinstance(given.get(key), str):
            summary = " ".join(given[key].split())
            return summary if len(summary) <= 120 else summary[:119] + "…"
    return ""


def _denial_key(denial: dict[str, Any]) -> str:
    """What identifies a denied call: its tool use id, or the call itself."""
    if isinstance(denial.get("tool_use_id"), str):
        return denial["tool_use_id"]
    return json.dumps(denial, sort_keys=True, ensure_ascii=False)


class Stream:
    """The run's event stream: written whole to the transcript, its tool calls to
    the progress file, and read for the run's session, its final result, and every
    tool call it was denied.

    A run has one `result` event per turn, and a background task finishing can
    wake the session for another turn, so the last result is the run's end but
    its `permission_denials` are only its own turn's; the denials are gathered
    from every result, keyed by the call, and each takes the reason the harness
    gave in its `permission_denied` event: `mode` for a call no allow rule
    matched, `rule` for one a deny rule refused, and `subcommandResults` for a
    shell command the harness refused by one of its parts. A denial with no such
    event carries no reason.
    """

    def __init__(self, transcript: Path, progress: Path, clock: Clock = utc_now,
                 echo: Callable[[str], None] | None = None) -> None:
        self.transcript = transcript
        self.progress = progress
        self.clock = clock
        self.echo = echo
        self.session: str | None = None
        self.result: dict[str, Any] | None = None
        # Every turn's result, for what the run cost; the last is `result`.
        self.results: list[dict[str, Any]] = []
        # The first model call's token usage, which says whether it read the cache.
        self.first_usage: dict[str, Any] | None = None
        # Output that is not an event, such as an error printed before the stream
        # starts.
        self.notices: list[str] = []
        self._denials: dict[str, dict[str, Any]] = {}
        self._reasons: dict[str, str] = {}
        # Every tool call the run made, by id, which names the subagents it started.
        self.tool_use_ids: set[str] = set()
        self._files: dict[Path, TextIO] = {}

    def close(self) -> None:
        """Close the transcript and the progress file; a later line opens them again."""
        for file in self._files.values():
            file.close()
        self._files.clear()

    def _append(self, path: Path, text: str) -> None:
        file = self._files.get(path)
        if file is None:
            file = self._files[path] = path.open("a", encoding="utf-8")
        file.write(text)
        # Flushed per line, so the progress is followed while the run goes on.
        file.flush()

    @property
    def denials(self) -> list[dict[str, Any]]:
        """Every denial the run recorded, in order, each with the harness's reason
        when it gave one."""
        return [{**denial, **({"reason": self._reasons[key]} if key in self._reasons else {})}
                for key, denial in self._denials.items()]

    def feed(self, line: str) -> None:
        self._append(self.transcript, line if line.endswith("\n") else line + "\n")
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            self.notices.append(line.rstrip("\n"))
            return
        if not isinstance(event, dict):
            return
        self.take(event)
        message = event.get("message") if event.get("type") == "assistant" else None
        content = message.get("content") if isinstance(message, dict) else None
        for item in content if isinstance(content, list) else []:
            if isinstance(item, dict) and item.get("type") == "tool_use":
                if isinstance(item.get("id"), str):
                    self.tool_use_ids.add(item["id"])
                at = self.clock().astimezone(timezone.utc).strftime("%H:%M:%SZ")
                shown = f"{at} {item.get('name', '?')} {tool_summary(item)}".rstrip()
                self._append(self.progress, shown + "\n")
                if self.echo:
                    self.echo(shown)

    def take(self, event: dict[str, Any]) -> None:
        """Read an event for the run's session, its results, and its denials."""
        if isinstance(event.get("session_id"), str):
            self.session = event["session_id"]
        if event.get("type") == "assistant" and self.first_usage is None:
            message = event.get("message")
            usage = message.get("usage") if isinstance(message, dict) else None
            if isinstance(usage, dict):
                self.first_usage = usage
        if event.get("type") == "result":
            self.result = event
            self.results.append(event)
            denials = event.get("permission_denials")
            for denial in denials if isinstance(denials, list) else []:
                if isinstance(denial, dict):
                    self._denials.setdefault(_denial_key(denial), denial)
        if event.get("type") == "system" and event.get("subtype") == "permission_denied":
            if isinstance(event.get("tool_use_id"), str) and isinstance(
                    event.get("decision_reason_type"), str):
                self._reasons[event["tool_use_id"]] = event["decision_reason_type"]

    def failure_text(self, status: int | None) -> str:
        """What a run that failed said about it: its result and any other output.

        Empty for a run that ended with a result that is not an error, since that
        run reached its model whatever its result says.
        """
        result = self.result or {}
        if status == 0 and self.result is not None and not result.get("is_error"):
            return ""
        detail = result.get("result")
        return "\n".join([*self.notices, *([detail] if isinstance(detail, str) else [])])


def read_transcript(path: Path) -> Stream:
    """A Claude run's transcript read back as its stream was: its session, results,
    and denials.

    A review's transcript may begin with another harness's output, which is not
    events and is passed over.
    """
    stream = Stream(path, path.with_suffix(".progress"))
    for line in path.read_text("utf-8").splitlines() if path.is_file() else []:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            stream.take(event)
    return stream


def transcript_denials(path: Path) -> list[dict[str, Any]]:
    """The denials a Claude run's transcript records, gathered as its stream was."""
    return read_transcript(path).denials
