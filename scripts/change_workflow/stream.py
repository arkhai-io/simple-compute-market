"""A Claude Code run's event stream: its transcript, its progress, its denials, and
its refusals.

Every line a run prints is kept in its transcript, `reviews/transcripts/NN-<step>.jsonl`,
events or not, with a progress file of its tool calls beside it. The stream is read
for the run's session, its results, every tool call it was denied, and every write
the sandbox refused it: each denial as the harness lists it, with the harness's
reason for it, gathered over every turn of the run, since a background task
finishing can wake a session for another turn after its first `result` event; and
each failed call whose result says a write failed as a read-only file system, or
busy, with the call's tool, its command or path, and that line (CW-w3oa). A line's
denials and refusals are always this record, never the step's own account of them.

A run's `init` event lists the skills its harness loaded. A run given the skills it
must load is stopped at that event when one is missing, before its session takes a
turn: `feed` raises `SkillsNotLoaded`, naming each, and the caller passes the model
over as unavailable, so a harness that stops loading the installed skills fails the
run rather than running it without them (CW-d8de).

Both files stay open from the run's first line to its end. Closeout archives the
change it runs for, which renames the change's directory, `reviews/` with it, while
the run is still writing; an open file moves with its directory, where a path
opened again for each line would name a directory that no longer exists.
"""

from __future__ import annotations

import json
from datetime import timezone
from pathlib import Path
from typing import Any, Callable, Collection, TextIO

from .common import Clock, utc_now
from .harness import refused

# The fields of a call's input naming the path a file tool wrote.
_PATH_FIELDS = ("file_path", "notebook_path", "path")


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


def _tool_uses(event: dict[str, Any]) -> list[dict[str, Any]]:
    """The tool calls an assistant event makes."""
    message = event.get("message") if event.get("type") == "assistant" else None
    content = message.get("content") if isinstance(message, dict) else None
    return [item for item in content if isinstance(item, dict) and item.get("type") == "tool_use"
            ] if isinstance(content, list) else []


def _tool_results(event: dict[str, Any]) -> list[dict[str, Any]]:
    """The tool results a user event carries back to the session."""
    message = event.get("message") if event.get("type") == "user" else None
    content = message.get("content") if isinstance(message, dict) else None
    return [item for item in content
            if isinstance(item, dict) and item.get("type") == "tool_result"
            ] if isinstance(content, list) else []


def _result_text(result: dict[str, Any]) -> str:
    """A tool result's output, given as text or as a list of parts."""
    content = result.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(part["text"] for part in content
                         if isinstance(part, dict) and isinstance(part.get("text"), str))
    return ""


def _refusal(call: dict[str, Any], error: str) -> dict[str, Any]:
    """A refused write as a line records it: the call's tool, the command it ran or
    the path it wrote, and the error."""
    given = call.get("tool_input", {})
    named: dict[str, Any] = {}
    if isinstance(given.get("command"), str):
        named["command"] = given["command"]
    elif path := next((given[key] for key in _PATH_FIELDS if isinstance(given.get(key), str)),
                      None):
        named["path"] = path
    return {"tool": call.get("tool_name", "?"), **named, "error": error}


def _is_init(event: dict[str, Any]) -> bool:
    """Whether `event` is a turn's opening `init` event, which lists the skills its
    harness loaded."""
    return event.get("type") == "system" and event.get("subtype") == "init"


def _denial_key(denial: dict[str, Any]) -> str:
    """What identifies a denied call: its tool use id, or the call itself."""
    if isinstance(denial.get("tool_use_id"), str):
        return denial["tool_use_id"]
    return json.dumps(denial, sort_keys=True, ensure_ascii=False)


