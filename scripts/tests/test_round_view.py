"""Tests for the round view, against real Git repositories.

What the owner sees is Git's own status of the checkout, and what the view must
preserve is Git's own state — the branch, the commits, the files — so a temporary
repository is the lowest level that proves it. The push and the pipeline dispatch
go through an injected runner, since they reach a remote and GitHub.
"""

from __future__ import annotations

import importlib.util
import json
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

    def __init__(self, *, refuse_push: bool = False, fail: str | None = None) -> None:
        self.calls: list[list[str]] = []
        self.refuse_push = refuse_push
        self.fail = fail
        self.pushed: str | None = None

    def __call__(self, command: Sequence[str], cwd: Path) -> tuple[int, str]:
        command = list(command)
        if command[0] == "git":
            return rounds._run(command, cwd)
        self.calls.append(command)
        if command[-1] == self.fail:
            return 1, "failed"
        if command[-1] == "push-branch":
            if self.refuse_push:
                return 1, "REFUSED: protected branch"
            self.pushed = _git(cwd, "rev-parse", "HEAD")
            return 0, ""
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


def _round_line(repo: Path, commit: str | None) -> None:
    reviews = repo / REVIEWS
    reviews.mkdir(parents=True, exist_ok=True)
    line = {"seq": 1, "step": "orchestrator", "outcome": "round", "sections": [[2]],
            "by": "plan", "after": 0, **({"commit": commit} if commit else {})}
    with (reviews / "workflow.jsonl").open("a", encoding="utf-8") as log:
        log.write(json.dumps(line) + "\n")


def test_the_base_is_the_commit_the_latest_round_started_at(repo: Path) -> None:
    validated = _git(repo, "rev-parse", "HEAD")
    _validation(repo, 3, validated, triaged=True)
    # A design revision lands on the branch between the rounds.
    started = _write(repo, {f"openspec/changes/{CHANGE}/notes.txt": "revised\n"})
    _round_line(repo, started)
    _write(repo, {"src/kept.py": "2\n"})

    view = rounds.start(repo, CHANGE, e2e=False)

    assert view.base == started


def test_a_round_line_naming_no_commit_falls_back_to_the_triaged_validation(
        repo: Path) -> None:
    validated = _git(repo, "rev-parse", "HEAD")
    _validation(repo, 3, validated, triaged=True)
    _round_line(repo, _write(repo, {"src/kept.py": "2\n"}))
    _round_line(repo, None)
    _write(repo, {"src/kept.py": "3\n"})

    view = rounds.start(repo, CHANGE, e2e=False)

    assert view.base == validated


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


def test_a_commit_during_the_view_leaves_only_its_own_changes_on_the_round(
        repo: Path) -> None:
    base, head = _round(repo)
    rounds.start(repo, CHANGE, base=base, e2e=False)
    (repo / "src/kept.py").write_text("fixed while reading\n", "utf-8")
    _git(repo, "commit", "-q", "-am", "committed while reading")
    stray = _git(repo, "rev-parse", "HEAD")

    closed = rounds.done(repo)

    assert closed.stray == (stray,)
    assert _git(repo, "rev-parse", "HEAD") == head
    assert _status(repo) == {"M src/kept.py"}
    assert rounds.open_view(repo) is None


def test_a_view_already_back_at_the_round_is_closed(repo: Path) -> None:
    base, head = _round(repo)
    rounds.start(repo, CHANGE, base=base, e2e=False)
    _git(repo, "reset", "-q", "--mixed", head)

    closed = rounds.done(repo)

    assert closed.stray == ()
    assert _git(repo, "rev-parse", "HEAD") == head
    assert rounds.open_view(repo) is None
    rounds.check(repo)


def test_a_fix_committed_after_returning_by_hand_stays_on_the_branch(repo: Path) -> None:
    base, head = _round(repo)
    rounds.start(repo, CHANGE, base=base, e2e=False)
    _git(repo, "reset", "-q", "--mixed", head)
    fix = _write(repo, {"src/kept.py": "fixed\n"})

    closed = rounds.done(repo)

    assert closed.stray == ()
    assert _git(repo, "rev-parse", "HEAD") == fix
    assert _status(repo) == set()
    assert rounds.open_view(repo) is None


def test_a_branch_reset_to_a_round_commit_names_no_strays(repo: Path) -> None:
    base = _git(repo, "rev-parse", "HEAD")
    middle = _write(repo, {"src/kept.py": "2\n"})
    head = _write(repo, {"src/new.py": "new\n"})
    rounds.start(repo, CHANGE, base=base, e2e=False)
    _git(repo, "reset", "-q", "--mixed", middle)

    closed = rounds.done(repo)

    assert closed.stray == ()
    assert _git(repo, "rev-parse", "HEAD") == head


def test_a_view_recorded_but_never_reset_is_closed(repo: Path) -> None:
    base, head = _round(repo)
    # An interrupted start: the state written, the branch not yet moved.
    view = rounds.View(CHANGE, "feat/change", base, head)
    rounds._git_path(repo, rounds.STATE).write_text(
        rounds.json.dumps(rounds.asdict(view)), "utf-8")

    rounds.done(repo)

    assert _git(repo, "rev-parse", "HEAD") == head
    assert _status(repo) == set()
    assert rounds.open_view(repo) is None


def test_done_refuses_on_another_branch_and_keeps_the_view(repo: Path) -> None:
    base, _ = _round(repo)
    rounds.start(repo, CHANGE, base=base, e2e=False)
    _git(repo, "switch", "-q", "-c", "elsewhere")

    with pytest.raises(rounds.RoundError, match="switch back to feat/change"):
        rounds.done(repo)
    assert rounds.open_view(repo) is not None
    assert _git(repo, "rev-parse", "HEAD") == base


