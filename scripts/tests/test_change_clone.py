"""Tests for a change's clone, against real Git repositories.

What a clone must get right is Git's own state — its remotes, the branch it has
checked out and where that branch tracks, what a rerun leaves alone — so a
temporary workspace with a bare `origin` is the lowest level that proves it. The
bootstrap is started through an injected spawn, since `make init` builds every
environment; the real spawn is exercised with a command that ends at once, and with
one that runs on while nothing but the spawn itself records it.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Sequence

import pytest

import change_clone as clones

CHANGE = "seed-pool"
BRANCH = f"feat/{CHANGE}"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True).stdout.strip()


@pytest.fixture(autouse=True)
def _git_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "test")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "test@example.invalid")


def _commit(repo: Path, name: str, text: str) -> str:
    (repo / name).parent.mkdir(parents=True, exist_ok=True)
    (repo / name).write_text(text, "utf-8")
    _git(repo, "add", "--all")
    _git(repo, "commit", "-q", "-m", f"write {name}")
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "dev", str(origin))
    work = tmp_path / "work"
    _git(tmp_path, "init", "-q", "-b", "dev", str(work))
    # The settings link is ignored, as the repository ignores .claude/'s local files.
    (work / ".gitignore").write_text(".claude/settings.local.json\n", "utf-8")
    _commit(work, "README.md", "1\n")
    _git(work, "remote", "add", "origin", str(origin))
    _git(work, "push", "-q", "origin", "dev")
    return work


class Spawned:
    """The bootstrap's spawn, recorded; each call ends at once with `status`."""

    def __init__(self, status: int | None = 0) -> None:
        self.calls: list[tuple[list[str], Path]] = []
        self.status = status

    def __call__(self, command: Sequence[str], cwd: Path, log: Path, status: Path) -> int:
        self.calls.append((list(command), cwd))
        log.write_text("bootstrap output\n", "utf-8")
        if self.status is not None:
            status.write_text(f"{self.status}\n", "utf-8")
        # This process: alive for as long as the test runs.
        return os.getpid()


def _create(workspace: Path, spawn: Spawned | None = None, **options) -> clones.Created:
    return clones.create(workspace, CHANGE, bootstrap=("make", "init"),
                         spawn=spawn or Spawned(), **options)


def _git_file(clone: Path, name: str) -> Path:
    path = Path(_git(clone, "rev-parse", "--git-path", name))
    return path if path.is_absolute() else clone / path


# A fresh clone.

def test_a_fresh_clone_has_both_remotes_the_branch_the_link_and_a_bootstrap(
        workspace: Path) -> None:
    spawn = Spawned()

    created = _create(workspace, spawn)

    clone = created.clone
    assert clone == workspace.parent / "work.changes" / CHANGE
    assert created.done == ("cloned", "remotes", "branch", "settings", "bootstrap")
    assert _git(clone, "remote", "get-url", "origin") == _git(workspace, "remote", "get-url",
                                                               "origin")
    assert Path(_git(clone, "remote", "get-url", "workspace")).resolve() == workspace.resolve()
    assert _git(clone, "branch", "--show-current") == BRANCH
    assert _git(clone, "rev-parse", "HEAD") == _git(workspace, "rev-parse", "dev")
    assert os.readlink(clone / ".claude/settings.local.json") == str(
        workspace.resolve() / ".claude/settings.local.json")
    assert spawn.calls == [(["make", "init"], clone)]
    assert created.bootstrap == clones.Bootstrap("succeeded",
                                                 _git_file(clone, clones.BOOTSTRAP_LOG))
    assert json.loads(_git_file(clone, clones.BOOTSTRAP).read_text("utf-8"))["pid"] == os.getpid()
    assert _git(clone, "status", "--porcelain") == ""


def test_the_clone_tracks_nothing_in_the_workspace(workspace: Path) -> None:
    clone = _create(workspace).clone

    # No push from the clone goes to the workspace: the branch it was made on is
    # gone, and the change's branch has no upstream until it is pushed.
    assert _git(clone, "branch", "--format=%(refname:short)") == BRANCH
    assert subprocess.run(["git", "config", f"branch.{BRANCH}.remote"], cwd=clone,
                          capture_output=True).returncode == 1


