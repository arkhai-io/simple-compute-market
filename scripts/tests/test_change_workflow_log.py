"""A step's outcome and the orchestrating session's notes are kept in the workflow log."""

from __future__ import annotations

import fcntl
import json
import os
import threading
import time
from pathlib import Path

import pytest

from change_workflow.cli import main
from change_workflow.common import StepError
from change_workflow.log import (LogError, append_entry, branch_decisions, last_entries,
                                 note_orchestrator, note_round, numbered, read_log,
                                 record_interactive, record_outcome, replace_log, unmarked,
                                 unused_direction)
from change_workflow_fixtures import (CHANGE, COMMIT, DENIALS, VALID, clock, descriptors_of,
                                      log_file)


def test_the_owners_branch_decision_is_recorded_and_found(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    log = log_file(tmp_path)
    note_orchestrator(log, "runs here", "its own evidence", by="owner",
                      branch="feat/x", change=CHANGE, clock=clock)
    note_orchestrator(log, "rerun", "renewed", clock=clock)

    assert main(["log", CHANGE, "--branch", "feat/x"], root=tmp_path) == 0
    shown = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [(entry["seq"], entry["change"]) for entry in shown] == [(1, CHANGE)]
    assert branch_decisions(read_log(log), "feat/x", "another-change") == []
    assert branch_decisions(read_log(log), "feat/y") == []


@pytest.mark.parametrize("fields,problem", [
    ({"branch": "feat/x"}, "both the branch and the change"),
    ({"change": CHANGE}, "both the branch and the change"),
    ({"branch": "feat/x", "change": CHANGE, "by": "orchestrator"}, "the owner's"),
])
def test_a_branch_decision_names_both_and_is_the_owners(tmp_path: Path, fields: dict,
                                                        problem: str) -> None:
    fields = {"by": "owner", **fields}

    with pytest.raises(StepError, match=problem):
        note_orchestrator(log_file(tmp_path), "runs here", "pilot", **fields)


def test_an_outcome_is_logged_with_its_run(tmp_path: Path) -> None:
    log = log_file(tmp_path)

    line = record_outcome(log, "validate", VALID["question"], session="51aa",
                          commit=COMMIT, clock=clock)

    assert line == {"seq": 1, "at": "2026-10-21T09:15:40Z", "format": 2, "step": "validate",
                    "session": "51aa", "commit": COMMIT, **VALID["question"]}
    assert [json.loads(text) for text in log.read_text("utf-8").splitlines()] == [line]


def test_an_outcome_that_does_not_conform_is_not_logged(tmp_path: Path) -> None:
    log = log_file(tmp_path)

    with pytest.raises(StepError, match="has no next"):
        record_outcome(log, "implement", {"outcome": "finished", "message": "Done."},
                       session="s", commit=COMMIT)

    assert not log.exists()


def test_an_unknown_step_is_not_logged(tmp_path: Path) -> None:
    with pytest.raises(StepError, match="unknown step 'deploy'"):
        record_outcome(log_file(tmp_path), "deploy", VALID["finished"], session="s",
                       commit=COMMIT)


def test_seq_increases_across_outcomes_and_notes(tmp_path: Path) -> None:
    log = log_file(tmp_path)

    note_round(log, [[1, 2], [3]], "owner", clock=clock)
    record_outcome(log, "implement", VALID["finished"], session="s", commit=COMMIT,
                   extra={"sections": [1, 2]}, clock=clock)
    note_orchestrator(log, "rerun validate", "it died before an outcome", clock=clock)

    entries = read_log(log)
    assert [entry["seq"] for entry in entries] == [1, 2, 3]
    assert entries[0] == {"seq": 1, "at": "2026-10-21T09:15:40Z", "format": 2,
                          "step": "orchestrator", "outcome": "round", "sections": [[1, 2], [3]], "by": "owner",
                          "after": 0}
    assert entries[1]["sections"] == [1, 2]
    assert entries[2]["decision"] == "rerun validate"


def test_seq_follows_the_highest_in_the_log(tmp_path: Path) -> None:
    log = log_file(tmp_path)
    log.parent.mkdir()
    log.write_text('{"seq": 7, "step": "orchestrator"}\n', "utf-8")

    line = note_orchestrator(log, "d", "r", clock=clock)

    assert line["seq"] == 8


def test_a_malformed_line_is_reported_with_its_number(tmp_path: Path) -> None:
    log = log_file(tmp_path)
    log.parent.mkdir()
    log.write_text('{"seq": 1}\n\nnot json\n', "utf-8")

    with pytest.raises(LogError, match=r"workflow\.jsonl:3: not a JSON line"):
        read_log(log)
    with pytest.raises(LogError, match=r":3:"):
        note_orchestrator(log, "d", "r")
    assert log.read_text("utf-8") == '{"seq": 1}\n\nnot json\n'


def test_a_line_without_seq_is_reported(tmp_path: Path) -> None:
    log = log_file(tmp_path)
    log.parent.mkdir()
    log.write_text('{"seq": 1}\n["seq"]\n', "utf-8")

    with pytest.raises(LogError, match=r":2: not a JSON object"):
        read_log(log)


def test_an_absent_log_reads_empty(tmp_path: Path) -> None:
    assert read_log(log_file(tmp_path)) == []


def test_the_last_lines_are_read(tmp_path: Path) -> None:
    log = log_file(tmp_path)
    for index in range(4):
        note_orchestrator(log, f"d{index}", "r", clock=clock)

    assert [entry["decision"] for entry in last_entries(log, 2)] == ["d2", "d3"]
    assert last_entries(log, 0) == []


@pytest.mark.parametrize("sections", [[], [[]], [1], [[0.5]], [[""]], [[True]]])
def test_a_round_without_sessions_of_sections_is_refused(tmp_path: Path, sections) -> None:
    log = log_file(tmp_path)

    with pytest.raises(StepError, match="a round names"):
        note_round(log, sections, "owner")

    assert not log.exists()


def test_a_round_without_who_agreed_it_is_refused(tmp_path: Path) -> None:
    with pytest.raises(StepError, match="who agreed"):
        note_round(log_file(tmp_path), [[1]], "")


@pytest.mark.parametrize("decision,reason", [("", "r"), ("d", "")])
def test_an_orchestrator_line_without_its_decision_or_reason_is_refused(
        tmp_path: Path, decision: str, reason: str) -> None:
    with pytest.raises(StepError, match="decision and its reason"):
        note_orchestrator(log_file(tmp_path), decision, reason)


def test_a_decision_names_who_decided_the_run_it_resolves_and_the_next_step(
        tmp_path: Path) -> None:
    log = log_file(tmp_path)
    run = record_outcome(log, "implement", VALID["returned"], session="s", commit=COMMIT)

    line = note_orchestrator(log, "return to design confirmed", "the owner's word",
                             by="owner", resolves=run["seq"], next_step="design",
                             clock=clock)
    review = note_orchestrator(log, "review again", "the owner asked", by="owner",
                               next_step="review", kind="pre-closeout", clock=clock)

    assert line == {"seq": 2, "at": "2026-10-21T09:15:40Z", "format": 2,
                    "step": "orchestrator", "outcome": "orchestrator", "by": "owner",
                    "decision": "return to design confirmed", "reason": "the owner's word",
                    "resolves": 1, "next": {"step": "design"}}
    # The repeat review names no run, since no run waits on it.
    assert review["next"] == {"step": "review", "kind": "pre-closeout"}
    assert "resolves" not in review and "kind" not in review
    assert note_orchestrator(log, "d", "r")["by"] == "orchestrator"


# The owner's directions: any node, checked only against the unwaivable entry
# guards of the nodes they name.

def _archived_log(tmp_path: Path) -> Path:
    directory = tmp_path / "openspec/changes/archive" / f"2026-10-21-{CHANGE}"
    directory.mkdir(parents=True)
    return directory / "reviews" / "workflow.jsonl"


def _review(log: Path, name: str, triaged: bool = False) -> None:
    log.parent.mkdir(parents=True, exist_ok=True)
    (log.parent / name).with_suffix(".md").write_text("A review.\n", "utf-8")
    if triaged:
        (log.parent / name).with_suffix(".triage.md").write_text("Its triage.\n", "utf-8")
        record_outcome(log, "triage", {"outcome": "finished", "message": "Advance.",
                                       "next": {"step": "plan"}, "triaged": [name]},
                       session="s", commit=COMMIT)


@pytest.mark.parametrize("fields,target", [
    ({"next_step": "archive-cleanup"}, {"step": "archive-cleanup"}),
    ({"next_step": "review", "kind": "closeout"}, {"step": "review", "kind": "closeout"}),
    ({"next_step": "triage", "kind": "closeout"}, {"step": "triage", "kind": "closeout"}),
    ({"next_step": "closeout"}, {"step": "closeout"}),
    ({"next_step": "validate", "target": "archive-cleanup"},
     {"step": "validate", "target": {"step": "archive-cleanup"}}),
])
def test_the_owner_directs_an_archived_change_past_the_archive(
        tmp_path: Path, fields: dict, target: dict) -> None:
    log = _archived_log(tmp_path)
    _review(log, "05-closeout")

    # Archive cleanup's validation is waived by a plain direction, its reason
    # saying what it skips.
    line = note_orchestrator(log, "waive archive cleanup's validation", "the paths judged",
                             by="owner", **fields)

    assert line["next"] == target and "resolves" not in line


@pytest.mark.parametrize("fields,guard", [
    ({"next_step": "design"}, "design's entry guard (the change is not archived)"),
    ({"next_step": "plan"}, "plan's entry guard (the change is not archived)"),
    ({"next_step": "implement", "sections": [[5]]},
     "round's entry guard (the change is not archived)"),
    ({"next_step": "validate", "target": "design"},
     "design's entry guard (the change is not archived)"),
])
def test_an_archived_change_is_not_directed_to_an_earlier_phase(
        tmp_path: Path, fields: dict, guard: str) -> None:
    log = _archived_log(tmp_path)

    with pytest.raises(StepError, match="refused") as refused:
        note_orchestrator(log, "back to design", "r", by="owner", **fields)

    assert guard in str(refused.value) and "the change is archived" in str(refused.value)
    assert not log.exists()


def test_done_is_never_directed(tmp_path: Path) -> None:
    log = _archived_log(tmp_path)

    with pytest.raises(StepError, match="reached only by archive cleanup's exit"):
        note_orchestrator(log, "done", "r", by="owner", next_step="done")


@pytest.mark.parametrize("fields,label", [
    ({"next_step": "archive-cleanup"}, "archive-cleanup"),
    ({"next_step": "review", "kind": "closeout"}, "review:closeout"),
    ({"next_step": "triage", "kind": "closeout"}, "triage:closeout"),
    # A directed validation that could never reach its target runs no validation.
    ({"next_step": "validate", "target": "archive-cleanup"}, "archive-cleanup"),
])
def test_a_change_not_archived_is_not_directed_past_the_archive(
        tmp_path: Path, fields: dict, label: str) -> None:
    log = log_file(tmp_path)

    with pytest.raises(StepError) as refused:
        note_orchestrator(log, "d", "r", by="owner", **fields)

    assert (f"{label}'s entry guard (the change is archived) is not met: the change is not "
            "archived") in str(refused.value)
    assert not log.exists()


def test_a_directed_validation_names_its_target(tmp_path: Path) -> None:
    log = log_file(tmp_path)

    line = note_orchestrator(log, "validate before closeout", "r", by="owner",
                             next_step="validate", target="closeout")
    round_ = note_orchestrator(log, "validate the fix", "r", by="owner", next_step="validate",
                               target="implement", sections=[[5], [6]])

    assert line["next"] == {"step": "validate", "target": {"step": "closeout"}}
    assert round_["next"] == {"step": "validate",
                              "target": {"step": "implement", "sections": [[5], [6]]}}
    # Refused by validation's entry guard, which the refusal names.
    with pytest.raises(StepError) as refused:
        note_orchestrator(log, "d", "r", by="owner", next_step="validate")
    assert ("validate's entry guard (it carries a target that is a node) is not met: a "
            "validation names the target it is for") in str(refused.value)


def test_a_triage_is_directed_only_while_a_review_of_its_kind_awaits_it(
        tmp_path: Path) -> None:
    log = log_file(tmp_path)
    _review(log, "13-design", triaged=True)
    # The first round's validation, after the design review: no design triage's fix.
    _review(log, "14-validation")

    with pytest.raises(StepError, match="no design review, and no validation after it, "
                                        "awaits triage"):
        note_orchestrator(log, "triage again", "r", by="owner", next_step="triage",
                          kind="design")
    # A review awaits its triage until a triage's outcome names it, its triage file
    # written or not, an external review among them.
    _review(log, "21-design-external")
    line = note_orchestrator(log, "triage it", "r", by="owner", next_step="triage",
                             kind="design")

    assert line["next"] == {"step": "triage", "kind": "design"}


def test_a_triage_is_directed_for_a_validation_after_its_kinds_latest_review(
        tmp_path: Path) -> None:
    # The validation of a fix commit a triage made: its failures are triaged by a
    # triage of the same kind, which names that review again.
    log = log_file(tmp_path)
    _review(log, "50-validation")
    _review(log, "52-implementation", triaged=True)

    # A validation before the latest review was triaged with it, or superseded.
    with pytest.raises(StepError, match="no implementation review, and no validation"):
        note_orchestrator(log, "d", "r", by="owner", next_step="triage", kind="implementation")
    _review(log, "53-validation")
    line = note_orchestrator(log, "triage the fix's failures", "r", by="owner",
                             next_step="triage", kind="implementation")
    (log.parent / "53-validation.triage.md").write_text("Its triage.\n", "utf-8")
    record_outcome(log, "triage", {"outcome": "finished", "message": "Fixed.",
                                   "next": {"step": "round"},
                                   "triaged": ["52-implementation", "53-validation"]},
                   session="s", commit=COMMIT)

    assert line["next"] == {"step": "triage", "kind": "implementation"}
    with pytest.raises(StepError, match="no implementation review, and no validation"):
        note_orchestrator(log, "d", "r", by="owner", next_step="triage", kind="implementation")


def test_a_direction_checks_no_exit_guard(tmp_path: Path) -> None:
    # The pre-closeout review's validation is waivable, and closeout's is an exit
    # guard: neither refuses the owner's direction.
    log = log_file(tmp_path)

    for fields in ({"next_step": "review", "kind": "pre-closeout"}, {"next_step": "closeout"}):
        assert note_orchestrator(log, "d", "r", by="owner", **fields)["next"]


@pytest.mark.parametrize("fields,target", [
    ({"next_step": "design"}, {"step": "design"}),
    ({"next_step": "plan"}, {"step": "plan"}),
    ({"next_step": "round"}, {"step": "round"}),
    ({"next_step": "implement", "sections": [[5]]}, {"step": "implement", "sections": [[5]]}),
])
def test_a_change_not_archived_is_directed_to_an_earlier_phase(
        tmp_path: Path, fields: dict, target: dict) -> None:
    log = log_file(tmp_path)

    assert note_orchestrator(log, "d", "r", by="owner", **fields)["next"] == target


@pytest.mark.parametrize("fields", [
    {"next_step": "review", "kind": "pre-closeout"},
    {"next_step": "design"},
    {"next_step": "plan"},
])
def test_only_the_owner_directs_a_step(tmp_path: Path, fields: dict) -> None:
    log = log_file(tmp_path)
    run = record_outcome(log, "triage", VALID["returned"], session="s", commit=COMMIT)

    # A return confirmed by anyone but the owner, or a review the orchestrating
    # session asks for of its own accord.
    with pytest.raises(StepError, match="is the owner's; the orchestrating session directs"):
        note_orchestrator(log, "directed", "r", resolves=run["seq"], **fields)

    assert len(read_log(log)) == 1


@pytest.mark.parametrize("fields,problem", [
    ({"resolves": 9}, "no run has seq 9"),
    ({"reads": 9}, "no run has seq 9"),
    ({"by": "owner", "next_step": "deploy"}, "'deploy' is no node"),
    ({"kind": "design"}, "qualify the step a decision directs"),
    ({"by": "owner", "next_step": "review", "kind": "triage"}, "review:triage is no node"),
    # A directed review, or a directed triage, names its kind.
    ({"by": "owner", "next_step": "review"}, "a review is a node only with the kind"),
    ({"by": "owner", "next_step": "triage"}, "a triage is a node only with the kind"),
    ({"by": "owner", "next_step": "plan", "kind": "design"},
     "only a review or a triage names a kind"),
    ({"by": ""}, "names who decided"),
])
def test_a_decision_naming_what_the_log_lacks_is_refused(tmp_path: Path, fields: dict,
                                                         problem: str) -> None:
    log = log_file(tmp_path)
    note_orchestrator(log, "an earlier decision", "r", clock=clock)

    with pytest.raises(StepError, match=problem):
        note_orchestrator(log, "d", "r", **fields)

    assert len(read_log(log)) == 1


def test_a_decision_resolves_only_a_steps_run(tmp_path: Path) -> None:
    log = log_file(tmp_path)
    note = note_orchestrator(log, "an earlier decision", "r", clock=clock)

    with pytest.raises(StepError, match="a decision resolves a step's run"):
        note_orchestrator(log, "d", "r", resolves=note["seq"])


def test_a_decision_reads_a_run_with_denials_without_resolving_it(tmp_path: Path) -> None:
    log = log_file(tmp_path)
    run = record_outcome(log, "validate", {**VALID["question"], "denials": DENIALS},
                         session="s", commit=COMMIT)

    line = note_orchestrator(log, "gap: gh run view", "the skill names it", reads=run["seq"],
                             clock=clock)
    both = note_orchestrator(log, "gap: gh run view; rerun", "r", reads=run["seq"],
                             resolves=run["seq"], clock=clock)

    assert (line["reads"], "resolves" in line) == (1, False)
    assert (both["reads"], both["resolves"]) == (1, 1)


def test_a_decision_may_not_read_a_run_that_recorded_no_denial(tmp_path: Path) -> None:
    log = log_file(tmp_path)
    run = record_outcome(log, "validate", VALID["question"], session="s", commit=COMMIT)

    with pytest.raises(StepError, match="recorded no denial"):
        note_orchestrator(log, "d", "r", reads=run["seq"])

    assert len(read_log(log)) == 1


def test_an_outcome_may_not_set_what_the_wrapper_records(tmp_path: Path) -> None:
    with pytest.raises(StepError, match="does not conform"):
        record_outcome(log_file(tmp_path), "plan", {**VALID["finished"], "commit": "x"},
                       session="s", commit=COMMIT)


@pytest.mark.parametrize("extra", [{"commit": "other"}, {"step": "plan"}, {"message": "m"},
                                   {"seq": 9}])
def test_run_fields_are_recorded_once(tmp_path: Path, extra: dict) -> None:
    log = log_file(tmp_path)

    with pytest.raises(StepError, match="recorded twice|the log assigns"):
        record_outcome(log, "implement", VALID["finished"], session="s", commit=COMMIT,
                       extra=extra)

    assert not log.exists()


def test_every_appended_line_carries_the_logs_format(tmp_path: Path) -> None:
    log = log_file(tmp_path)

    note_round(log, [[1]], "owner", clock=clock)
    record_outcome(log, "implement", VALID["finished"], session="s", commit=COMMIT,
                   clock=clock)
    note_orchestrator(log, "d", "r", clock=clock)
    append_entry(log, {"step": "orchestrator", "outcome": "round"}, clock)

    assert [entry["format"] for entry in read_log(log)] == [2, 2, 2, 2]


@pytest.mark.parametrize("record", [True, False])
def test_no_writer_sets_the_logs_format(tmp_path: Path, record: bool) -> None:
    log = log_file(tmp_path)

    with pytest.raises(StepError, match="format"):
        if record:
            record_outcome(log, "plan", {**VALID["finished"], "format": 1}, session="s",
                           commit=COMMIT)
        else:
            append_entry(log, {"step": "orchestrator", "format": 1})

    assert not log.exists()


@pytest.mark.parametrize("session,commit,named", [
    ("", COMMIT, "names its session"), ("s", None, "the commit at HEAD")])
def test_an_interactive_outcome_names_its_session_and_commit(
        tmp_path: Path, session: str, commit: str | None, named: str) -> None:
    log = log_file(tmp_path)

    with pytest.raises(StepError, match=named):
        record_interactive(log, "design", VALID["finished"], session=session, commit=commit)

    assert not log.exists()
    line = record_interactive(log, "design", VALID["finished"], session="s", commit=COMMIT)
    assert (line["interactive"], line["session"], line["commit"]) == (True, "s", COMMIT)


def _while_replaced(log: Path, call) -> tuple[list, str]:
    """Run `call` in a second thread that opens the log while this one holds its
    lock, then rename a new log over the name and release the lock: what `call`
    returned, and what the replaced file holds afterwards.

    The thread's opening is observed as a second descriptor naming the log, a
    bounded wait, so a call that never opens the log fails rather than hangs.
    """
    replacement = log.with_name("workflow.jsonl.new")
    replacement.write_text('{"seq": 5, "step": "orchestrator", "format": 2}\n', "utf-8")
    returned: list = []
    failures: list[BaseException] = []

    def run() -> None:
        try:
            returned.append(call())
        except BaseException as exc:
            failures.append(exc)

    with log.open("a+", encoding="utf-8") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        caller = threading.Thread(target=run)
        caller.start()
        deadline = time.monotonic() + 10
        while descriptors_of(log) < 2:
            assert time.monotonic() < deadline, "the call never opened the log"
            time.sleep(0.01)
        os.replace(replacement, log)
        fcntl.flock(held, fcntl.LOCK_UN)
        caller.join(10)
        held.seek(0)
        replaced = held.read()
    assert not caller.is_alive() and not failures, failures
    return returned, replaced


@pytest.mark.skipif(not Path("/proc/self/fd").is_dir(),
                    reason="observes the thread's descriptors through /proc")
def test_an_append_waiting_on_a_replacement_lands_in_the_new_log(tmp_path: Path) -> None:
    # A writer that replaces the log holds its lock while it renames a new file over
    # the name; a run appending its outcome, which opened the log before the rename,
    # takes the lock on the replaced file and must append to the new one.
    log = log_file(tmp_path)
    note_orchestrator(log, "old", "r", clock=clock)
    old = log.read_text("utf-8")

    (line,), replaced = _while_replaced(log, lambda: record_outcome(
        log, "implement", VALID["finished"], session="s", commit=COMMIT, clock=clock))

    assert [entry["seq"] for entry in read_log(log)] == [5, 6]
    assert read_log(log)[-1] == line
    # The replaced file was never written: the line went where readers look.
    assert replaced == old


def test_a_replaced_log_holds_the_new_lines_with_the_old_ones_permissions(
        tmp_path: Path) -> None:
    log = log_file(tmp_path)
    first = note_orchestrator(log, "old", "r", clock=clock)
    log.chmod(0o640)

    lines = replace_log(log, lambda entries: [*entries, numbered(entries, {"step": "x"}, clock)])

    assert read_log(log) == lines == [first, {"seq": 2, "at": first["at"], "format": 2,
                                              "step": "x"}]
    assert log.stat().st_mode & 0o777 == 0o640
    assert sorted(path.name for path in log.parent.iterdir()) == [log.name]


@pytest.mark.parametrize("logged", [True, False])
def test_a_replacement_refused_or_interrupted_writes_nothing(tmp_path: Path,
                                                             logged: bool) -> None:
    log = log_file(tmp_path)
    log.parent.mkdir(parents=True)
    if logged:
        note_orchestrator(log, "old", "r", clock=clock)
    before = log.read_bytes() if logged else None

    def refused(entries: list) -> list:
        raise StepError("refused")

    def interrupted(new: Path, old: Path) -> None:
        raise OSError("interrupted")

    with pytest.raises(StepError, match="refused"):
        replace_log(log, refused)
    with pytest.raises(OSError, match="interrupted"):
        replace_log(log, lambda entries: [*entries, numbered(entries, {"step": "x"}, clock)],
                    replace=interrupted)

    # Neither leaves a log that was not there, nor a temporary file beside it.
    assert (log.read_bytes() if log.exists() else None) == before
    assert sorted(path.name for path in log.parent.iterdir()) == ([log.name] if logged else [])


def test_a_replacement_failing_after_its_rename_keeps_the_new_log(tmp_path: Path) -> None:
    log = log_file(tmp_path)

    def renamed_then_failed(new: Path, old: Path) -> None:
        os.replace(new, old)
        raise OSError("failed after the rename")

    with pytest.raises(OSError, match="after the rename"):
        replace_log(log, lambda entries: [numbered(entries, {"step": "x"}, clock)],
                    replace=renamed_then_failed)

    assert [entry["step"] for entry in read_log(log)] == ["x"]


def test_a_replacement_of_a_missing_log_creates_it(tmp_path: Path) -> None:
    log = log_file(tmp_path)

    replace_log(log, lambda entries: [numbered(entries, {"step": "x"}, clock)])

    assert [entry["seq"] for entry in read_log(log)] == [1]


def test_a_line_without_the_format_is_found() -> None:
    marked = {"seq": 1, "format": 2}
    older = {"seq": 2}

    assert unmarked([marked, older, {"seq": 3}]) == older
    assert unmarked([marked]) is None


@pytest.mark.skipif(not Path("/proc/self/fd").is_dir(),
                    reason="observes the thread's descriptors through /proc")
def test_a_read_waiting_on_a_replacement_reads_the_new_log(tmp_path: Path) -> None:
    log = log_file(tmp_path)
    note_orchestrator(log, "old", "r", clock=clock)

    (entries,), _ = _while_replaced(log, lambda: read_log(log))

    assert [entry["seq"] for entry in entries] == [5]


def test_a_last_line_without_its_newline_is_not_joined(tmp_path: Path) -> None:
    log = log_file(tmp_path)
    log.parent.mkdir()
    log.write_text('{"seq": 1}', "utf-8")

    note_orchestrator(log, "d", "r", clock=clock)

    assert [entry["seq"] for entry in read_log(log)] == [1, 2]


def test_a_round_records_the_last_record_before_it(tmp_path: Path) -> None:
    log = log_file(tmp_path)
    (log.parent / "transcripts").mkdir(parents=True)
    (log.parent / "transcripts" / "04-review.log").write_text("x", "utf-8")

    assert note_round(log, [[2]], "owner", clock=clock)["after"] == 4


def test_a_round_recorded_after_the_fact_is_given_its_last_record_before_it(
        tmp_path: Path) -> None:
    log = log_file(tmp_path)
    (log.parent / "transcripts").mkdir(parents=True)
    (log.parent / "transcripts" / "09-triage.jsonl").write_text("x", "utf-8")

    assert note_round(log, [[1, 2, 3]], "owner", after=1, clock=clock)["after"] == 1
    with pytest.raises(StepError, match="a record number"):
        note_round(log, [[1]], "owner", after=-1)


# The owner's waiver of another design review is a plain direction to planning.

def test_the_owner_waives_another_design_review_by_a_direction(tmp_path: Path) -> None:
    log = log_file(tmp_path)

    waiver = note_orchestrator(log, "waive another design review", "the decision is small",
                               by="owner", next_step="plan")

    assert waiver["next"] == {"step": "plan"} and "resolves" not in waiver


def test_the_owners_latest_direction_is_unused_until_its_node_runs(tmp_path: Path) -> None:
    log = log_file(tmp_path)
    note_orchestrator(log, "review again", "r", by="owner", next_step="review",
                      kind="pre-closeout")
    directed = read_log(log)[-1]
    record_outcome(log, "review", VALID["finished"], session="s", commit=COMMIT,
                   extra={"kind": "implementation"})

    assert unused_direction(read_log(log)) == directed
    record_outcome(log, "review", VALID["finished"], session="s", commit=COMMIT,
                   extra={"kind": "pre-closeout"})
    assert unused_direction(read_log(log)) is None


def test_a_direction_to_a_triage_is_used_by_a_triage_of_its_kind(tmp_path: Path) -> None:
    log = log_file(tmp_path)
    _review(log, "13-design")
    _review(log, "14-implementation", triaged=False)
    (log.parent / "14-implementation.triage.md").write_text("Its triage.\n", "utf-8")
    note_orchestrator(log, "triage it", "r", by="owner", next_step="triage", kind="design")
    directed = read_log(log)[-1]
    record_outcome(log, "triage", {"outcome": "finished", "message": "Round.",
                                   "next": {"step": "round"}, "triaged": ["14-implementation"]},
                   session="s", commit=COMMIT)

    assert unused_direction(read_log(log)) == directed
    (log.parent / "13-design.triage.md").write_text("Its triage.\n", "utf-8")
    record_outcome(log, "triage", {"outcome": "finished", "message": "Plan.",
                                   "next": {"step": "plan"}, "triaged": ["13-design"]},
                   session="s", commit=COMMIT)
    assert unused_direction(read_log(log)) is None


def test_a_direction_to_any_other_step_is_used_by_its_run_taking_an_exit(
        tmp_path: Path) -> None:
    log = log_file(tmp_path)
    note_orchestrator(log, "plan", "r", by="owner", next_step="plan")
    directed = read_log(log)[-1]
    record_outcome(log, "design", VALID["finished"], session="s", commit=COMMIT)

    assert unused_direction(read_log(log)) == directed
    # A question took no exit: the step directed is still the one to run.
    record_outcome(log, "plan", VALID["question"], session="s", commit=COMMIT)
    assert unused_direction(read_log(log)) == directed
    record_outcome(log, "plan", VALID["finished"], session="s", commit=COMMIT)
    assert unused_direction(read_log(log)) is None
    # Only the owner's latest direction counts.
    note_orchestrator(log, "closeout", "r", by="owner", next_step="closeout")
    assert unused_direction(read_log(log))["next"] == {"step": "closeout"}