def test_done_refuses_a_branch_moved_off_the_base_and_names_the_way_back(
        repo: Path) -> None:
    root = _git(repo, "rev-parse", "HEAD")
    base = _write(repo, {"src/kept.py": "base\n"})
    _write(repo, {"src/kept.py": "2\n"})
    head = _git(repo, "rev-parse", "HEAD")
    rounds.start(repo, CHANGE, base=base, e2e=False)
    _git(repo, "reset", "-q", "--mixed", root)

    with pytest.raises(rounds.RoundError, match=f"git reset --mixed {head}"):
        rounds.done(repo)
    assert _git(repo, "rev-parse", "HEAD") == root
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
    head = _git(repo, "rev-parse", "HEAD")
    with pytest.raises(rounds.RoundError, match="not an ancestor"):
        rounds.start(repo, CHANGE, base=other, e2e=False)
    assert _git(repo, "rev-parse", "HEAD") == head
    assert rounds.open_view(repo) is None


def test_a_detached_head_or_an_empty_round_is_refused(repo: Path) -> None:
    head = _git(repo, "rev-parse", "HEAD")
    with pytest.raises(rounds.RoundError, match="the base is HEAD"):
        rounds.start(repo, CHANGE, base=head, e2e=False)
    assert _git(repo, "rev-parse", "HEAD") == head
    later = _write(repo, {"src/kept.py": "2\n"})
    _git(repo, "checkout", "-q", "--detach")
    with pytest.raises(rounds.RoundError, match="detached"):
        rounds.start(repo, CHANGE, base=head, e2e=False)
    assert _git(repo, "rev-parse", "HEAD") == later
    assert rounds.open_view(repo) is None


@pytest.mark.parametrize("change", ["", "archive", "missing"])
def test_an_unknown_change_is_refused(repo: Path, change: str) -> None:
    (repo / "openspec/changes/archive").mkdir()
    head = _git(repo, "rev-parse", "HEAD")
    with pytest.raises(rounds.RoundError, match="not a change name|no change"):
        rounds.start(repo, change, base="HEAD", e2e=False)
    assert _git(repo, "rev-parse", "HEAD") == head
    assert rounds.open_view(repo) is None


def test_an_archived_change_takes_its_base_from_the_archive(repo: Path) -> None:
    base, _ = _round(repo)
    archived = repo / "openspec/changes/archive" / f"2026-10-14-{CHANGE}"
    archived.parent.mkdir()
    (repo / "openspec/changes" / CHANGE).rename(archived)
    (archived / "reviews").mkdir()
    (archived / "reviews/01-validation.md").write_text(
        f"# Validation\n\n- **Commit:** {base}\n- **Result:** passed\n", "utf-8")
    (archived / "reviews/01-validation.triage.md").write_text("# Triage\n", "utf-8")
    head = _write(repo, {})  # commits the archive's move

    view = rounds.start(repo, CHANGE, e2e=False)

    assert (view.base, view.head) == (base, head)


def test_start_pushes_and_dispatches_first_and_records_the_baseline(repo: Path) -> None:
    base, head = _round(repo)
    remote = Remote()

    rounds.start(repo, CHANGE, base=base, run=remote)

    assert [call[-1] for call in remote.calls] == ["push-branch", ".[0].databaseId", "run-e2e"]
    assert remote.pushed == head
    assert _git(repo, "rev-parse", "HEAD") == base
    assert rounds.e2e_baseline(repo, base) is None
    assert rounds.e2e_baseline(repo, head, consume=True) == "41"
    assert rounds.e2e_baseline(repo, head) is None


@pytest.mark.parametrize("failing", [".[0].databaseId", "run-e2e"])
def test_a_failed_dispatch_opens_no_view(repo: Path, failing: str) -> None:
    base, head = _round(repo)

    with pytest.raises(rounds.RoundError):
        rounds.start(repo, CHANGE, base=base, run=Remote(fail=failing))

    assert _git(repo, "rev-parse", "HEAD") == head
    assert rounds.open_view(repo) is None
    assert rounds.e2e_baseline(repo, head) is None


def test_a_refused_push_opens_no_view(repo: Path) -> None:
    base, head = _round(repo)
    remote = Remote(refuse_push=True)

    with pytest.raises(rounds.RoundError, match="refused"):
        rounds.start(repo, CHANGE, base=base, run=remote)

    assert [call[-1] for call in remote.calls] == ["push-branch"]
    assert _git(repo, "rev-parse", "HEAD") == head
    assert rounds.open_view(repo) is None


def test_the_command_line_guard_fails_while_a_view_is_open(repo: Path,
                                                           capsys: pytest.CaptureFixture[str]
                                                           ) -> None:
    base, _ = _round(repo)
    assert rounds.main(["check"], root=repo) == 0
    assert rounds.main(["start", CHANGE, "--base", base, "--no-e2e"], root=repo) == 0
    assert rounds.main(["check"], root=repo) == 1
    assert "round-done" in capsys.readouterr().err
    assert rounds.main(["done"], root=repo) == 0
    assert rounds.main(["check"], root=repo) == 0


def test_the_command_line_baseline_is_printed_once(repo: Path,
                                                   capsys: pytest.CaptureFixture[str]) -> None:
    base, head = _round(repo)
    rounds.start(repo, CHANGE, base=base, run=Remote())
    rounds.done(repo)
    capsys.readouterr()

    assert rounds.main(["e2e-baseline"], root=repo) == 0
    assert capsys.readouterr().out == "41\n"
    assert rounds.main(["e2e-baseline"], root=repo) == 0
    assert capsys.readouterr().out == ""