def test_an_existing_branch_is_checked_out_at_its_furthest_point(workspace: Path) -> None:
    _git(workspace, "switch", "-q", "-c", BRANCH)
    pushed = _commit(workspace, "a.txt", "pushed\n")
    _git(workspace, "push", "-q", "origin", BRANCH)
    unpushed = _commit(workspace, "a.txt", "unpushed\n")
    _git(workspace, "switch", "-q", "dev")

    clone = _create(workspace).clone

    assert _git(clone, "rev-parse", "HEAD") == unpushed != pushed
    assert _git(clone, "rev-parse", "--abbrev-ref", f"{BRANCH}@{{upstream}}") == (
        f"origin/{BRANCH}")


def test_a_branch_diverged_between_the_workspace_and_origin_is_refused(
        workspace: Path, tmp_path: Path) -> None:
    _git(workspace, "switch", "-q", "-c", BRANCH)
    _commit(workspace, "a.txt", "mine\n")
    _git(workspace, "switch", "-q", "dev")
    other = tmp_path / "other"
    _git(tmp_path, "clone", "-q", str(tmp_path / "origin.git"), str(other))
    _git(other, "switch", "-q", "-c", BRANCH)
    _commit(other, "a.txt", "theirs\n")
    _git(other, "push", "-q", "origin", BRANCH)

    with pytest.raises(clones.CloneError, match="diverged"):
        _create(workspace)

    # Reconciled in the workspace, unpushed: the rerun reads the workspace as it is now.
    _git(workspace, "fetch", "-q", "origin")
    _git(workspace, "switch", "-q", BRANCH)
    _git(workspace, "merge", "-q", "--no-edit", "-X", "ours", f"origin/{BRANCH}")
    merged = _git(workspace, "rev-parse", "HEAD")
    _git(workspace, "switch", "-q", "dev")

    assert _git(_create(workspace).clone, "rev-parse", "HEAD") == merged


def test_a_clone_made_while_the_workspace_has_the_branch_checked_out_tracks_nothing_there(
        workspace: Path) -> None:
    _git(workspace, "switch", "-q", "-c", BRANCH)
    _commit(workspace, "a.txt", "reading\n")

    clone = _create(workspace).clone

    assert _git(clone, "branch", "--format=%(refname:short)") == BRANCH
    assert subprocess.run(["git", "config", f"branch.{BRANCH}.remote"], cwd=clone,
                          capture_output=True).returncode == 1


def test_a_checkout_interrupted_before_its_upstream_was_settled_is_settled(
        workspace: Path) -> None:
    clone = clones.clone_directory(workspace, CHANGE)
    clone.parent.mkdir(parents=True)
    _git(workspace, "clone", "-q", "--no-checkout", "--origin", "workspace", str(workspace),
         str(clone))
    _git(clone, "remote", "add", "origin", _git(workspace, "remote", "get-url", "origin"))
    # The checkout done, tracking the workspace, and the branch `git clone` made kept.
    _git(clone, "checkout", "-q", "-b", BRANCH, "--track", "workspace/dev")
    sentinel = _sentinel(clone)

    created = _create(workspace)

    assert created.done == ("settings", "bootstrap")
    assert sentinel.read_text("utf-8") == "kept\n"
    assert _git(clone, "branch", "--format=%(refname:short)") == BRANCH
    assert subprocess.run(["git", "config", f"branch.{BRANCH}.remote"], cwd=clone,
                          capture_output=True).returncode == 1


def test_a_new_branch_starts_from_the_given_branch(workspace: Path) -> None:
    _git(workspace, "switch", "-q", "-c", "feat/tooling")
    tooling = _commit(workspace, "tools.txt", "tooling\n")
    _git(workspace, "switch", "-q", "dev")

    clone = _create(workspace, from_ref="feat/tooling").clone

    assert (_git(clone, "branch", "--show-current"), _git(clone, "rev-parse", "HEAD")) == (
        BRANCH, tooling)


def test_a_new_branch_from_dev_starts_from_origins_when_the_workspaces_is_behind(
        workspace: Path, tmp_path: Path) -> None:
    other = tmp_path / "other"
    _git(tmp_path, "clone", "-q", "-b", "dev", str(tmp_path / "origin.git"), str(other))
    ahead = _commit(other, "landed.txt", "landed\n")
    _git(other, "push", "-q", "origin", "dev")

    clone = _create(workspace).clone

    assert _git(clone, "rev-parse", "HEAD") == ahead


