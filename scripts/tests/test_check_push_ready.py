"""Tests for the guarded push of a change branch, against real Git repositories.

The guard's meaning is Git's own state — attachment, upstream configuration, what a
push sends — so a temporary repository with a bare remote is the lowest level that
proves it; a fake Git would only restate the guard's assumptions. Each repository's
workflow configuration protects `main` and `dev` and declares no `pre-push` unless a
test provides one.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from change_workflow import cli
from change_workflow import clone as clones
from change_workflow import push as guard
from change_workflow.common import SESSION_ID, UNATTENDED_RUN
from change_workflow.running import invocations_directory, kept_invocations
from change_workflow_fixtures import (CHANGE, SESSION, VALID, FakeClaude, configured, event_lines,
                                      make_wrapper)

# Two pre-push checks a test provides, each a script the configuration's `pre-push`
# runs.
PUBLIC_CONTENT, SECRETS = "checks/first_check.py", "checks/second_check.py"
PROTECTED = '[repository]\nprotected-branches = ["main", "dev"]\n'


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
    _configure(work)
    _track_own_name(work)
    return work


def _track_own_name(repo: Path, remote: str = "origin") -> None:
    """The change branch's upstream, a branch of its own name on `remote` that does
    not exist yet, as a change's clone configures it."""
    _git(repo, "config", "branch.feat/change.remote", remote)
    _git(repo, "config", "branch.feat/change.merge", "refs/heads/feat/change")


def _untrack(repo: Path) -> None:
    _git(repo, "config", "--unset", "branch.feat/change.remote")
    _git(repo, "config", "--unset", "branch.feat/change.merge")


def _configure(repo: Path, text: str = PROTECTED, checks: tuple[str, ...] = ()) -> None:
    """The repository's workflow configuration, ignored so the worktree stays clean:
    `text`, and a `pre-push` running each of `checks` as Git runs a pre-push hook."""
    pre_push = ("[hooks]\npre-push = [" + ", ".join(
        f'"{shlex.quote(sys.executable)} {name} --pre-push {{remote}}"' for name in checks)
        + "]\n") if checks else ""
    configured(repo, text + pre_push)
    exclude = repo / ".git/info/exclude"
    if "/.agents/" not in exclude.read_text("utf-8"):
        with exclude.open("a", encoding="utf-8") as stream:
            stream.write("/.agents/\n")


def _remote_head(repo: Path, branch: str) -> str:
    return _git(repo, "ls-remote", "origin", f"refs/heads/{branch}").split("\t")[0]


def test_a_branch_tracking_its_own_name_not_yet_pushed_is_pushed_there(repo: Path) -> None:
    head = _git(repo, "rev-parse", "HEAD")

    assert guard.main(["push"], root=repo) == 0

    assert _remote_head(repo, "feat/change") == head
    assert _git(repo, "rev-parse", "--abbrev-ref", "@{upstream}") == "origin/feat/change"


