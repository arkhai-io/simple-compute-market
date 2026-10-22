"""Tests for copying a change's history from its clone into the owner's workspace.

The copy itself is files on disk; the command and the records lookup find the
workspace through the clone's Git remote, which only a real clone shows. Every
test here runs over a temporary workspace with a bare `origin` and a clone made by
`change_clone.create`, its bootstrap's spawn injected since `make init` builds every
environment. Which evidence the records name is read from text alone.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Sequence

import pytest

import change_clone
import change_history as history
import find_change

CHANGE = "seed-pool"
ARCHIVED = Path("openspec/changes/archive/2026-10-22-seed-pool")
REVIEWS = ARCHIVED / "reviews"
COMMIT = "0123456789abcdef0123456789abcdef01234567"
VALIDATION = Path(".snapshot/validation") / COMMIT[:12]
CITED = Path(".snapshot/validation/fedcba987654")
RUN = Path(".snapshot/e2e-logs/39744936158")


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


def _spawn(command: Sequence[str], cwd: Path, log: Path, status: Path) -> int:
    log.write_text("bootstrap output\n", "utf-8")
    status.write_text("0\n", "utf-8")
    return os.getpid()


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "dev", str(origin))
    work = tmp_path / "work"
    _git(tmp_path, "init", "-q", "-b", "dev", str(work))
    # Ignored as the repository ignores them: records, evidence, and the settings link.
    (work / ".gitignore").write_text(
        ".claude/settings.local.json\n.snapshot/\nopenspec/changes/**/reviews/\n", "utf-8")
    (work / "README.md").write_text("1\n", "utf-8")
    _git(work, "add", "--all")
    _git(work, "commit", "-q", "-m", "start")
    _git(work, "remote", "add", "origin", str(origin))
    _git(work, "push", "-q", "origin", "dev")
    return work


@pytest.fixture
def clone(workspace: Path) -> Path:
    return change_clone.create(workspace, CHANGE, spawn=_spawn).clone


def _write(root: Path, relative: Path | str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, "utf-8")
    return path


VALIDATION_RECORD = f"""\
# Validation — {CHANGE} — {COMMIT[:12]}

- **Commit:** {COMMIT} on feat/{CHANGE}
- **Result:** passed
- **Pipeline:** run {RUN.name}, success
"""


def _history(clone: Path) -> None:
    """An archived change's records in the clone, and the evidence they name."""
    _write(clone, REVIEWS / "01-implementation.md", "# Implementation review\n")
    _write(clone, REVIEWS / "02-validation.md", VALIDATION_RECORD)
    _write(clone, REVIEWS / "workflow.jsonl",
           f'{{"step": "validate", "evidence": "{CITED}/helm/1/"}}\n')
    _write(clone, REVIEWS / "transcripts/03-validate.progress",
           "read .snapshot/validation/aaaaaaaaaaaa/helm/1/summary.json\n")
    _write(clone, VALIDATION / "local/1/summary.json", '{"passed": true}\n')
    _write(clone, VALIDATION / "helm/1/test.log", "helm\n")
    _write(clone, CITED / "helm/1/summary.json", '{"passed": true}\n')
    _write(clone, RUN / "actions.log", "pipeline\n")
    # Beside the evidence but not named by any record, or rebuildable from it.
    _write(clone, ".snapshot/validation/bbbbbbbbbbbb/local/1/summary.json", "{}\n")
    _write(clone, ".snapshot/e2e-logs/39744936158.zip", "zip\n")


# Which evidence the records name.

def test_the_records_name_cited_paths_validated_commits_and_pipeline_runs(
        tmp_path: Path) -> None:
    reviews = tmp_path / "reviews"
    _write(reviews, "02-validation.md", VALIDATION_RECORD)
    _write(reviews, "05-implementation.triage.md",
           f"Read `{CITED}/helm/1/` and `.snapshot/e2e-logs/111/actions.log`.\n")
    # A transcript cites whatever its session read, so it names nothing.
    _write(reviews, "transcripts/03-validate.jsonl", ".snapshot/e2e-logs/222/actions.log\n")

    assert history.named_evidence(reviews) == sorted([
        VALIDATION, CITED, RUN, Path(".snapshot/e2e-logs/111")])


def test_a_records_directory_naming_nothing_names_no_evidence(tmp_path: Path) -> None:
    reviews = tmp_path / "reviews"
    _write(reviews, "01-implementation.md", "- **Commit:** short\nno evidence\n")

    assert history.named_evidence(reviews) == []


