"""Evidence, `change_workflow.evidence`: the tree and commit it describes, and which of
it a change's `HEAD` still lacks.

Library integration throughout: a real temporary Git repository, its identities
read by Git itself, its evidence files written where a kind's pattern finds them.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from change_workflow import evidence
from change_workflow.cli import main
from change_workflow.next_step import TASKS_FILE
from change_workflow_fixtures import CHANGE, configured, evidence_kind

KINDS = (evidence_kind("pipeline", identity="commit", start="true", collect="true")
         + evidence_kind("ci", required="owed", identity="commit", start="true",
                         collect="true")
         + evidence_kind("local", run="true")
         + evidence_kind("helm", run="true", after="local"))
TASKS = "# Tasks\n\n## 1. A section\n\n- [x] 1.1 Done.\n\n## 2. Closeout\n\n- [ ] 2.1 Archive.\n"


def _git(root: Path, *arguments: str) -> str:
    return subprocess.run(["git", *arguments], cwd=root, check=True, capture_output=True,
                          text=True).stdout.strip()


@pytest.fixture
def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A Git repository whose one commit holds a module, a document, the change's
    task list, and a configuration of four kinds; `.snapshot/` is ignored."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "test")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "test@example.invalid")
    root = tmp_path / "repository"
    root.mkdir()
    _git(root, "init", "-q", "-b", "feat/x")
    configured(root, KINDS)
    for path, text in (("src/module.py", "x = 1\n"), ("docs/guide.md", "# Guide\n"),
                       (f"openspec/changes/{CHANGE}/{TASKS_FILE}", TASKS)):
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text, "utf-8")
    _git(root, "add", "--all")
    _git(root, "commit", "-q", "-m", "start")
    return root


def _write(root: Path, relative: str, text: str = '{"passed": true}\n') -> str:
    (root / relative).parent.mkdir(parents=True, exist_ok=True)
    (root / relative).write_text(text, "utf-8")
    return relative


def _owing(root: Path, *lines: str) -> None:
    """The change's first section, complete, owing each of `lines`; committed."""
    owed = "".join(f"  {line}\n" for line in lines)
    (root / f"openspec/changes/{CHANGE}/{TASKS_FILE}").write_text(
        TASKS.replace("- [x] 1.1 Done.\n", f"- [x] 1.1 Done.\n{owed}"), "utf-8")
    _git(root, "commit", "-q", "-am", "owe")


def _entries(root: Path) -> dict[str, dict]:
    shown = evidence.change_report(root, CHANGE)
    return {evidence.label(entry): entry for entry in shown.entries}


# The tree: the worktree as tested, through a temporary index.

def test_a_clean_worktrees_tree_is_heads(repository: Path) -> None:
    assert evidence.worktree_tree(repository) == _git(repository, "rev-parse", "HEAD^{tree}")


def test_a_dirty_worktrees_tree_is_the_tree_its_commit_then_holds(repository: Path) -> None:
    """CW-t3ev: staged, unstaged, and untracked changes, a deletion among them, are
    the tree the commit then made of exactly those changes holds."""
    (repository / "src/module.py").write_text("x = 2\n", "utf-8")
    _git(repository, "add", "src/module.py")
    (repository / "src/module.py").write_text("x = 3\n", "utf-8")
    (repository / "src/new.py").write_text("y = 1\n", "utf-8")
    (repository / "docs/guide.md").unlink()

    tree = evidence.worktree_tree(repository)
    _git(repository, "add", "--all")
    _git(repository, "commit", "-q", "-m", "the changes tested")

    assert tree == _git(repository, "rev-parse", "HEAD^{tree}")


def test_an_ignored_file_changes_no_tree(repository: Path) -> None:
    """CW-g1gn: evidence written under an ignored directory never changes the tree it
    describes."""
    head = _git(repository, "rev-parse", "HEAD^{tree}")
    _write(repository, f".snapshot/evidence/{head}/local/20261117T1003Z/summary.json")

    assert evidence.worktree_tree(repository) == head


