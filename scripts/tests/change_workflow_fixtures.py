"""What the workflow tooling's tests share: a change, the outcomes its steps end
with, fake harnesses that replay a run, and reviews to publish."""

from __future__ import annotations

import errno
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from change_workflow.steps import Model
from change_workflow.wrapper import Wrapper

CHANGE = "shape-bounds"
COMMIT = "7f3c6e90"
AT = datetime(2026, 10, 21, 9, 15, 40, tzinfo=timezone.utc)
# The commit each review is told it reviews; HEAD is injected, never read from Git.
HEAD = "0123456789abcdef0123456789abcdef01234567"
SESSION = "9c07d1e2-0000-4000-8000-000000000000"

VALID = {
    "finished": {"outcome": "finished", "message": "The sections are committed.", "next": "triage"},
    "question": {"outcome": "question", "message": "Delete the volume?", "awaiting": "remedy"},
    "returned": {"outcome": "returned", "message": "Needs a decision.", "return_to": "design",
                 "evidence": "the section's notes"},
    "blocked": {"outcome": "blocked", "message": "Waits on its prerequisite.",
                "blocked_on": "split-pools"},
    "stopped": {"outcome": "stopped", "message": "Denied make lock.", "reason": "denied",
                "denials": [{"tool_name": "Bash", "tool_input": {"command": "make lock"}}]},
}

OPUS = Model("claude", "claude-opus-5-5", "high")
SONNET = Model("claude", "claude-sonnet-5-5", "medium")

LIMIT = "You've hit your session limit · resets 11:20pm (Europe/Paris)"
NETWORK = "API Error: Can't reach the API server — check your internet or DNS (EAI_AGAIN)"

# A run denied a call can still end with a question or a return, so the reading
# of its denials is recorded apart from the decision that settles its outcome.
DENIALS = [{"tool_name": "Bash", "tool_input": {"command": "gh run view 1"}, "reason": "mode"}]
# The run id is a fixture value, not a pipeline run.
DENIED = {"tool_name": "Bash", "tool_use_id": "t1",
          "tool_input": {"command": "gh run view 123456 --json headSha"}}

FINDING = """### F1 — The override has no carrier

- **Lens:** architecture
- **Basis:** evidence
- **Severity:** blocking
- **Evidence:** `kit/pool-overrides/records.py:43`

The record has no field for it.

**Suggested action:** Choose one.
"""


def clock() -> datetime:
    return AT


def log_file(tmp_path: Path) -> Path:
    directory = tmp_path / "openspec/changes" / CHANGE
    directory.mkdir(parents=True)
    return directory / "reviews" / "workflow.jsonl"


# Running a step: the wrapper's command, its stream, and the outcome it logs.

def event_lines(outcome: dict | None = None, *, denials: list | None = None,
                tools: tuple[tuple[str, dict], ...] = (), result: bool = True,
                is_error: bool = False, session: str = SESSION) -> list[str]:
    events: list[dict] = [{"type": "system", "subtype": "init", "session_id": session}]
    for name, given in tools:
        events.append({"type": "assistant", "session_id": session,
                       "message": {"content": [{"type": "tool_use", "name": name,
                                                "input": given}]}})
    if result:
        final = {"type": "result", "subtype": "error_during_execution" if is_error else "success",
                 "is_error": is_error, "session_id": session,
                 "permission_denials": denials or [], "result": "done"}
        if outcome is not None:
            final["structured_output"] = outcome
        events.append(final)
    return [json.dumps(event) + "\n" for event in events]


class FakeClaude:
    """Stands in for `claude -p`: records each command and replays a stream."""

    def __init__(self, *runs: tuple[list[str], int]) -> None:
        self.runs = list(runs)
        self.commands: list[list[str]] = []

    def __call__(self, command, cwd: Path, feed) -> int:
        self.commands.append(list(command))
        lines, status = self.runs.pop(0)
        for line in lines:
            feed(line)
        return status


def conversations(tmp_path: Path) -> Path:
    """Where the tests keep Claude Code's conversation files, never the owner's own."""
    return tmp_path / "conversations"


def make_wrapper(tmp_path: Path, claude: FakeClaude) -> Wrapper:
    (tmp_path / "openspec/changes" / CHANGE).mkdir(parents=True, exist_ok=True)
    return Wrapper(root=tmp_path, runner=claude, head=lambda _: COMMIT, clock=clock,
                   echo=None,
                   conversation=lambda _, session: conversations(tmp_path) / f"{session}.jsonl",
                   runs=lambda _: None)


