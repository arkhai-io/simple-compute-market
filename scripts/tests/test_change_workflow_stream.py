"""A run's event stream is kept as its transcript, with its progress, and read for
its denials."""

from __future__ import annotations

import json
from pathlib import Path

from change_workflow.stream import Stream, transcript_denials
from change_workflow_fixtures import (CHANGE, DENIED, SESSION, VALID, FakeClaude, clock,
                                      event_lines, make_wrapper, two_turn_lines)


def test_the_stream_is_kept_as_a_numbered_transcript_with_progress(tmp_path: Path) -> None:
    reviews = tmp_path / "openspec/changes" / CHANGE / "reviews"
    (reviews / "transcripts").mkdir(parents=True)
    (reviews / "02-implementation.md").write_text("x", "utf-8")
    (reviews / "transcripts" / "03-design.log").write_text("x", "utf-8")
    lines = event_lines(VALID["finished"], tools=(
        ("Read", {"file_path": "AGENTS.md"}), ("Bash", {"command": "make   test\n -q"})))
    claude = FakeClaude((lines, 0))

    line = make_wrapper(tmp_path, claude).run("implement", CHANGE)

    transcript = reviews / "transcripts" / "04-implement.jsonl"
    assert line["transcript"] == "transcripts/04-implement.jsonl"
    assert transcript.read_text("utf-8") == "".join(lines)
    assert (reviews / "transcripts" / "04-implement.progress").read_text("utf-8") == (
        "09:15:40Z Read AGENTS.md\n09:15:40Z Bash make test -q\n")


def test_each_run_claims_its_own_transcript(tmp_path: Path) -> None:
    claude = FakeClaude((event_lines(VALID["question"]), 0), (event_lines(VALID["finished"]), 0))
    wrapper = make_wrapper(tmp_path, claude)

    first = wrapper.run("design", CHANGE)
    second = wrapper.resume(CHANGE, first["seq"], "Option A.")

    assert (first["transcript"], second["transcript"]) == (
        "transcripts/01-design.jsonl", "transcripts/02-design.jsonl")


def test_lines_that_are_not_events_are_kept_but_not_read(tmp_path: Path) -> None:
    claude = FakeClaude((["warning: slow start\n", *event_lines(VALID["finished"])], 0))

    line = make_wrapper(tmp_path, claude).run("design", CHANGE)

    assert line["outcome"] == "finished"
    transcript = tmp_path / "openspec/changes" / CHANGE / "reviews" / line["transcript"]
    assert transcript.read_text("utf-8").startswith("warning: slow start\n")


def test_the_transcript_follows_its_directory_when_it_is_renamed(tmp_path: Path) -> None:
    # Archiving renames the change's directory while the run is still writing.
    first, second = event_lines(VALID["finished"], tools=(("Bash", {"command": "ls"}),))[1:3]
    before, after = tmp_path / "active", tmp_path / "archived"
    before.mkdir()
    stream = Stream(before / "01-closeout.jsonl", before / "01-closeout.progress", clock)

    stream.feed(first)
    before.rename(after)
    stream.feed(second)
    stream.close()

    assert (after / "01-closeout.jsonl").read_text("utf-8") == first + second
    assert (after / "01-closeout.progress").read_text("utf-8") == "09:15:40Z Bash ls\n"
    assert not before.exists()
    assert stream.result is not None


def test_denials_are_gathered_over_every_turn_with_the_harness_reason(tmp_path: Path) -> None:
    claude = FakeClaude((two_turn_lines(VALID["stopped"], VALID["finished"]), 0))

    line = make_wrapper(tmp_path, claude).run("validate", CHANGE)

    assert line["outcome"] == "finished"
    assert line["denials"] == [{**DENIED, "reason": "mode"}]


def _killed_run_events() -> list[dict]:
    """A run denied a call and was then ended by a signal: no `result` event."""
    return [
        {"type": "system", "subtype": "init", "session_id": SESSION},
        {"type": "assistant", "session_id": SESSION,
         "message": {"content": [{"type": "tool_use", "id": "t1", "name": "Bash",
                                  "input": DENIED["tool_input"]}]}},
        {"type": "system", "subtype": "permission_denied", "session_id": SESSION,
         "tool_use_id": "t1", "decision_reason_type": "rule"},
        {"type": "system", "subtype": "permission_denied", "session_id": SESSION,
         "tool_use_id": "t9", "decision_reason_type": "mode", "tool_name": "Write"},
        {"type": "system", "subtype": "permission_denied", "session_id": SESSION,
         "tool_use_id": "t10", "decision_reason_type": "mode"},
        {"type": "system", "subtype": "permission_denied", "session_id": SESSION,
         "tool_use_id": "t11", "tool_name": "Edit"},
    ]


def test_a_run_ended_without_a_result_keeps_the_denials_its_events_name(tmp_path: Path) -> None:
    transcript = tmp_path / "01-implement.jsonl"
    transcript.write_text("".join(json.dumps(e) + "\n" for e in _killed_run_events()), "utf-8")

    assert transcript_denials(transcript) == [
        {**DENIED, "reason": "rule"},
        {"tool_name": "Write", "tool_use_id": "t9", "tool_input": {}, "reason": "mode"},
        {"tool_name": "?", "tool_use_id": "t10", "tool_input": {}, "reason": "mode"},
        {"tool_name": "Edit", "tool_use_id": "t11", "tool_input": {}},
    ]


def test_a_denial_a_result_lists_is_listed_once(tmp_path: Path) -> None:
    stream = Stream(tmp_path / "01-validate.jsonl", tmp_path / "01-validate.progress", clock)

    for line in two_turn_lines(VALID["stopped"], VALID["finished"]):
        stream.feed(line)
    stream.close()

    assert stream.denials == [{**DENIED, "reason": "mode"}]
