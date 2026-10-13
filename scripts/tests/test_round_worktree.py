"""Tests for the round worktree, against real Git repositories.

What the owner sees is Git's own status and diff of the worktree, so a temporary
repository is the lowest level that proves it; a fake Git would only restate the
overlay's assumptions.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "round_worktree.py"
_SPEC = importlib.util.spec_from_file_location("round_worktree", SCRIPT)
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


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    work = tmp_path / "work"
    _git(tmp_path, "init", "-q", "-b", "feat/change", str(work))
    # Reviews are untracked, as in the repository.
    (work / ".gitignore").write_text("reviews/\n", "utf-8")
    _write(work, {"src/kept.py": "1\n", "src/gone.py": "gone\n",
                  f"openspec/changes/{CHANGE}/notes.txt": "1\n",
                  "openspec/changes/other/notes.txt": "1\n",
                  "openspec/changes/README.md": "1\n"})
    return work


def _status(path: Path) -> set[str]:
    return {line.strip() for line in _git(path, "status", "--porcelain").splitlines()}


def test_the_worktree_shows_the_round_over_its_base_except_other_changes(repo: Path,
                                                                         tmp_path: Path) -> None:
    base = _git(repo, "rev-parse", "HEAD")
    _write(repo, {"src/kept.py": "2\n", "src/gone.py": None, "src/new.py": "1\n",
                  f"openspec/changes/{CHANGE}/notes.txt": "2\n",
                  "openspec/changes/other/notes.txt": "2\n",
                  "openspec/changes/README.md": "2\n"})
    head = _write(repo, {"src/later.py": "later\n"})

    prepared = rounds.prepare(repo, CHANGE, base=base, path=tmp_path / "round")

    assert (prepared.base, prepared.head) == (base, head)
    assert _git(prepared.path, "rev-parse", "HEAD") == base
    assert _status(prepared.path) == {
        "M src/kept.py", "D src/gone.py", "A src/new.py", "A src/later.py",
        f"M openspec/changes/{CHANGE}/notes.txt", "M openspec/changes/README.md"}
    assert (prepared.path / "openspec/changes/other/notes.txt").read_text("utf-8") == "1\n"
    assert _git(repo, "rev-parse", "HEAD") == head
    assert _git(repo, "status", "--porcelain") == ""


def test_the_base_is_the_latest_triaged_validation(repo: Path, tmp_path: Path) -> None:
    first = _git(repo, "rev-parse", "HEAD")
    second = _write(repo, {"src/kept.py": "2\n"})
    third = _write(repo, {"src/kept.py": "3\n"})
    _validation(repo, 3, first, triaged=True)
    _validation(repo, 5, second, triaged=True)
    _validation(repo, 7, third, triaged=False)

    prepared = rounds.prepare(repo, CHANGE, path=tmp_path / "round")

    assert prepared.base == second
    assert _status(prepared.path) == {"M src/kept.py"}


def test_with_no_triaged_validation_the_base_must_be_given(repo: Path, tmp_path: Path) -> None:
    _validation(repo, 1, _git(repo, "rev-parse", "HEAD"), triaged=False)
    with pytest.raises(rounds.RoundError, match="BASE="):
        rounds.prepare(repo, CHANGE, path=tmp_path / "round")


def test_a_second_run_replaces_the_worktree(repo: Path, tmp_path: Path) -> None:
    base = _git(repo, "rev-parse", "HEAD")
    _write(repo, {"src/kept.py": "2\n"})
    rounds.prepare(repo, CHANGE, base=base, path=tmp_path / "round")
    _write(repo, {"src/new.py": "1\n"})

    prepared = rounds.prepare(repo, CHANGE, base=base, path=tmp_path / "round")

    assert _status(prepared.path) == {"M src/kept.py", "A src/new.py"}


def test_a_path_that_is_not_a_worktree_is_never_removed(repo: Path, tmp_path: Path) -> None:
    occupied = tmp_path / "round"
    occupied.mkdir()
    (occupied / "mine.txt").write_text("keep", "utf-8")
    with pytest.raises(rounds.RoundError, match="nothing was removed"):
        rounds.prepare(repo, CHANGE, base="HEAD", path=occupied)
    assert (occupied / "mine.txt").read_text("utf-8") == "keep"


def test_an_unknown_change_is_refused(repo: Path, tmp_path: Path) -> None:
    with pytest.raises(rounds.RoundError, match="no active change"):
        rounds.prepare(repo, "missing", base="HEAD", path=tmp_path / "round")


def test_new_files_git_quotes_or_ignores_are_part_of_the_round(repo: Path,
                                                               tmp_path: Path) -> None:
    base = _git(repo, "rev-parse", "HEAD")
    (repo / ".gitignore").write_text("reviews/\n*.lock\n", "utf-8")
    (repo / "über.py").write_text("umlaut\n", "utf-8")
    (repo / "deps.lock").write_text("pinned\n", "utf-8")
    _git(repo, "add", "--force", ".gitignore", "über.py", "deps.lock")
    _git(repo, "commit", "-q", "-m", "commit")

    prepared = rounds.prepare(repo, CHANGE, base=base, path=tmp_path / "round")

    diff = _git(prepared.path, "-c", "core.quotePath=false", "diff", "--name-status")
    assert set(diff.splitlines()) == {"M\t.gitignore", "A\tüber.py", "A\tdeps.lock"}


def test_a_worktree_deleted_by_hand_is_replaced(repo: Path, tmp_path: Path) -> None:
    base = _git(repo, "rev-parse", "HEAD")
    _write(repo, {"src/kept.py": "2\n"})
    first = rounds.prepare(repo, CHANGE, base=base, path=tmp_path / "round")
    shutil.rmtree(first.path)

    prepared = rounds.prepare(repo, CHANGE, base=base, path=tmp_path / "round")

    assert _status(prepared.path) == {"M src/kept.py"}


def test_the_change_removed_in_the_round_shows_as_deleted(repo: Path, tmp_path: Path) -> None:
    base = _git(repo, "rev-parse", "HEAD")
    _write(repo, {f"openspec/changes/{CHANGE}/notes.txt": None})
    # The change's directory still exists in the checkout through its reviews.
    (repo / REVIEWS).mkdir(parents=True)

    prepared = rounds.prepare(repo, CHANGE, base=base, path=tmp_path / "round")

    assert _status(prepared.path) == {f"D openspec/changes/{CHANGE}/notes.txt"}


@pytest.mark.parametrize("change", ["", "archive"])
def test_an_empty_change_or_the_archive_is_refused(repo: Path, tmp_path: Path,
                                                   change: str) -> None:
    (repo / "openspec/changes/archive").mkdir()
    with pytest.raises(rounds.RoundError, match="no active change"):
        rounds.prepare(repo, change, base="HEAD", path=tmp_path / "round")
