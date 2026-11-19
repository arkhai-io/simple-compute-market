"""The engine's `git`, `change_workflow.sandbox_git`, which the sandbox mounts over the
system's Git executables to refuse every push of an unattended run but the guarded
push's (CW-j4cs).

Its decision — where the subcommand stands among Git's options, and when a push is
refused — is unit tested on command lines. Its refusal kept for the session's line is
tested on a real Git checkout, whose Git directory holds the invocations. The tests
that launch real bubblewrap are external-process integration, on a real repository
with a bare remote: a shell program stands in for the harness and runs Git as a step
would, and the guarded push runs as the engine's command. Each is skipped, saying
why, where the engine's own probe finds the sandbox cannot run."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from change_workflow import sandbox, sandbox_git, scope
from change_workflow.common import GUARDED_PUSH, SESSION_ID, UNATTENDED_RUN
from change_workflow.running import (ATTEMPTED_PUSH, REFUSED_PUSH, invocations_directory,
                                     kept_invocations)
from change_workflow_fixtures import SESSION, clock, configured

UNATTENDED = {UNATTENDED_RUN: "implement"}
ENGINE = Path(__file__).resolve().parents[1] / "change-workflow"


# Where the subcommand stands.

@pytest.mark.parametrize("arguments", [
    ["push"],
    ["push", "origin", "HEAD:dev"],
    ["push", "--no-verify", "origin", "HEAD:dev"],
    ["-c", "core.hooksPath=/dev/null", "push", "origin", "HEAD:dev"],
    ["-C", "/elsewhere", "push"],
    ["--git-dir", "/elsewhere/.git", "--work-tree", "/elsewhere", "push"],
    ["--git-dir=/elsewhere/.git", "--no-pager", "push", "-f"],
    ["--config-env", "core.hooksPath=HOOKS", "push"],
    ["-c", "a.b=c", "-C", "dir", "--namespace", "n", "--no-replace-objects", "push"],
], ids=["bare", "refspec", "no-verify", "hooks path", "-C", "git-dir", "git-dir=",
        "config-env", "several"])
def test_a_push_is_found_wherever_it_stands_among_gits_options(arguments: list[str]) -> None:
    assert sandbox_git.subcommand(arguments) == "push"
    assert sandbox_git.refusal(arguments, UNATTENDED) is not None


@pytest.mark.parametrize("arguments,found", [
    (["status"], "status"),
    (["commit", "-m", "push"], "commit"),
    (["-C", "push", "status"], "status"),
    (["-c", "alias.x=push", "log", "--grep", "push"], "log"),
    (["--version"], None),
], ids=["status", "push in a message", "a directory named push", "push in a value",
        "no subcommand"])
def test_any_other_command_runs(arguments: list[str], found: str | None) -> None:
    assert sandbox_git.subcommand(arguments) == found
    assert sandbox_git.refusal(arguments, UNATTENDED) is None


@pytest.mark.parametrize("name,found", [
    ("/usr/bin/git-receive-pack", "receive-pack"), ("git-upload-pack", "upload-pack"),
    ("git-push", "push"), ("/usr/lib/git-core/git", "/elsewhere/remote.git")])
def test_git_run_by_a_dashed_name_runs_the_subcommand_it_names(name: str,
                                                              found: str | None) -> None:
    """Git's transport runs `git-receive-pack <path>` to serve a push to a local path:
    the path is no subcommand. Run as `git`, the first argument is."""
    assert sandbox_git.subcommand(["/elsewhere/remote.git"], name) == found


def test_a_push_outside_an_unattended_run_runs() -> None:
    assert sandbox_git.refusal(["push", "--no-verify"], {}) is None


def test_the_guarded_push_runs() -> None:
    assert sandbox_git.refusal(["push", "origin", "HEAD:refs/heads/feat/x"],
                               {**UNATTENDED, GUARDED_PUSH: "1"}) is None


def test_a_refusal_is_said_and_kept_for_the_sessions_line(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)

    status = sandbox_git.main(["--no-pager", "push", "--no-verify", "origin", "HEAD:dev"],
                              "/usr/bin/git", environ={**UNATTENDED, SESSION_ID: SESSION},
                              root=tmp_path, clock=clock)

    assert status == 1
    command = "git --no-pager push --no-verify origin HEAD:dev"
    assert f"REFUSED: {command}: git push is refused" in capsys.readouterr().err
    (kept,) = kept_invocations(invocations_directory(tmp_path), SESSION, "any-change")
    assert kept == {"hook": REFUSED_PUSH, "command": command,
                    "error": sandbox_git.refusal(["push"], UNATTENDED),
                    "started": "2026-10-21T09:15:40Z"}


# Through real bubblewrap.

PROBED = sandbox.probe()
needs_bwrap = pytest.mark.skipif(PROBED is not None, reason=f"the sandbox cannot run: {PROBED}")
IDENTITY = {"GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@example.invalid",
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, env={**os.environ, **IDENTITY}, check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A change's checkout on `feat/change`, tracking a branch of its own name on a bare
    `origin` that holds `dev`, its workflow configuration protecting `dev` and ignored
    so the worktree stays clean."""
    remote, work = tmp_path / "remote.git", tmp_path / "work"
    _git(tmp_path, "init", "-q", "--bare", str(remote))
    _git(tmp_path, "init", "-q", "-b", "dev", str(work))
    (work / "base").write_text("base\n", "utf-8")
    _git(work, "add", "base")
    _git(work, "commit", "-qm", "base")
    _git(work, "remote", "add", "origin", str(remote))
    _git(work, "push", "-q", "origin", "dev")
    _git(work, "checkout", "-q", "-b", "feat/change")
    _git(work, "config", "branch.feat/change.remote", "origin")
    _git(work, "config", "branch.feat/change.merge", "refs/heads/feat/change")
    configured(work, '[repository]\nprotected-branches = ["main", "dev"]\n')
    with (work / ".git/info/exclude").open("a", encoding="utf-8") as exclude:
        exclude.write("/.agents/\n")
    return work


