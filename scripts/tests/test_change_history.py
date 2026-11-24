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

from change_workflow import history
from change_workflow import clone as change_clone
from change_workflow import find as find_change
from change_workflow.log import record_outcome
from change_workflow.wrapper import Wrapper
from change_workflow_fixtures import (ACCEPTED, ACCEPTING, LANDED, LOCAL_CONFIGURED, NO_SANDBOX,
                                      VALID, FakeClaude, clock, event_lines)

CHANGE = "seed-pool"
ARCHIVED = Path("openspec/changes/archive/2026-10-22-seed-pool")
REVIEWS = ARCHIVED / "reviews"
COMMIT = "0123456789abcdef0123456789abcdef01234567"
TREE = "fedcba9876543210fedcba9876543210fedcba98"
OTHER_TREE = "a" * 40
# Where the workspace's evidence kinds' patterns fix their evidence, as the clone's
# checkout carries them: the three kinds share one directory.
EVIDENCE = [".snapshot/evidence/"]
BY_TREE = Path(".snapshot/evidence") / TREE
BY_COMMIT = Path(".snapshot/evidence") / COMMIT
# An attempt a record cites by its path, of a tree no record names.
CITED = Path(".snapshot/evidence") / OTHER_TREE / "helm/20261117T1140Z"


def _kind(name: str, pattern: str, shape: str = 'run = "true"') -> str:
    required = "owed" if "{owed}" in pattern else "always"
    return (f'[validation.evidence.{name}]\nrequired = "{required}"\n{shape}\n'
            f'evidence = "{pattern}"\nguide = ".agents/evidence/{name}.md"\n')


CONFIGURATION = (_kind("pipeline", ".snapshot/evidence/{commit}/pipeline/*/summary.json",
                       'start = "true"\ncollect = "true"')
                 + _kind("local", ".snapshot/evidence/{tree}/local/*/summary.json")
                 + _kind("helm", ".snapshot/evidence/{tree}/helm/*/summary.json"))


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
    # Ignored as the repository ignores them: records, evidence, and the links to the
    # workspace's settings and local configuration.
    (work / ".gitignore").write_text(
        ".claude/settings.local.json\n.agents/workflow.local.toml\n.snapshot/\n"
        "openspec/changes/**/reviews/\n", "utf-8")
    (work / "README.md").write_text("1\n", "utf-8")
    (work / ".agents/evidence").mkdir(parents=True)
    (work / ".agents/workflow.toml").write_text(ACCEPTED + CONFIGURATION, "utf-8")
    for name in ("pipeline", "local", "helm"):
        (work / ".agents/evidence" / f"{name}.md").write_text(f"# The {name} kind\n", "utf-8")
    _git(work, "add", "--all")
    _git(work, "commit", "-q", "-m", "start")
    _git(work, "remote", "add", "origin", str(origin))
    _git(work, "push", "-q", "-u", "origin", "dev")
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
- **Tree:** {TREE}
- **Result:** passed
"""


def _history(clone: Path) -> None:
    """An archived change's records in the clone, and the evidence they name."""
    _write(clone, REVIEWS / "01-implementation.md", "# Implementation review\n")
    _write(clone, REVIEWS / "02-validation.md", VALIDATION_RECORD)
    _write(clone, REVIEWS / "workflow.jsonl",
           f'{{"step": "validate", "evidence": "{CITED}/summary.json"}}\n')
    _write(clone, REVIEWS / "transcripts/03-validate.progress",
           f"read .snapshot/evidence/{'b' * 40}/helm/1/summary.json\n")
    _write(clone, BY_TREE / "local/20261117T1003Z/summary.json", '{"passed": true}\n')
    _write(clone, BY_TREE / "helm/20261117T1003Z/summary.json", '{"passed": true}\n')
    _write(clone, BY_TREE / "helm/20261117T1003Z/test.log", "helm\n")
    _write(clone, BY_COMMIT / "pipeline/20261117T1003Z/summary.json", '{"passed": true}\n')
    _write(clone, BY_COMMIT / "pipeline/20261117T1003Z/actions.log", "pipeline\n")
    _write(clone, CITED / "summary.json", '{"passed": true}\n')
    # Beside the evidence but not named by any record: another attempt of the cited
    # tree, another tree, and a zip of logs.
    _write(clone, CITED.parent / "20261117T1003Z/summary.json", '{"passed": false}\n')
    _write(clone, f".snapshot/evidence/{'b' * 40}/local/1/summary.json", "{}\n")
    _write(clone, ".snapshot/e2e-logs/39744936158.zip", "zip\n")


# Which evidence the records name.

