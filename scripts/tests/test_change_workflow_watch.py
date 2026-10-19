"""A change's steps are followed as they run, and a run's denials are reported with
the calls it made after each."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from change_workflow.cli import main
from change_workflow.log import log_path, record_outcome
from change_workflow.watch import watch
from change_workflow_fixtures import (CHANGE, COMMIT, VALID, FakeClaude, event_lines,
                                      make_wrapper, two_turn_lines)


def test_a_runs_denials_are_listed_with_the_calls_after_each(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    claude = FakeClaude((two_turn_lines(VALID["stopped"], VALID["finished"]), 0))
    make_wrapper(tmp_path, claude).run("validate", CHANGE)

    assert main(["denials", CHANGE, "1"], root=tmp_path) == 0

    assert capsys.readouterr().out.splitlines() == [
        "denied: Bash gh run view 123456 --json headSha (mode)",
        "  calls after it:",
        "    Bash tail -n 20 local/1/test.log",
    ]


def test_a_run_without_denials_or_without_a_transcript_says_so(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    claude = FakeClaude((event_lines(VALID["finished"]), 0))
    make_wrapper(tmp_path, claude).run("design", CHANGE)
    log = log_path(tmp_path, CHANGE)
    # A review's line has no transcript to read: Codex's session is its own log.
    record_outcome(log, "review", {**VALID["stopped"], "denials": []}, session=None,
                   commit=COMMIT, extra={"kind": "design"})
    record_outcome(log, "review", VALID["stopped"], session=None, commit=COMMIT,
                   extra={"kind": "design"})

    assert main(["denials", CHANGE, "1"], root=tmp_path) == 0
    assert capsys.readouterr().out == "seq 1: the design run recorded no denial\n"
    assert main(["denials", CHANGE, "2"], root=tmp_path) == 0
    assert capsys.readouterr().out == "seq 2: the review run recorded no denial\n"
    assert main(["denials", CHANGE, "3"], root=tmp_path) == 1
    assert "no transcript" in capsys.readouterr().err
    assert main(["denials", CHANGE, "9"], root=tmp_path) == 1
    assert "no seq 9" in capsys.readouterr().err


def test_watch_follows_the_newest_progress_file(tmp_path: Path) -> None:
    transcripts = tmp_path / "transcripts"
    transcripts.mkdir()
    first = transcripts / "03-validate.progress"
    first.write_text("".join(f"line {n}\n" for n in range(12)), "utf-8")
    shown: list[str] = []
    polls = iter(range(10))

    def tick(_: float) -> None:
        n = next(polls)
        if n == 0:
            with first.open("a", encoding="utf-8") as stream:
                stream.write("line 12\n")
        elif n == 1:
            second = transcripts / "04-triage.progress"
            second.write_text("triage 0\n", "utf-8")
            os.utime(second, ns=(first.stat().st_mtime_ns + 1,) * 2)

    watch(tmp_path, echo=shown.append, sleep=tick, polls=3)
    assert shown == ["== 03-validate.progress", *(f"line {n}" for n in range(2, 12)),
                     "line 12", "== 04-triage.progress", "triage 0"]


def test_watch_waits_for_a_first_progress_file(tmp_path: Path) -> None:
    shown: list[str] = []
    watch(tmp_path, echo=shown.append, sleep=lambda _: None, polls=2)
    assert shown == []
