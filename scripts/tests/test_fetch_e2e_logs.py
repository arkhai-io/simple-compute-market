"""Tests for the E2E workflow log fetcher."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from typing import IO, Sequence

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "fetch-e2e-logs.py"
_SPEC = importlib.util.spec_from_file_location("fetch_e2e_logs", SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
fetcher = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = fetcher
_SPEC.loader.exec_module(fetcher)


class FakeRunner:
    def __init__(
        self,
        *,
        runs: list[dict[str, object]] | None = None,
        fail_watch: bool = False,
        fail_actions_log: bool = False,
        fail_artifact: bool = False,
    ) -> None:
        self.runs = (
            runs
            if runs is not None
            else [{"databaseId": 42, "headBranch": "feature/test"}]
        )
        self.fail_watch = fail_watch
        self.fail_actions_log = fail_actions_log
        self.fail_artifact = fail_artifact
        self.commands: list[list[str]] = []

    def __call__(
        self,
        command: Sequence[str],
        *,
        capture_output: bool = False,
        stdout: IO[str] | None = None,
        text: bool,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        args = list(command)
        self.commands.append(args)

        if args == ["git", "branch", "--show-current"]:
            return subprocess.CompletedProcess(args, 0, "feature/test\n", "")
        if args[:3] == ["gh", "run", "list"]:
            return subprocess.CompletedProcess(args, 0, json.dumps(self.runs), "")
        if args[:3] == ["gh", "run", "watch"]:
            if self.fail_watch:
                raise subprocess.CalledProcessError(1, args, stderr="watch failed")
            return subprocess.CompletedProcess(args, 0, "", "")
        if args[:3] == ["gh", "run", "view"] and "--json" in args:
            return subprocess.CompletedProcess(
                args, 0, json.dumps({"conclusion": "failure"}), ""
            )
        if args[:3] == ["gh", "run", "view"] and "--log" in args:
            if self.fail_actions_log:
                raise subprocess.CalledProcessError(1, args, stderr="log unavailable")
            assert stdout is not None
            stdout.write("actions log\n")
            return subprocess.CompletedProcess(args, 0, "", "")
        if args[:3] == ["gh", "run", "download"]:
            if self.fail_artifact:
                raise subprocess.CalledProcessError(
                    1, args, stderr="artifact unavailable"
                )
            output_dir = Path(args[args.index("--dir") + 1])
            (output_dir / fetcher.COMPOSE_LOG).write_text("compose log\n", "utf-8")
            return subprocess.CompletedProcess(args, 0, "", "")
        raise AssertionError(f"unexpected command: {args}")


def test_latest_current_branch_run_is_waited_for_and_downloaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(
        runs=[
            {"databaseId": 51, "headBranch": "another-branch"},
            {"databaseId": 42, "headBranch": "feature/test"},
        ]
    )
    monkeypatch.setattr(fetcher.subprocess, "run", runner)

    assert fetcher.main(["--output-dir", str(tmp_path)]) == 0

    run_dir = tmp_path / "42"
    assert (run_dir / "actions.log").read_text("utf-8") == "actions log\n"
    assert (run_dir / fetcher.COMPOSE_LOG).read_text("utf-8") == "compose log\n"
    assert ["gh", "run", "watch", "42"] in runner.commands


def test_explicit_run_id_skips_branch_lookup_and_tolerates_missing_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(fail_artifact=True)
    monkeypatch.setattr(fetcher.subprocess, "run", runner)

    assert fetcher.main(["--output-dir", str(tmp_path), "--run-id", "77"]) == 0

    assert (tmp_path / "77" / "actions.log").is_file()
    assert not any(command[0] == "git" for command in runner.commands)
    assert not any(command[:3] == ["gh", "run", "list"] for command in runner.commands)


def test_wait_failure_stops_before_log_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = FakeRunner(fail_watch=True)
    monkeypatch.setattr(fetcher.subprocess, "run", runner)

    assert fetcher.main(["--output-dir", str(tmp_path), "--run-id", "77"]) == 1

    assert "watch failed" in capsys.readouterr().err
    assert not any("--log" in command for command in runner.commands)
    assert not any(
        command[:3] == ["gh", "run", "download"] for command in runner.commands
    )


def test_missing_current_branch_run_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = FakeRunner(runs=[{"databaseId": 51, "headBranch": "another-branch"}])
    monkeypatch.setattr(fetcher.subprocess, "run", runner)

    assert fetcher.main(["--output-dir", str(tmp_path)]) == 1

    assert (
        "no e2e.yml workflow run found for branch feature/test"
        in capsys.readouterr().err
    )


def test_make_target_delegates_to_python_helper() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text("utf-8")
    target = makefile.split("fetch-e2e-logs:", 1)[1].split("prune-tombstones:", 1)[0]

    assert "$(CURDIR)/scripts/fetch-e2e-logs.py" in target
    assert "gh run" not in target