def test_the_records_name_cited_paths_and_validated_trees_and_commits(
        tmp_path: Path) -> None:
    reviews = tmp_path / "reviews"
    _write(reviews, "02-validation.md", VALIDATION_RECORD)
    _write(reviews, "05-implementation.triage.md",
           f"Read `{CITED}/` and `.snapshot/evidence/{'c' * 40}/local/1/summary.json`.\n")
    # A transcript cites whatever its session read, so it names nothing.
    _write(reviews, "transcripts/03-validate.jsonl",
           f".snapshot/evidence/{'d' * 40}/local/1/summary.json\n")

    cited, keys = history.named_evidence(reviews, EVIDENCE)

    assert cited == sorted([CITED, Path(f".snapshot/evidence/{'c' * 40}/local/1/summary.json")])
    # Where a validated tree's or commit's evidence lies the records do not say; the
    # copy looks where each kind keyed by that identity puts it.
    assert keys == [("commit", COMMIT), ("tree", TREE)]


def test_a_citation_ending_a_sentence_names_the_path_without_its_full_stop(
        tmp_path: Path) -> None:
    reviews = tmp_path / "reviews"
    _write(reviews, "02-validation.md", f"The rerun is {CITED}.\n")

    assert history.named_evidence(reviews, EVIDENCE) == ([CITED], [])


def test_a_records_directory_naming_nothing_names_no_evidence(tmp_path: Path) -> None:
    reviews = tmp_path / "reviews"
    _write(reviews, "01-implementation.md", "- **Commit:** short\nno evidence\n")

    assert history.named_evidence(reviews, EVIDENCE) == ([], [])


def test_a_directory_no_kind_declares_is_never_named(tmp_path: Path) -> None:
    reviews = tmp_path / "reviews"
    _write(reviews, "05-implementation.triage.md", f"Read `{CITED}/`.\n")

    assert history.named_evidence(reviews, [".snapshot/e2e-logs/"]) == ([], [])


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
        (BY_TREE / "local/20261117T1003Z/summary.json").as_posix(),
        (BY_TREE / "helm/20261117T1003Z/summary.json").as_posix(),
        (BY_TREE / "helm/20261117T1003Z/test.log").as_posix(),
        (BY_COMMIT / "pipeline/20261117T1003Z/summary.json").as_posix(),
        (BY_COMMIT / "pipeline/20261117T1003Z/actions.log").as_posix(),
        (CITED / "summary.json").as_posix(),
    }
    assert set(synced.copied) == copied
    assert synced.extended == synced.unchanged == synced.refused == []
    for name in copied:
        assert (workspace / name).read_bytes() == (clone / name).read_bytes()
    # A cited file brings the attempt holding it, and no other attempt of its tree.
    assert not (workspace / CITED.parent / "20261117T1003Z").exists()
    assert not (workspace / f".snapshot/evidence/{'b' * 40}").exists()
    assert not (workspace / ".snapshot/e2e-logs/39744936158.zip").exists()
    # The transcript's citation names nothing, so it is neither copied nor missed.
    assert synced.absent == []
    assert not list(workspace.rglob("*.tmp"))
    assert history.differences(clone, workspace, CHANGE) == []


def test_the_engine_copies_archive_cleanups_history_once_its_session_finishes(
        workspace: Path, clone: Path) -> None:
    """CW-hak6's "Records grow after archive cleanup copied them": the engine copies the
    records after archive cleanup's session, before its outcome is logged, the copy
    on the line's `invoked`; once the outcome and another record follow in the clone,
    the next copy extends the workspace's log and adds the record. Library
    integration: the wrapper on a real clone, the harness doubled."""
    _history(clone)
    log = REVIEWS / "workflow.jsonl"
    # The log as the engine writes it, closeout's line its last before cleanup.
    (clone / log).unlink()
    record_outcome(clone / log, "closeout", VALID["finished"], session="c-1", commit=COMMIT)
    (clone / ".agents/workflow.toml").write_text(ACCEPTED + CONFIGURATION, "utf-8")
    (clone / ".agents/workflow.local.toml").write_text(LOCAL_CONFIGURED, "utf-8")
    claude = FakeClaude((event_lines({**VALID["finished"], "next": {"step": "done"},
                                      "landing": LANDED}), 0))
    wrapper = Wrapper(root=clone, runner=claude, head=lambda _: COMMIT, clock=clock,
                      echo=None, conversation=lambda _, session: clone / f"{session}.jsonl",
                      runs=lambda _: None, checkout=lambda *_: ACCEPTING,
                      target=lambda *_: None, kind=lambda *_: None, confinement=NO_SANDBOX)

    line = wrapper.run("archive-cleanup", CHANGE)

    copied = (workspace / log).read_text("utf-8")
    assert line["outcome"] == "finished", line.get("reason")
    (copy,) = [entry for entry in line["invoked"] if entry["hook"] == "history"]
    assert (copy["command"], copy["exit_status"]) == (f"history sync {CHANGE}", 0)
    # Copied before the line was written: the workspace's log lacks it.
    assert '"archive-cleanup"' not in copied
    assert (clone / log).read_text("utf-8").startswith(copied)
    _write(clone, REVIEWS / "05-merge.md", "# Merge review\n")

    synced = history.sync(clone, workspace.resolve(), CHANGE)

    assert log.as_posix() in synced.extended
    assert (REVIEWS / "05-merge.md").as_posix() in synced.copied
    assert history.differences(clone, workspace, CHANGE) == []


