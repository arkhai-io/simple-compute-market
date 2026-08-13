"""`e2e-ci.sh run` chains dispatch, watch, and logs against a stubbed `gh`.

The three commands were being typed by hand every loop. Chaining them has one
behaviour worth pinning rather than assuming: a failing run must still download
its evidence, because a red run is exactly when the logs are wanted. A naive
`dispatch && watch && logs` would skip the download on the case that needs it.

`gh` and `git` are stubbed as shell scripts on PATH, so this exercises the real
script without a network, a repository, or an authenticated CLI.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "e2e-ci.sh"
RUN_ID = "31479739305"


def _executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _stub_bin(tmp_path: Path, *, watch_exit: int) -> Path:
    """A `gh`/`git` pair recording every invocation to a log file."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls.txt"

    _executable(bin_dir / "git", f"""#!/bin/sh
case "$1 $2" in
  "rev-parse --abbrev-ref") echo ci-branch ;;
  "rev-parse HEAD") echo abc123 ;;
  "ls-remote --exit-code") exit 0 ;;
  "ls-remote origin") printf 'abc123\\trefs/heads/ci-branch\\n' ;;
  *) exit 0 ;;
esac
""")

    _executable(bin_dir / "gh", f"""#!/bin/sh
echo "gh $*" >> {calls}
case "$1 $2" in
  "auth status") exit 0 ;;
  "--version ") echo "gh version 2.0.0" ;;
  "workflow run") exit 0 ;;
  "run list") echo {RUN_ID} ;;
  "run view") echo "https://example.invalid/run/{RUN_ID}" ;;
  "run watch") exit {watch_exit} ;;
  "run download") exit 0 ;;
  *) exit 0 ;;
esac
""")
    return bin_dir


def _run(tmp_path: Path, bin_dir: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["E2E_LOG_DIR"] = str(tmp_path / "logs")
    return subprocess.run(
        ["bash", str(SCRIPT), "run"],
        cwd=tmp_path, env=env, capture_output=True, text=True,
    )


def _calls(tmp_path: Path) -> list[str]:
    log = tmp_path / "calls.txt"
    return log.read_text().splitlines() if log.exists() else []


class TestChainedRun:
    def test_a_passing_run_dispatches_watches_and_downloads(self, tmp_path):
        result = _run(tmp_path, _stub_bin(tmp_path, watch_exit=0))

        assert result.returncode == 0, result.stderr
        calls = " | ".join(_calls(tmp_path))
        assert "workflow run" in calls
        assert f"run watch {RUN_ID}" in calls
        assert f"run download {RUN_ID}" in calls

    def test_a_failing_run_still_downloads_its_evidence(self, tmp_path):
        """The case the chain exists for — do not short-circuit on red."""
        result = _run(tmp_path, _stub_bin(tmp_path, watch_exit=1))

        calls = " | ".join(_calls(tmp_path))
        assert f"run download {RUN_ID}" in calls, (
            "a failed run must still fetch its logs — that is when they are wanted"
        )
        assert result.returncode != 0, (
            "the command must still report failure, or CI cannot tell red from green"
        )

    def test_watch_and_logs_target_the_dispatched_run(self, tmp_path):
        """One id, captured once.

        Re-resolving "newest run for this branch" per subcommand would let a
        nightly run starting mid-loop be watched instead of the dispatched one.
        """
        _run(tmp_path, _stub_bin(tmp_path, watch_exit=0))

        watched = [c for c in _calls(tmp_path) if "run watch" in c]
        downloaded = [c for c in _calls(tmp_path) if "run download" in c]
        assert watched and downloaded
        assert all(RUN_ID in c for c in watched + downloaded)


class TestUsage:
    def test_run_is_documented(self, tmp_path):
        env = dict(os.environ)
        env["PATH"] = f"{_stub_bin(tmp_path, watch_exit=0)}:{env['PATH']}"
        result = subprocess.run(
            ["bash", str(SCRIPT), "--help"],
            cwd=tmp_path, env=env, capture_output=True, text=True,
        )

        assert result.returncode == 0
        assert "run " in result.stdout
        assert "dispatch" in result.stdout


@pytest.mark.parametrize("command", ["dispatch", "watch", "status", "logs"])
def test_existing_commands_still_dispatch(tmp_path, command):
    """The chain must not have broken the individual commands."""
    env = dict(os.environ)
    env["PATH"] = f"{_stub_bin(tmp_path, watch_exit=0)}:{env['PATH']}"
    env["E2E_LOG_DIR"] = str(tmp_path / "logs")
    result = subprocess.run(
        ["bash", str(SCRIPT), command],
        cwd=tmp_path, env=env, capture_output=True, text=True,
    )

    assert result.returncode == 0, f"{command}: {result.stderr}"
