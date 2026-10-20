"""Denials a step's subagents met, read from their transcripts once the run ends.

The harness streams only the parent session's events, and the `permission_denials`
on its result are the parent's own turn's. A subagent the step spawns keeps its
own transcript beside the session's conversation file, under
`<session>/subagents/agent-<id>.jsonl`, with a `.meta.json` naming its task, and a
call it was denied is recorded there as the tool result whose `permissionDecision`
rejects it. Those denials are read after the run and recorded on its log line
beside the parent's, each naming the subagent it ran in, so the orchestrating
session's reading covers every call the step was denied and not only the parent's.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SUBAGENT_PREFIX = "agent-"


def subagents_directory(conversation: Path) -> Path:
    """Where Claude Code keeps the subagent transcripts of the session whose
    conversation file is `conversation`: a directory of the session's name beside it."""
    return conversation.with_suffix("") / "subagents"


def subagent_denials(conversation: Path) -> list[dict[str, Any]]:
    """Every call a subagent of the session was denied, in transcript order, each
    shaped as the harness shapes the parent's denials and naming its subagent."""
    directory = subagents_directory(conversation)
    if not directory.is_dir():
        return []
    denials: list[dict[str, Any]] = []
    for transcript in sorted(directory.glob(f"{SUBAGENT_PREFIX}*.jsonl")):
        denials.extend(_transcript_denials(transcript))
    return denials


def _description(transcript: Path) -> str | None:
    meta = transcript.with_name(transcript.name[: -len(".jsonl")] + ".meta.json")
    try:
        data = json.loads(meta.read_text("utf-8"))
    except (OSError, ValueError):
        return None
    description = data.get("description") if isinstance(data, dict) else None
    return description if isinstance(description, str) and description else None


def _transcript_denials(transcript: Path) -> list[dict[str, Any]]:
    subagent: dict[str, Any] = {"id": transcript.name[len(SUBAGENT_PREFIX): -len(".jsonl")]}
    if (description := _description(transcript)) is not None:
        subagent["description"] = description
    try:
        lines = transcript.read_text("utf-8").splitlines()
    except OSError:
        return []
    calls: dict[str, dict[str, Any]] = {}
    denials: list[dict[str, Any]] = []
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        message = event.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        items = [i for i in content if isinstance(i, dict)] if isinstance(content, list) else []
        for item in items:
            if item.get("type") == "tool_use" and isinstance(item.get("id"), str):
                calls[item["id"]] = {
                    "tool_name": item.get("name", "?"),
                    "tool_input": item.get("input") if isinstance(item.get("input"), dict) else {},
                }
        decision = event.get("permissionDecision")
        if not (isinstance(decision, dict) and decision.get("decision") == "reject"):
            continue
        for item in items:
            if item.get("type") != "tool_result":
                continue
            key = item.get("tool_use_id")
            call = calls.get(key) if isinstance(key, str) else None
            denial: dict[str, Any] = {"tool_name": call["tool_name"] if call else "?",
                                      "tool_use_id": key,
                                      "tool_input": call["tool_input"] if call else {}}
            # The harness names a reason only for a decision of the permission
            # mode; a call that met a deny rule carries none, as on the parent's.
            if decision.get("reasonType") == "mode":
                denial["reason"] = "mode"
            denial["subagent"] = subagent
            denials.append(denial)
    return denials