def test_a_runs_inputs_directory_is_copied_with_the_records(
        workspace: Path, clone: Path) -> None:
    """CW-i9np: what the actions and hooks around a run left is under the change's
    records, so it is copied with them."""
    _history(clone)
    inputs = REVIEWS / "runs/20261021T091540Z-validate"
    names = [inputs / "before/status.md", inputs / "before/gather.log",
             inputs / "before/message.md", inputs / "after/status.md"]
    for name in names:
        _write(clone, name, f"{name.name}\n")

    synced = history.sync(clone, workspace.resolve(), CHANGE)

    assert {name.as_posix() for name in names} <= set(synced.copied)
    assert history.differences(clone, workspace, CHANGE) == []


def test_evidence_the_records_name_that_the_clone_lacks_is_reported(
        workspace: Path, clone: Path) -> None:
    _history(clone)
    _write(clone, REVIEWS / "04-validation.md",
           f"- **Commit:** {'9' * 40} on feat/seed-pool\n"
           f"Read `.snapshot/evidence/{'7' * 40}/local/1/`.\n")

    synced = history.sync(clone, workspace, CHANGE)

    # A commit no kind's pattern finds is reported as each kind keyed by the commit
    # fills its pattern; a cited path where it was cited.
    assert synced.absent == [f".snapshot/evidence/{'7' * 40}/local/1",
                             f".snapshot/evidence/{'9' * 40}/pipeline/*/summary.json"]
    assert synced.refused == []


def test_evidence_under_a_directory_no_kind_declares_is_not_copied(
        workspace: Path, clone: Path) -> None:
    _history(clone)
    _write(clone, f".snapshot/validation/{TREE}/local/1/summary.json", "{}\n")
    (clone / ".agents/workflow.toml").write_text(
        ACCEPTED + _kind("local", ".snapshot/validation/{tree}/local/*/summary.json"), "utf-8")

    synced = history.sync(clone, workspace, CHANGE)

    assert not any(name.startswith(".snapshot/evidence/") for name in synced.copied)
    assert f".snapshot/validation/{TREE}/local/1/summary.json" in synced.copied
    assert not (workspace / BY_COMMIT).exists()


@pytest.mark.parametrize(("pattern", "named", "unnamed"), [
    # Evidence keyed by a file directly in the evidence directory.
    (".snapshot/runs/{tree}.json", f".snapshot/runs/{TREE}.json",
     f".snapshot/runs/{OTHER_TREE}.json"),
    # Evidence keyed by a directory whose name embeds the identity.
    (".snapshot/runs/run-{tree}/summary.json", f".snapshot/runs/run-{TREE}/summary.json",
     f".snapshot/runs/run-{OTHER_TREE}/summary.json"),
    # Evidence keyed by a file in a directory per owed argument, which holds every
    # tree's evidence of that argument.
    (".snapshot/runs/{owed}/{tree}.json", f".snapshot/runs/tests.yml/{TREE}.json",
     f".snapshot/runs/tests.yml/{OTHER_TREE}.json"),
], ids=["file", "embedded", "owed"])
def test_the_kinds_pattern_says_which_evidence_the_records_name(
        workspace: Path, clone: Path, pattern: str, named: str, unnamed: str) -> None:
    """CW-hak6 over any layout CW-t3ev admits: what the records name is copied, and
    nothing else beside it, nor is named evidence the clone holds reported absent."""
    _write(clone, REVIEWS / "02-validation.md",
           VALIDATION_RECORD + f"\nCurrent: `{named}`.\n")
    _write(clone, named, '{"passed": true}\n')
    _write(clone, unnamed, '{"passed": false}\n')
    (clone / ".agents/workflow.toml").write_text(ACCEPTED + _kind("local", pattern), "utf-8")

    synced = history.sync(clone, workspace, CHANGE)

    assert synced.copied == [(REVIEWS / "02-validation.md").as_posix(), named]
    assert synced.absent == [] and synced.refused == []
    assert not (workspace / unnamed).exists()
    assert history.differences(clone, workspace, CHANGE) == []


