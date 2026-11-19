"""A run's invariants, `change_workflow.invariants`: the state recorded as a session
starts, and the seven checks against it after (CW-q7ub).

The checks' tests are library integration: the checks read Git's own state —
commits, branches, the stash, a remote's branches, the worktree as a tree — so a
real checkout of a real repository with a bare `origin` is the lowest level that
proves them. A test plays the session by changing the checkout between `record` and
`check`, as a step would. The stopped outcome's, last, is a unit test."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from change_workflow import invariants
from change_workflow.invariants import LEDGER, Violation
from change_workflow.running import ATTEMPTED_PUSH
from change_workflow_fixtures import CHANGE

INERT = ("docs/", "**/README.md", "AGENTS.md")
PROTECTED = ("main", "dev")
IDENTITY = {"GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@example.invalid"}
CHANGED = f"openspec/changes/{CHANGE}"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, env={**os.environ, **IDENTITY}, check=True,
                          capture_output=True, text=True).stdout.strip()


def _write(root: Path, path: str, text: str) -> None:
    (root / path).parent.mkdir(parents=True, exist_ok=True)
    (root / path).write_text(text, "utf-8")


def _commit(root: Path, message: str, *paths: str) -> str:
    _git(root, "add", *(paths or ("--all",)))
    _git(root, "commit", "-qm", message)
    return _git(root, "rev-parse", "HEAD")


@pytest.fixture(autouse=True)
def _own_git_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A change's checkout on `feat/change`, pushed to a bare `origin` holding `dev`:
    code beside a README, the change's documents, ledger, and delta, and, in its
    ignored `reviews/`, a review record and the workflow log."""
    remote, root = tmp_path / "remote.git", tmp_path / "work"
    _git(tmp_path, "init", "-q", "--bare", str(remote))
    _git(tmp_path, "init", "-q", "-b", "dev", str(root))
    for path, text in ((".gitignore", "openspec/changes/**/reviews/\n"),
                       ("src/main.py", "code\n"), ("src/README.md", "readme\n"),
                       ("uv.lock", "locked\n"), ("openspec/changes/README.md", "index\n"),
                       ("openspec/specs/cap/spec.md", "spec\n"),
                       (f"{CHANGED}/notes.md", "tasks\n"),
                       (f"{CHANGED}/specs/cap/spec.md", "delta\n"),
                       (f"{CHANGED}/{LEDGER}", '{"n": 1}\n{"n": 2}\n')):
        _write(root, path, text)
    _commit(root, "base")
    _git(root, "remote", "add", "origin", str(remote))
    _git(root, "push", "-q", "origin", "dev")
    _git(root, "checkout", "-q", "-b", "feat/change")
    _git(root, "push", "-q", "-u", "origin", "feat/change")
    _write(root, f"{CHANGED}/reviews/01-implementation.md", "# Design review\n")
    _write(root, f"{CHANGED}/reviews/workflow.jsonl", '{"seq": 1}\n')
    return root


def _start(repo: Path, step: str = "implement") -> invariants.Start:
    return invariants.record(repo, step, CHANGE, inert_paths=INERT,
                             protected_branches=PROTECTED)


def _checks(repo: Path, start: invariants.Start, invoked=()) -> list[str]:
    return [violation.check for violation in invariants.check(repo, start, invoked)]


def _append(path: Path, text: str) -> None:
    with path.open("a", encoding="utf-8") as appended:
        appended.write(text)


def _pushed(commit: str, status: int = 0) -> dict:
    return {"hook": ATTEMPTED_PUSH, "branch": "feat/change", "remote": "origin",
            "commit": commit, "exit_status": status}


# What is recorded.

def test_the_state_a_session_starts_from_is_recorded(repo: Path) -> None:
    head = _git(repo, "rev-parse", "HEAD")

    start = _start(repo)

    assert (start.commit, start.branch, start.stash) == (head, "feat/change", None)
    assert start.tree == _git(repo, "rev-parse", "HEAD^{tree}")
    assert "src/main.py" in start.tracked
    assert start.log.length == len('{"seq": 1}\n')
    assert start.ledger.length == len('{"n": 1}\n{"n": 2}\n')
    assert set(start.records) == {"01-implementation.md"}
    assert start.remotes == {"origin": {"feat/change": head, "dev": head}}
    assert start.capabilities == {"cap"}


def test_reading_the_worktree_as_a_tree_leaves_the_checkouts_index_alone(repo: Path) -> None:
    """An edit and a new file are in the tree, and neither is staged."""
    _write(repo, "src/main.py", "edited\n")
    _write(repo, "src/new.py", "new\n")

    tree = invariants.worktree_tree(repo)

    assert _git(repo, "diff", "--cached", "--name-only") == ""
    assert _git(repo, "ls-files", "--others", "--exclude-standard") == "src/new.py"
    assert _git(repo, "show", f"{tree}:src/new.py") == "new"
    assert _git(repo, "show", f"{tree}:src/main.py") == "edited"


