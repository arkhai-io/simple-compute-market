"""A review runs read-only on the review row's models, is published only when it is
a review, and its outcome is logged."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import pytest

from change_workflow.log import log_path, read_log
from change_workflow.review import (ReviewError, claim_record, prior_session, review_and_log,
                                    review_models, run_review)
from change_workflow.running import live_runs
from change_workflow.steps import Model, load_steps
from change_workflow_fixtures import (CHANGE, HEAD, RECORDS, VALIDATED, FakeClaude,
                                      claude_review, clock, codex_missing, codex_saying,
                                      not_installed, option, option_rules, repository,
                                      review_text, reviews_of, validation_text, writing)


def test_a_review_is_published_and_its_transcript_kept_apart(tmp_path: Path) -> None:
    root = repository(tmp_path)
    kind = "design"

    path = run_review(CHANGE, kind, root=root, runner=writing(review_text()), head=lambda _: HEAD)

    assert path == reviews_of(root) / f"01-{kind}.md"
    assert path.read_text("utf-8") == (review_text().rstrip("\n") + "\n\n"
                                       "<!-- reviewer-session: codex:s-1 -->\n"
                                       "<!-- reviewer: codex gpt-6-sol high -->\n"
                                       f"<!-- reviewed-commit: {HEAD} -->\n")
    assert (reviews_of(root) / "transcripts" / "01-design.log").is_file()
    assert sorted(p.name for p in reviews_of(root).iterdir()) == [path.name, "transcripts"]


def test_numbering_follows_records_and_transcripts(tmp_path: Path) -> None:
    root = repository(tmp_path, "01-design.log", "02-validation.log",
                      "transcripts/03-implementation.log")

    path = run_review(CHANGE, "implementation", root=root,
                      runner=writing(review_text("implementation")), head=lambda _: HEAD)

    assert path.name == "04-implementation.md"


def test_reviewer_runs_read_only_with_the_skill(tmp_path: Path) -> None:
    root = repository(tmp_path)
    calls: list[list[str]] = []

    run_review(CHANGE, "pre-closeout", base="main", model="m1", effort="high", root=root,
               unvalidated=True, runner=writing(review_text("pre-closeout"), calls=calls),
               head=lambda _: HEAD)

    command = calls[0]
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert command[command.index("--model") + 1] == "m1"
    assert command[command.index("--config") + 1] == 'model_reasoning_effort="high"'
    assert command[-1] == ("Use the change-review skill. Review kind: pre-closeout. "
                           f"Change: {CHANGE}. Base: main.")


def test_design_review_names_no_base(tmp_path: Path) -> None:
    root = repository(tmp_path)
    calls: list[list[str]] = []

    run_review(CHANGE, "design", root=root, runner=writing(review_text(), calls=calls),
               head=lambda _: HEAD)

    assert "Base:" not in calls[0][-1]


def test_a_review_runs_on_the_review_rows_codex_entry(tmp_path: Path) -> None:
    root = repository(tmp_path)
    calls: list[list[str]] = []

    run_review(CHANGE, "design", root=root, runner=writing(review_text(), calls=calls),
               head=lambda _: HEAD)

    assert calls[0][calls[0].index("--model") + 1] == "gpt-6-sol"
    assert calls[0][calls[0].index("--config") + 1] == 'model_reasoning_effort="high"'


def test_the_owners_model_replaces_the_review_rows_for_one_run() -> None:
    rules = load_steps()["review"]

    assert review_models(rules, "claude-fable-5-1") == (
        Model("claude", "claude-fable-5-1", "high"),)
    assert review_models(rules, "gpt-6-astra", "low") == (
        Model("codex", "gpt-6-astra", "low"),)
    assert review_models(rules, "gpt-6-astra") == (
        Model("codex", "gpt-6-astra", "high"),)
    assert review_models(rules, effort="low") == (Model("codex", "gpt-6-sol", "low"),
                                                  Model("claude", "claude-opus-5-5", "low"))
    assert review_models(rules) == rules.models


def test_a_review_on_the_owners_model_is_recorded_as_an_override(tmp_path: Path) -> None:
    root = repository(tmp_path)
    claude = claude_review(review_text("implementation"))

    line = review_and_log(CHANGE, "implementation", root=root, clock=clock,
                          model="claude-fable-5-1", runner=codex_missing, claude=claude,
                          head=lambda _: HEAD, echo=None)

    assert option(claude.commands[0], "--model") == "claude-fable-5-1"
    text = (reviews_of(root) / "01-implementation.md").read_text("utf-8")
    assert "<!-- reviewer: claude claude-fable-5-1 high -->" in text
    assert "<!-- reviewer-override: owner -->" in text
    assert (line["outcome"], line["model"], line["override"]) == (
        "finished", "claude-fable-5-1", True)
    assert "unavailable" not in line


def test_a_review_at_the_owners_effort_is_recorded_as_an_override(tmp_path: Path) -> None:
    root = repository(tmp_path)
    kind = "design"
    calls: list[list[str]] = []

    line = review_and_log(CHANGE, kind, root=root, clock=clock, effort="low",
                          runner=writing(review_text(), session="codex-1", calls=calls),
                          head=lambda _: HEAD)

    assert calls[0][calls[0].index("--config") + 1] == 'model_reasoning_effort="low"'
    assert (line["model"], line["effort"], line["override"]) == ("gpt-6-sol", "low", True)
    assert "<!-- reviewer-override: owner -->" in (
        reviews_of(root) / f"01-{kind}.md").read_text("utf-8")


def test_a_review_on_the_rows_models_is_no_override(tmp_path: Path) -> None:
    root = repository(tmp_path)
    kind = "design"

    line = review_and_log(CHANGE, kind, root=root, clock=clock,
                          runner=writing(review_text(), session="codex-1"), head=lambda _: HEAD)

    assert "override" not in line
    assert "reviewer-override" not in (reviews_of(root) / f"01-{kind}.md").read_text("utf-8")


def test_the_owners_unavailable_model_has_no_fallback(tmp_path: Path) -> None:
    root = repository(tmp_path)
    claude = claude_review(review_text("design"))

    line = review_and_log(CHANGE, "design", root=root, clock=clock, model="gpt-6-astra",
                          runner=codex_missing, claude=claude, head=lambda _: HEAD,
                          echo=None)

    assert claude.commands == []
    assert (line["outcome"], line["override"]) == ("stopped", True)
    assert "no reviewer is available" in line["reason"]


def test_a_review_with_no_findings_is_accepted(tmp_path: Path) -> None:
    root = repository(tmp_path)

    path = run_review(CHANGE, "design", root=root,
                      runner=writing(review_text(findings="None: the change needs none.\n")),
                      head=lambda _: HEAD)

    assert path.is_file()


@pytest.mark.parametrize("text,status,reason", [
    ("", 0, "empty"),
    (review_text(), 1, "exited 1"),
    ("ERROR: the model is not supported\n", 0, "title"),
    (review_text().replace("## Questions", "## Notes"), 0, "missing section '## Questions'"),
    (review_text().replace("- **Basis:** evidence\n", ""), 0, "F1 has no Basis"),
    (review_text().replace("blocking", "urgent"), 0, "F1 has Severity 'urgent'"),
    (review_text("implementation"), 0, "title"),
])
def test_output_that_is_not_a_review_publishes_nothing(
    tmp_path: Path, text: str, status: int, reason: str
) -> None:
    root = repository(tmp_path)

    with pytest.raises(ReviewError, match=reason):
        run_review(CHANGE, "design", root=root, runner=writing(text, status), head=lambda _: HEAD)

    assert [p.name for p in reviews_of(root).iterdir()] == ["transcripts"]
    assert (reviews_of(root) / "transcripts" / "01-design.log").is_file()


def test_rejected_output_is_kept_with_its_transcript(tmp_path: Path) -> None:
    root = repository(tmp_path)

    with pytest.raises(ReviewError):
        run_review(CHANGE, "design", root=root, runner=writing("ERROR: refused\n"),
                   head=lambda _: HEAD)

    rejected = reviews_of(root) / "transcripts" / "01-design.rejected.md"
    assert rejected.read_text("utf-8") == "ERROR: refused\n"


@pytest.mark.parametrize("change,kind", [("missing", "design"), ("archive", "design"),
                                         ("../x", "design"), (CHANGE, "triage")])
def test_unknown_change_or_kind_is_refused(tmp_path: Path, change: str, kind: str) -> None:
    root = repository(tmp_path)

    with pytest.raises(ReviewError):
        run_review(change, kind, root=root, runner=writing(review_text()), head=lambda _: HEAD)


def test_a_closeout_review_of_an_archived_change_is_recorded_in_the_archive(tmp_path: Path) -> None:
    archived = tmp_path / "openspec/changes/archive" / f"2026-10-14-{CHANGE}"
    archived.mkdir(parents=True)

    path = run_review(CHANGE, "closeout", root=tmp_path,
                      runner=writing(review_text("closeout")), head=lambda _: HEAD)

    assert path == archived / "reviews" / "01-closeout.md"


def test_a_closeout_review_of_an_active_change_is_refused(tmp_path: Path) -> None:
    root = repository(tmp_path)
    calls: list[list[str]] = []

    with pytest.raises(ReviewError, match="not archived"):
        run_review(CHANGE, "closeout", root=root, head=lambda _: HEAD,
                   runner=writing(review_text("closeout"), calls=calls))

    assert calls == []
    assert not (reviews_of(root) / "transcripts").exists()


def test_a_later_review_continues_the_last_reviewer_read_only(tmp_path: Path) -> None:
    root = repository(tmp_path)
    run_review(CHANGE, "design", root=root, runner=writing(review_text(), session="first"),
               head=lambda _: HEAD)
    calls: list[list[str]] = []

    path = run_review(CHANGE, "design", root=root,
                      runner=writing(review_text(), calls=calls, session="first"),
                      head=lambda _: HEAD)

    command = calls[0]
    assert command[:4] == ["codex", "exec", "resume", "first"]
    assert command[command.index("--config") + 1] == 'sandbox_mode="read-only"'
    assert "01-design" in command[-1] and "triage records" in command[-1]
    assert path.stem == "02-design"
    assert path.read_text("utf-8").count("<!-- reviewer-session: codex:first -->\n") == 1


def test_the_latest_review_is_continued_past_two_digit_numbers(tmp_path: Path) -> None:
    root = repository(tmp_path)
    for number, session in ((94, "older"), (101, "latest")):
        (reviews_of(root) / f"{number}-implementation.md").write_text(
            review_text("implementation") + f"\n<!-- reviewer-session: codex:{session} -->\n",
            "utf-8")
    calls: list[list[str]] = []

    run_review(CHANGE, "implementation", root=root,
               runner=writing(review_text("implementation"), calls=calls), head=lambda _: HEAD)

    assert calls[0][:4] == ["codex", "exec", "resume", "latest"]
    assert "101-implementation" in calls[0][-1]


def test_an_untagged_reviewer_session_is_continued_in_codex(tmp_path: Path) -> None:
    root = repository(tmp_path)
    kind = "design"
    (reviews_of(root) / f"01-{kind}.md").write_text(
        review_text() + "\n<!-- reviewer-session: old -->\n", "utf-8")
    calls: list[list[str]] = []

    run_review(CHANGE, "design", root=root, runner=writing(review_text(), calls=calls),
               head=lambda _: HEAD)

    assert calls[0][:4] == ["codex", "exec", "resume", "old"]


def test_fresh_starts_a_new_reviewer(tmp_path: Path) -> None:
    root = repository(tmp_path)
    run_review(CHANGE, "design", root=root, runner=writing(review_text(), session="first"),
               head=lambda _: HEAD)
    calls: list[list[str]] = []

    run_review(CHANGE, "design", fresh=True, root=root,
               runner=writing(review_text(), calls=calls, session="second"), head=lambda _: HEAD)

    assert calls[0][:3] == ["codex", "exec", "--sandbox"]


def test_a_review_of_another_kind_does_not_continue(tmp_path: Path) -> None:
    root = repository(tmp_path)
    run_review(CHANGE, "design", root=root, runner=writing(review_text(), session="first"),
               head=lambda _: HEAD)
    calls: list[list[str]] = []

    run_review(CHANGE, "implementation", root=root,
               runner=writing(review_text("implementation"), calls=calls), head=lambda _: HEAD)

    assert "resume" not in calls[0]


def test_a_closeout_review_does_not_continue_a_pre_closeout_reviewer(tmp_path: Path) -> None:
    reviews = tmp_path / "reviews"
    reviews.mkdir()
    (reviews / "28-pre-closeout.md").write_text(
        review_text("pre-closeout") + "\n<!-- reviewer-session: codex:pre -->\n", "utf-8")

    assert prior_session(reviews, "closeout") is None

    (reviews / "35-closeout.md").write_text(
        review_text("closeout") + "\n<!-- reviewer-session: codex:close -->\n", "utf-8")

    assert prior_session(reviews, "closeout") == ("codex", "close", "35-closeout")
    assert prior_session(reviews, "pre-closeout") == ("codex", "pre", "28-pre-closeout")


def test_an_external_review_is_never_continued(tmp_path: Path) -> None:
    root = repository(tmp_path)
    (reviews_of(root) / "01-design-external.md").write_text(review_text(), "utf-8")
    calls: list[list[str]] = []

    run_review(CHANGE, "design", root=root, runner=writing(review_text(), calls=calls),
               head=lambda _: HEAD)

    assert "resume" not in calls[0]


def test_a_record_written_during_the_run_takes_the_earlier_number(tmp_path: Path) -> None:
    root = repository(tmp_path, "01-design.log")
    inner = writing(review_text("implementation"))

    def runner(command: Sequence[str], log: Path) -> int:
        # A validation started beside the review publishes its record meanwhile.
        (reviews_of(root) / "02-validation.md").write_text("x", "utf-8")
        return inner(command, log)

    path = run_review(CHANGE, "implementation", root=root, runner=runner, head=lambda _: HEAD)

    assert path.name == "03-implementation.md"
    assert (reviews_of(root) / "transcripts" / "03-implementation.log").is_file()
    assert not list((reviews_of(root) / "transcripts").glob("pending-*"))


@pytest.mark.parametrize("records, reason", [
    ({}, "no validation record"),
    ({"03-validation.md": validation_text("f" * 40, "passed")}, "not HEAD"),
    ({"03-validation.md": validation_text(HEAD, "inconclusive")}, "inconclusive, not passed"),
    ({"03-validation.md": validation_text(HEAD, "passed"),
      "05-validation.md": validation_text(HEAD, "failed")}, "05-validation.md's result is failed"),
])
def test_a_pre_closeout_review_needs_a_passing_validation_of_head(
    tmp_path: Path, records: dict[str, str], reason: str
) -> None:
    root = repository(tmp_path)
    for name, text in records.items():
        (reviews_of(root) / name).write_text(text, "utf-8")
    calls: list[list[str]] = []

    with pytest.raises(ReviewError, match=reason):
        run_review(CHANGE, "pre-closeout", root=root, head=lambda _: HEAD,
                   runner=writing(review_text("pre-closeout"), calls=calls))

    assert calls == []


def test_a_passing_validation_of_head_admits_a_pre_closeout_review(tmp_path: Path) -> None:
    root = repository(tmp_path)
    (reviews_of(root) / "03-validation.md").write_text(validation_text(HEAD, "passed"), "utf-8")

    path = run_review(CHANGE, "pre-closeout", root=root, head=lambda _: HEAD,
                      runner=writing(review_text("pre-closeout")))

    assert path.name == "04-pre-closeout.md"


def test_a_ledger_commit_after_validation_admits_a_pre_closeout_review(tmp_path: Path) -> None:
    root = repository(tmp_path)
    (reviews_of(root) / "03-validation.md").write_text(validation_text(VALIDATED, "passed"),
                                                       "utf-8")

    path = run_review(
        CHANGE, "pre-closeout", root=root, head=lambda _: HEAD,
        changed_since=lambda *_: [f"{RECORDS}/interventions.jsonl"],
        runner=writing(review_text("pre-closeout")))

    assert path.name == "04-pre-closeout.md"


DOCUMENTS = ["openspec/changes/README.md", f"{RECORDS}/specs/x/spec.md"]


def test_a_document_commit_after_a_pre_closeout_triage_admits_the_next_review(
        tmp_path: Path) -> None:
    root = repository(tmp_path)
    (reviews_of(root) / "03-validation.md").write_text(validation_text(VALIDATED, "passed"),
                                                       "utf-8")
    (reviews_of(root) / "04-pre-closeout.md").write_text("x", "utf-8")
    (reviews_of(root) / "04-pre-closeout.triage.md").write_text("## Next\n\nAnother round\n",
                                                               "utf-8")

    path = run_review(CHANGE, "pre-closeout", root=root, head=lambda _: HEAD,
                      changed_since=lambda *_: DOCUMENTS,
                      runner=writing(review_text("pre-closeout")))

    assert path.name == "05-pre-closeout.md"


def test_a_document_commit_before_any_pre_closeout_review_needs_validating(
        tmp_path: Path) -> None:
    root = repository(tmp_path)
    (reviews_of(root) / "03-validation.md").write_text(validation_text(VALIDATED, "passed"),
                                                       "utf-8")

    with pytest.raises(ReviewError, match="specs/x/spec.md"):
        run_review(CHANGE, "pre-closeout", root=root, head=lambda _: HEAD,
                   changed_since=lambda *_: DOCUMENTS,
                   runner=writing(review_text("pre-closeout")))


def test_the_owner_may_run_a_pre_closeout_review_unvalidated(tmp_path: Path) -> None:
    root = repository(tmp_path)

    path = run_review(CHANGE, "pre-closeout", root=root, unvalidated=True,
                      head=lambda _: HEAD, runner=writing(review_text("pre-closeout")))

    assert path.name == "01-pre-closeout.md"


def test_an_implementation_review_never_waits_for_validation(tmp_path: Path) -> None:
    root = repository(tmp_path)

    path = run_review(CHANGE, "implementation", root=root, head=lambda _: HEAD,
                      runner=writing(review_text("implementation")))

    assert path.name == "01-implementation.md"


def test_an_interrupted_run_still_numbers_its_transcript(tmp_path: Path) -> None:
    root = repository(tmp_path)

    def runner(command: Sequence[str], log: Path) -> int:
        log.write_text("partial\n", "utf-8")
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_review(CHANGE, "design", root=root, runner=runner, head=lambda _: HEAD)

    transcripts = reviews_of(root) / "transcripts"
    assert [p.name for p in transcripts.iterdir()] == ["01-design.log"]


def test_a_claimed_name_is_never_overwritten(tmp_path: Path) -> None:
    reviews = reviews_of(repository(tmp_path))
    taken = reviews / "03-validation.md"
    taken.write_text("another writer's record", "utf-8")
    proposals = iter([taken, reviews / "04-validation.md"])

    claimed = claim_record(reviews, "validation", propose=lambda *_: next(proposals))

    assert claimed.name == "04-validation.md"
    assert taken.read_text("utf-8") == "another writer's record"


def test_an_interrupted_run_leaves_no_empty_record(tmp_path: Path) -> None:
    root = repository(tmp_path)

    def runner(command: Sequence[str], log: Path) -> int:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_review(CHANGE, "design", root=root, runner=runner, head=lambda _: HEAD)

    assert sorted(p.name for p in reviews_of(root).iterdir()) == ["transcripts"]


def test_the_proposed_number_advances_past_a_record_written_meanwhile(tmp_path: Path) -> None:
    reviews = reviews_of(repository(tmp_path, "01-design.log"))
    (reviews / "02-validation.md").write_text("another writer's record", "utf-8")

    claimed = claim_record(reviews, "validation")

    assert claimed.name == "03-validation.md"
    assert (reviews / "02-validation.md").read_text("utf-8") == "another writer's record"


# A review's outcome in the workflow log.

def test_a_published_review_is_logged_finished_naming_its_record_and_commit(
        tmp_path: Path) -> None:
    root = repository(tmp_path)
    kind = "design"

    line = review_and_log(CHANGE, kind, root=root, clock=clock,
                          runner=writing(review_text(), session="codex-1"),
                          head=lambda _: HEAD)

    assert line == {"seq": 1, "at": "2026-10-21T09:15:40Z", "format": 2, "step": "review",
                    "session": "codex:codex-1", "commit": HEAD, "kind": "design",
                    "record": f"01-{kind}.md", "harness": "codex", "model": "gpt-6-sol",
                    "effort": "high", "outcome": "finished",
                    "next": {"step": "triage", "kind": "design"},
                    "message": f"01-{kind}.md written; triage is next"}


@pytest.mark.parametrize("codex,why", [
    (codex_missing, "codex is not installed"),
    (codex_saying("ERROR: Not logged in. Run codex login."),
     "ERROR: Not logged in. Run codex login."),
    (codex_saying("ERROR: You've hit your usage limit. Try again at 3:05 PM."),
     "ERROR: You've hit your usage limit. Try again at 3:05 PM."),
])
def test_a_review_falls_back_to_claude_when_codex_is_unavailable(
        tmp_path: Path, codex, why: str) -> None:
    root = repository(tmp_path)
    claude = claude_review(review_text("implementation"))

    line = review_and_log(CHANGE, "implementation", root=root, clock=clock, runner=codex,
                          claude=claude, head=lambda _: HEAD, echo=None)

    command = claude.commands[0]
    assert command[:3] == ["claude", "-p", ("Use the change-review skill. Review kind: "
                                            f"implementation. Change: {CHANGE}. Base: dev.")]
    assert "--json-schema" not in command
    assert (option(command, "--model"), option(command, "--effort")) == ("claude-opus-5-5",
                                                                         "high")
    assert option_rules(command, "--allowedTools") == list(load_steps()["review"].allow)
    assert "Edit" in option_rules(command, "--disallowedTools")
    record = reviews_of(root) / "01-implementation.md"
    text = record.read_text("utf-8")
    assert "<!-- reviewer-session: claude:c-1 -->" in text
    assert "<!-- reviewer: claude claude-opus-5-5 high -->" in text
    assert f"<!-- reviewer-unavailable: codex gpt-6-sol: {why} -->" in text
    assert (line["outcome"], line["record"], line["session"]) == (
        "finished", "01-implementation.md", "claude:c-1")
    assert (line["harness"], line["model"], line["effort"]) == ("claude", "claude-opus-5-5",
                                                               "high")
    assert line["unavailable"] == [{"harness": "codex", "model": "gpt-6-sol", "reason": why}]
    assert line["transcript"] == "transcripts/01-implementation.log"
    assert line["denials"] == []
    assert "codex gpt-6-sol being unavailable" in line["message"]


def test_a_claude_reviews_denials_are_recorded_from_its_transcript(tmp_path: Path) -> None:
    root = repository(tmp_path)
    denied = [{"tool_name": "Edit", "tool_use_id": "t1",
               "tool_input": {"file_path": "scripts/x.py"}}]
    claude = claude_review(review_text(), denials=denied)

    line = review_and_log(CHANGE, "design", root=root, clock=clock, runner=codex_missing,
                          claude=claude, head=lambda _: HEAD, echo=None)

    assert line["denials"] == denied


def test_a_claude_review_continues_only_a_claude_reviewer(tmp_path: Path) -> None:
    root = repository(tmp_path)
    run_review(CHANGE, "design", root=root, runner=codex_missing,
               claude=claude_review(review_text(), session="c-1"), head=lambda _: HEAD,
               echo=None)
    again = claude_review(review_text(), session="c-1")

    run_review(CHANGE, "design", root=root, runner=codex_missing, claude=again,
               head=lambda _: HEAD, echo=None)
    calls: list[list[str]] = []
    run_review(CHANGE, "design", root=root, runner=writing(review_text(), calls=calls),
               head=lambda _: HEAD)

    assert option(again.commands[0], "--resume") == "c-1"
    assert "01-design" in again.commands[0][2]
    # Codex is available again, and starts fresh rather than resuming Claude's session.
    assert calls[0][:3] == ["codex", "exec", "--sandbox"]


def test_a_review_with_no_reviewer_available_publishes_nothing(tmp_path: Path) -> None:
    root = repository(tmp_path)

    def missing(command, cwd, feed) -> int:
        raise not_installed("claude")

    line = review_and_log(CHANGE, "design", root=root, clock=clock, runner=codex_missing,
                          claude=missing, head=lambda _: HEAD, echo=None)

    assert line["outcome"] == "stopped"
    assert line["reason"] == ("the reviewer produced no review: no reviewer is available: "
                              "codex gpt-6-sol: codex is not installed; claude "
                              "claude-opus-5-5: claude is not installed")
    assert [entry["model"] for entry in line["unavailable"]] == ["gpt-6-sol", "claude-opus-5-5"]
    assert not [p for p in reviews_of(root).iterdir() if p.suffix == ".md"]


@pytest.mark.parametrize("lost", ["codex", "claude"])
def test_a_file_the_reviewer_cannot_find_is_no_unavailability(tmp_path: Path,
                                                               lost: str) -> None:
    # Only the program failing to launch says the harness cannot serve its model,
    # so a reviewer whose run cannot find another file stops the review rather
    # than falling to the next model.
    root = repository(tmp_path)
    claude = claude_review(review_text())

    def codex_lost(command, log) -> int:
        raise not_installed(str(log))

    def claude_lost(command, cwd, feed) -> int:
        raise not_installed(str(tmp_path / "gone" / "01-design.log"))

    line = review_and_log(CHANGE, "design", root=root, clock=clock,
                          runner=codex_lost if lost == "codex" else codex_missing,
                          claude=claude if lost == "codex" else claude_lost,
                          head=lambda _: HEAD, echo=None)

    assert line["outcome"] == "stopped"
    assert line["reason"].startswith("the review did not finish: FileNotFoundError")
    assert "unavailable" not in line
    assert claude.commands == []


def test_a_failed_claude_reviews_denials_are_on_its_stopped_line(tmp_path: Path) -> None:
    root = repository(tmp_path)
    denied = [{"tool_name": "Edit", "tool_use_id": "t1", "tool_input": {}}]

    line = review_and_log(CHANGE, "design", root=root, clock=clock, runner=codex_missing,
                          claude=claude_review("not a review", denials=denied),
                          head=lambda _: HEAD, echo=None)

    assert line["outcome"] == "stopped"
    assert (line["denials"], line["transcript"]) == (denied, "transcripts/01-design.log")
    assert line["unavailable"][0]["harness"] == "codex"


def test_a_reviewers_output_mentioning_a_limit_is_not_read_as_codex_unavailable(
        tmp_path: Path) -> None:
    root = repository(tmp_path)
    claude = FakeClaude()

    line = review_and_log(CHANGE, "design", root=root, clock=clock,
                          runner=codex_saying("exec\ncat scripts/x.py\n"
                                              "# a usage limit, a connection error"),
                          claude=claude, head=lambda _: HEAD, echo=None)

    assert claude.commands == []
    assert line["reason"].startswith("the reviewer produced no review: the reviewer exited 1")


def test_a_reviews_network_error_is_retried_and_never_falls_back(tmp_path: Path) -> None:
    root = repository(tmp_path)
    calls: list[list[str]] = []

    def unreachable(command: Sequence[str], log: Path) -> int:
        calls.append(list(command))
        return codex_saying("ERROR: stream error: connection error; retrying")(command, log)

    line = review_and_log(CHANGE, "design", root=root, clock=clock, runner=unreachable,
                          claude=FakeClaude(), head=lambda _: HEAD, echo=None)

    assert len(calls) == 3
    assert line["outcome"] == "stopped"
    assert "gpt-6-sol could not be reached after 3 attempts" in line["reason"]


def test_a_failed_review_beside_an_earlier_record_is_logged_stopped(tmp_path: Path) -> None:
    root = repository(tmp_path)
    kind = "design"
    (reviews_of(root) / f"01-{kind}.md").write_text(review_text(), "utf-8")

    line = review_and_log(CHANGE, "design", root=root, clock=clock,
                          runner=writing("ERROR: refused\n"), head=lambda _: HEAD)

    assert (line["outcome"], line["commit"], line["session"]) == ("stopped", HEAD, None)
    assert line["reason"].startswith("the reviewer produced no review")
    assert "record" not in line


def test_a_review_refused_before_it_runs_is_logged_stopped(tmp_path: Path) -> None:
    root = repository(tmp_path)

    line = review_and_log(CHANGE, "pre-closeout", root=root, clock=clock,
                          runner=writing(review_text("pre-closeout")), head=lambda _: HEAD)

    assert line["outcome"] == "stopped"
    assert "no validation record" in line["reason"]
    assert "override" not in line


def test_a_refused_review_on_the_owners_model_is_marked_an_override(tmp_path: Path) -> None:
    root = repository(tmp_path)

    line = review_and_log(CHANGE, "pre-closeout", root=root, clock=clock,
                          model="gpt-6-astra", runner=writing(review_text("pre-closeout")),
                          head=lambda _: HEAD)

    assert (line["outcome"], line["override"]) == ("stopped", True)


def test_an_interrupted_review_is_logged_stopped(tmp_path: Path) -> None:
    root = repository(tmp_path)

    def runner(command, log: Path) -> int:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        review_and_log(CHANGE, "design", root=root, clock=clock, runner=runner,
                       head=lambda _: HEAD)

    line = read_log(log_path(root, CHANGE))[-1]
    assert (line["outcome"], line["reason"]) == (
        "stopped", "the review did not finish: KeyboardInterrupt")


def test_a_review_quoting_an_earlier_records_markers_is_logged_with_its_own(
        tmp_path: Path) -> None:
    root = repository(tmp_path)
    quoted = review_text().replace("The record has no field for it.",
                                   "The earlier record ends `<!-- reviewer-session: old -->` and "
                                   f"`<!-- reviewed-commit: {'e' * 40} -->`.")

    line = review_and_log(CHANGE, "design", root=root, clock=clock,
                          runner=writing(quoted, session="new"), head=lambda _: HEAD)

    assert (line["session"], line["commit"]) == ("codex:new", HEAD)


def test_a_reviewer_that_cannot_start_is_logged_stopped_with_head(tmp_path: Path) -> None:
    root = repository(tmp_path)

    def broken(command, log: Path) -> int:
        raise PermissionError("codex")

    line = review_and_log(CHANGE, "design", root=root, clock=clock, runner=broken,
                          head=lambda _: HEAD)

    assert (line["outcome"], line["commit"]) == ("stopped", HEAD)
    assert line["reason"] == "the review did not finish: PermissionError: codex"


def test_a_review_is_recorded_in_progress_while_it_runs_and_forgotten_after(
        tmp_path: Path) -> None:
    root = repository(tmp_path)
    runs = tmp_path / "git" / "change-runs"
    seen: list[list] = []
    review = writing(review_text(), session="codex-1")

    def watched(command: Sequence[str], log: Path) -> int:
        seen.append(live_runs(runs))
        return review(command, log)

    def head(_: Path) -> str:
        seen.append(live_runs(runs))
        return HEAD

    line = review_and_log(CHANGE, "design", root=root, clock=clock, runner=watched, head=head,
                          runs=lambda _: runs)

    assert line["outcome"] == "finished" and len(seen) >= 2
    assert all([(run.step, run.change) for run in live] == [("review", CHANGE)]
               for live in seen)
    assert list(runs.iterdir()) == []