def test_a_named_branch_is_recorded_and_found(workspace: Path) -> None:
    clone = _create(workspace, branch="feat/other-name").clone

    assert _git(clone, "branch", "--show-current") == "feat/other-name"
    assert clones.clone_of(workspace, CHANGE) == clone


# An interrupted creation is finished, never recloned.

def _sentinel(clone: Path) -> Path:
    sentinel = _git_file(clone, "sentinel")
    sentinel.write_text("kept\n", "utf-8")
    return sentinel


def test_a_clone_made_but_not_finished_resumes_after_its_clone(workspace: Path) -> None:
    clone = clones.clone_directory(workspace, CHANGE)
    clone.parent.mkdir(parents=True)
    _git(workspace, "clone", "-q", "--no-checkout", "--origin", "workspace", str(workspace),
         str(clone))
    sentinel = _sentinel(clone)

    created = _create(workspace)

    assert created.done == ("remotes", "branch", "settings", "bootstrap")
    assert sentinel.read_text("utf-8") == "kept\n"
    assert _git(clone, "branch", "--show-current") == BRANCH


def test_a_clone_with_its_remotes_resumes_at_its_branch(workspace: Path) -> None:
    clone = clones.clone_directory(workspace, CHANGE)
    clone.parent.mkdir(parents=True)
    _git(workspace, "clone", "-q", "--no-checkout", "--origin", "workspace", str(workspace),
         str(clone))
    _git(clone, "remote", "add", "origin", _git(workspace, "remote", "get-url", "origin"))
    sentinel = _sentinel(clone)

    assert _create(workspace).done == ("branch", "settings", "bootstrap")
    assert sentinel.read_text("utf-8") == "kept\n"


def test_a_clone_without_its_link_or_bootstrap_resumes_at_the_link(workspace: Path) -> None:
    clone = _create(workspace).clone
    (clone / ".claude/settings.local.json").unlink()
    for name in (clones.BOOTSTRAP, clones.BOOTSTRAP_STATUS, clones.BOOTSTRAP_LOG):
        _git_file(clone, name).unlink()
    sentinel = _sentinel(clone)

    assert _create(workspace).done == ("settings", "bootstrap")
    assert sentinel.read_text("utf-8") == "kept\n"


def test_a_clone_without_its_bootstrap_resumes_at_the_bootstrap(workspace: Path) -> None:
    clone = _create(workspace).clone
    for name in (clones.BOOTSTRAP, clones.BOOTSTRAP_STATUS, clones.BOOTSTRAP_LOG):
        _git_file(clone, name).unlink()
    sentinel = _sentinel(clone)
    spawn = Spawned()

    assert _create(workspace, spawn).done == ("bootstrap",)
    assert len(spawn.calls) == 1
    assert sentinel.read_text("utf-8") == "kept\n"


def test_a_complete_clone_is_left_as_it_is(workspace: Path) -> None:
    _create(workspace)
    spawn = Spawned()

    created = _create(workspace, spawn)

    assert (created.done, spawn.calls) == ((), [])
    assert created.bootstrap.state == "succeeded"


# The bootstrap: restarted when it failed, otherwise left alone.

def test_rerunning_restarts_a_failed_bootstrap(workspace: Path) -> None:
    clone = _create(workspace, Spawned(status=2)).clone
    assert clones.bootstrap_state(clone).state == "failed"
    spawn = Spawned(status=None)

    created = _create(workspace, spawn)

    assert created.done == ("bootstrap",)
    assert len(spawn.calls) == 1
    assert not _git_file(clone, clones.BOOTSTRAP_STATUS).exists()
    assert created.bootstrap.state == "running"


def test_rerunning_leaves_a_running_bootstrap_alone(workspace: Path) -> None:
    _create(workspace, Spawned(status=None))
    spawn = Spawned()

    created = _create(workspace, spawn)

    assert (created.done, spawn.calls, created.bootstrap.state) == ((), [], "running")