def test_the_checkouts_index_is_left_as_it_was(repository: Path) -> None:
    (repository / "src/module.py").write_text("x = 2\n", "utf-8")
    _git(repository, "add", "src/module.py")
    (repository / "src/new.py").write_text("y = 1\n", "utf-8")
    index = repository / ".git/index"
    before = (index.read_bytes(), _git(repository, "status", "--porcelain"))

    evidence.worktree_tree(repository)

    assert (index.read_bytes(), _git(repository, "status", "--porcelain")) == before


# The report: each kind's requirement, pattern, and evidence for HEAD.

def test_only_local_evidence_exists(repository: Path) -> None:
    """CW-e2vd: `local` present with its path, every other required kind missing,
    and the owed kind not required while no complete section owes it."""
    tree = _git(repository, "rev-parse", "HEAD^{tree}")
    path = _write(repository, f".snapshot/evidence/{tree}/local/20261117T1003Z/summary.json")

    entries = _entries(repository)

    assert {name: entry["status"] for name, entry in entries.items()} == {
        "pipeline": "missing", "ci": "not required", "local": "present", "helm": "missing"}
    assert (entries["local"]["matches"], entries["local"]["current"]) == ([path], path)
    assert entries["local"]["pattern"] == f".snapshot/evidence/{tree}/local/*/summary.json"
    assert entries["pipeline"]["identity"] == "commit"


def test_a_rerun_beside_a_failed_attempt(repository: Path) -> None:
    """CW-e2vd: both attempts listed, the later in path order current."""
    tree = _git(repository, "rev-parse", "HEAD^{tree}")
    failed = _write(repository, f".snapshot/evidence/{tree}/helm/20261117T1003Z/summary.json",
                    '{"passed": false}\n')
    rerun = _write(repository, f".snapshot/evidence/{tree}/helm/20261117T1140Z/summary.json")

    helm = _entries(repository)["helm"]

    assert (helm["status"], helm["matches"], helm["current"]) == ("present", [failed, rerun],
                                                                  rerun)


def test_two_workflows_are_owed_and_one_has_evidence(repository: Path) -> None:
    """CW-r5qk: each owed argument's evidence is its own."""
    _owing(repository, "Owed by validation (ci tests.yml): job `py` — passes",
           "Owed by validation (ci docker.yml): job `build` — builds")
    commit = _git(repository, "rev-parse", "HEAD")
    _write(repository, f".snapshot/evidence/{commit}/ci-tests.yml/20261117T1003Z/summary.json")

    entries = _entries(repository)

    assert (entries["ci tests.yml"]["status"], entries["ci docker.yml"]["status"]) == (
        "present", "missing")
    assert entries["ci docker.yml"]["sections"] == ["1"]
    assert "ci" not in entries


def test_a_section_owes_the_pipeline(repository: Path) -> None:
    """CW-r5qk: a repository owing its pipeline names it by the workflow dispatching
    it, and `evidence` lists it required for that section."""
    configured(repository, KINDS.replace('[validation.evidence.pipeline]\nrequired = "always"',
                                         '[validation.evidence.pipeline]\nrequired = "owed"')
               .replace("{commit}/pipeline/", "{commit}/pipeline-{owed}/"))
    _owing(repository, "Owed by validation (pipeline e2e.yml): scenario "
                       "test_spot_deal_settles passes")

    entries = _entries(repository)

    assert (entries["pipeline e2e.yml"]["requirement"], entries["pipeline e2e.yml"]["status"],
            entries["pipeline e2e.yml"]["sections"]) == ("owed", "missing", ["1"])


def test_an_owed_argument_climbing_out_of_its_directory_is_reported_refused(
        repository: Path) -> None:
    """CW-r5qk: `evidence` reports the refusal rather than a kind present or
    missing."""
    _owing(repository, "Owed by validation (ci ..): job lint — passes")

    (ci,) = [entry for entry in evidence.change_report(repository, CHANGE).entries
             if entry["kind"] == "ci"]

    assert ci["status"] == "refused"
    assert "section 1's owed line names '..'" in ci["refusal"]
    assert "matches" not in ci