# An ordinary run passes every check.

def test_an_ordinary_implementation_run_passes_every_check(repo: Path) -> None:
    start = _start(repo)
    _write(repo, "src/main.py", "more code\n")
    head = _commit(repo, "section")
    _git(repo, "push", "-q", "origin", "HEAD:refs/heads/feat/change")
    _append(repo / CHANGED / "reviews/workflow.jsonl", '{"seq": 2}\n')
    _append(repo / CHANGED / LEDGER, '{"n": 3}\n')
    _write(repo, f"{CHANGED}/reviews/02-validation.md", "# Validation\n")
    _write(repo, f"{CHANGED}/reviews/01-implementation.triage.md", "# Triage\n")

    assert _checks(repo, start, [_pushed(head)]) == []


# 1. History.

def test_an_amended_earlier_commit_does_not_descend_from_the_start(repo: Path) -> None:
    """CW-q7ub's "A step amends an earlier commit"."""
    start = _start(repo)
    _git(repo, "commit", "-q", "--amend", "-m", "rewritten")

    assert _checks(repo, start) == ["history"]


def test_a_switched_branch_is_found(repo: Path) -> None:
    start = _start(repo)
    _git(repo, "checkout", "-q", "dev")

    assert _checks(repo, start) == ["history"]


# 2. Validation and review change nothing tracked.

def test_a_review_appending_to_the_log_during_a_validation_passes(repo: Path) -> None:
    """CW-q7ub's "A review appends to the log during a validation"."""
    start = _start(repo, "validate")
    _append(repo / CHANGED / "reviews/workflow.jsonl", '{"seq": 2, "step": "review"}\n')
    _write(repo, f"{CHANGED}/reviews/02-validation.md", "# Validation\n")

    assert _checks(repo, start) == []


def test_a_validation_that_relocks_changes_a_tracked_file(repo: Path) -> None:
    """CW-4yhk's "Validation attempts to relock": the lock is named."""
    start = _start(repo, "validate")
    _write(repo, "uv.lock", "relocked\n")

    (found,) = invariants.check(repo, start)

    assert found == Violation("unchanged", "tracked files changed: uv.lock")


def test_a_validation_that_commits_moves_head(repo: Path) -> None:
    start = _start(repo, "validate")
    _write(repo, "uv.lock", "relocked\n")
    head = _commit(repo, "relock")

    moved, files = invariants.check(repo, start)

    assert moved == Violation("unchanged", f"HEAD moved from {start.commit[:12]} to {head[:12]}")
    assert files == Violation("unchanged", "tracked files changed: uv.lock")


def test_an_implementation_may_change_tracked_files(repo: Path) -> None:
    start = _start(repo)
    _write(repo, "uv.lock", "relocked\n")

    assert _checks(repo, start) == []


# 3 and 4. The log, the review records, and the ledger only grow.

def test_a_rewritten_log_is_found(repo: Path) -> None:
    start = _start(repo, "triage")
    _write(repo, f"{CHANGED}/reviews/workflow.jsonl", '{"seq": 9}\n{"seq": 2}\n')

    assert _checks(repo, start) == ["log"]


def test_a_rewritten_review_record_is_found(repo: Path) -> None:
    start = _start(repo, "triage")
    _write(repo, f"{CHANGED}/reviews/01-implementation.md", "# Design review, softened\n")

    (found,) = invariants.check(repo, start)

    assert found == Violation("records", "review records changed or removed: 01-implementation.md")


def test_a_ledger_edited_mid_file_is_found(repo: Path) -> None:
    start = _start(repo, "triage")
    _write(repo, f"{CHANGED}/{LEDGER}", '{"n": 1}\n{"n": 2, "edited": true}\n{"n": 3}\n')

    assert _checks(repo, start) == ["records"]


# 5. The stash.

def test_a_stash_is_found(repo: Path) -> None:
    start = _start(repo)
    _write(repo, "src/main.py", "half done\n")
    _git(repo, "stash", "-q")

    assert _checks(repo, start) == ["stash"]


# 6. The remote.

def test_a_push_reaching_a_protected_branch_is_found(repo: Path) -> None:
    """CW-q7ub's "A push reaches a protected branch": a commit made in the run is on
    the remote's `dev` after it."""
    start = _start(repo)
    _write(repo, "src/main.py", "more code\n")
    _commit(repo, "section")
    _git(repo, "push", "-q", "origin", "HEAD:dev")

    (found,) = invariants.check(repo, start)

    assert found.check == "remote" and "origin's dev, a protected branch" in found.found