@pytest.mark.parametrize("status,record,alive,expected", [
    ("0\n", True, False, "succeeded"),
    ("1\n", True, True, "failed"),
    (None, True, True, "running"),
    # A process that died without recording a status failed.
    (None, True, False, "failed"),
    (None, False, False, "absent"),
])
def test_the_bootstraps_states(workspace: Path, status: str | None, record: bool,
                               alive: bool, expected: str) -> None:
    clone = _create(workspace).clone
    for name in (clones.BOOTSTRAP, clones.BOOTSTRAP_STATUS):
        _git_file(clone, name).unlink(missing_ok=True)
    if record:
        _git_file(clone, clones.BOOTSTRAP).write_text(json.dumps({"pid": 12345}), "utf-8")
    if status is not None:
        _git_file(clone, clones.BOOTSTRAP_STATUS).write_text(status, "utf-8")

    state = clones.bootstrap_state(clone, alive=lambda pid: alive and pid == 12345)

    assert state.state == expected
    assert (state.log is None) == (expected == "absent")


def test_the_real_spawn_records_the_commands_output_and_exit_status(workspace: Path) -> None:
    clone = _create(workspace).clone
    log = _git_file(clone, clones.BOOTSTRAP_LOG)
    status = _git_file(clone, clones.BOOTSTRAP_STATUS)
    status.unlink()

    pid = clones._spawn(["sh", "-c", "echo building; exit 3"], clone, log, status)
    os.waitpid(pid, 0)

    assert log.read_text("utf-8") == "building\n"
    assert status.read_text("utf-8") == "3\n"
    assert clones.bootstrap_state(clone).state == "failed"


def test_the_real_spawn_records_itself_before_its_command_runs(workspace: Path) -> None:
    clone = _create(workspace).clone
    log = _git_file(clone, clones.BOOTSTRAP_LOG)
    status = _git_file(clone, clones.BOOTSTRAP_STATUS)
    record = _git_file(clone, clones.BOOTSTRAP)
    for path in (status, record):
        path.unlink()
    # Outside the worktree, which a rerun requires clean.
    ready = _git_file(clone, "bootstrap-ready")

    # The process that spawned it records nothing, as when it is killed at once.
    pid = clones._spawn(["sh", "-c", f"touch {ready}; sleep 30"], clone, log, status)
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        recorded = json.loads(record.read_text("utf-8"))

        assert recorded["pid"] == pid and recorded["log"] == str(log)
        assert clones.bootstrap_state(clone).state == "running"
        # A rerun leaves it alone rather than starting a second bootstrap.
        rerun = Spawned()
        _create(workspace, spawn=rerun)
        assert rerun.calls == []
        assert json.loads(record.read_text("utf-8"))["pid"] == pid
    finally:
        os.killpg(pid, 15)
        os.waitpid(pid, 0)


# Refusals delete nothing.

def test_a_directory_that_is_not_a_clone_is_refused(workspace: Path) -> None:
    target = clones.clone_directory(workspace, CHANGE)
    target.mkdir(parents=True)
    (target / "notes.txt").write_text("mine\n", "utf-8")

    with pytest.raises(clones.CloneError, match="not a clone of"):
        _create(workspace)
    assert (target / "notes.txt").read_text("utf-8") == "mine\n"


def test_a_file_where_the_clone_goes_is_refused(workspace: Path) -> None:
    target = clones.clone_directory(workspace, CHANGE)
    target.parent.mkdir(parents=True)
    target.write_text("mine\n", "utf-8")

    with pytest.raises(clones.CloneError, match="not a clone of"):
        _create(workspace)
    assert target.read_text("utf-8") == "mine\n"


def test_the_clone_of_another_change_is_refused(workspace: Path) -> None:
    clone = _create(workspace).clone
    _git_file(clone, clones.MARKER).write_text(
        json.dumps({"change": "another", "branch": "feat/another"}), "utf-8")

    with pytest.raises(clones.CloneError, match="the clone of another"):
        _create(workspace)
    assert _git(clone, "branch", "--show-current") == BRANCH


def test_a_from_naming_nothing_is_refused_and_records_no_branch(workspace: Path) -> None:
    with pytest.raises(clones.CloneError, match="--from nowhere names no branch"):
        _create(workspace, from_ref="nowhere")
    clone = clones.clone_directory(workspace, CHANGE)
    assert not _git_file(clone, clones.MARKER).exists()

    assert _git(_create(workspace, branch="feat/else").clone, "branch",
                "--show-current") == "feat/else"