def test_a_line_owing_a_kind_owed_always_is_refused_apart_from_that_kind(
        repository: Path) -> None:
    """A refused line naming a kind that is not owed is listed after every kind, under
    no kind, so the kind's own entry keeps its requirement."""
    _owing(repository, "Owed by validation (local x.yml): job lint — passes")

    entries = evidence.change_report(repository, CHANGE).entries

    assert [(entry["kind"], entry["requirement"], entry["status"]) for entry in entries] == [
        ("pipeline", "always", "missing"), ("ci", "not required", "not required"),
        ("local", "always", "missing"), ("helm", "always", "missing"),
        (None, "owed", "refused")]
    assert "names 'local', which is no evidence kind" in entries[-1]["refusal"]
    assert evidence.label(entries[-1]) == "owed line"


def test_a_commit_amended_only_in_its_message(repository: Path) -> None:
    """CW-t3ev and MCW-r4tx: tree kinds stay present; the commit kind is missing for
    the amended commit."""
    tree, commit = (_git(repository, "rev-parse", "HEAD^{tree}"),
                    _git(repository, "rev-parse", "HEAD"))
    _write(repository, f".snapshot/evidence/{tree}/local/20261117T1003Z/summary.json")
    _write(repository, f".snapshot/evidence/{commit}/pipeline/20261117T1003Z/summary.json")
    assert _entries(repository)["pipeline"]["status"] == "present"

    _git(repository, "commit", "-q", "--amend", "-m", "start, reworded")

    entries = _entries(repository)
    assert _git(repository, "rev-parse", "HEAD^{tree}") == tree
    assert (entries["local"]["status"], entries["pipeline"]["status"]) == ("present", "missing")


def test_evidence_only_for_an_earlier_commits_tree(repository: Path) -> None:
    """CW-zkhs: it is not evidence of the validated commit, and the kind is
    missing."""
    earlier = _git(repository, "rev-parse", "HEAD^{tree}")
    _write(repository, f".snapshot/evidence/{earlier}/local/20261117T1003Z/summary.json")
    (repository / "src/module.py").write_text("x = 2\n", "utf-8")
    _git(repository, "commit", "-q", "-am", "change the module")

    assert _entries(repository)["local"]["status"] == "missing"


def test_evidence_placed_from_beyond_the_checkout_is_present(repository: Path) -> None:
    """CW-p4rs: whatever wrote the file at the pattern, it counts."""
    commit = _git(repository, "rev-parse", "HEAD")
    _write(repository, f".snapshot/evidence/{commit}/pipeline/external-topology/summary.json")

    assert _entries(repository)["pipeline"]["status"] == "present"


def test_a_waived_kind_names_the_owners_decision(repository: Path,
                                                 capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["note", CHANGE, "orchestrator", "--by", "owner", "--waives", "helm",
                 "--decision", "waive helm while no chart changes", "--reason", "r"],
                root=repository) == 0
    seq = json.loads(capsys.readouterr().out)["seq"]

    helm = _entries(repository)["helm"]

    assert (helm["status"], helm["waived"]) == (
        "waived", {"seq": seq, "decision": "waive helm while no chart changes"})


def test_the_command_reports_as_lines_and_as_json(repository: Path,
                                                  capsys: pytest.CaptureFixture[str]) -> None:
    tree, commit = (_git(repository, "rev-parse", "HEAD^{tree}"),
                    _git(repository, "rev-parse", "HEAD"))
    path = _write(repository, f".snapshot/evidence/{tree}/local/20261117T1003Z/summary.json")

    assert main(["evidence", CHANGE], root=repository) == 0
    lines = capsys.readouterr().out.splitlines()
    assert main(["evidence", CHANGE, "--json"], root=repository) == 0
    shown = json.loads(capsys.readouterr().out)

    assert lines[:2] == [f"tree     {tree}", f"commit   {commit}"]
    assert any(line.split()[:2] == ["local", "present"] for line in lines)
    assert f"    {path}   current" in lines
    assert (shown["tree"], shown["commit"]) == (tree, commit)
    assert [entry["kind"] for entry in shown["kinds"]] == ["pipeline", "ci", "local", "helm"]


def test_the_command_refuses_a_repository_with_no_kinds(repository: Path,
                                                        capsys: pytest.CaptureFixture[str]
                                                        ) -> None:
    configured(repository, "[hooks]\npre-commit = 'true'\n")

    assert main(["evidence", CHANGE], root=repository) == 1

    assert "the evidence report needs validation.evidence" in capsys.readouterr().err
