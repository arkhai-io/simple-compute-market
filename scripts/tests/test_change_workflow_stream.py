"""A run's event stream is kept as its transcript, with its progress, and read for
its denials."""

from __future__ import annotations

from pathlib import Path

from change_workflow.stream import Stream
from change_workflow_fixtures import (CHANGE, DENIED, VALID, FakeClaude, clock, event_lines,
                                      make_wrapper, two_turn_lines)


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
