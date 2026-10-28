"""A change's records are converted to the workflow log's format on the owner's
confirmation, ending with the owner's direction to where the change stands."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import pytest

import change_next_step as nxt
from change_workflow.cli import main
from change_workflow.common import StepError
from change_workflow.convert import (ADVANCE, ANOTHER_ROUND, OTHER, RETURNED, convert_change,
                                     read_triage, rewritten)
from change_workflow.log import FORMAT, log_path, read_log, record_interactive, record_outcome
from change_workflow_fixtures import CHANGE, HEAD, clock, descriptors_of

TASKS = """## 1. First

- [x] 1.1 Done.

## 2. Second

- [ ] 2.1 Open.

## 3. Closeout

- [ ] 3.1 Archive.
"""
LAST_ROUND_DONE = TASKS.replace("- [ ] 2.1", "- [x] 2.1")
# The review kind the design records below are named for.
KIND = "design"
# What HEAD changed since a commit a record names: a fix in code.
SEAMS = {"head": lambda _: HEAD, "changed_since": lambda *_: ["scripts/change_next_step.py"]}
QUESTION = {"outcome": "question", "message": "Which option?", "awaiting": "a choice"}


def _repository(tmp_path: Path, status: str = "in design", tasks: str = TASKS) -> Path:
    directory = tmp_path / "openspec/changes" / CHANGE
    (directory / "reviews").mkdir(parents=True)
    (directory / nxt.TASKS_FILE).write_text(tasks, "utf-8")
    (tmp_path / "openspec/changes/README.md").write_text(
        "| Change | Status | Depends on | Notes | Acceptance boundary |\n|---|---|---|---|---|\n"
        f"| [`{CHANGE}`]({CHANGE}/) | {status} | — | the notes | x |\n", "utf-8")
    return tmp_path


def _reviews(root: Path) -> Path:
    return root / "openspec/changes" / CHANGE / "reviews"


def _design(number: str) -> str:
    """A design review's record, by its number."""
    return f"{number}-{KIND}.md"


def _log(root: Path) -> Path:
    return log_path(root, CHANGE)


def _record(root: Path, name: str, next_words: str | None = None, *,
            triage: str | None = None, text: str = "x") -> None:
    """A numbered record, and its triage file: one ending with `## Next` and
    `next_words`, or holding `triage` as it is."""
    (_reviews(root) / name).write_text(text, "utf-8")
    if next_words is not None:
        triage = f"# Triage\n\n### F1 — x\n\n## Next\n\n{next_words}\n"
    if triage is not None:
        (_reviews(root) / name.replace(".md", ".triage.md")).write_text(triage, "utf-8")


def _older(root: Path, *lines: dict) -> list[dict]:
    """Lines as the older tooling appended them, numbered after the log's last and
    without the log's format."""
    path = _log(root)
    seq = max((entry["seq"] for entry in read_log(path)), default=0)
    written = []
    with path.open("a", encoding="utf-8") as stream:
        for line in lines:
            seq += 1
            written.append({"seq": seq, "at": "2026-10-20T10:00:00Z", **line})
            stream.write(json.dumps(written[-1]) + "\n")
    return written


def _run(step: str, outcome: str = "finished", **fields) -> dict:
    """An older run's line: its prose `next` on a finished outcome."""
    line = {"step": step, "session": "s", "commit": HEAD, "outcome": outcome,
            "message": f"The {step} ran."}
    if outcome == "finished":
        line["next"] = f"What follows the {step}."
    return {**line, **fields}


def _review_run(name: str) -> dict:
    kind = name.split("-", 1)[1].removesuffix(".md")
    return _run("review", kind=kind, record=name, next="triage", session="codex:x")


def _decision(by: str = "owner", **fields) -> dict:
    return {"step": "orchestrator", "outcome": "orchestrator", "by": by, "decision": "decided",
            "reason": "a reason", **fields}


def _convert(root: Path, **options) -> list[str]:
    return convert_change(root, CHANGE, clock=clock, **SEAMS, **options)