def test_a_clone_of_another_repository_is_refused(workspace: Path, tmp_path: Path) -> None:
    target = clones.clone_directory(workspace, CHANGE)
    target.parent.mkdir(parents=True)
    _git(tmp_path, "clone", "-q", str(tmp_path / "origin.git"), str(target))

    with pytest.raises(clones.CloneError, match="not a clone of"):
        _create(workspace)
    assert (target / "README.md").is_file()


def test_a_clone_with_another_branch_checked_out_is_refused(workspace: Path) -> None:
    clone = _create(workspace).clone
    _git(clone, "switch", "-q", "-c", "elsewhere")

    with pytest.raises(clones.CloneError, match="elsewhere checked out"):
        _create(workspace)
    assert _git(clone, "branch", "--show-current") == "elsewhere"
    assert clones.clone_of(workspace, CHANGE) is None


def test_a_clone_with_uncommitted_changes_is_refused(workspace: Path) -> None:
    clone = _create(workspace, Spawned(status=1)).clone
    (clone / "README.md").write_text("in progress\n", "utf-8")
    spawn = Spawned()

    with pytest.raises(clones.CloneError, match="uncommitted changes"):
        _create(workspace, spawn)
    assert (clone / "README.md").read_text("utf-8") == "in progress\n"
    assert spawn.calls == []


def test_a_clone_asked_for_another_branch_is_refused(workspace: Path) -> None:
    clone = _create(workspace).clone

    with pytest.raises(clones.CloneError, match=f"holds {BRANCH}"):
        _create(workspace, branch="feat/else")
    assert _git(clone, "branch", "--format=%(refname:short)") == BRANCH


def test_a_clone_whose_origin_is_not_the_workspaces_is_refused(workspace: Path,
                                                                tmp_path: Path) -> None:
    clone = clones.clone_directory(workspace, CHANGE)
    clone.parent.mkdir(parents=True)
    _git(workspace, "clone", "-q", "--no-checkout", "--origin", "workspace", str(workspace),
         str(clone))
    _git(clone, "remote", "add", "origin", str(tmp_path / "elsewhere.git"))

    with pytest.raises(clones.CloneError, match="nothing was changed"):
        _create(workspace)
    assert _git(clone, "remote", "get-url", "origin") == str(tmp_path / "elsewhere.git")
    assert not _git_file(clone, clones.MARKER).exists()
    assert not _git_file(clone, "index").exists()


def test_a_settings_file_that_is_not_the_link_is_refused(workspace: Path) -> None:
    clone = _create(workspace).clone
    settings = clone / ".claude/settings.local.json"
    settings.unlink()
    settings.write_text("{}\n", "utf-8")

    with pytest.raises(clones.CloneError, match="is not the link"):
        _create(workspace)
    assert settings.read_text("utf-8") == "{}\n"


def test_a_workspace_without_an_origin_is_refused(workspace: Path) -> None:
    _git(workspace, "remote", "remove", "origin")

    with pytest.raises(clones.CloneError, match="no origin remote"):
        _create(workspace)
    assert not clones.clone_directory(workspace, CHANGE).exists()


def test_creating_a_clone_from_a_clone_is_refused(workspace: Path) -> None:
    clone = _create(workspace).clone

    with pytest.raises(clones.CloneError, match="itself a change's clone"):
        clones.create(clone, "another", spawn=Spawned())
    assert not clones.clone_directory(clone, "another").exists()


# What the computation reads.

def test_clone_of_finds_only_a_clone_holding_the_changes_branch(workspace: Path) -> None:
    assert clones.clone_of(workspace, CHANGE) is None
    clone = _create(workspace).clone

    assert clones.clone_of(workspace, CHANGE) == clone
    assert clones.workspace_of(clone) == workspace.resolve()
    assert clones.workspace_of(workspace) is None


def test_the_command_line_reports_the_clone_and_its_bootstrap(
        workspace: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert clones.main(["create", "bad/name"], root=workspace) == 1
    assert "not a change name" in capsys.readouterr().err
