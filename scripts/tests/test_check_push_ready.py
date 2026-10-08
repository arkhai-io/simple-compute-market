"""Tests for the guarded push of a change branch, against real Git repositories.

The guard's meaning is Git's own state — attachment, upstream configuration, what a
push sends — so a temporary repository with a bare remote is the lowest level that
proves it; a fake Git would only restate the guard's assumptions.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check_push_ready.py"
_SPEC = importlib.util.spec_from_file_location("check_push_ready", SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
guard = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = guard
_SPEC.loader.exec_module(guard)


def _git(cwd: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
           "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@example.invalid",
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True,
                          capture_output=True, text=True).stdout.strip()


def _commit(repo: Path, name: str) -> str:
    (repo / name).write_text(name, "utf-8")
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", name)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    # The guard's own git calls read configuration too; keep them off the
    # developer's global configuration, as the fixture's calls are.
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    _git(tmp_path, "init", "-q", "--bare", str(remote))
    _git(tmp_path, "init", "-q", "-b", "dev", str(work))
    _commit(work, "base")
    _git(work, "remote", "add", "origin", str(remote))
    _git(work, "push", "-q", "-u", "origin", "dev")
    _git(work, "checkout", "-q", "-b", "feat/change")
    _commit(work, "slice")
    return work


def _remote_head(repo: Path, branch: str) -> str:
    return _git(repo, "ls-remote", "origin", f"refs/heads/{branch}").split("\t")[0]


def test_a_new_branch_is_pushed_to_its_own_name_and_tracks_it(repo: Path) -> None:
    head = _git(repo, "rev-parse", "HEAD")

    assert guard.main(["push"], root=repo) == 0

    assert _remote_head(repo, "feat/change") == head
    assert _git(repo, "rev-parse", "--abbrev-ref", "@{upstream}") == "origin/feat/change"


def test_a_tracked_branch_pushes_exactly_head(repo: Path) -> None:
    _git(repo, "push", "-q", "-u", "origin", "feat/change")
    head = _commit(repo, "fix")

    assert guard.main(["check"], root=repo) == 0
    assert guard.main(["push"], root=repo) == 0
    assert _remote_head(repo, "feat/change") == head


def test_a_remote_that_moved_on_rejects_the_push_rather_than_being_forced(
    repo: Path, tmp_path: Path
) -> None:
    _git(repo, "push", "-q", "-u", "origin", "feat/change")
    other = tmp_path / "other"
    _git(tmp_path, "clone", "-q", "-b", "feat/change", str(tmp_path / "remote.git"), str(other))
    moved = _commit(other, "someone-else")
    _git(other, "push", "-q", "origin", "feat/change")
    _commit(repo, "local")

    assert guard.main(["push"], root=repo) != 0
    assert _remote_head(repo, "feat/change") == moved


def test_a_detached_head_is_refused(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _git(repo, "checkout", "-q", "--detach")

    head = _git(repo, "rev-parse", "HEAD")

    assert guard.main(["push"], root=repo) == 1
    assert "detached" in capsys.readouterr().err
    assert _remote_head(repo, "feat/change") == ""
    assert _git(repo, "rev-parse", "HEAD") == head
    assert _git(repo, "branch", "--show-current") == ""


@pytest.mark.parametrize("branch", ["main", "dev"])
def test_a_protected_branch_is_refused(repo: Path, branch: str) -> None:
    _git(repo, "checkout", "-q", "-B", branch)
    before = _remote_head(repo, branch)

    target, problems = guard.check(repo)

    assert target is None
    assert any("protected" in problem for problem in problems)
    assert guard.main(["push"], root=repo) == 1
    assert _remote_head(repo, branch) == before


@pytest.mark.parametrize("dirt", ["tracked", "untracked"])
def test_a_dirty_worktree_is_refused_and_left_as_it_was(repo: Path, dirt: str) -> None:
    if dirt == "tracked":
        (repo / "slice").write_text("edited", "utf-8")
    else:
        (repo / "scratch.txt").write_text("scratch", "utf-8")
    before = _git(repo, "status", "--porcelain", "--untracked-files=all")

    assert guard.main(["push"], root=repo) == 1

    assert _git(repo, "status", "--porcelain", "--untracked-files=all") == before
    assert _remote_head(repo, "feat/change") == ""


def test_an_upstream_of_another_name_is_refused(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _git(repo, "branch", "--set-upstream-to=origin/dev")

    assert guard.main(["push"], root=repo) == 1
    assert "tracks origin/dev" in capsys.readouterr().err
    assert _git(repo, "rev-parse", "--abbrev-ref", "@{upstream}") == "origin/dev"
    assert _remote_head(repo, "feat/change") == ""
    assert _remote_head(repo, "dev") != _git(repo, "rev-parse", "HEAD")


def test_every_refusal_is_reported_at_once(repo: Path) -> None:
    _git(repo, "branch", "--set-upstream-to=origin/dev")
    (repo / "scratch.txt").write_text("scratch", "utf-8")

    _, problems = guard.check(repo)

    assert len(problems) == 2


def test_make_targets_delegate_to_the_script() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text("utf-8")

    assert "scripts/check_push_ready.py check" in makefile
    assert "scripts/check_push_ready.py push" in makefile