# Synchronizing.

def test_the_first_copy_brings_the_records_and_named_evidence_to_the_same_paths(
        workspace: Path, clone: Path) -> None:
    _history(clone)

    synced = history.sync(clone, workspace.resolve(), CHANGE)

    copied = {
        (REVIEWS / "01-implementation.md").as_posix(),
        (REVIEWS / "02-validation.md").as_posix(),
        (REVIEWS / "workflow.jsonl").as_posix(),
        (REVIEWS / "transcripts/03-validate.progress").as_posix(),
        (VALIDATION / "local/1/summary.json").as_posix(),
        (VALIDATION / "helm/1/test.log").as_posix(),
        (CITED / "helm/1/summary.json").as_posix(),
        (RUN / "actions.log").as_posix(),
    }
    assert set(synced.copied) == copied
    assert synced.extended == synced.unchanged == synced.refused == []
    for name in copied:
        assert (workspace / name).read_bytes() == (clone / name).read_bytes()
    assert not (workspace / ".snapshot/validation/bbbbbbbbbbbb").exists()
    assert not (workspace / ".snapshot/e2e-logs/39744936158.zip").exists()
    # The transcript's citation names nothing, so it is neither copied nor missed.
    assert synced.absent == []
    assert not list(workspace.rglob("*.tmp"))
    assert history.differences(clone, workspace, CHANGE) == []


def test_evidence_the_records_name_that_the_clone_lacks_is_reported(
        workspace: Path, clone: Path) -> None:
    _history(clone)
    _write(clone, REVIEWS / "04-validation.md",
           "- **Commit:** 999999999999aaaa on feat/seed-pool\n")

    synced = history.sync(clone, workspace, CHANGE)

    assert synced.absent == [".snapshot/validation/999999999999"]
    assert synced.refused == []


def test_a_second_copy_extends_what_grew_adds_what_is_new_and_leaves_the_rest(
        workspace: Path, clone: Path) -> None:
    _history(clone)
    history.sync(clone, workspace, CHANGE)
    log = clone / REVIEWS / "workflow.jsonl"
    log.write_text(log.read_text("utf-8") + '{"step": "archive-cleanup"}\n', "utf-8")
    transcript = clone / REVIEWS / "transcripts/03-validate.progress"
    transcript.write_text(transcript.read_text("utf-8") + "ran make validate-helm\n", "utf-8")
    _write(clone, REVIEWS / "06-orchestrator.md", "Observations of the orchestrating session\n")

    synced = history.sync(clone, workspace, CHANGE)

    assert synced.extended == [(REVIEWS / "workflow.jsonl").as_posix(),
                               (REVIEWS / "transcripts/03-validate.progress").as_posix()]
    assert synced.copied == [(REVIEWS / "06-orchestrator.md").as_posix()]
    assert len(synced.unchanged) == 6 and synced.refused == []
    assert (workspace / REVIEWS / "workflow.jsonl").read_bytes() == log.read_bytes()
    assert (workspace / REVIEWS / "transcripts/03-validate.progress").read_bytes() == (
        transcript.read_bytes())


def test_a_conflicting_file_is_refused_and_named_and_the_rest_still_copied(
        workspace: Path, clone: Path) -> None:
    _history(clone)
    _write(workspace, REVIEWS / "01-implementation.md", "# The owner's own copy\n")
    _write(workspace, REVIEWS / "workflow.jsonl", '{"step": "design"}\n')

    synced = history.sync(clone, workspace, CHANGE)

    assert synced.refused == [
        f"{(REVIEWS / '01-implementation.md').as_posix()}: the workspace's copy differs from "
        "the clone's, other than by the clone's having grown it",
        f"{(REVIEWS / 'workflow.jsonl').as_posix()}: the workspace's copy differs from the "
        "clone's, other than by the clone's having grown it",
    ]
    assert (workspace / REVIEWS / "01-implementation.md").read_text("utf-8") == (
        "# The owner's own copy\n")
    assert (workspace / REVIEWS / "workflow.jsonl").read_text("utf-8") == '{"step": "design"}\n'
    assert (workspace / REVIEWS / "02-validation.md").is_file()
    assert history.differences(clone, workspace, CHANGE) == [
        f"{(REVIEWS / '01-implementation.md').as_posix()}: the workspace's copy differs",
        f"{(REVIEWS / 'workflow.jsonl').as_posix()}: the workspace's copy differs",
    ]