def _in_sandbox(repo: Path, script: str, **environ: str) -> subprocess.CompletedProcess:
    """`script` run by a shell in an unattended implementation run's sandbox. The bare
    remote stands in for a remote across the network, so the sandbox lets it be written:
    a push that does not reach it was refused, not stopped by a read-only file system."""
    found = scope.resolve("implement", repo, inert_paths=(), home=repo.parent / "home",
                          temporary=repo.parent / "tmp",
                          writable=(str(repo.parent / "remote.git"),))
    with sandbox.launch(found, ["sh", "-c", script]) as launched:
        assert launched.unconfined is None
        return subprocess.run(launched.command, cwd=repo, capture_output=True, text=True,
                              pass_fds=launched.fds,
                              env={**os.environ, **IDENTITY, **UNATTENDED,
                                   SESSION_ID: SESSION, **environ})


def _remote_head(repo: Path, branch: str) -> str:
    return _git(repo, "ls-remote", "origin", f"refs/heads/{branch}").partition("\t")[0]


@needs_bwrap
@pytest.mark.parametrize("push", [
    "git push origin HEAD:dev",
    "git push --no-verify origin HEAD:dev",
    "git -c core.hooksPath=/dev/null push origin HEAD:dev",
    "/usr/lib/git-core/git push origin HEAD:dev",
], ids=["directly", "no-verify", "hooks path", "exec path"])
def test_a_steps_own_push_is_refused_and_nothing_reaches_the_remote(repo: Path,
                                                                   push: str) -> None:
    """CW-j4cs's "A step pushes directly", "A step skips the hooks", and "A step calls
    Git's exec path"."""
    before = _remote_head(repo, "dev")

    pushed = _in_sandbox(repo, f"echo next > base && git commit -qam next && {push}")

    assert pushed.returncode == 1, pushed.stderr
    assert "git push is refused during an unattended implement run" in pushed.stderr
    assert _remote_head(repo, "dev") == before
    (kept,) = kept_invocations(invocations_directory(repo), SESSION)
    assert kept["hook"] == REFUSED_PUSH
    # Kept as Git read it, by the name it was run as.
    assert kept["command"] == "git " + push.split(" ", 1)[1]


@needs_bwrap
def test_git_otherwise_works_in_the_sandbox(repo: Path) -> None:
    ran = _in_sandbox(repo, "echo next > base && git commit -qam next && git status --short "
                            "&& git rev-parse --abbrev-ref HEAD")

    assert ran.returncode == 0, ran.stderr
    assert ran.stdout.strip() == "feat/change"
    assert _git(repo, "log", "-1", "--format=%s") == "next"


@needs_bwrap
def test_the_guarded_push_reaches_the_remote_and_is_kept_with_its_commit(repo: Path) -> None:
    """The guarded push runs as the engine's command inside the sandbox; its own `git
    push` carries the guarded push's marker, so the engine's `git` lets it through."""
    _git(repo, "commit", "-q", "--allow-empty", "-m", "slice")
    head = _git(repo, "rev-parse", "HEAD")

    pushed = _in_sandbox(repo, f"{sys.executable} {ENGINE} push")

    assert pushed.returncode == 0, pushed.stderr
    assert _remote_head(repo, "feat/change") == head
    (kept,) = [entry for entry in kept_invocations(invocations_directory(repo), SESSION)
               if entry["hook"] == ATTEMPTED_PUSH]
    assert {key: kept[key] for key in ("hook", "branch", "remote", "commit", "exit_status")} == {
        "hook": ATTEMPTED_PUSH, "branch": "feat/change", "remote": "origin", "commit": head,
        "exit_status": 0}