def test_what_lies_beside_a_validated_trees_evidence_but_no_pattern_describes_is_not_copied(
        workspace: Path, clone: Path) -> None:
    """CW-hak6: a validated tree's evidence is what its kinds' patterns match, each
    attempt with its logs, not everything under the directory its identity names."""
    _history(clone)
    # A retired kind's attempt, a stray file, and a file in a kind's directory
    # outside any attempt, all under the validated tree.
    strays = [BY_TREE / "retired/20261117T1003Z/summary.json", BY_TREE / "notes.txt",
              BY_TREE / "local/notes.txt"]
    for stray in strays:
        _write(clone, stray, "stray\n")

    synced = history.sync(clone, workspace, CHANGE)

    assert (BY_TREE / "helm/20261117T1003Z/test.log").as_posix() in synced.copied
    for stray in strays:
        assert not (workspace / stray).exists()
    assert synced.absent == [] and synced.refused == []


def test_a_pattern_matching_a_directory_copies_it_and_nothing_beside_it(
        workspace: Path, clone: Path) -> None:
    attempt = BY_TREE / "local/run-20261117T1003Z"
    _write(clone, REVIEWS / "02-validation.md", VALIDATION_RECORD)
    for name in (attempt / "summary.json", attempt / "test.log", BY_TREE / "local/notes.txt"):
        _write(clone, name, "{}\n")
    (clone / ".agents/workflow.toml").write_text(
        ACCEPTED + _kind("local", ".snapshot/evidence/{tree}/local/run-*"), "utf-8")

    synced = history.sync(clone, workspace, CHANGE)

    assert synced.copied == [(REVIEWS / "02-validation.md").as_posix(),
                             (attempt / "summary.json").as_posix(),
                             (attempt / "test.log").as_posix()]
    assert not (workspace / BY_TREE / "local/notes.txt").exists()
    assert synced.absent == [] and synced.refused == []


def test_a_kinds_evidence_in_a_directory_another_kind_reaches_is_copied_alone(
        workspace: Path, clone: Path) -> None:
    """A file one kind keys directly in the tree's directory, where another kind's
    attempts also lie, is copied without the directory holding it."""
    report = BY_TREE / "report.json"
    attempt = BY_TREE / "local/20261117T1003Z"
    _write(clone, REVIEWS / "02-validation.md", VALIDATION_RECORD)
    for name in (report, attempt / "summary.json", attempt / "test.log", BY_TREE / "notes.txt"):
        _write(clone, name, "{}\n")
    _write(clone, ".agents/evidence/report.md", "# The report kind\n")
    (clone / ".agents/workflow.toml").write_text(
        ACCEPTED + _kind("report", ".snapshot/evidence/{tree}/report.json")
        + _kind("local", ".snapshot/evidence/{tree}/local/*/summary.json"), "utf-8")

    synced = history.sync(clone, workspace, CHANGE)

    assert synced.copied == [(REVIEWS / "02-validation.md").as_posix(),
                             (attempt / "summary.json").as_posix(),
                             (attempt / "test.log").as_posix(), report.as_posix()]
    assert not (workspace / BY_TREE / "notes.txt").exists()
    assert synced.absent == [] and synced.refused == []


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
    assert len(synced.unchanged) == 8 and synced.refused == []
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
    (clone / REVIEWS / "linked-directory").symlink_to(clone / BY_TREE)

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
    assert f"Into {workspace.resolve()}: 10 file(s) copied, 0 extended, 0 already there." in out
    assert (workspace / REVIEWS / "02-validation.md").is_file()


def test_the_command_fails_naming_each_refusal(
        workspace: Path, clone: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _history(clone)
    _write(workspace, REVIEWS / "01-implementation.md", "# The owner's own copy\n")

    assert history.main(["sync", CHANGE], root=clone) == 1

    out, err = capsys.readouterr()
    assert "Refused, the workspace's file left as it is:" in out
    assert f"{(REVIEWS / '01-implementation.md').as_posix()}: the workspace's copy" in out
    # The exit 1's reason is on standard error too, not only in the report.
    assert (f"ERROR: not copied, the workspace's file left as it is: "
            f"{(REVIEWS / '01-implementation.md').as_posix()}: the workspace's copy") in err


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
