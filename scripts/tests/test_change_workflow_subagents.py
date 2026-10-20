"""A run's denials include the calls its subagents were denied, read from their
transcripts beside the session's conversation file once the run ends."""

from __future__ import annotations

import json
from pathlib import Path

from change_workflow.log import record_outcome
from change_workflow.outcome import load_schema
from change_workflow.subagents import subagent_denials, subagents_directory
from change_workflow.watch import denial_report
from change_workflow_fixtures import (CHANGE, SESSION, VALID, FakeClaude, clock, conversations,
                                      event_lines, make_wrapper)

AGENT = "a380bfa5164895f6a"


def _use(tool_id: str, command: str) -> str:
    return json.dumps({"type": "assistant", "agentId": AGENT, "message": {
        "role": "assistant", "content": [
            {"type": "tool_use", "id": tool_id, "name": "Bash", "input": {"command": command}}]}})


def _result(tool_id: str, decision: dict | None) -> str:
    event = {"type": "user", "agentId": AGENT, "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": tool_id, "content": "Permission denied"}]}}
    if decision is not None:
        event["permissionDecision"] = decision
    return json.dumps(event)


def write_subagent(conversation: Path, lines: list[str], description: str | None = None,
                   agent: str = AGENT, started_by: str | None = None) -> Path:
    directory = subagents_directory(conversation)
    directory.mkdir(parents=True, exist_ok=True)
    transcript = directory / f"agent-{agent}.jsonl"
    transcript.write_text("\n".join(lines) + "\n", "utf-8")
    meta: dict = {}
    if description is not None:
        meta["description"] = description
    if started_by is not None:
        meta["toolUseId"] = started_by
    if meta:
        (directory / f"agent-{agent}.meta.json").write_text(json.dumps(meta), "utf-8")
    return transcript


def test_a_subagent_transcript_yields_its_denials_shaped_like_the_parents(tmp_path: Path) -> None:
    conversation = tmp_path / f"{SESSION}.jsonl"
    write_subagent(conversation, [
        _use("t-1", "sleep 5"),
        _result("t-1", {"decision": "reject", "source": "config", "reasonType": "mode"}),
        _use("t-2", "git push"),
        _result("t-2", {"decision": "reject", "source": "config", "reasonType": "rule"}),
        _use("t-3", "ls"),
        _result("t-3", {"decision": "allow", "source": "config"}),
        _use("t-4", "cat x"),
        _result("t-4", None),
    ], description="Verify the claims")

    denials = subagent_denials(conversation)

    assert denials == [
        {"tool_name": "Bash", "tool_use_id": "t-1", "tool_input": {"command": "sleep 5"},
         "reason": "mode", "subagent": {"id": AGENT, "description": "Verify the claims"}},
        {"tool_name": "Bash", "tool_use_id": "t-2", "tool_input": {"command": "git push"},
         "subagent": {"id": AGENT, "description": "Verify the claims"}},
    ]


def test_no_subagent_directory_means_no_denials(tmp_path: Path) -> None:
    assert subagent_denials(tmp_path / f"{SESSION}.jsonl") == []


def _spawn(tool_id: str) -> str:
    return json.dumps({"type": "assistant", "session_id": SESSION, "message": {
        "role": "assistant", "content": [
            {"type": "tool_use", "id": tool_id, "name": "Agent", "input": {"prompt": "verify"}}]}})


def test_a_runs_line_carries_the_denials_of_the_subagents_it_started(tmp_path: Path) -> None:
    parent = {"tool_name": "Bash", "tool_use_id": "p-1", "tool_input": {"command": "make lock"}}
    claude = FakeClaude(([_spawn("spawn-1") + "\n"]
                         + event_lines(VALID["finished"], denials=[parent]), 0))
    conversation = conversations(tmp_path) / f"{SESSION}.jsonl"
    write_subagent(conversation, [
        _use("s-1", "sleep 5"),
        _result("s-1", {"decision": "reject", "source": "config", "reasonType": "mode"}),
    ], description="Verify F3", started_by="spawn-1")
    # The same session's earlier run started another subagent, read on its own line.
    write_subagent(conversation, [
        _use("e-1", "awk 1 x"),
        _result("e-1", {"decision": "reject", "source": "config", "reasonType": "mode"}),
    ], description="Earlier run", agent="aaaaaaaaaaaaaaaaa", started_by="spawn-0")
    # One with no record of what started it is left out rather than guessed at.
    write_subagent(conversation, [
        _use("u-1", "sed -i x"),
        _result("u-1", {"decision": "reject", "source": "config", "reasonType": "mode"}),
    ], agent="bbbbbbbbbbbbbbbbb")

    line = make_wrapper(tmp_path, claude).run("triage", CHANGE)

    assert line["denials"] == [parent, {
        "tool_name": "Bash", "tool_use_id": "s-1", "tool_input": {"command": "sleep 5"},
        "reason": "mode", "subagent": {"id": AGENT, "description": "Verify F3"}}]


def test_without_a_spawned_set_every_subagent_is_read(tmp_path: Path) -> None:
    conversation = tmp_path / f"{SESSION}.jsonl"
    write_subagent(conversation, [
        _use("u-1", "sleep 1"),
        _result("u-1", {"decision": "reject", "source": "config", "reasonType": "mode"}),
    ])

    assert [d["tool_use_id"] for d in subagent_denials(conversation)] == ["u-1"]


def test_the_denial_report_names_the_subagent_instead_of_listing_later_calls(tmp_path: Path) -> None:
    reviews = tmp_path / "reviews"
    (reviews / "transcripts").mkdir(parents=True)
    (reviews / "transcripts" / "01-triage.jsonl").write_text(
        json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "p-1", "name": "Read", "input": {"file_path": "a.md"}}]}})
        + "\n", "utf-8")
    entry = record_outcome(
        reviews / "workflow.jsonl", "triage",
        {"outcome": "finished", "message": "done", "next": "x",
         "denials": [{"tool_name": "Bash", "tool_use_id": "s-1",
                      "tool_input": {"command": "sleep 5"}, "reason": "mode",
                      "subagent": {"id": AGENT, "description": "Verify F3"}}]},
        session=SESSION, commit="c", extra={"transcript": "transcripts/01-triage.jsonl"},
        schema=load_schema(), clock=clock)

    shown = denial_report(reviews, entry)

    assert shown == ["denied in subagent 'Verify F3': Bash sleep 5 (mode)",
                     "  its later calls are in the subagent's own transcript"]