def test_a_branch_with_no_upstream(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """CW-59c7: with no upstream and no remote given, the push refuses, naming the
    argument that gives the remote, and pushes nothing."""
    _untrack(repo)

    assert guard.main(["push"], root=repo) == 1

    assert "give it with --remote <remote>" in capsys.readouterr().err
    assert _remote_head(repo, "feat/change") == ""


def test_a_branch_with_no_upstream_is_pushed_to_the_remote_given_and_tracks_it(
        repo: Path) -> None:
    _untrack(repo)
    head = _git(repo, "rev-parse", "HEAD")

    assert cli.main(["push", "--remote", "origin"], root=repo, environ={}) == 0

    assert _remote_head(repo, "feat/change") == head
    assert _git(repo, "rev-parse", "--abbrev-ref", "@{upstream}") == "origin/feat/change"


def test_a_remote_given_overrides_the_upstreams_for_one_push(repo: Path,
                                                            tmp_path: Path) -> None:
    other = tmp_path / "other.git"
    _git(tmp_path, "init", "-q", "--bare", str(other))
    _git(repo, "remote", "add", "mirror", str(other))
    head = _git(repo, "rev-parse", "HEAD")

    assert guard.main(["push", "--remote", "mirror"], root=repo) == 0

    assert _git(repo, "ls-remote", "mirror", "refs/heads/feat/change").split("\t")[0] == head
    assert _remote_head(repo, "feat/change") == ""
    assert _git(repo, "config", "branch.feat/change.remote") == "origin"


@pytest.mark.parametrize("remote", ["workspace", "."])
def test_no_push_goes_to_the_workspace_whatever_remote_is_given(
        repo: Path, capsys: pytest.CaptureFixture[str], remote: str) -> None:
    assert guard.main(["push", "--remote", remote], root=repo) == 1

    assert "is no remote a change's branch is pushed to" in capsys.readouterr().err
    assert _remote_head(repo, "feat/change") == ""


def test_a_new_change_branch_is_pushed_first(repo: Path) -> None:
    """CW-59c7: a change's clone made for a new branch from a landing branch
    tracking `origin` gave the branch an upstream of its own name on `origin`, so
    its first push goes there with no remote given. Library integration: a real
    clone of a real workspace."""
    _git(repo, "checkout", "-q", "dev")
    clone = clones.create(repo, CHANGE, bootstrap=lambda _: None).clone
    _configure(clone)
    # The settings link the clone makes, which this repository's .gitignore holds.
    with (clone / ".git/info/exclude").open("a", encoding="utf-8") as exclude:
        exclude.write("/.claude/\n")
    (clone / "slice.txt").write_text("slice", "utf-8")
    _git(clone, "add", "slice.txt")
    _git(clone, "commit", "-qm", "slice")

    assert _git(clone, "config", f"branch.feat/{CHANGE}.remote") == "origin"
    assert guard.main(["push"], root=clone) == 0
    assert _remote_head(repo, f"feat/{CHANGE}") == _git(clone, "rev-parse", "HEAD")


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

    target, problems = guard.check(repo, ("main", "dev"))

    assert target is None
    assert any("protected" in problem for problem in problems)
    assert guard.main(["push"], root=repo) == 1
    assert _remote_head(repo, branch) == before


def test_a_configured_protected_branch_is_refused_and_no_other(
        repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """CW-f3qk: the engine holds no branch name of its own."""
    _configure(repo, '[repository]\nprotected-branches = ["trunk"]\n')
    _git(repo, "checkout", "-q", "-B", "trunk")

    assert guard.main(["push"], root=repo) == 1
    assert "trunk is a protected branch" in capsys.readouterr().err
    assert _remote_head(repo, "trunk") == ""

    _git(repo, "checkout", "-q", "-B", "dev")
    assert guard.main(["push"], root=repo) == 0


def test_a_push_with_no_protected_branches_declared_is_refused_naming_the_field(
        repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _configure(repo, "")

    assert guard.main(["push"], root=repo) == 1
    assert "repository.protected-branches" in capsys.readouterr().err
    assert _remote_head(repo, "feat/change") == ""


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

    _, problems = guard.check(repo, ("main", "dev"))

    assert len(problems) == 2


def _provide_check(repo: Path, source: str, *names: str) -> None:
    """Give the repository pre-push checks running `source`, each ignored so the
    worktree stays clean, and declare them its `pre-push`."""
    for name in names or (PUBLIC_CONTENT,):
        script = repo / name
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(source, "utf-8")
        with (repo / ".git/info/exclude").open("a", encoding="utf-8") as exclude:
            exclude.write(f"/{name}\n")
    _configure(repo, checks=names or (PUBLIC_CONTENT,))


def test_the_repository_provides_no_pre_push_check(repo: Path) -> None:
    """CW-p7kq: with no `pre-push` declared, the push goes once its own check passes."""
    head = _git(repo, "rev-parse", "HEAD")

    assert guard.main(["push"], root=repo) == 0
    assert _remote_head(repo, "feat/change") == head


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
        captured = capsys.readouterr()
        # The hook's reasons are on standard error, and nothing of it on standard
        # output.
        assert f"REFUSED: --pre-push origin | {ref} {head} {ref} {'0' * 40}" in captured.err
        assert captured.out == ""
    assert _remote_head(repo, "feat/change") == ""


def test_a_pre_push_check_failing_silently_is_named(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _provide_check(repo, "import sys\nsys.exit(3)\n")

    assert guard.main(["push"], root=repo) == 1
    err = capsys.readouterr().err
    assert f"{PUBLIC_CONTENT} --pre-push origin (exit 3)" in err
    assert "pre-push hook refused the push" in err
    assert _remote_head(repo, "feat/change") == ""


def test_a_steps_push_refused_by_the_pre_push_hook_is_on_the_runs_line(repo: Path) -> None:
    """CW-q5fy: the run's log line lists `pre-push` with the command it ran and its
    exit status, and nothing is left kept once the line holds it."""
    _provide_check(repo, "import sys\nprint('REFUSED: a private path')\nsys.exit(1)\n")
    with (repo / ".git/info/exclude").open("a", encoding="utf-8") as exclude:
        exclude.write("/openspec/changes/*/reviews/\n")
    # The validation run's own model, beside the guarded push's configuration.
    configured(repo, (repo / ".agents/workflow.toml").read_text("utf-8")
               + '\n[models]\nvalidate = [{ harness = "claude", model = "claude-sonnet-5-5" }]\n')
    pushed: list[int] = []

    class Pushing(FakeClaude):
        """A validation run whose step makes the guarded push."""

        def __call__(self, command, cwd, feed, step) -> int:
            pushed.append(cli.main(["push"], root=repo,
                                   environ={SESSION_ID: SESSION, UNATTENDED_RUN: step}))
            return super().__call__(command, cwd, feed, step)

    line = make_wrapper(repo, Pushing((event_lines(VALID["finished"]), 0))).run("validate",
                                                                               CHANGE)

    assert pushed == [1]
    (invoked,) = line["invoked"]
    assert (invoked["hook"], invoked["exit_status"]) == ("pre-push", 1)
    assert invoked["command"].endswith(f"{PUBLIC_CONTENT} --pre-push origin")
    assert {"started", "seconds"} <= invoked.keys()
    assert kept_invocations(invocations_directory(repo), SESSION) == []


def test_a_push_outside_any_session_keeps_nothing(repo: Path) -> None:
    _provide_check(repo, "import sys\nsys.exit(0)\n")

    assert guard.main(["push"], root=repo, environ={}) == 0

    kept = invocations_directory(repo)
    assert kept is not None and not kept.exists()


def test_every_pre_push_check_runs_and_each_refusal_is_reported(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _provide_check(repo, "import sys\nprint('REFUSED: ' + sys.argv[0], file=sys.stderr)\n"
                         "sys.exit(1)\n", PUBLIC_CONTENT, SECRETS)

    assert guard.main(["push"], root=repo) == 1

    err = capsys.readouterr().err
    assert f"REFUSED: {PUBLIC_CONTENT}" in err
    assert f"REFUSED: {SECRETS}" in err
    assert _remote_head(repo, "feat/change") == ""