def test_a_commit_pushed_to_a_protected_branch_from_a_branch_since_deleted_is_found(
        repo: Path) -> None:
    """`HEAD`'s reflog keeps the commit after the branch that held it is gone."""
    start = _start(repo)
    _git(repo, "checkout", "-q", "-b", "aside")
    _write(repo, "src/main.py", "aside\n")
    _commit(repo, "aside")
    _git(repo, "push", "-q", "origin", "HEAD:dev")
    _git(repo, "checkout", "-q", "feat/change")
    _git(repo, "branch", "-q", "-D", "aside")

    assert _checks(repo, start) == ["remote"]


def test_another_partys_commit_on_a_protected_branch_is_not_the_runs(
        repo: Path, tmp_path: Path) -> None:
    """A commit pushed to `dev` by someone else during the run, which the step's fetch
    brought in, was not made in the run."""
    start = _start(repo)
    other = tmp_path / "other"
    _git(tmp_path, "clone", "-q", "-b", "dev", str(tmp_path / "remote.git"), str(other))
    _write(other, "elsewhere.txt", "theirs\n")
    _commit(other, "theirs")
    _git(other, "push", "-q", "origin", "dev")
    _git(repo, "fetch", "-q", "origin")

    assert _checks(repo, start) == []


def test_the_change_branch_moved_but_by_the_guarded_push_is_found(repo: Path) -> None:
    start = _start(repo)
    _write(repo, "src/main.py", "more code\n")
    head = _commit(repo, "section")
    _git(repo, "push", "-q", "origin", "HEAD:refs/heads/feat/change")

    assert _checks(repo, start) == ["remote"]
    # A failed guarded push of that commit is no account of it either.
    assert _checks(repo, start, [_pushed(head, status=1)]) == ["remote"]
    assert _checks(repo, start, [_pushed(head)]) == []


def test_an_unreachable_remote_is_not_checked(repo: Path, tmp_path: Path) -> None:
    start = _start(repo)
    (tmp_path / "remote.git").rename(tmp_path / "gone.git")

    assert _checks(repo, start) == []


# 7. Closeout changes only what closeout may.

def test_closeout_editing_code_beside_a_readme_is_found(repo: Path) -> None:
    """CW-q7ub's "Closeout edits code beside a README": the README's directory is in
    closeout's scope, and the code beside it is not closeout's to change."""
    start = _start(repo, "closeout")
    _write(repo, "src/README.md", "readme, promoted\n")
    _write(repo, "src/main.py", "code, edited\n")
    _commit(repo, "closeout")

    (found,) = invariants.check(repo, start)

    assert found == Violation("closeout",
                              "paths closeout may not change were changed: src/main.py")


def test_closeouts_own_writes_and_the_archive_pass(repo: Path) -> None:
    start = _start(repo, "closeout")
    _write(repo, "src/README.md", "readme, promoted\n")
    _write(repo, "docs/guide.md", "guide\n")
    _write(repo, f"{CHANGED}/notes.md", "tasks, compressed\n")
    _write(repo, "openspec/specs/cap/spec.md", "spec, merged\n")
    _write(repo, "openspec/changes/README.md", "index, archived\n")
    archived = f"openspec/changes/archive/2026-11-19-{CHANGE}"
    (repo / archived).parent.mkdir()
    # The directory moves whole, its ignored records with it, as the archive moves it.
    _git(repo, "mv", CHANGED, archived)
    _commit(repo, "archive")
    _append(repo / archived / "reviews/workflow.jsonl", '{"seq": 2}\n')

    assert _checks(repo, start) == []


def test_closeout_writing_another_changes_documents_or_specification_is_found(
        repo: Path) -> None:
    start = _start(repo, "closeout")
    _write(repo, "openspec/changes/other/notes.md", "another change's\n")
    _write(repo, "openspec/specs/unrelated/spec.md", "not this change's delta\n")

    (found,) = invariants.check(repo, start)

    assert found.check == "closeout"
    assert "openspec/changes/other/notes.md" in found.found
    assert "openspec/specs/unrelated/spec.md" in found.found


# The stopped outcome.

def test_a_violation_stops_the_run_keeping_the_steps_message_ahead() -> None:
    outcome = {"outcome": "finished", "message": "Validated.", "denials": [{"tool": "x"}],
               "next": {"step": "triage", "kind": "implementation"}}

    found = invariants.stopped(outcome, [Violation("unchanged", "tracked files changed: a.py")])

    reason = "the run broke its invariants: unchanged: tracked files changed: a.py"
    assert found == {"outcome": "stopped", "message": f"Validated.\n\n{reason}",
                     "reason": reason, "denials": [{"tool": "x"}]}
    json.dumps(found)
