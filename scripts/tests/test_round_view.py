"""Tests for the round view, against real Git repositories.

What the owner sees is Git's own status of the checkout, and what the view must
preserve is Git's own state — the branch, the commits, the files — so a temporary
repository is the lowest level that proves it. The push and the pipeline dispatch
go through an injected runner, since they reach a remote and GitHub.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from typing import Sequence

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "round_view.py"
_SPEC = importlib.util.spec_from_file_location("round_view", SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
rounds = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = rounds
_SPEC.loader.exec_module(rounds)

CHANGE = "the-change"
REVIEWS = Path("openspec/changes") / CHANGE / "reviews"


def _git(cwd: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
           "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@example.invalid",
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True,
                          capture_output=True, text=True).stdout.strip()


def _write(repo: Path, files: dict[str, str | None]) -> str:
    for name, text in files.items():
        target = repo / name
        if text is None:
            target.unlink()
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, "utf-8")
    _git(repo, "add", "--all")
    _git(repo, "commit", "-q", "-m", "commit")
    return _git(repo, "rev-parse", "HEAD")


def _validation(repo: Path, number: int, commit: str, *, triaged: bool) -> None:
    reviews = repo / REVIEWS
    reviews.mkdir(parents=True, exist_ok=True)
    (reviews / f"{number:02d}-validation.md").write_text(
        f"# Validation\n\n- **Commit:** {commit} on feat/change\n- **Result:** passed\n", "utf-8")
    if triaged:
        (reviews / f"{number:02d}-validation.triage.md").write_text("# Triage\n", "utf-8")


class Remote:
    """The push and the dispatch, recorded; any other command runs for real."""

    def __init__(self, *, refuse_push: bool = False) -> None:
        self.calls: list[list[str]] = []
        self.refuse_push = refuse_push

    def __call__(self, command: Sequence[str], cwd: Path) -> tuple[int, str]:
        command = list(command)
        if command[0] == "git":
            return rounds._run(command, cwd)
        self.calls.append(command)
        if command[-1] == "push-branch":
            return (1, "REFUSED: protected branch") if self.refuse_push else (0, "")
        if command[:3] == ["gh", "run", "list"]:
            return 0, "41\n"
        return 0, ""


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    work = tmp_path / "work"
    _git(tmp_path, "init", "-q", "-b", "feat/change", str(work))
    # Reviews are untracked, as in the repository.
    (work / ".gitignore").write_text("reviews/\n", "utf-8")
    _write(work, {"src/kept.py": "1\n", "src/gone.py": "gone\n",
                  f"openspec/changes/{CHANGE}/notes.txt": "1\n"})
    return work


def _status(repo: Path) -> set[str]:
    return {line.strip() for line in _git(repo, "status", "--porcelain").splitlines()}


def _round(repo: Path) -> tuple[str, str]:
    base = _git(repo, "rev-parse", "HEAD")
    _write(repo, {"src/kept.py": "2\n", "src/gone.py": None})
    head = _write(repo, {"src/new.py": "new\n"})
    return base, head


def test_the_round_shows_as_uncommitted_changes_with_the_files_unchanged(repo: Path) -> None:
    base, head = _round(repo)

    view = rounds.start(repo, CHANGE, base=base, e2e=False)

    assert (view.base, view.head) == (base, head)
    assert _git(repo, "rev-parse", "HEAD") == base
    assert _git(repo, "branch", "--show-current") == "feat/change"
    assert _status(repo) == {"M src/kept.py", "D src/gone.py", "A src/new.py"}
    assert (repo / "src/new.py").read_text("utf-8") == "new\n"
    assert "src/new.py" in _git(repo, "diff", "--name-only")


def test_done_restores_the_commit_and_keeps_the_owners_edits(repo: Path) -> None:
    base, head = _round(repo)
    rounds.start(repo, CHANGE, base=base, e2e=False)
    (repo / "src/kept.py").write_text("edited while reading\n", "utf-8")

    rounds.done(repo)

    assert _git(repo, "rev-parse", "HEAD") == head
    assert _status(repo) == {"M src/kept.py"}
    assert rounds.open_view(repo) is None


def test_done_without_edits_leaves_a_clean_worktree(repo: Path) -> None:
    base, head = _round(repo)
    rounds.start(repo, CHANGE, base=base, e2e=False)

    rounds.done(repo)

    assert _git(repo, "rev-parse", "HEAD") == head
    assert _status(repo) == set()


def test_the_base_is_the_latest_triaged_validation(repo: Path) -> None:
    first = _git(repo, "rev-parse", "HEAD")
    second = _write(repo, {"src/kept.py": "2\n"})
    _write(repo, {"src/kept.py": "3\n"})
    _validation(repo, 3, first, triaged=True)
    _validation(repo, 5, second, triaged=True)
    _validation(repo, 7, _git(repo, "rev-parse", "HEAD"), triaged=False)

    view = rounds.start(repo, CHANGE, e2e=False)

    assert view.base == second


def test_with_no_triaged_validation_the_base_must_be_given(repo: Path) -> None:
    _write(repo, {"src/kept.py": "2\n"})
    with pytest.raises(rounds.RoundError, match="BASE="):
        rounds.start(repo, CHANGE, e2e=False)


def test_steps_that_describe_a_commit_refuse_while_the_view_is_open(repo: Path) -> None:
    base, _ = _round(repo)
    rounds.check(repo)
    rounds.start(repo, CHANGE, base=base, e2e=False)
    with pytest.raises(rounds.RoundError, match="round-done"):
        rounds.check(repo)
    with pytest.raises(rounds.RoundError, match="already open"):
        rounds.start(repo, CHANGE, base=base, e2e=False)


def test_done_refuses_when_something_committed_during_the_view(repo: Path) -> None:
    base, head = _round(repo)
    rounds.start(repo, CHANGE, base=base, e2e=False)
    _git(repo, "commit", "-q", "-am", "committed while reading")

    with pytest.raises(rounds.RoundError, match=head):
        rounds.done(repo)
    assert rounds.open_view(repo) is not None


@pytest.mark.parametrize("dirty", ["src/kept.py", "untracked.txt"])
def test_a_dirty_worktree_is_refused_and_nothing_moves(repo: Path, dirty: str) -> None:
    base, head = _round(repo)
    (repo / dirty).write_text("mine\n", "utf-8")
    with pytest.raises(rounds.RoundError, match="not clean"):
        rounds.start(repo, CHANGE, base=base, e2e=False)
    assert _git(repo, "rev-parse", "HEAD") == head
    assert rounds.open_view(repo) is None


def test_a_base_that_is_not_an_ancestor_is_refused(repo: Path) -> None:
    root = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "-b", "elsewhere")
    other = _write(repo, {"src/other.py": "other\n"})
    _git(repo, "checkout", "-q", "feat/change")
    _git(repo, "reset", "-q", "--hard", root)
    _write(repo, {"src/kept.py": "2\n"})
    with pytest.raises(rounds.RoundError, match="not an ancestor"):
        rounds.start(repo, CHANGE, base=other, e2e=False)


@pytest.mark.parametrize("change", ["", "archive", "missing"])
def test_an_unknown_change_is_refused(repo: Path, change: str) -> None:
    (repo / "openspec/changes/archive").mkdir()
    with pytest.raises(rounds.RoundError, match="no active change"):
        rounds.start(repo, change, base="HEAD", e2e=False)


def test_start_pushes_and_dispatches_first_and_records_the_baseline(repo: Path) -> None:
    base, head = _round(repo)
    remote = Remote()

    rounds.start(repo, CHANGE, base=base, run=remote)

    assert [call[-1] for call in remote.calls] == ["push-branch", ".[0].databaseId", "run-e2e"]
    assert rounds.e2e_baseline(repo, head) == "41"
    assert rounds.e2e_baseline(repo, base) is None


def test_a_refused_push_opens_no_view(repo: Path) -> None:
    base, head = _round(repo)
    remote = Remote(refuse_push=True)

    with pytest.raises(rounds.RoundError, match="refused"):
        rounds.start(repo, CHANGE, base=base, run=remote)

    assert [call[-1] for call in remote.calls] == ["push-branch"]
    assert _git(repo, "rev-parse", "HEAD") == head
    assert rounds.open_view(repo) is None