def test_a_directory_where_the_clone_has_a_file_is_refused(workspace: Path,
                                                           clone: Path) -> None:
    _history(clone)
    (workspace / REVIEWS / "02-validation.md").mkdir(parents=True)

    synced = history.sync(clone, workspace, CHANGE)

    assert synced.refused == [
        f"{(REVIEWS / '02-validation.md').as_posix()}: not a regular file in the workspace"]
    assert (workspace / REVIEWS / "02-validation.md").is_dir()


def test_a_link_in_the_clones_history_is_refused_and_named_not_followed(
        workspace: Path, clone: Path) -> None:
    _history(clone)
    (clone / REVIEWS / "linked.md").symlink_to(clone / REVIEWS / "02-validation.md")
    (clone / REVIEWS / "linked-directory").symlink_to(clone / VALIDATION)

    synced = history.sync(clone, workspace, CHANGE)

    assert synced.refused == [
        f"{(REVIEWS / 'linked-directory').as_posix()}: not a regular file in the clone",
        f"{(REVIEWS / 'linked.md').as_posix()}: not a regular file in the clone",
    ]
    assert not (workspace / REVIEWS / "linked.md").exists()
    assert not (workspace / REVIEWS / "linked-directory").exists()
    assert len(history.differences(clone, workspace, CHANGE)) == 2


def test_a_change_that_is_not_archived_has_no_history_to_copy(workspace: Path,
                                                              clone: Path) -> None:
    _write(clone, f"openspec/changes/{CHANGE}/reviews/01-implementation.md",
           "# Implementation review\n")

    with pytest.raises(history.HistoryError, match="not archived"):
        history.sync(clone, workspace, CHANGE)


def test_an_archived_change_without_records_has_no_history_to_copy(workspace: Path,
                                                                   clone: Path) -> None:
    (clone / ARCHIVED).mkdir(parents=True)

    with pytest.raises(history.HistoryError, match="does not exist"):
        history.sync(clone, workspace, CHANGE)


# The command line.

def test_the_command_copies_from_a_clone_and_reports(
        workspace: Path, clone: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _history(clone)

    assert history.main(["sync", CHANGE], root=clone) == 0

    out = capsys.readouterr().out
    assert f"Into {workspace.resolve()}: 8 file(s) copied, 0 extended, 0 already there." in out
    assert (workspace / REVIEWS / "02-validation.md").is_file()


def test_the_command_fails_naming_each_refusal(
        workspace: Path, clone: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _history(clone)
    _write(workspace, REVIEWS / "01-implementation.md", "# The owner's own copy\n")

    assert history.main(["sync", CHANGE], root=clone) == 1

    out = capsys.readouterr().out
    assert "Refused, the workspace's file left as it is:" in out
    assert f"{(REVIEWS / '01-implementation.md').as_posix()}: the workspace's copy" in out


def test_the_command_refuses_outside_a_clone(
        workspace: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert history.main(["sync", CHANGE], root=workspace) == 1
    assert "is not a change's clone" in capsys.readouterr().err


# Records found wherever they are.

def test_records_are_found_in_the_checkout_then_in_the_workspace(
        workspace: Path, clone: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _history(clone)
    other = Path("openspec/changes/archive/2026-10-01-other-change/reviews")
    _write(workspace, other / "01-implementation.md", "# Implementation review\n")

    assert find_change.find_records(clone, CHANGE) == clone / REVIEWS
    assert find_change.find_records(clone, "other-change") == workspace.resolve() / other
    assert find_change.main(["--records", CHANGE], root=clone) == 0
    assert find_change.main(["--records", "other-change"], root=clone) == 0
    assert capsys.readouterr().out.splitlines() == [
        REVIEWS.as_posix(), str(workspace.resolve() / other)]


def test_a_cleaned_up_changes_records_are_found_from_another_clone(
        workspace: Path, clone: Path) -> None:
    _history(clone)
    history.sync(clone, workspace, CHANGE)
    other = change_clone.create(workspace, "other-change", spawn=_spawn).clone

    assert find_change.find_records(other, CHANGE) == workspace.resolve() / REVIEWS


def test_records_found_nowhere_are_refused_naming_both_places(
        workspace: Path, clone: Path) -> None:
    with pytest.raises(find_change.ChangeNotFound, match="or in the workspace"):
        find_change.find_records(clone, CHANGE)
