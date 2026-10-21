"""Every run's line records what it cost."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import pytest

from change_workflow.review import review_and_log
from change_workflow_fixtures import (CHANGE, HEAD, LIMIT, NETWORK, SESSION, VALID, FakeClaude,
                                      clock, codex_missing, conversations, event_lines,
                                      failed_run, make_wrapper, repository, review_text,
                                      writing)


def _usage(*, read: int = 0, written: int = 0, given: int = 2, out: int = 100) -> dict:
    return {"input_tokens": given, "output_tokens": out, "cache_read_input_tokens": read,
            "cache_creation_input_tokens": written}


def _costed(outcome: dict | None, *results: tuple[float, dict], session: str = SESSION,
            first_read: int | None = None) -> list[str]:
    """A run whose turns end with `results`, each a session total and that turn's
    usage, its first model call reading `first_read` tokens from the cache."""
    events: list[dict] = [{"type": "system", "subtype": "init", "session_id": session}]
    if first_read is not None:
        events.append({"type": "assistant", "session_id": session,
                       "message": {"content": [], "usage": _usage(read=first_read)}})
    for index, (total, usage) in enumerate(results):
        final = {"type": "result", "subtype": "success", "is_error": False,
                 "session_id": session, "permission_denials": [], "result": "done",
                 "total_cost_usd": total, "usage": usage, "num_turns": 3,
                 "duration_ms": 1500}
        if outcome is not None and index == len(results) - 1:
            final["structured_output"] = outcome
        events.append(final)
    return [json.dumps(event) + "\n" for event in events]


def _conversation(tmp_path: Path, session: str, entries: int, last: str) -> None:
    path = conversations(tmp_path) / f"{session}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps({"type": "user" if n % 2 == 0 else "assistant",
                                        "timestamp": last}) + "\n"
                            for n in range(entries)), "utf-8")


def test_a_fresh_runs_cost_is_its_sessions_total(tmp_path: Path) -> None:
    claude = FakeClaude((_costed(VALID["question"], (5.9, _usage(written=200_000))), 0))

    line = make_wrapper(tmp_path, claude).run("design", CHANGE)

    assert line["cost"] == {"turns": 3, "duration_s": 1.5, "input": 2, "output": 100,
                            "cache_read": 0, "cache_write": 200_000, "usd": 5.9,
                            "session_usd": 5.9}
    assert "gap_s" not in line and "cache_hit" not in line


def test_a_resumed_runs_dollars_are_differenced_and_its_tokens_its_own(tmp_path: Path) -> None:
    claude = FakeClaude((_costed(VALID["question"], (5.9, _usage(written=200_000))), 0),
                        (_costed(VALID["question"], (6.2, _usage(read=250_000)),
                                 first_read=250_000), 0))
    wrapper = make_wrapper(tmp_path, claude)
    asked = wrapper.run("triage", CHANGE)

    line = wrapper.resume(CHANGE, asked["seq"], "accept")

    assert line["cost"]["usd"] == pytest.approx(0.3)
    assert (line["cost"]["cache_read"], line["cost"]["cache_write"]) == (250_000, 0)
    assert line["cost"]["session_usd"] == 6.2
    assert "usd_partial" not in line["cost"]
    assert line["cache_hit"] is True


def test_a_runs_turns_are_summed_over_its_result_events(tmp_path: Path) -> None:
    claude = FakeClaude((_costed(VALID["finished"], (0.5, _usage(out=100)),
                                 (0.8, _usage(out=40))), 0))

    line = make_wrapper(tmp_path, claude).run("validate", CHANGE)

    assert (line["cost"]["output"], line["cost"]["turns"], line["cost"]["duration_s"]) == (
        140, 6, 3.0)
    assert line["cost"]["usd"] == 0.8


def test_a_crashed_predecessor_marks_the_dollars_partial(tmp_path: Path) -> None:
    claude = FakeClaude((_costed(VALID["question"], (1.0, _usage())), 0),
                        (event_lines(result=False), 1),
                        (_costed(VALID["finished"], (2.0, _usage())), 0))
    wrapper = make_wrapper(tmp_path, claude)
    asked = wrapper.run("triage", CHANGE)
    crashed = wrapper.resume(CHANGE, asked["seq"], "accept")

    line = wrapper.resume(CHANGE, crashed["seq"], "go on")

    assert "usd" not in crashed["cost"]
    assert (line["cost"]["usd"], line["cost"]["usd_partial"]) == (1.0, True)


def test_turns_the_wrapper_did_not_run_mark_the_dollars_partial_and_set_the_gap(
        tmp_path: Path) -> None:
    claude = FakeClaude((_costed(VALID["question"], (1.0, _usage())), 0),
                        (_costed(VALID["finished"], (3.0, _usage()), first_read=0), 0))
    wrapper = make_wrapper(tmp_path, claude)
    _conversation(tmp_path, SESSION, 4, "2026-10-21T07:00:00Z")
    asked = wrapper.run("triage", CHANGE)
    # The owner takes the session over for two turns, the last two hours and a
    # quarter before the resume.
    _conversation(tmp_path, SESSION, 6, "2026-10-21T07:00:40Z")

    line = wrapper.resume(CHANGE, asked["seq"], "accept")

    assert asked["cost"]["entries"] == 4
    assert (line["cost"]["usd"], line["cost"]["usd_partial"]) == (2.0, True)
    assert line["gap_s"] == 2 * 3600 + 15 * 60
    assert line["cache_hit"] is False


def test_a_resume_with_no_conversation_file_measures_the_gap_from_the_log(
        tmp_path: Path) -> None:
    claude = FakeClaude((_costed(VALID["question"], (1.0, _usage())), 0),
                        (_costed(VALID["finished"], (1.2, _usage())), 0))
    wrapper = make_wrapper(tmp_path, claude)
    asked = wrapper.run("triage", CHANGE)

    line = wrapper.resume(CHANGE, asked["seq"], "accept")

    assert line["gap_s"] == 0
    assert "cache_hit" not in line


def test_a_codex_review_records_the_tokens_it_reports(tmp_path: Path) -> None:
    root = repository(tmp_path)

    def counting(command: Sequence[str], log: Path) -> int:
        status = writing(review_text())(command, log)
        with log.open("a", encoding="utf-8") as stream:
            stream.write("tokens used\n403,900\n")
        return status

    line = review_and_log(CHANGE, "design", root=root, clock=clock, runner=counting,
                          head=lambda _: HEAD)

    assert line["cost"] == {"tokens": 403_900}


def test_a_run_that_reached_no_model_leaves_its_sessions_total_as_it_was(
        tmp_path: Path) -> None:
    claude = FakeClaude((_costed(VALID["question"], (1.0, _usage())), 0),
                        (failed_run(LIMIT), 1),
                        (_costed(VALID["finished"], (1.4, _usage())), 0))
    wrapper = make_wrapper(tmp_path, claude)
    _conversation(tmp_path, SESSION, 2, "2026-10-21T09:00:00Z")
    asked = wrapper.run("triage", CHANGE)
    limited = wrapper.resume(CHANGE, asked["seq"], "accept")

    line = wrapper.resume(CHANGE, limited["seq"], "accept")

    assert limited["cost"]["session_usd"] == 1.0 and "usd" not in limited["cost"]
    assert line["cost"]["usd"] == pytest.approx(0.4)
    assert "usd_partial" not in line["cost"]


def test_every_attempts_turns_count_toward_the_run(tmp_path: Path) -> None:
    failed = _costed(None, (0.1, _usage(out=7)))
    failed[-1] = failed[-1].replace('"is_error": false', '"is_error": true').replace(
        '"result": "done"', json.dumps({"result": NETWORK})[1:-1])
    claude = FakeClaude((failed, 1), (_costed(VALID["finished"], (0.3, _usage(out=50))), 0))

    line = make_wrapper(tmp_path, claude).run("design", CHANGE)

    assert line["outcome"] == "finished"
    assert (line["cost"]["output"], line["cost"]["turns"]) == (57, 6)


def test_a_rejected_codex_review_still_records_its_tokens(tmp_path: Path) -> None:
    root = repository(tmp_path)

    def rejected(command: Sequence[str], log: Path) -> int:
        status = writing("not a review")(command, log)
        with log.open("a", encoding="utf-8") as stream:
            stream.write("tokens used\n12,000\n")
        return status

    line = review_and_log(CHANGE, "design", root=root, clock=clock, runner=rejected,
                          head=lambda _: HEAD)

    assert line["outcome"] == "stopped"
    assert line["cost"] == {"tokens": 12_000}


def test_a_continued_claude_reviewer_records_its_gap_and_cache_hit(tmp_path: Path) -> None:
    root = repository(tmp_path)

    def reviewing(total: float, read: int) -> FakeClaude:
        events = [{"type": "system", "subtype": "init", "session_id": "c-1"},
                  {"type": "assistant", "session_id": "c-1",
                   "message": {"content": [], "usage": _usage(read=read)}},
                  {"type": "result", "subtype": "success", "is_error": False,
                   "session_id": "c-1", "result": review_text(), "permission_denials": [],
                   "total_cost_usd": total, "usage": _usage(read=read), "num_turns": 4,
                   "duration_ms": 9_000}]
        return FakeClaude(([json.dumps(event) + "\n" for event in events], 0))

    first = review_and_log(CHANGE, "design", root=root, clock=clock,
                           runner=codex_missing, claude=reviewing(4.0, 0),
                           head=lambda _: HEAD, echo=None)
    later = datetime(2026, 10, 21, 11, 15, 40, tzinfo=timezone.utc)
    second = review_and_log(CHANGE, "design", root=root, clock=lambda: later,
                            runner=codex_missing, claude=reviewing(4.9, 300_000),
                            head=lambda _: HEAD, echo=None)

    assert "gap_s" not in first
    assert second["cost"]["usd"] == pytest.approx(0.9)
    assert (second["gap_s"], second["cache_hit"]) == (7200, True)


def test_a_claude_reviews_cost_is_recorded_from_its_transcript(tmp_path: Path) -> None:
    root = repository(tmp_path)
    events = [{"type": "system", "subtype": "init", "session_id": "c-1"},
              {"type": "result", "subtype": "success", "is_error": False, "session_id": "c-1",
               "result": review_text(), "permission_denials": [], "total_cost_usd": 4.5,
               "usage": _usage(written=90_000), "num_turns": 9, "duration_ms": 60_000}]
    claude = FakeClaude(([json.dumps(event) + "\n" for event in events], 0))

    line = review_and_log(CHANGE, "design", root=root, clock=clock, runner=codex_missing,
                          claude=claude, head=lambda _: HEAD, echo=None)

    assert (line["cost"]["usd"], line["cost"]["cache_write"], line["cost"]["turns"]) == (
        4.5, 90_000, 9)
    assert "cache_hit" not in line
