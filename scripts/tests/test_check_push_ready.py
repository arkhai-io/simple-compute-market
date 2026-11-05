"""Tests for the guarded push of a change branch, against real Git repositories.

The guard's meaning is Git's own state — attachment, upstream configuration, what a
push sends — so a temporary repository with a bare remote is the lowest level that
proves it; a fake Git would only restate the guard's assumptions. The repository's
pre-push checks are absent unless a test provides one.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from change_workflow import push as guard

PUBLIC_CONTENT, SECRETS = (script for script, *_ in guard.PRE_PUSH_CHECKS)


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


def _provide_check(repo: Path, source: str, name: str = PUBLIC_CONTENT) -> None:
    """Give the repository a pre-push check, ignored so the worktree stays clean."""
    script = repo / name
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(source, "utf-8")
    with (repo / ".git/info/exclude").open("a", encoding="utf-8") as exclude:
        exclude.write(f"/{name}\n")


def test_the_pre_push_check_is_run_as_a_git_hook_and_its_refusal_stops_both_actions(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _provide_check(repo, "import sys\n"
                         "print('REFUSED: ' + ' '.join(sys.argv[1:]) + ' | '"
                         " + sys.stdin.read().strip(), file=sys.stderr)\n"
                         "sys.exit(1)\n")
    head = _git(repo, "rev-parse", "HEAD")
    ref = "refs/heads/feat/change"

    for action in ("check", "push"):
        assert guard.main([action], root=repo) == 1
        err = capsys.readouterr().err
        assert f"REFUSED: --pre-push origin | {ref} {head} {ref} {'0' * 40}" in err
    assert _remote_head(repo, "feat/change") == ""


def test_a_pre_push_check_failing_silently_is_named(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _provide_check(repo, "import sys\nsys.exit(3)\n")

    assert guard.main(["push"], root=repo) == 1
    assert "exited with status 3" in capsys.readouterr().err
    assert _remote_head(repo, "feat/change") == ""


def _provide_this_repositorys_check(repo: Path) -> None:
    """This repository's own pre-push check, the public-content scan, where the
    engine looks for it."""
    provided = Path(__file__).resolve().parents[2] / PUBLIC_CONTENT
    _provide_check(repo, provided.read_text("utf-8"))


def test_this_repositorys_check_passes_a_clean_push(repo: Path) -> None:
    _provide_this_repositorys_check(repo)

    assert guard.main(["push"], root=repo) == 0
    assert _remote_head(repo, "feat/change") == _git(repo, "rev-parse", "HEAD")


@pytest.mark.parametrize("removed_later", [False, True])
def test_private_content_refuses_publication(
    repo: Path, capsys: pytest.CaptureFixture[str], removed_later: bool
) -> None:
    _provide_this_repositorys_check(repo)
    # Synthetic prohibited account assembled so this test remains publishable.
    private = "/home/" + "fixture-person" + "/work"
    (repo / "notes.md").write_text(private, "utf-8")
    _git(repo, "add", "notes.md")
    _git(repo, "commit", "-qm", "notes")
    if removed_later:
        _git(repo, "rm", "-q", "notes.md")
        _git(repo, "commit", "-qm", "remove notes")

    assert guard.main(["push"], root=repo) == 1
    assert _remote_head(repo, "feat/change") == ""
    err = capsys.readouterr().err
    assert "personal home path" in err
    assert private not in err


def test_every_pre_push_check_runs_and_each_refusal_is_reported(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for name in (PUBLIC_CONTENT, SECRETS):
        _provide_check(repo, f"import sys\nprint('REFUSED: {name}', file=sys.stderr)\n"
                             "sys.exit(1)\n", name)

    assert guard.main(["push"], root=repo) == 1

    err = capsys.readouterr().err
    assert f"REFUSED: {PUBLIC_CONTENT}" in err
    assert f"REFUSED: {SECRETS}" in err
    assert _remote_head(repo, "feat/change") == ""
