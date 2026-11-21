"""The engine's sandbox, `change_workflow.sandbox`: a scope rendered as a bubblewrap
command, the paths it creates before launch, its probe, and the unconfined fallback.

The rendered arguments, the creation of absent paths, and the probe with its runner
doubled are unit tests, on scopes built by hand. The tests that launch real bubblewrap
are external-process integration: a shell program stands in for the harness, in a
scope resolved on a real Git checkout. Each is skipped, saying why, where the engine's
own probe finds the sandbox cannot run, and failed there under `SANDBOX_REQUIRED=1`,
which CI's packaging job sets; that they ran, not skipped, is the evidence
that the real probe passes on the machine that ran them."""

from __future__ import annotations

import json
import os
import select
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterator

import pytest

from change_workflow import adapters, sandbox, scope
from change_workflow.sandbox import BWRAP, Launch
from change_workflow.scope import ADAPTER, ENGINE, GRANT, Scope, ScopedPath
from change_workflow_fixtures import needs_bwrap, with_test_directory

BASE = [BWRAP, "--unshare-pid", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc"]
# The engine's `git` over the system's two, read from descriptors 7 and 8, and the
# system's Git where only the engine's names it.
GIT = ["--ro-bind", "/usr/bin/git", "/dev/change-workflow-git",
       "--perms", "0755", "--ro-bind-data", "7", "/usr/bin/git",
       "--perms", "0755", "--ro-bind-data", "8", "/usr/lib/git-core/git"]
# The step's private `/tmp`: a tmpfs of mode 0700 with `TMPDIR` pointing at it.
TMPFS = ["--perms", "0700", "--tmpfs", "/tmp", "--setenv", "TMPDIR", "/tmp"]
PRIVATE = ScopedPath(Path("/tmp"), ENGINE, "<temporary directory>", private=True)


def _paths(source: str, *paths: Path, create: bool = False) -> tuple[ScopedPath, ...]:
    return tuple(ScopedPath(path, source, path.name, create) for path in paths)


# The rendered command.

def test_a_scope_renders_writable_paths_then_the_protected_ones_inside_them() -> None:
    root, home = Path("/work/checkout"), Path("/user-home")
    design = Scope("design",
                   (PRIVATE, *_paths(ENGINE, root / "openspec", home / ".cache", root / ".git")),
                   _paths(ENGINE, root / ".agents/workflow.toml", root / ".git/config",
                          Path("/usr/bin/git")))

    command = sandbox.arguments(design, ["claude", "-p", "go"], git=(7, 8))

    def bind(flag: str, path: str) -> list[str]:
        return [flag, path, path]

    assert command == [
        *BASE,
        # The private `/tmp`, made rather than bound, before every bind.
        *TMPFS,
        # Shallower paths first, so no mount hides one inside it.
        *bind("--bind", "/user-home/.cache"),
        *bind("--bind", "/work/checkout/.git"), *bind("--bind", "/work/checkout/openspec"),
        # Only the protected path inside a writable one: the configuration and Git's
        # executable lie outside design's, read-only under the root already.
        *bind("--ro-bind", "/work/checkout/.git/config"),
        # Then the engine's `git` over the system's, after every writable path, so no
        # writable directory holding an executable hides it.
        *GIT,
        "--die-with-parent", "--", "claude", "-p", "go"]


def test_a_path_under_the_hosts_tmp_is_bound_inside_the_private_one() -> None:
    """CW-m8wq: a path under the host's `/tmp` that the scope names, as the review's
    drafts directory or a grant, is bound at its own path after the tmpfs, so it lands
    inside the private `/tmp`; a protected path inside it is bound read-only after
    it."""
    drafts = Path("/tmp/change-workflow-review-x")
    review = Scope("review", (*_paths(ENGINE, Path("/work/checkout/.git/change-invocations"),
                                      drafts), PRIVATE),
                   _paths(ADAPTER, drafts / "settings.json"))

    command = sandbox.arguments(review, ["codex"], git=(7, 8))

    assert command[len(BASE):-3] == [
        *TMPFS, "--bind", str(drafts), str(drafts),
        "--bind", "/work/checkout/.git/change-invocations",
        "/work/checkout/.git/change-invocations",
        "--ro-bind", str(drafts / "settings.json"), str(drafts / "settings.json"), *GIT]


def test_the_private_tmp_is_not_bound_from_the_host(tmp_path: Path) -> None:
    """The private `/tmp` is the sandbox's own: it is none of the paths bound from the
    host, which are all `prepare` creates."""
    found = Scope("design", (PRIVATE, *_paths(GRANT, tmp_path / "build", create=True)), ())

    assert sandbox.mounted_writable(found) == list(_paths(GRANT, tmp_path / "build",
                                                          create=True))
    sandbox.prepare(found)
    assert (tmp_path / "build").is_dir()


def test_a_checkout_wide_scope_mounts_the_configuration_read_only_after_the_checkout() -> None:
    root = Path("/work/checkout")
    implement = Scope("implement", _paths(ENGINE, root),
                      _paths(ENGINE, root / ".agents/workflow.toml"))

    command = sandbox.arguments(implement, ["true"], git=(7, 8))

    assert command[len(BASE):-3] == ["--bind", str(root), str(root), "--ro-bind",
                                     str(root / ".agents/workflow.toml"),
                                     str(root / ".agents/workflow.toml"), *GIT]


def test_paths_that_are_symlinks_are_mounted_where_they_lead(tmp_path: Path) -> None:
    """Bubblewrap cannot mount over a symlink, so a writable path that is one is bound
    at its target, a protected file linked inside a writable path is bound read-only at
    its target, and one linked outside every writable path, as a clone's local settings
    link to the owner's workspace, is read-only under the root and not mounted."""
    root, workspace, home = tmp_path / "clone", tmp_path / "workspace", tmp_path / "home"
    (root / ".claude").mkdir(parents=True)
    (workspace / ".claude").mkdir(parents=True)
    (workspace / ".claude/settings.local.json").write_text("{}", "utf-8")
    (root / ".claude/settings.local.json").symlink_to(workspace / ".claude/settings.local.json")
    (root / "shared.json").write_text("{}", "utf-8")
    (root / ".claude/settings.json").symlink_to("../shared.json")
    (tmp_path / "cache").mkdir()
    home.mkdir()
    (home / ".cache").symlink_to(tmp_path / "cache")
    implement = Scope("implement", _paths(ENGINE, root, home / ".cache"),
                      _paths(ADAPTER, root / ".claude/settings.local.json",
                             root / ".claude/settings.json"))

    command = sandbox.arguments(implement, ["true"], git=(7, 8))

    assert command[len(BASE):-3] == [
        "--bind", str(tmp_path / "cache"), str(tmp_path / "cache"),
        "--bind", str(root), str(root),
        "--ro-bind", str(root / "shared.json"), str(root / "shared.json"), *GIT]


# What is created before launch.

def test_absent_paths_are_created_in_their_empty_forms(tmp_path: Path) -> None:
    """CW-r6kd: a settings file the harness loads, absent at launch, is created in its
    empty form — `{}` for JSON, an empty file otherwise, a directory for an entry
    ending in `/` — and an absent writable path as a directory."""
    root = tmp_path / "checkout"
    found = Scope("implement",
                  (ScopedPath(root, ENGINE, ".", create=True),
                   ScopedPath(root / "build/cache", GRANT, "build/cache", create=True)),
                  (ScopedPath(root / ".claude/settings.local.json", ADAPTER,
                              ".claude/settings.local.json"),
                   ScopedPath(root / ".claude/notes", ADAPTER, ".claude/notes"),
                   ScopedPath(root / "secrets", ADAPTER, "secrets/")))

    sandbox.prepare(found)

    assert json.loads((root / ".claude/settings.local.json").read_text("utf-8")) == {}
    assert (root / ".claude/notes").read_text("utf-8") == ""
    assert (root / "secrets").is_dir()
    assert (root / "build/cache").is_dir()


def test_an_absent_path_behind_a_symlink_is_created_where_it_leads(tmp_path: Path) -> None:
    root = tmp_path / "checkout"
    (root / ".claude").mkdir(parents=True)
    (root / ".claude/settings.json").symlink_to("../shared/settings.json")
    (root / "cache").symlink_to("build/cache")
    found = Scope("implement", _paths(ENGINE, root) + _paths(GRANT, root / "cache"),
                  _paths(ADAPTER, root / ".claude/settings.json"))

    sandbox.prepare(found)

    assert json.loads((root / "shared/settings.json").read_text("utf-8")) == {}
    assert (root / "build/cache").is_dir()
    assert (root / ".claude/settings.json").is_symlink() and (root / "cache").is_symlink()


def test_an_absent_state_file_mounted_alone_is_created_as_a_file(tmp_path: Path) -> None:
    home = tmp_path / "home"
    found = Scope("design", (ScopedPath(home / ".claude.json", ADAPTER, "~/.claude.json",
                                        create=True, alone=True),), ())

    sandbox.prepare(found)
    command = sandbox.arguments(found, ["true"], git=(7, 8))

    assert json.loads((home / ".claude.json").read_text("utf-8")) == {}
    assert command[len(BASE):len(BASE) + 3] == ["--bind", str(home / ".claude.json"),
                                                str(home / ".claude.json")]


def test_a_protected_path_outside_every_writable_one_is_not_created(tmp_path: Path) -> None:
    root = tmp_path / "checkout"
    review = Scope("review", _paths(ENGINE, root / ".git/change-invocations", create=True),
                   _paths(ADAPTER, root / ".claude/settings.local.json"))

    sandbox.prepare(review)

    assert (root / ".git/change-invocations").is_dir()
    assert not (root / ".claude").exists()


# The probe and the unconfined fallback.

def _missing(*_, **__):
    raise FileNotFoundError(2, "No such file or directory", BWRAP)


def _not_executable(*_, **__):
    raise PermissionError(13, "Permission denied", BWRAP)


def _refused(*args, **_):
    return subprocess.CompletedProcess(args[0], 1, "",
                                       "bwrap: setting up uid map: Permission denied\n")


def _silent(*args, **_):
    return subprocess.CompletedProcess(args[0], 2, "", "")


@pytest.mark.parametrize("run,reason", [
    (_missing, "bwrap is not installed"),
    (_refused, "bwrap cannot run here: bwrap: setting up uid map: Permission denied"),
    (_not_executable, "bwrap cannot be run: [Errno 13] Permission denied: 'bwrap'"),
    (_silent, "bwrap cannot run here: exit 2"),
], ids=["not installed", "user namespaces refused", "not executable", "no message"])
def test_the_probe_says_why_the_sandbox_cannot_run(run, reason: str) -> None:
    assert sandbox.probe(run) == reason


def test_the_probe_runs_a_trivial_program_in_the_base_sandbox() -> None:
    seen = []

    def run(command, **_):
        seen.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    assert sandbox.probe(run) is None
    assert seen == [[*BASE, "--die-with-parent", "--", "true"]]


def test_without_the_sandbox_the_program_runs_unconfined_with_the_reason(
        tmp_path: Path) -> None:
    found = Scope("triage", _paths(GRANT, tmp_path / "build", create=True), ())

    launched = sandbox.launch(found, ["claude", "-p", "go"],
                              probing=lambda: "bwrap is not installed")

    assert launched == Launch(("claude", "-p", "go"), unconfined="bwrap is not installed")
    # Nothing is created for a sandbox that does not run.
    assert not (tmp_path / "build").exists()


def test_with_the_sandbox_the_program_runs_inside_it(tmp_path: Path) -> None:
    found = Scope("triage", _paths(GRANT, tmp_path / "build", create=True), ())

    with sandbox.launch(found, ["claude"], probing=lambda: None,
                        inside=lambda: False) as launched:
        assert launched.unconfined is None
        assert launched.command[0] == BWRAP and launched.command[-2:] == ("--", "claude")
        # The engine's `git`, open for bubblewrap to read over each Git executable.
        assert [os.read(fd, 10) for fd in launched.fds] == [b"#!/bin/sh\n"] * 2
    assert (tmp_path / "build").is_dir()


def test_inside_the_engines_sandbox_the_git_it_finds_is_kept(tmp_path: Path) -> None:
    """The enclosing sandbox's `git` cannot be mounted over, so a sandbox started
    inside it keeps that `git` and mounts the system's Git from where it sits there;
    its private `/tmp` is made as outside, and a path under `/tmp` bound inside it from
    the enclosing sandbox's."""
    found = Scope("triage", (PRIVATE, *_paths(GRANT, tmp_path / "build", create=True)), ())

    with sandbox.launch(found, ["claude"], probing=lambda: None,
                        inside=lambda: True) as launched:
        assert launched.fds == ()
        assert launched.command[len(BASE):] == (
            *TMPFS, "--bind", str(tmp_path / "build"), str(tmp_path / "build"),
            "--ro-bind", "/dev/change-workflow-git", "/dev/change-workflow-git",
            "--die-with-parent", "--", "claude")


# Through real bubblewrap.

INERT = ("openspec/", "docs/", "**/README.md", "AGENTS.md")


def _scope(step: str, root: Path, **more) -> Scope:
    return scope.resolve(step, root, inert_paths=INERT, home=root.parent / "home", **more)


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    root = tmp_path / "checkout"
    for path in ("openspec/specs/x/spec.md", "src/main.py", ".agents/workflow.toml"):
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text("x\n", "utf-8")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    return root


def _run(found: Scope, script: str, root: Path, *,
         hiding: bool = False) -> subprocess.CompletedProcess:
    """`script` in the scope's sandbox, from `root`, the test's directory around it
    read-only unless `hiding`, when the private `/tmp` hides it as it hides the
    host's."""
    with sandbox.launch(found, ["sh", "-c", script]) as launched:
        assert launched.unconfined is None
        command = (list(launched.command) if hiding
                   else with_test_directory(launched.command, root.parent))
        return subprocess.run(command, cwd=root, capture_output=True, text=True,
                              pass_fds=launched.fds)


@needs_bwrap
def test_a_write_inside_the_scope_succeeds_and_one_outside_fails(checkout: Path) -> None:
    found = _scope("design", checkout)

    inside = _run(found, "echo y > openspec/new.md", checkout)
    outside = _run(found, "echo y > src/new.py", checkout)

    assert inside.returncode == 0, inside.stderr
    assert (checkout / "openspec/new.md").read_text("utf-8") == "y\n"
    assert outside.returncode != 0
    assert "Read-only file system" in outside.stderr
    assert not (checkout / "src/new.py").exists()


@needs_bwrap
def test_a_protected_file_cannot_be_written_or_replaced(checkout: Path) -> None:
    found = _scope("implement", checkout)

    written = _run(found, "echo y > .agents/workflow.toml", checkout)
    replaced = _run(found, "echo y > .agents/new.toml && mv .agents/new.toml "
                           ".agents/workflow.toml", checkout)

    assert "Read-only file system" in written.stderr
    assert replaced.returncode != 0
    assert "Device or resource busy" in replaced.stderr
    assert (checkout / ".agents/workflow.toml").read_text("utf-8") == "x\n"


@needs_bwrap
def test_a_step_cannot_rewire_gits_hooks(checkout: Path) -> None:
    """CW-r6kd's "A step rewires Git's hooks": Git writes its lock file and cannot
    rename it over `.git/config`."""
    before = (checkout / ".git/config").read_text("utf-8")

    rewired = _run(_scope("implement", checkout), "git config core.hooksPath /tmp/hooks",
                   checkout)

    assert rewired.returncode != 0
    assert "Device or resource busy" in rewired.stderr, rewired.stderr
    assert (checkout / ".git/config").read_text("utf-8") == before


@needs_bwrap
def test_a_step_cannot_create_an_absent_settings_file(checkout: Path) -> None:
    """CW-r6kd's "A step creates an absent settings file": the engine created it as
    `{}` and mounted it read-only."""
    found = _scope("implement", checkout, adapter_protected=(".claude/settings.local.json",))

    created = _run(found, "echo '{\"permissions\": {}}' > .claude/settings.local.json",
                   checkout)

    assert created.returncode != 0
    assert "Read-only file system" in created.stderr
    assert (checkout / ".claude/settings.local.json").read_text("utf-8") == "{}"


@needs_bwrap
def test_a_settings_file_linked_to_the_workspace_launches_and_stays_read_only(
        checkout: Path) -> None:
    """CW-r6kd's "A clone's settings file is a link": a clone links its
    `.claude/settings.local.json` to the owner's workspace by an absolute symlink; the
    sandbox launches, and a write through the link fails as a read-only file system,
    the workspace's file and the link unchanged."""
    workspace = checkout.parent / "workspace"
    (workspace / ".claude").mkdir(parents=True)
    (workspace / ".claude/settings.local.json").write_text("{}", "utf-8")
    (checkout / ".claude").mkdir()
    (checkout / ".claude/settings.local.json").symlink_to(
        workspace / ".claude/settings.local.json")
    found = _scope("implement", checkout, adapter_protected=(".claude/settings.local.json",))

    written = _run(found, "echo '{\"permissions\": {}}' > .claude/settings.local.json",
                   checkout)

    assert written.returncode != 0
    assert "Read-only file system" in written.stderr, written.stderr
    assert (workspace / ".claude/settings.local.json").read_text("utf-8") == "{}"
    assert (checkout / ".claude/settings.local.json").is_symlink()


@needs_bwrap
def test_a_settings_file_linked_inside_the_scope_stays_read_only(checkout: Path) -> None:
    """A protected file linked to another file inside a writable path is mounted
    read-only where the link leads, so a write through the link fails."""
    (checkout / "shared.json").write_text("{}", "utf-8")
    (checkout / ".claude").mkdir()
    (checkout / ".claude/settings.json").symlink_to("../shared.json")
    found = _scope("implement", checkout, adapter_protected=(".claude/settings.json",))

    written = _run(found, "echo '{\"hooks\": {}}' > .claude/settings.json", checkout)
    beside = _run(found, "echo y > src/new.py", checkout)

    assert "Read-only file system" in written.stderr, written.stderr
    assert (checkout / "shared.json").read_text("utf-8") == "{}"
    assert beside.returncode == 0, beside.stderr


@needs_bwrap
def test_a_writable_path_that_is_a_symlink_is_written_where_it_leads(checkout: Path) -> None:
    home = checkout.parent / "home"
    (checkout.parent / "cache").mkdir()
    home.mkdir()
    (home / ".cache").symlink_to(checkout.parent / "cache")

    written = _run(_scope("design", checkout), f"echo y > {home}/.cache/entry", checkout)

    assert written.returncode == 0, written.stderr
    assert (checkout.parent / "cache/entry").read_text("utf-8") == "y\n"


@needs_bwrap
def test_an_adapters_state_file_is_written_in_place_and_its_directory_is_not(
        checkout: Path) -> None:
    """Claude Code's `~/.claude.json` is mounted alone: written in place it changes,
    while the home directory beside it stays read-only, and a file moved over it from
    another directory, which crosses a mount, fails and leaves it as it was."""
    home = checkout.parent / "home"
    found = _scope("design", checkout, adapter_files=("~/.claude.json",))

    written = _run(found, f"echo '{{\"n\": 1}}' > {home}/.claude.json", checkout)
    beside = _run(found, f"echo x > {home}/other", checkout)
    renamed = _run(found, f"echo x > /tmp/state.json && "
                          f"mv /tmp/state.json {home}/.claude.json", checkout)

    assert written.returncode == 0, written.stderr
    assert "Read-only file system" in beside.stderr
    assert renamed.returncode != 0
    assert "Read-only file system" in renamed.stderr, renamed.stderr
    assert (home / ".claude.json").read_text("utf-8") == '{"n": 1}\n'


CODEX = shutil.which("codex")
needs_codex = pytest.mark.skipif(CODEX is None, reason="Codex is not installed here")


@needs_bwrap
@needs_codex
def test_codex_runs_in_the_reviews_scope(checkout: Path) -> None:
    """Codex starts in the review's scope, its state writable but its configuration,
    and runs Git there through the engine's `git`. The home directory is the test's
    own."""
    home = checkout.parent / "home"
    adapter = adapters.ADAPTERS["codex"]
    found = scope.resolve("review", checkout, inert_paths=INERT, home=home,
                          adapter_writable=adapter.state, adapter_protected=adapter.protected)

    version = _run(found, "codex --version", checkout)
    toplevel = _run(found, "git rev-parse --show-toplevel", checkout)
    state = _run(found, f"echo x > {home}/.codex/session.json", checkout)
    configuration = _run(found, f"echo x > {home}/.codex/config.toml", checkout)

    assert version.returncode == 0, version.stderr
    assert version.stdout.startswith("codex"), version.stdout
    assert (toplevel.returncode, toplevel.stdout) == (0, f"{checkout}\n"), toplevel.stderr
    assert state.returncode == 0, state.stderr
    assert "Read-only file system" in configuration.stderr
    assert (home / ".codex/config.toml").read_text("utf-8") == ""


@needs_bwrap
def test_design_writes_a_prerequisites_proposal_in_its_worktree(checkout: Path) -> None:
    """CW-k8dn's "A design needs a prerequisite": a worktree beside the checkout, made
    as `propose` makes one, is writable to the resumed design, and a sibling worktree
    is not."""
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
    subprocess.run([*git, "add", "-A"], cwd=checkout, check=True)
    subprocess.run([*git, "commit", "-qm", "x"], cwd=checkout, check=True)
    proposal, sibling = checkout.parent / "shape-floor-proposal", checkout.parent / "sibling"
    for path, branch in ((proposal, "propose-shape-floor"), (sibling, "sibling")):
        subprocess.run([*git, "worktree", "add", "-q", "-b", branch, str(path)], cwd=checkout,
                       check=True)
    written = proposal / "openspec/changes/shape-floor/notes.txt"

    proposed = _run(_scope("design", checkout),
                    f"mkdir -p {written.parent} && echo y > {written}", checkout)
    beside = _run(_scope("design", checkout), f"echo y > {sibling}/notes.md", checkout)

    assert proposed.returncode == 0, proposed.stderr
    assert written.read_text("utf-8") == "y\n"
    assert "Read-only file system" in beside.stderr


@needs_bwrap
def test_a_file_outside_the_scope_is_read(checkout: Path) -> None:
    read = _run(_scope("review", checkout), "cat src/main.py", checkout)

    assert (read.returncode, read.stdout) == (0, "x\n")


# The ancestor check the bare-metal working-data helper makes of a directory it keeps
# files in: each ancestor below `/` owned by root or the caller and writable by no
# one else, `/tmp` exempt only where it is root's and sticky.
ANCESTORS = r"""
import os, stat, sys
path, failed = "/", []
for part in sys.argv[1].split("/")[1:]:
    path = os.path.join(path, part)
    info = os.stat(path, follow_symlinks=False)
    sticky_tmp = path == "/tmp" and info.st_uid == 0 and info.st_mode & stat.S_ISVTX
    if not sticky_tmp and (info.st_uid not in (0, os.getuid()) or info.st_mode & 0o022):
        failed.append(f"{path} {info.st_uid} {oct(info.st_mode & 0o7777)}")
print("unsafe ancestor: " + ", ".join(failed) if failed else "safe")
"""


@needs_bwrap
def test_a_suites_temporary_directory_passes_an_owner_check(checkout: Path) -> None:
    """CW-m8wq's "A suite checks its temporary directory's owner": inside the sandbox
    `/tmp` is the owner's with mode 0700, so each ancestor of a directory made under it
    is root's or the caller's and writable by no one else, though the host's `/tmp`,
    root's, would show there as the overflow uid's."""
    # The umask is pinned: under a group-writable one, such as Debian's 002, the
    # directories made here would be writable by others for that reason alone.
    script = (f"umask 022 && mkdir -p /tmp/ledger/work && stat -c '%u %a' /tmp && "
              f"{shlex.join([sys.executable, '-I', '-c', ANCESTORS, '/tmp/ledger/work'])}")

    checked = _run(_scope("implement", checkout), script, checkout)

    assert checked.returncode == 0, checked.stderr
    assert checked.stdout.splitlines() == [f"{os.getuid()} 700", "safe"]


@needs_bwrap
def test_tmpdir_names_the_private_tmp(checkout: Path) -> None:
    """A `TMPDIR` the owner set elsewhere is replaced by `/tmp`, so a program's
    temporary files land in the private one."""
    found = _scope("review", checkout)
    with sandbox.launch(found, ["sh", "-c", "echo $TMPDIR"]) as launched:
        said = subprocess.run(launched.command, capture_output=True, text=True,
                              pass_fds=launched.fds, env={**os.environ, "TMPDIR": "/var/tmp"})

    assert (said.returncode, said.stdout) == (0, "/tmp\n"), said.stderr


@pytest.fixture
def host_tmp() -> Iterator[Path]:
    """A directory of the test's own under the host's `/tmp` itself, wherever pytest
    keeps its temporary directories."""
    made = Path(tempfile.mkdtemp(prefix="change-workflow-host-tmp-", dir="/tmp"))
    yield made
    shutil.rmtree(made, ignore_errors=True)


@needs_bwrap
def test_the_hosts_tmp_is_hidden_but_for_the_paths_the_scope_names(
        checkout: Path, host_tmp: Path) -> None:
    """A file under the host's `/tmp` outside the scope is not visible inside; a path
    under it the scope names — here a grant — is written at the same host path, and a
    file written to the private `/tmp` is left nowhere on the host."""
    hidden, granted = host_tmp / "hidden.txt", host_tmp / "granted"
    hidden.write_text("x\n", "utf-8")
    marker = f"{host_tmp.name}-private"
    found = _scope("implement", checkout, grants=(str(granted),))

    looked = _run(found, f"test -e {hidden} && echo seen || echo hidden", checkout,
                  hiding=True)
    written = _run(found, f"echo y > {granted}/entry && echo z > /tmp/{marker}", checkout,
                   hiding=True)

    assert (looked.returncode, looked.stdout) == (0, "hidden\n"), looked.stderr
    assert written.returncode == 0, written.stderr
    assert (granted / "entry").read_text("utf-8") == "y\n"
    assert not (Path("/tmp") / marker).exists()


PING = ("import socket, sys\n"
        "client = socket.socket(socket.AF_UNIX)\n"
        "client.connect(sys.argv[1])\n"
        "client.sendall(b'GET /_ping HTTP/1.0\\r\\nHost: docker\\r\\n\\r\\n')\n"
        "answer = b''\n"
        "while chunk := client.recv(4096):\n"
        "    answer += chunk\n"
        "print(answer.decode().rsplit(chr(10), 1)[-1])\n")


def _docker_socket() -> str | None:
    """A Docker socket this user can talk to here, answering its ping."""
    for path in ("/var/run/docker.sock", "/run/docker.sock"):
        if os.path.exists(path):
            pinged = subprocess.run([sys.executable, "-c", PING, path], capture_output=True,
                                    text=True)
            if pinged.returncode == 0 and pinged.stdout.strip() == "OK":
                return path
    return None


@needs_bwrap
def test_the_docker_socket_carries_traffic_from_inside(checkout: Path) -> None:
    if (path := _docker_socket()) is None:
        pytest.skip("no Docker socket answering this user here")
    with sandbox.launch(_scope("design", checkout), [sys.executable, "-c", PING, path]) as launched:
        pinged = subprocess.run(launched.command, capture_output=True, text=True,
                                pass_fds=launched.fds)

    assert (pinged.returncode, pinged.stdout.strip()) == (0, "OK"), pinged.stderr


@needs_bwrap
def test_the_session_dies_with_its_launcher(checkout: Path) -> None:
    """Once the process that launched the sandbox dies, every process inside dies with
    it, a command left running in the background included: the pipe they all hold
    reaches its end only when the last of them is gone."""
    with sandbox.launch(_scope("design", checkout),
                        ["sh", "-c", "sleep 600 & echo ready; exec sleep 600"]) as launched:
        # The launcher hands bubblewrap the descriptors it inherited.
        launcher = subprocess.Popen(
            [sys.executable, "-c",
             "import subprocess, sys; subprocess.Popen(sys.argv[1:], close_fds=False).wait()",
             *launched.command], stdout=subprocess.PIPE, pass_fds=launched.fds)
    assert launcher.stdout is not None
    try:
        assert launcher.stdout.readline() == b"ready\n"
    finally:
        launcher.send_signal(signal.SIGKILL)
        launcher.wait()

    ended, _, _ = select.select([launcher.stdout], [], [], 10)
    assert ended and launcher.stdout.read() == b"", "a sandboxed process outlived its launcher"
    launcher.stdout.close()
