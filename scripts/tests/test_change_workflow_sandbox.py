"""The engine's sandbox, `change_workflow.sandbox`: a scope rendered as a bubblewrap
command, the paths it creates before launch, its probe, and the unconfined fallback.

The rendered arguments, the creation of absent paths, and the probe with its runner
doubled are unit tests, on scopes built by hand. The tests that launch real bubblewrap
are external-process integration: a shell program stands in for the harness, in a
scope resolved on a real Git checkout. Each is skipped, saying why, where the engine's
own probe finds the sandbox cannot run; that they ran, not skipped, is the evidence
that the real probe passes on the machine that ran them."""

from __future__ import annotations

import json
import os
import select
import signal
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from change_workflow import sandbox, scope
from change_workflow.sandbox import BWRAP, Launch
from change_workflow.scope import ADAPTER, ENGINE, GRANT, Scope, ScopedPath

BASE = [BWRAP, "--unshare-pid", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc"]


def _paths(source: str, *paths: Path, create: bool = False) -> tuple[ScopedPath, ...]:
    return tuple(ScopedPath(path, source, path.name, create) for path in paths)


# The rendered command.

def test_a_scope_renders_writable_paths_then_the_protected_ones_inside_them() -> None:
    root, home = Path("/work/checkout"), Path("/user-home")
    design = Scope("design",
                   _paths(ENGINE, root / "openspec", home / ".cache", Path("/tmp"), root / ".git"),
                   _paths(ENGINE, root / ".agents/workflow.toml", root / ".git/config",
                          Path("/usr/bin/git")))

    command = sandbox.arguments(design, ["claude", "-p", "go"],
                                binds=[(Path("/opt/engine-git"), Path("/usr/bin/git"))])

    def bind(flag: str, path: str) -> list[str]:
        return [flag, path, path]

    assert command == [
        *BASE,
        # Shallower paths first, so no mount hides one inside it.
        *bind("--bind", "/tmp"), *bind("--bind", "/user-home/.cache"),
        *bind("--bind", "/work/checkout/.git"), *bind("--bind", "/work/checkout/openspec"),
        # Only the protected path inside a writable one: the configuration and Git's
        # executable lie outside design's, read-only under the root already.
        *bind("--ro-bind", "/work/checkout/.git/config"),
        "--ro-bind", "/opt/engine-git", "/usr/bin/git",
        "--die-with-parent", "--", "claude", "-p", "go"]


def test_a_checkout_wide_scope_mounts_the_configuration_read_only_after_the_checkout() -> None:
    root = Path("/work/checkout")
    implement = Scope("implement", _paths(ENGINE, root),
                      _paths(ENGINE, root / ".agents/workflow.toml"))

    command = sandbox.arguments(implement, ["true"])

    assert command[len(BASE):-3] == ["--bind", str(root), str(root), "--ro-bind",
                                     str(root / ".agents/workflow.toml"),
                                     str(root / ".agents/workflow.toml")]


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

    launched = sandbox.launch(found, ["claude"], probing=lambda: None)

    assert launched.unconfined is None
    assert launched.command[0] == BWRAP and launched.command[-2:] == ("--", "claude")
    assert (tmp_path / "build").is_dir()


# Through real bubblewrap.

PROBED = sandbox.probe()
needs_bwrap = pytest.mark.skipif(PROBED is not None, reason=f"the sandbox cannot run: {PROBED}")
INERT = ("openspec/", "docs/", "**/README.md", "AGENTS.md")


def _scope(step: str, root: Path, **more) -> Scope:
    return scope.resolve(step, root, inert_paths=INERT, home=root.parent / "home",
                         temporary=root.parent / "tmp", **more)


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    root = tmp_path / "checkout"
    for path in ("openspec/specs/x/spec.md", "src/main.py", ".agents/workflow.toml"):
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text("x\n", "utf-8")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    return root


def _run(found: Scope, script: str, root: Path) -> subprocess.CompletedProcess:
    launched = sandbox.launch(found, ["sh", "-c", script])
    assert launched.unconfined is None
    return subprocess.run(launched.command, cwd=root, capture_output=True, text=True)


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
def test_a_file_outside_the_scope_is_read(checkout: Path) -> None:
    read = _run(_scope("review", checkout), "cat src/main.py", checkout)

    assert (read.returncode, read.stdout) == (0, "x\n")


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
    launched = sandbox.launch(_scope("design", checkout), [sys.executable, "-c", PING, path])

    pinged = subprocess.run(launched.command, capture_output=True, text=True)

    assert (pinged.returncode, pinged.stdout.strip()) == (0, "OK"), pinged.stderr


@needs_bwrap
def test_the_session_dies_with_its_launcher(checkout: Path) -> None:
    """Once the process that launched the sandbox dies, every process inside dies with
    it, a command left running in the background included: the pipe they all hold
    reaches its end only when the last of them is gone."""
    launched = sandbox.launch(_scope("design", checkout),
                              ["sh", "-c", "sleep 600 & echo ready; exec sleep 600"])
    launcher = subprocess.Popen(
        [sys.executable, "-c", "import subprocess, sys; subprocess.Popen(sys.argv[1:]).wait()",
         *launched.command], stdout=subprocess.PIPE)
    assert launcher.stdout is not None
    try:
        assert launcher.stdout.readline() == b"ready\n"
    finally:
        launcher.send_signal(signal.SIGKILL)
        launcher.wait()

    ended, _, _ = select.select([launcher.stdout], [], [], 10)
    assert ended and launcher.stdout.read() == b"", "a sandboxed process outlived its launcher"
    launcher.stdout.close()