def _interrupted(new: Path, old: Path) -> None:
    """A replacement stopped before its rename."""
    raise OSError("interrupted before the rename")


def _next(root: Path) -> dict:
    return nxt.compute(root, CHANGE, view=lambda _: None, uncommitted=lambda *_: False,
                       branch=lambda _: f"feat/{CHANGE}", workspace=lambda _: None,
                       clone=lambda *_: None, merging=lambda _: False, **SEAMS)


def _design_reviewed(root: Path) -> list[dict]:
    """A change in design whose two design reviews were triaged, the latest
    recording another round, with an older repeat-review decision between them."""
    _record(root, _design("13"), "Advance — rejected by the owner later.")
    _record(root, _design("21"), "Another round: the reviewer reads the fix.")
    return _older(root, _run("design"), _review_run(_design("13")), _run("triage"),
                  _decision(by="orchestrator", next="review", kind="design"),
                  _review_run(_design("21")), _run("triage"))


# The conversion's three parts.

def test_a_change_is_converted(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    older = _design_reviewed(root)
    assert _next(root)["convert"] == f"python3 scripts/run_change_step.py convert {CHANGE}"

    shown = _convert(root)

    assert read_log(_log(root)) == older
    assert any(line.startswith('proposed direction: {"step": "review", "kind": "design"}')
               for line in shown)
    written = [json.loads(line) for line in _convert(root, confirm=True)]
    lines = read_log(_log(root))
    assert [line["seq"] for line in lines] == [*range(1, 7), 7, 8]
    assert all(line["format"] == FORMAT for line in lines)
    assert lines[3]["next"] == {"step": "review", "kind": "design"} and "kind" not in lines[3]
    assert lines[2]["message"] == "The triage ran.\n\nNext: What follows the triage."
    assert "next" not in lines[2] and "next" not in lines[4]
    conversion, direction = lines[-2:]
    assert written == [conversion, direction]
    assert (conversion["step"], conversion["outcome"], conversion["triaged"]) == (
        "convert", "converted", ["13-design", "21-design"])
    assert "next" not in conversion
    assert (direction["by"], direction["next"]) == ("owner", {"step": "review", "kind": "design"})
    assert _next(root)["step"] == "review" and _next(root)["kind"] == "design"


def test_a_change_with_records_and_no_log_gains_its_log(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    _record(root, _design("03"), "Advance to planning.")
    assert _next(root)["step"] == "owner" and "convert" in _next(root)

    _convert(root, confirm=True)

    conversion, direction = read_log(_log(root))
    assert conversion["triaged"] == ["03-design"]
    assert direction["next"] == {"step": "plan"}
    assert _next(root)["step"] == "plan"


def test_a_change_already_converted_is_refused(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    _design_reviewed(root)
    _convert(root, confirm=True)
    converted = _log(root).read_text("utf-8")

    with pytest.raises(StepError, match="format already"):
        _convert(root, confirm=True)

    assert _log(root).read_text("utf-8") == converted


def test_a_change_is_converted_with_a_triage_in_progress(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    _design_reviewed(root)
    _record(root, _design("30"), triage="# Triage\n\n### F1 — x\n\nAccepted.\n")
    older = _log(root).read_text("utf-8")

    with pytest.raises(StepError, match="triage of 30-design is in progress") as refused:
        _convert(root, confirm=True)

    assert "record" in str(refused.value) and "on the code it started with" in str(refused.value)
    assert _log(root).read_text("utf-8") == older
    assert _next(root)["step"] == "owner" and "convert" in _next(root)


def test_a_refused_or_interrupted_conversion_of_a_change_with_no_log_writes_none(
        tmp_path: Path) -> None:
    root = _repository(tmp_path)
    _record(root, _design("03"), triage="# Triage\n\nAccepted.\n")

    with pytest.raises(StepError, match="in progress"):
        _convert(root, confirm=True)
    _record(root, _design("03"), "Advance to planning.")
    with pytest.raises(OSError, match="interrupted"):
        _convert(root, confirm=True, replace=_interrupted)

    assert not _log(root).exists()
    assert "convert" in _next(root)


def test_a_triage_its_recorded_outcome_names_is_not_in_progress(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    _design_reviewed(root)
    _record(root, _design("30"), triage="# Triage\n\nAccepted.\n")
    record_interactive(_log(root), "triage", {
        "outcome": "finished", "message": "Triaged.", "next": {"step": "plan"},
        "triaged": ["30-design"]}, session="s", commit=HEAD, clock=clock)

    _convert(root, confirm=True)

    assert read_log(_log(root))[-2]["triaged"] == ["13-design", "21-design", "30-design"]
    assert _next(root)["step"] == "plan"


def test_a_conversions_triage_is_not_attested_until_the_owner_confirms(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    _design_reviewed(root)
    _record(root, _design("30"), "Advance to planning: the design holds.")
    older = _log(root).read_text("utf-8")

    shown = _convert(root)

    assert "  * 30-design: ## Next: Advance to planning: the design holds." in shown
    assert "  * 21-design: ## Next: Another round: the reviewer reads the fix." in shown
    assert any(line.startswith('proposed direction: {"step": "plan"}') for line in shown)
    # The owner declines: nothing is written, and the triage is finished with
    # `record`, whose outcome then names its review, and its exit, whatever the
    # prose under `## Next` begins with.
    assert _log(root).read_text("utf-8") == older
    record_interactive(_log(root), "triage", {
        "outcome": "finished", "message": "Triaged.",
        "next": {"step": "review", "kind": "design"}, "triaged": ["30-design"]},
        session="s", commit=HEAD, clock=clock)
    shown = _convert(root)
    assert "    30-design: ## Next: Advance to planning: the design holds." in shown
    assert any(line.startswith('proposed direction: {"step": "review", "kind": "design"}')
               for line in shown)
    _convert(root, confirm=True)
    assert _next(root)["step"] == "review"


# The proposal.

def test_a_conversion_follows_a_later_direction(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    _design_reviewed(root)
    _older(root, _decision(next="plan"))

    _convert(root, confirm=True)

    assert read_log(_log(root))[-1]["next"] == {"step": "plan"}
    assert _next(root)["step"] == "plan"


def test_a_later_direction_that_can_no_longer_be_entered_proposes_nothing(
        tmp_path: Path) -> None:
    root = _repository(tmp_path)
    _design_reviewed(root)
    # Every design review is triaged once the conversion line names them.
    _older(root, _decision(next="triage", kind="design"))

    shown = _convert(root)

    assert any(line.startswith("no direction is proposed:") and "no design review awaits"
               in line for line in shown)


def test_a_conversion_after_later_runs_proposes_nothing(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _record(root, _design("13"), "Advance to planning.")
    older = _older(root, _review_run(_design("13")), _run("triage"),
                   _run("plan", rounds=[[[2]]]))

    shown = _convert(root)

    assert any(line.startswith("no direction is proposed:") and "plan at seq 3" in line
               for line in shown)
    with pytest.raises(StepError, match="give the node the change stands at with --next"):
        _convert(root, confirm=True)
    assert read_log(_log(root)) == older
    _convert(root, confirm=True, given={"step": "round"})
    assert read_log(_log(root))[-1]["next"] == {"step": "round"}
    assert _next(root)["step"] == "round" and _next(root)["sections"] == [[2]]


def test_a_conversion_proposes_a_guards_remedy(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _record(root, _design("13"), "Advance to planning.")
    _record(root, "20-implementation.md", "Advance: the fixes are committed.",
            text=f"x\n<!-- reviewed-commit: {'e' * 40} -->\n")
    _record(root, "21-validation.md",
            text=f"# Validation\n\n- **Commit:** {'e' * 40} on feat/x\n- **Result:** passed\n")
    _older(root, _review_run(_design("13")), _run("triage"), _run("plan", rounds=[[[1]], [[2]]]),
           {"step": "orchestrator", "outcome": "round", "sections": [[1]], "by": "plan",
            "after": 13},
           _run("implement"), _review_run("20-implementation.md"), _run("validate"),
           _run("triage"))

    shown = _convert(root)

    assert any(line.startswith('proposed direction: {"step": "validate", "target": '
                               '{"step": "round"}}') for line in shown)
    _convert(root, confirm=True)
    assert _next(root)["step"] == "validate" and _next(root)["target"] == {"step": "round"}


def test_the_last_rounds_advance_proposes_the_pre_closeout_reviews_remedy(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation", tasks=LAST_ROUND_DONE)
    _record(root, "20-implementation.md", "Advance.")
    _older(root, _review_run("20-implementation.md"), _run("triage"))

    shown = _convert(root)

    assert any(line.startswith('proposed direction: {"step": "validate", "target": '
                               '{"step": "review", "kind": "pre-closeout"}}')
               for line in shown)
    _convert(root, confirm=True)
    assert _next(root)["step"] == "validate"
    assert _next(root)["target"] == {"step": "review", "kind": "pre-closeout"}


def test_a_guard_no_direction_can_remedy_proposes_nothing(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation", tasks=LAST_ROUND_DONE)
    _record(root, "20-implementation.md", "Advance.")
    _record(root, "21-validation.md",
            text=f"# Validation\n\n- **Commit:** {HEAD} on feat/x\n- **Result:** failed\n")
    _older(root, _review_run("20-implementation.md"), _run("triage"))

    shown = _convert(root)

    assert any(line.startswith("no direction is proposed:") and "is failed" in line
               for line in shown)


@pytest.mark.parametrize("words,why", [
    ("The owner decides.", "leads to no exit"),
    # A return whose run is not logged has no run for a direction to resolve.
    ("Returned to design.", "no returned run of it is logged"),
])
def test_a_triage_leading_to_no_exit_proposes_nothing(tmp_path: Path, words: str,
                                                      why: str) -> None:
    root = _repository(tmp_path)
    _record(root, _design("13"), words)
    _older(root, _review_run(_design("13")), _run("triage"))

    shown = _convert(root)

    assert any(line.startswith("no direction is proposed:") and why in line
               for line in shown)


def test_a_review_awaiting_its_triage_proposes_nothing(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    _design_reviewed(root)
    _record(root, _design("30"))

    shown = _convert(root)

    assert any(line.startswith("no direction is proposed:") and "30-design awaits its triage"
               in line for line in shown)


def test_a_later_direction_naming_no_node_proposes_nothing(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    _design_reviewed(root)
    # An older direction to an implementation, which names no sections.
    _older(root, _decision(next="implement"))

    shown = _convert(root)

    assert any(line.startswith("no direction is proposed:") and "names no node" in line
               for line in shown)


def _returned(root: Path) -> list[dict]:
    """A pre-closeout triage whose run proposed a return to planning."""
    _record(root, "40-pre-closeout.md", "Returned: the second section needs a plan of its own.")
    return _older(root, _review_run("40-pre-closeout.md"),
                  _run("triage", "returned", return_to="planning", evidence="the triage"))


def test_a_pending_return_is_converted_then_confirmed(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation", tasks=LAST_ROUND_DONE)
    returned = _returned(root)[-1]

    _convert(root, confirm=True)

    lines = read_log(_log(root))
    assert lines[1]["seq"] == returned["seq"] and lines[1]["next"] == {"step": "plan"}
    assert lines[1]["return_to"] == "planning"
    assert (lines[-1]["next"], lines[-1]["resolves"]) == ({"step": "plan"}, returned["seq"])
    assert _next(root)["step"] == "plan"


def test_a_pending_return_the_owner_declines_waits_for_them(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation", tasks=LAST_ROUND_DONE)
    returned = _returned(root)[-1]
    assert any("--confirm --decline" in line for line in _convert(root))

    _convert(root, confirm=True, decline=True)

    assert read_log(_log(root))[-1]["step"] == "convert"
    result = _next(root)
    assert (result["step"], result["seq"]) == ("owner", returned["seq"])
    assert "proposes returning to plan" in result["reason"]


def test_a_return_a_decision_declined_proposes_nothing(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation", tasks=LAST_ROUND_DONE)
    returned = _returned(root)[-1]
    _older(root, _decision(resolves=returned["seq"]))

    shown = _convert(root)

    assert any(line.startswith("no direction is proposed:")
               and "resolved without directing it" in line for line in shown)


def test_decline_is_refused_with_no_return_to_decline(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    _design_reviewed(root)

    with pytest.raises(StepError, match="none is proposed"):
        _convert(root, confirm=True, decline=True)


def test_a_confirmed_return_is_converted(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _record(root, "30-implementation.md", "Returned: the provider needs a decision.")
    returned, confirmed = _older(
        root, _review_run("30-implementation.md"),
        _run("triage", "returned", return_to="design", evidence="the triage"),
        _decision(next="design", resolves=2))[1:]

    _convert(root, confirm=True)

    lines = {line["seq"]: line for line in read_log(_log(root))}
    assert lines[returned["seq"]]["next"] == {"step": "design"}
    assert (lines[confirmed["seq"]]["resolves"], lines[confirmed["seq"]]["next"]) == (
        returned["seq"], {"step": "design"})
    direction = read_log(_log(root))[-1]
    assert direction["next"] == {"step": "design"} and "resolves" not in direction
    assert _next(root)["step"] == "design"


# The replacement.

def test_a_conversion_is_interrupted(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    _design_reviewed(root)
    older = _log(root).read_text("utf-8")

    with pytest.raises(OSError, match="interrupted"):
        _convert(root, confirm=True, replace=_interrupted)

    assert _log(root).read_text("utf-8") == older
    assert [path.name for path in _reviews(root).iterdir() if path.name.startswith(".")] == []
    assert "convert" in _next(root)
    _convert(root, confirm=True)
    assert _next(root)["step"] == "review"


@pytest.mark.skipif(not Path("/proc/self/fd").is_dir(),
                    reason="observes the thread's descriptors through /proc")
def test_an_append_waiting_on_the_conversion_lands_in_the_converted_log(
        tmp_path: Path) -> None:
    # A run's outcome appended while the conversion holds the log's lock takes the
    # lock once the converted log has replaced the older one, and appends to it.
    root = _repository(tmp_path)
    _design_reviewed(root)
    log = _log(root)
    appended: list[dict] = []
    failures: list[BaseException] = []

    def append() -> None:
        try:
            appended.append(record_outcome(log, "review", QUESTION, session="s", commit=HEAD,
                                           extra={"kind": "design"}, clock=clock))
        except BaseException as exc:
            failures.append(exc)

    caller = threading.Thread(target=append)

    def replace(new: Path, old: Path) -> None:
        caller.start()
        deadline = time.monotonic() + 10
        while descriptors_of(old) < 2:
            assert time.monotonic() < deadline, "the run never opened the log"
            time.sleep(0.01)
        os.replace(new, old)

    _convert(root, confirm=True, replace=replace)
    caller.join(10)

    assert not caller.is_alive() and not failures, failures
    *converted, direction, line = read_log(log)
    assert converted[-1]["step"] == "convert" and direction["by"] == "owner"
    assert line == appended[0] and line["seq"] == direction["seq"] + 1


def test_an_older_wrapper_appending_after_the_conversion_needs_it_again(
        tmp_path: Path) -> None:
    root = _repository(tmp_path)
    _design_reviewed(root)
    _convert(root, confirm=True)
    # The converting run's own outcome, appended by the older wrapper that started it.
    (run,) = _older(root, _review_run(_design("30")))

    assert "convert" in _next(root)
    shown = _convert(root)
    assert any(line.startswith("no direction is proposed:")
               and f"review at seq {run['seq']}" in line for line in shown)
    # The first conversion's line attests what the owner attested then.
    assert "    13-design: ## Next: Advance — rejected by the owner later." in shown
    with pytest.raises(StepError, match="--next"):
        _convert(root, confirm=True)
    _convert(root, confirm=True, given={"step": "review", "kind": "design"})
    assert read_log(_log(root))[-2]["triaged"] == ["13-design", "21-design"]
    assert _next(root)["step"] == "review"


# The command line, and the older reading.

def test_the_command_shows_the_conversion_then_writes_it_on_confirmation(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _repository(tmp_path)
    _design_reviewed(root)

    assert main(["convert", CHANGE], root=root) == 0
    assert "nothing is written" in capsys.readouterr().out
    assert main(["convert", CHANGE, "--kind", "design"], root=root) == 1
    assert "qualify --next" in capsys.readouterr().err
    assert main(["convert", CHANGE, "--confirm", "--next", "review", "--kind", "design",
                 "--reason", "the owner's words"], root=root) == 0

    conversion, direction = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert conversion["step"] == "convert"
    assert (direction["next"], direction["reason"]) == (
        {"step": "review", "kind": "design"}, "the owner's words")


@pytest.mark.parametrize("flags,given", [
    (["--next", "validate", "--target", "review", "--kind", "pre-closeout"],
     {"step": "validate", "target": {"step": "review", "kind": "pre-closeout"}}),
    (["--next", "implement", "--sections", "2;3"],
     {"step": "implement", "sections": [[2], [3]]}),
])
def test_the_commands_flags_build_the_direction_given(
        tmp_path: Path, capsys: pytest.CaptureFixture[str], flags: list[str],
        given: dict) -> None:
    root = _repository(tmp_path)
    _design_reviewed(root)

    assert main(["convert", CHANGE, *flags], root=root) == 0

    assert f"direction given: {json.dumps(given)}" in capsys.readouterr().out


@pytest.mark.parametrize("text,heading,token", [
    ("## Next\n\nAdvance to planning.\n", "## Next", ADVANCE),
    ("## Next: Another round over the fix\n", "## Next", ANOTHER_ROUND),
    ("## Next\n\nReturned to design.\n", "## Next", RETURNED),
    ("## Next\n\nThe owner decides.\n", "## Next", OTHER),
    ("## Gate\n\nPassed, with notes.\n", "## Gate", ADVANCE),
    ("## Gate\n\nNot passed.\n", "## Gate", OTHER),
    ("## Next round\n\nAdvance.\n", None, None),
])
def test_a_triage_file_is_read_for_its_token(tmp_path: Path, text: str, heading: str | None,
                                            token: str | None) -> None:
    path = tmp_path / "13-design.triage.md"
    path.write_text(f"# Triage\n\n{text}", "utf-8")

    reading = read_triage(path)

    assert (reading.heading, reading.token) == (heading, token)


def test_an_older_line_is_rewritten_in_place() -> None:
    decision = {"seq": 4, "at": "t", "step": "orchestrator", "outcome": "orchestrator",
                "by": "owner", "next": "review", "kind": "pre-closeout", "resolves": 3}
    returned = {"seq": 3, "at": "t", "step": "triage", "outcome": "returned",
                "message": "Back.", "return_to": "implementation", "evidence": "e"}
    finished = {"seq": 2, "at": "t", "step": "plan", "outcome": "finished", "next": "Round 1."}
    marked = {"seq": 5, "at": "t", "format": FORMAT, "step": "design", "outcome": "finished",
              "message": "m", "next": "prose the schema still admits"}

    assert rewritten(decision) == {"seq": 4, "at": "t", "format": FORMAT,
                                   "step": "orchestrator", "outcome": "orchestrator",
                                   "by": "owner", "next": {"step": "review",
                                                           "kind": "pre-closeout"},
                                   "resolves": 3}
    # Written as the log's appender writes a line: its seq, time, and format first.
    assert list(rewritten(decision))[:4] == ["seq", "at", "format", "step"]
    assert rewritten(returned)["next"] == {"step": "round"}
    assert rewritten(finished) == {"seq": 2, "at": "t", "format": FORMAT, "step": "plan",
                                   "outcome": "finished", "message": "Round 1."}
    assert rewritten(marked) is marked