def option(command: list[str], flag: str) -> str:
    return command[command.index(flag) + 1]


def option_rules(command: list[str], flag: str) -> list[str]:
    start = command.index(flag) + 1
    end = next((i for i in range(start, len(command)) if command[i].startswith("--")),
               len(command))
    return command[start:end]


def failed_run(said: str) -> list[str]:
    """A run Claude Code ended with an error result saying `said`."""
    return [json.dumps({"type": "system", "subtype": "init", "session_id": SESSION}) + "\n",
            json.dumps({"type": "result", "subtype": "success", "is_error": True,
                        "session_id": SESSION, "result": said,
                        "permission_denials": []}) + "\n"]


def two_turn_lines(first: dict, second: dict) -> list[str]:
    """A run denied a call in its first turn, woken for a second by a background
    task finishing: two result events, only the first listing the denial."""
    def assistant(id_: str, name: str, given: dict) -> dict:
        return {"type": "assistant", "session_id": SESSION,
                "message": {"content": [{"type": "tool_use", "id": id_, "name": name,
                                         "input": given}]}}

    def result(outcome: dict, denials: list) -> dict:
        return {"type": "result", "subtype": "success", "is_error": False,
                "session_id": SESSION, "permission_denials": denials, "result": "done",
                "structured_output": outcome}

    events = [
        {"type": "system", "subtype": "init", "session_id": SESSION},
        assistant("t1", "Bash", DENIED["tool_input"]),
        {"type": "system", "subtype": "permission_denied", "session_id": SESSION,
         "tool_use_id": "t1", "decision_reason_type": "mode"},
        result(first, [DENIED]),
        {"type": "system", "subtype": "task_notification", "session_id": SESSION},
        assistant("t2", "Bash", {"command": "tail -n 20 local/1/test.log"}),
        result(second, []),
    ]
    return [json.dumps(event) + "\n" for event in events]


# Reviews: run read-only in Codex, published only when they are reviews.

def review_text(kind: str = "design", findings: str = FINDING) -> str:
    return (f"# {kind.capitalize()} review — {CHANGE}\n\n## Summary\n\nWhat it does.\n\n"
            "## Assessment\n\nSound.\n\n## Questions\n\n### consistency — Is it consistent?\n\n"
            f"Yes.\n\n## Findings\n\n{findings}\n## Readiness\n\nNot yet.\n")


def repository(tmp_path: Path, *records: str) -> Path:
    reviews = tmp_path / "openspec/changes" / CHANGE / "reviews"
    reviews.mkdir(parents=True)
    for name in records:
        (reviews / name).parent.mkdir(parents=True, exist_ok=True)
        (reviews / name).write_text("x", "utf-8")
    return tmp_path


def writing(text: str, status: int = 0, calls: list[list[str]] | None = None,
            session: str = "s-1"):
    def runner(command: Sequence[str], log: Path) -> int:
        if calls is not None:
            calls.append(list(command))
        log.write_text(f"--------\nsession id: {session}\n--------\nsession output\n", "utf-8")
        Path(command[command.index("--output-last-message") + 1]).write_text(text, "utf-8")
        return status
    return runner


def reviews_of(root: Path) -> Path:
    return root / "openspec/changes" / CHANGE / "reviews"


def claude_review(text: str, session: str = "c-1", denials: list | None = None) -> FakeClaude:
    """Claude Code ending a review run with `text` as its final message."""
    events = [{"type": "system", "subtype": "init", "session_id": session},
              {"type": "result", "subtype": "success", "is_error": False, "session_id": session,
               "result": text, "permission_denials": denials or []}]
    return FakeClaude(([json.dumps(event) + "\n" for event in events], 0))


def codex_saying(said: str, status: int = 1):
    def runner(command: Sequence[str], log: Path) -> int:
        with log.open("a", encoding="utf-8") as stream:
            stream.write(f"OpenAI Codex v0.157.0\n{said}\n")
        return status
    return runner


def not_installed(program: str) -> FileNotFoundError:
    """What launching `program` raises when it is not installed: an error naming it."""
    return FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), program)


def codex_missing(command: Sequence[str], log: Path) -> int:
    raise not_installed("codex")


# A validated ancestor of HEAD, and where the change's records live.
VALIDATED = "f" * 40
RECORDS = f"openspec/changes/{CHANGE}"


def validation_text(commit: str, result: str) -> str:
    return (f"# Validation — {CHANGE} — {commit[:12]}\n\n- **Commit:** {commit} on feat/x\n"
            f"- **Result:** {result} — why\n")