class SkillsNotLoaded(Exception):
    """A run's harness did not load a skill the run must load; the message names each."""


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

    A run ended by a signal emits no `result` for its last turn, so a call its
    `permission_denied` event names that no result lists is a denial too, shaped
    as a result shapes one from the `tool_use` that made the call, whether or
    not the event gives a reason; a call the stream never showed takes the tool
    the event names, or `?`, with no input.
    """

    def __init__(self, transcript: Path, progress: Path, clock: Clock = utc_now,
                 echo: Callable[[str], None] | None = None,
                 skills: Collection[str] = ()) -> None:
        self.transcript = transcript
        # The skills the run's harness must load, and those its `init` event did not
        # list.
        self.skills = frozenset(skills)
        self.unloaded: list[str] = []
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
        # Every call a `permission_denied` event names, in order, with a reason
        # or without one, so a run with no `result` keeps each of them.
        self._denied: dict[str, None] = {}
        # Every tool call the run made, by id, which names the subagents it started.
        self.tool_use_ids: set[str] = set()
        # Each call's tool and input, by id, which shape a denial no result lists,
        # and the tool a `permission_denied` event names, for a call never shown.
        self._calls: dict[str, dict[str, Any]] = {}
        self._denied_tools: dict[str, str] = {}
        # Each write the sandbox refused, by the call whose result says so.
        self._refusals: dict[str, dict[str, Any]] = {}
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
        unlisted = {key: self._calls.get(key, {"tool_name": self._denied_tools.get(key, "?"),
                                               "tool_use_id": key, "tool_input": {}})
                    for key in self._denied if key not in self._denials}
        return [{**denial, **({"reason": self._reasons[key]} if key in self._reasons else {})}
                for key, denial in {**self._denials, **unlisted}.items()]

    @property
    def refusals(self) -> list[dict[str, Any]]:
        """Every write the sandbox refused the run, in order, once per call."""
        return list(self._refusals.values())

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
        if self.unloaded and _is_init(event):
            raise SkillsNotLoaded(
                "Claude Code did not load the workflow's "
                + ("skill " if len(self.unloaded) == 1 else "skills ")
                + ", ".join(self.unloaded) + ", which `change-workflow install` writes into "
                "its user skill directory; the run was stopped before its first turn")
        for item in _tool_uses(event):
            at = self.clock().astimezone(timezone.utc).strftime("%H:%M:%SZ")
            shown = f"{at} {item.get('name', '?')} {tool_summary(item)}".rstrip()
            self._append(self.progress, shown + "\n")
            if self.echo:
                self.echo(shown)

    def take(self, event: dict[str, Any]) -> None:
        """Read an event for the run's session, its results, its denials, and its
        refusals."""
        if isinstance(event.get("session_id"), str):
            self.session = event["session_id"]
        if self.skills and _is_init(event):
            listed = event.get("skills")
            loaded = {name for name in listed if isinstance(name, str)} \
                if isinstance(listed, list) else set()
            self.unloaded = sorted(self.skills - loaded)
        for item in _tool_uses(event):
            if isinstance(item.get("id"), str):
                self.tool_use_ids.add(item["id"])
                given = item.get("input")
                self._calls[item["id"]] = {"tool_name": item.get("name", "?"),
                                           "tool_use_id": item["id"],
                                           "tool_input": given if isinstance(given, dict) else {}}
        for result in _tool_results(event):
            key = result.get("tool_use_id")
            # Only a failed call: a read, or a search, whose output quotes such an
            # error met none.
            if isinstance(key, str) and key not in self._refusals and result.get("is_error") and (
                    error := refused(_result_text(result))):
                self._refusals[key] = _refusal(self._calls.get(key, {}), error)
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
            if isinstance(event.get("tool_use_id"), str):
                self._denied.setdefault(event["tool_use_id"], None)
                if isinstance(event.get("decision_reason_type"), str):
                    self._reasons[event["tool_use_id"]] = event["decision_reason_type"]
                if isinstance(event.get("tool_name"), str):
                    self._denied_tools[event["tool_use_id"]] = event["tool_name"]

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


def transcript_refusals(path: Path) -> list[dict[str, Any]]:
    """The refusals a Claude run's transcript records, gathered as its stream was."""
    return read_transcript(path).refusals
