"""A validation record clears a commit when it names that commit, or an ancestor that
differs from it only in changes' records."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from change_workflow.records import changed_since, validation_problem
from change_workflow_fixtures import (CHANGE, HEAD, RECORDS, VALIDATED, repository, reviews_of,
                                      validation_text)


@pytest.mark.parametrize("changed, reason", [
    ([f"{RECORDS}/interventions.jsonl", f"{RECORDS}/reviews/05-validation.triage.md"], None),
    ([], None),
    ([f"{RECORDS}/interventions.jsonl", f"{RECORDS}/notes.txt"], f"also changes {RECORDS}/notes.txt"),
    (["openspec/changes/other/interventions.jsonl", "openspec/changes/other/reviews/01-review.txt"],
     None),
    (["openspec/changes/other/notes.jsonl"], "also changes openspec/changes/other/notes.jsonl"),
    (["openspec/changes/interventions.jsonl"], "also changes openspec/changes/interventions.jsonl"),
    (["openspec/changes/archive/interventions.jsonl"], "also changes openspec/changes/archive/"),
    (["openspec/changes/archive/reviews/01-closeout.md"], "also changes openspec/changes/archive/"),
    ([f"openspec/changes/archive/2026-10-20-{CHANGE}/interventions.jsonl",
      f"openspec/changes/archive/2026-10-20-{CHANGE}/reviews/09-closeout.triage.md"], None),
    (None, "not HEAD"),
])
def test_a_validation_of_an_ancestor_clears_head_when_only_records_changed(
    tmp_path: Path, changed: list[str] | None, reason: str | None
) -> None:
    root = repository(tmp_path)
    (reviews_of(root) / "03-validation.md").write_text(validation_text(VALIDATED, "passed"),
                                                       "utf-8")
    compared: list[tuple[str, str]] = []

    def changed_since(_: Path, commit: str, head: str) -> list[str] | None:
        compared.append((commit, head))
        return changed

    problem = validation_problem(reviews_of(root), HEAD, root, changed_since)

    assert compared == [(VALIDATED, HEAD)]
    if reason is None:
        assert problem is None
    else:
        assert problem is not None and reason in problem


def test_the_paths_changed_since_are_read_from_git(tmp_path: Path) -> None:
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=tmp_path, capture_output=True, text=True,
                              check=True).stdout.strip()

    git("init", "-q")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "Test")
    (tmp_path / "ledger.jsonl").write_text("1\n", "utf-8")
    git("add", ".")
    git("commit", "-qm", "base")
    base = git("rev-parse", "HEAD")
    (tmp_path / "ledger.jsonl").write_text("1\n2\n", "utf-8")
    (tmp_path / "név.md").write_text("x", "utf-8")
    git("add", ".")
    git("commit", "-qm", "records")
    head = git("rev-parse", "HEAD")

    assert sorted(changed_since(tmp_path, base, head)) == ["ledger.jsonl", "név.md"]
    git("mv", "ledger.jsonl", "moved.jsonl")
    git("commit", "-qm", "rename")

    assert sorted(changed_since(tmp_path, head, git("rev-parse", "HEAD"))) == [
        "ledger.jsonl", "moved.jsonl"]
    assert changed_since(tmp_path, head, base) is None
    assert changed_since(tmp_path, "e" * 40, head) is None


@pytest.mark.parametrize("record, admitted", [
    (f"- **Commit:** {HEAD[:12]} on feat/x\n- **Result:** passed — why\n", True),
    (f"- **Commit:** `{HEAD}` on feat/x\n- **Result:** passed — why\n", False),
    (f"- **Commit:** {HEAD} on feat/x\n- **Result:** **passed**\n", False),
])
def test_the_validation_record_lines_are_read_exactly(
    tmp_path: Path, record: str, admitted: bool
) -> None:
    reviews = reviews_of(repository(tmp_path))
    (reviews / "02-validation.md").write_text(record, "utf-8")

    assert (validation_problem(reviews, HEAD) is None) is admitted
