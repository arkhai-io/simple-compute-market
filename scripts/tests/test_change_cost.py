"""A change's runs are reported by what they cost, by step and by round."""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from change_workflow.log import log_path, note_round, read_log, record_outcome

SCRIPTS = Path(__file__).resolve().parents[1]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Registered before it runs: its dataclasses look their module up by name.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


cost = _load("change_cost")

CHANGE = "shape-bounds"
COMMIT = "7f3c6e90"
FINISHED = {"outcome": "finished", "message": "Done.", "next": "next", "denials": []}


def _clock() -> datetime:
    return datetime(2026, 10, 21, 9, 15, 40, tzinfo=timezone.utc)


def _log(tmp_path: Path) -> Path:
    (tmp_path / "openspec/changes" / CHANGE).mkdir(parents=True)
    return log_path(tmp_path, CHANGE)


def _run(log: Path, name: str, usd: float | None = None, *, partial: bool = False,
         tokens: int | None = None, **extra) -> None:
    spent: dict = {"turns": 2, "duration_s": 60.0, "input": 1, "output": 10,
                   "cache_read": 1000, "cache_write": 100}
    if usd is not None:
        spent["usd"] = usd
    if partial:
        spent["usd_partial"] = True
    if tokens is not None:
        spent = {"tokens": tokens}
    record_outcome(log, name, FINISHED, session="s", commit=COMMIT,
                   extra={"cost": spent, **extra}, clock=_clock)


def _fixture(tmp_path: Path) -> Path:
    log = _log(tmp_path)
    _run(log, "design", 6.0)
    _run(log, "design", 0.5, gap_s=7200, cache_hit=False)
    _run(log, "review", tokens=400_000, kind="design")
    note_round(log, [[1, 2]], "plan", after=3, clock=_clock)
    _run(log, "implement", 9.0)
    _run(log, "triage", 2.0, partial=True)
    note_round(log, [[3]], "plan", after=8, clock=_clock)
    _run(log, "implement", 4.0)
    _run(log, "review", tokens=300_000, kind="pre-closeout")
    _run(log, "closeout", 3.0)
    return log


def test_lines_are_bucketed_by_the_round_in_force() -> None:
    log = [{"seq": 1, "step": "design"},
           {"seq": 2, "step": "orchestrator", "outcome": "round", "sections": [[1, 2]]},
           {"seq": 3, "step": "implement"},
           {"seq": 4, "step": "orchestrator", "outcome": "orchestrator"},
           {"seq": 5, "step": "orchestrator", "outcome": "round", "sections": [[3], [4]]},
           {"seq": 6, "step": "triage"},
           # Refused before it ran, for want of a passing validation.
           {"seq": 7, "step": "review", "kind": "pre-closeout", "outcome": "stopped"},
           {"seq": 8, "step": "validate"},
           {"seq": 9, "step": "review", "kind": "pre-closeout", "outcome": "finished"},
           {"seq": 10, "step": "triage"}]

    assert [(entry["seq"], label) for entry, label in cost.rounds(log)] == [
        (1, "design and planning"), (3, "round 1 (1,2)"), (6, "round 2 (3; 4)"),
        (7, "round 2 (3; 4)"), (8, "round 2 (3; 4)"), (9, "closeout"), (10, "closeout")]


def test_the_report_totals_by_step_and_round_with_partial_dollars_as_a_range(
        tmp_path: Path) -> None:
    lines = cost.report(read_log(_fixture(tmp_path)))

    def row(name: str, section: str) -> str:
        start = lines.index(section)
        return next(line for line in lines[start:] if line.strip().startswith(name))

    assert "$6.50" in row("design", "By step:")
    assert "codex 700k" in row("review", "By step:")
    assert "$0.00–$2.00" in row("triage", "By step:")
    assert "$6.50" in row("design and planning", "By round:")
    assert "$9.00–$11.00" in row("round 1 (1,2)", "By round:")
    assert "$4.00" in row("round 2 (3)", "By round:")
    assert "$3.00" in row("closeout", "By round:")
    assert "$22.50–$24.50" in row("all runs", "Total:")
    assert "$0.50" in row("resumed, cache missed", "By cache:")
    assert "$22.00–$24.00" in row("session openings", "By cache:")
    assert "runs 0" in row("resumed, cache warm", "By cache:")


def test_the_cache_misses_are_listed_with_their_gaps(tmp_path: Path) -> None:
    lines = cost.report(read_log(_fixture(tmp_path)))

    misses = lines[lines.index("Cache misses:") + 1:]
    assert len(misses) == 1
    assert "seq 2" in misses[0] and "design" in misses[0]
    assert "gap 2h00m" in misses[0] and "$0.50" in misses[0]


def test_a_log_without_costs_reports_no_misses(tmp_path: Path) -> None:
    log = _log(tmp_path)
    record_outcome(log, "design", FINISHED, session="s", commit=COMMIT, clock=_clock)

    lines = cost.report(read_log(log))

    assert lines[-1] == "  none recorded"


def test_the_command_prints_the_report_and_refuses_an_unknown_change(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _fixture(tmp_path)

    assert cost.main([CHANGE], root=tmp_path) == 0
    assert capsys.readouterr().out.startswith("By step:\n")
    assert cost.main(["missing"], root=tmp_path) == 1
    assert "ERROR" in capsys.readouterr().err


def test_a_cleaned_up_change_is_reported_from_its_archived_records(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    archived = tmp_path / "openspec/changes/archive" / f"2026-10-24-{CHANGE}"
    (archived / "reviews").mkdir(parents=True)
    _run(archived / "reviews/workflow.jsonl", "design", 6.0)
    # The workspace's branch carries the change's active directory, without records.
    (tmp_path / "openspec/changes" / CHANGE).mkdir()

    assert cost.main([CHANGE], root=tmp_path) == 0
    assert "all runs                           runs 1 " in capsys.readouterr().out
