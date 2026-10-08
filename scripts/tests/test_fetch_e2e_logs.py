"""Tests for the E2E workflow log fetcher."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from typing import IO, Sequence
from zipfile import ZipFile

import pytest

HEAD = "1111111111111111111111111111111111111111"
EARLIER = "2222222222222222222222222222222222222222"


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
        listings: list[list[dict[str, object]]] | None = None,
        fail_watch: bool = False,
        fail_actions_log: bool = False,
        fail_artifact: bool = False,
        missing_artifacts: tuple[str, ...] = (),
    ) -> None:
        self.runs = (
            runs
            if runs is not None
            else [{"databaseId": 42, "headBranch": "feature/test", "headSha": HEAD}]
        )
        # Successive `gh run list` answers, for a run that is listed only later.
        self.listings = listings
        self.fail_watch = fail_watch
        self.fail_actions_log = fail_actions_log
        self.fail_artifact = fail_artifact
        self.missing_artifacts = missing_artifacts
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
        if args[:3] == ["git", "rev-parse", "--verify"]:
            revision = args[3].removesuffix("^{commit}")
            full = {"HEAD": HEAD, EARLIER[:7]: EARLIER}.get(revision, revision)
            return subprocess.CompletedProcess(args, 0, full + "\n", "")
        if args[:3] == ["gh", "run", "list"]:
            runs = self.listings.pop(0) if self.listings else self.runs
            return subprocess.CompletedProcess(args, 0, json.dumps(runs), "")
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
            artifact = args[args.index("--name") + 1]
            if self.fail_artifact or artifact in self.missing_artifacts:
                raise subprocess.CalledProcessError(
                    1, args, stderr="artifact unavailable"
                )
            output_dir = Path(args[args.index("--dir") + 1])
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / fetcher.COMPOSE_LOG).write_text(f"{artifact}\n", "utf-8")
            return subprocess.CompletedProcess(args, 0, "", "")
        raise AssertionError(f"unexpected command: {args}")


def test_the_head_commits_run_on_the_current_branch_is_waited_for_and_downloaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(
        runs=[
            {"databaseId": 51, "headBranch": "another-branch", "headSha": HEAD},
            {"databaseId": 42, "headBranch": "feature/test", "headSha": HEAD},
        ]
    )
    monkeypatch.setattr(fetcher.subprocess, "run", runner)

    assert fetcher.main(["--output-dir", str(tmp_path)]) == 0

    run_dir = tmp_path / "42"
    assert (run_dir / "actions.log").read_text("utf-8") == "actions log\n"
    for artifact in ("e2e-vm-logs", "e2e-bare-metal-logs"):
        assert (run_dir / artifact / "compose-logs.txt").read_text("utf-8") == f"{artifact}\n"
    with ZipFile(tmp_path / "42.zip") as archive:
        assert archive.read("42/actions.log") == b"actions log\n"
        for artifact in ("e2e-vm-logs", "e2e-bare-metal-logs"):
            assert archive.read(f"42/{artifact}/compose-logs.txt") == f"{artifact}\n".encode()
    assert ["gh", "run", "watch", "42"] in runner.commands


def test_explicit_run_id_skips_branch_lookup_and_tolerates_missing_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(fail_artifact=True)
    monkeypatch.setattr(fetcher.subprocess, "run", runner)

    assert fetcher.main(["--output-dir", str(tmp_path), "--run-id", "77"]) == 0

    assert (tmp_path / "77" / "actions.log").is_file()
    with ZipFile(tmp_path / "77.zip") as archive:
        assert archive.read("77/actions.log") == b"actions log\n"
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


def test_missing_run_of_the_commit_is_reported_after_the_wait(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = FakeRunner(
        runs=[{"databaseId": 51, "headBranch": "another-branch", "headSha": HEAD}]
    )
    monkeypatch.setattr(fetcher.subprocess, "run", runner)

    assert fetcher.main(["--output-dir", str(tmp_path), "--wait-seconds", "0"]) == 1

    error = capsys.readouterr().err
    assert f"no e2e.yml workflow run of commit {HEAD[:12]} on branch feature/test" in error
    assert not any(command[:3] == ["gh", "run", "watch"] for command in runner.commands)


def test_a_finished_run_of_an_earlier_commit_is_never_fetched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(
        runs=[{"databaseId": 41, "headBranch": "feature/test", "headSha": EARLIER}]
    )
    monkeypatch.setattr(fetcher.subprocess, "run", runner)

    assert fetcher.main(["--output-dir", str(tmp_path), "--wait-seconds", "0"]) == 1

    assert not any(command[:3] == ["gh", "run", "watch"] for command in runner.commands)
    assert not (tmp_path / "41").exists()


def test_a_just_dispatched_run_is_waited_for_until_it_is_listed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    earlier = {"databaseId": 41, "headBranch": "feature/test", "headSha": EARLIER}
    dispatched = {"databaseId": 43, "headBranch": "feature/test", "headSha": HEAD}
    runner = FakeRunner(listings=[[earlier], [earlier], [dispatched, earlier]])
    monkeypatch.setattr(fetcher.subprocess, "run", runner)
    slept: list[float] = []
    now = iter([0.0, 1.0, 2.0, 3.0])

    fetcher.fetch_logs(
        workflow="e2e.yml",
        output_root=tmp_path,
        run_id=None,
        wait_seconds=60,
        sleep=slept.append,
        clock=lambda: next(now),
    )

    assert len(slept) == 2
    assert ["gh", "run", "watch", "43"] in runner.commands
    assert not any("41" in command for command in runner.commands)


def test_the_newest_of_several_runs_of_the_commit_is_taken(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(
        runs=[
            {"databaseId": 44, "headBranch": "feature/test", "headSha": HEAD},
            {"databaseId": 43, "headBranch": "feature/test", "headSha": HEAD},
        ]
    )
    monkeypatch.setattr(fetcher.subprocess, "run", runner)

    assert fetcher.main(["--output-dir", str(tmp_path)]) == 0
    assert ["gh", "run", "watch", "44"] in runner.commands


def test_a_repeated_dispatch_of_one_commit_waits_for_the_new_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    previous = {"databaseId": 43, "headBranch": "feature/test", "headSha": HEAD}
    redispatched = {"databaseId": 47, "headBranch": "feature/test", "headSha": HEAD}
    runner = FakeRunner(listings=[[previous], [redispatched, previous]])
    monkeypatch.setattr(fetcher.subprocess, "run", runner)
    now = iter([0.0, 1.0, 2.0])

    fetcher.fetch_logs(
        workflow="e2e.yml",
        output_root=tmp_path,
        run_id=None,
        wait_seconds=60,
        after_run=43,
        sleep=lambda seconds: None,
        clock=lambda: next(now),
    )

    assert ["gh", "run", "watch", "47"] in runner.commands
    assert ["gh", "run", "watch", "43"] not in runner.commands


def test_a_run_id_cannot_be_combined_with_commit_selection(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        fetcher.main(["--output-dir", str(tmp_path), "--run-id", "77", "--commit", HEAD])


def test_an_explicit_commit_replaces_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(
        runs=[{"databaseId": 41, "headBranch": "feature/test", "headSha": EARLIER}]
    )
    monkeypatch.setattr(fetcher.subprocess, "run", runner)

    assert fetcher.main(["--output-dir", str(tmp_path), "--commit", EARLIER[:7]]) == 0
    assert ["gh", "run", "watch", "41"] in runner.commands


def test_make_target_delegates_to_python_helper() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text("utf-8")
    target = makefile.split("fetch-e2e-logs:", 1)[1].split("prune-tombstones:", 1)[0]

    assert "$(CURDIR)/scripts/fetch-e2e-logs.py" in target
    assert '--commit "$(E2E_COMMIT)"' in target
    assert '--after-run "$(E2E_AFTER_RUN)"' in target
    assert "gh run" not in target


@pytest.mark.parametrize("missing", ["e2e-vm-logs", "e2e-bare-metal-logs"])
def test_one_missing_lane_preserves_other_lane_without_actions_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    runner = FakeRunner(fail_actions_log=True, missing_artifacts=(missing,))
    monkeypatch.setattr(fetcher.subprocess, "run", runner)

    assert fetcher.main(["--output-dir", str(tmp_path), "--run-id", "77"]) == 0
    for artifact in ("e2e-vm-logs", "e2e-bare-metal-logs"):
        assert (tmp_path / "77" / artifact / "compose-logs.txt").is_file() == (artifact != missing)


def test_repeated_fetch_reuses_each_lane_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner()
    monkeypatch.setattr(fetcher.subprocess, "run", runner)
    args = ["--output-dir", str(tmp_path), "--run-id", "77"]
    assert fetcher.main(args) == 0
    compose_log = tmp_path / "77" / "e2e-vm-logs" / "compose-logs.txt"
    compose_log.write_text("updated compose log\n", "utf-8")
    runner.commands.clear()
    assert fetcher.main(args) == 0
    with ZipFile(tmp_path / "77.zip") as archive:
        assert archive.read("77/e2e-vm-logs/compose-logs.txt") == b"updated compose log\n"
    assert not any(command[:3] == ["gh", "run", "download"] for command in runner.commands)


def test_no_available_logs_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = FakeRunner(fail_actions_log=True, fail_artifact=True)
    monkeypatch.setattr(fetcher.subprocess, "run", runner)

    assert fetcher.main(["--output-dir", str(tmp_path), "--run-id", "77"]) == 1
    assert "no logs could be fetched" in capsys.readouterr().err
    assert not (tmp_path / "77.zip").exists()
