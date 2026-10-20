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
from typing import Any, Collection

SUBAGENT_PREFIX = "agent-"


def subagents_directory(conversation: Path) -> Path:
    """Where Claude Code keeps the subagent transcripts of the session whose
    conversation file is `conversation`: a directory of the session's name beside it."""
    return conversation.with_suffix("") / "subagents"


def subagent_denials(conversation: Path, spawned: Collection[str] | None = None
                     ) -> list[dict[str, Any]]:
    """Every call a subagent of the session was denied, in transcript order, each
    shaped as the harness shapes the parent's denials and naming its subagent.

    A session's directory holds the subagents of every run of that session, so a
    resumed run passes `spawned`, the tool-use ids of its own turn, and only the
    subagents those calls started are read; their earlier runs' subagents were
    read on their own lines. A subagent whose record names no starting call is
    then left out rather than guessed at.
    """
    directory = subagents_directory(conversation)
    if not directory.is_dir():
        return []
    denials: list[dict[str, Any]] = []
    for transcript in sorted(directory.glob(f"{SUBAGENT_PREFIX}*.jsonl")):
        meta = _meta(transcript)
        if spawned is not None and meta.get("toolUseId") not in spawned:
            continue
        denials.extend(_transcript_denials(transcript, meta))
    return denials


def _meta(transcript: Path) -> dict[str, Any]:
    """The subagent's record beside its transcript: its task and the call that
    started it, or nothing when the harness wrote none."""
    meta = transcript.with_name(transcript.name[: -len(".jsonl")] + ".meta.json")
    try:
        data = json.loads(meta.read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _transcript_denials(transcript: Path, meta: dict[str, Any]) -> list[dict[str, Any]]:
    subagent: dict[str, Any] = {"id": transcript.name[len(SUBAGENT_PREFIX): -len(".jsonl")]}
    description = meta.get("description")
    if isinstance(description, str) and description:
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
