"""The gathering, `change_workflow.gather`: what it gathers, in what order, and what it
leaves alone.

Library integration: a real temporary Git repository, its evidence read by
`evidence` as validation reads it, and each kind's commands real shell commands
that write their evidence at the kind's pattern and note that they ran. The guarded
push, and in most tests the reading of a merge's lapse, are doubled at the
gathering's seams. One test reads this repository's own configuration, its commands
doubled at the hook runner's shell, since they build and deploy.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from change_workflow import config, evidence
from change_workflow.cli import main
from change_workflow.common import SESSION_ID
from change_workflow.evidence import merge_lapse
from change_workflow.gather import Gathering
from change_workflow.hooks import HookError, Hooks
from change_workflow.log import log_path, read_log
from change_workflow.next_step import TASKS_FILE
from change_workflow.running import invocations_directory, kept_invocations
from change_workflow_fixtures import CHANGE, configured, evidence_kind

UNATTENDED = "CHANGE_WORKFLOW_UNATTENDED"
REPOSITORY = Path(__file__).resolve().parents[2]


def _writes(kind: str, attempt: str = "20261117T1003Z", owed: bool = False,
            identity: str = "tree", passed: bool = True) -> str:
    """A shell command writing one attempt of `kind` at its pattern."""
    directory = (f".snapshot/evidence/{{{identity}}}/{kind}"
                 + ("-{owed}" if owed else "") + f"/{attempt}")
    return (f"mkdir -p {directory} && "
            f"echo '{{\"passed\": {json.dumps(passed)}}}' > {directory}/summary.json")


KINDS = ("[validation]\npreflight = \"echo preflight >> ../ran.log\"\n\n"
         + evidence_kind("pipeline", identity="commit",
                         start="echo pipeline-start >> ../ran.log; echo 40733870392",
                         collect="echo pipeline-collect {after} >> ../ran.log; "
                                 + _writes("pipeline", identity="commit"))
         + evidence_kind("ci", required="owed", identity="commit",
                         start="echo ci-start {owed} >> ../ran.log; echo run-{owed}",
                         collect="echo ci-collect {owed} {after} >> ../ran.log; "
                                 + _writes("ci", owed=True, identity="commit"))
         + evidence_kind("local", run="echo local >> ../ran.log; " + _writes("local"))
         + evidence_kind("helm", after="local",
                         run="echo helm >> ../ran.log; " + _writes("helm")))
TASKS = "# Tasks\n\n## 1. A section\n\n- [x] 1.1 Done.\n\n## 2. Closeout\n\n- [ ] 2.1 Archive.\n"


def _git(root: Path, *arguments: str) -> str:
    return subprocess.run(["git", *arguments], cwd=root, check=True, capture_output=True,
                          text=True).stdout.strip()


@pytest.fixture
def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A Git repository whose one commit holds a module, the change's task list, and
    a configuration of four kinds; `.snapshot/` and the change's records ignored."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "test")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "test@example.invalid")
    root = tmp_path / "repository"
    root.mkdir()
    _git(root, "init", "-q", "-b", "feat/x")
    configured(root, KINDS)
    with (root / ".git/info/exclude").open("a", encoding="utf-8") as exclude:
        exclude.write("/openspec/changes/*/reviews/\n")
    for path, text in (("src/module.py", "x = 1\n"),
                       (f"openspec/changes/{CHANGE}/{TASKS_FILE}", TASKS)):
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text, "utf-8")
    _git(root, "add", "--all")
    _git(root, "commit", "-q", "-m", "start")
    return root


def _owing(root: Path, *arguments: str) -> None:
    lines = "".join(f"  Owed by validation (ci {argument}): job `x` — passes\n"
                    for argument in arguments)
    (root / f"openspec/changes/{CHANGE}/{TASKS_FILE}").write_text(
        TASKS.replace("- [x] 1.1 Done.\n", f"- [x] 1.1 Done.\n{lines}"), "utf-8")
    _git(root, "commit", "-q", "-am", "owe")


def _gathering(root: Path, pushed: int = 0, lapse: str | None = None,
               echoed: list[str] | None = None, step: str = "validate") -> Gathering:
    configuration = config.load(root)
    hooks = Hooks(root, configuration, {UNATTENDED: step},
                  echo=echoed.append if echoed is not None else lambda _: None)
    return Gathering(hooks, CHANGE, None, push=lambda: pushed,
                     report=lambda: evidence.change_report(
                         root, CHANGE, configuration,
                         (lambda kind, waiver: lapse) if lapse is not None else None))


def _reconfigured(root: Path, text: str) -> None:
    """`root`'s configuration replaced by `text`, committed, so the worktree is
    `HEAD`'s as a gathering needs."""
    configured(root, text)
    _git(root, "commit", "-q", "-am", "reconfigure")


def _ran(root: Path) -> list[str]:
    log = root.parent / "ran.log"
    return log.read_text("utf-8").splitlines() if log.exists() else []


def _status(root: Path) -> dict[str, str]:
    return {evidence.label(entry): entry["status"]
            for entry in evidence.change_report(root, CHANGE).entries}


def _write(root: Path, relative: str, text: str = '{"passed": true}\n') -> None:
    (root / relative).parent.mkdir(parents=True, exist_ok=True)
    (root / relative).write_text(text, "utf-8")


# What `gather` gathers, in what order.

def test_the_gathering_starts_every_dispatch_then_runs_then_collects(repository: Path) -> None:
    """CW-g6th and MCW-r4tx's shape: the preflight, then each missing start, the owed
    argument among them, then the run kinds in order, then each collect waiting past
    its own start's marker; afterwards every kind is present."""
    _owing(repository, "tests.yml")

    assert _gathering(repository).missing()

    assert _ran(repository) == [
        "preflight", "pipeline-start", "ci-start tests.yml", "local", "helm",
        "pipeline-collect 40733870392", "ci-collect tests.yml run-tests.yml"]
    assert _status(repository) == {"pipeline": "present", "ci tests.yml": "present",
                                   "local": "present", "helm": "present"}


def test_a_long_kind_declared_before_a_dispatched_one(repository: Path) -> None:
    """CW-g4oz's scenario: `local`, a run kind, declared before `pipeline`; the
    gathering starts `pipeline` before it runs `local`."""
    text = (evidence_kind("local", run="echo local >> ../ran.log")
            + evidence_kind("pipeline", identity="commit",
                            start="echo pipeline-start >> ../ran.log; echo 7",
                            collect="echo pipeline-collect {after} >> ../ran.log"))
    _reconfigured(repository, text)

    _gathering(repository).missing()

    assert _ran(repository) == ["pipeline-start", "local", "pipeline-collect 7"]


def test_gathering_leaves_present_evidence_alone(repository: Path) -> None:
    """CW-g6th's scenario: `local` present and failing is not run again; validation
    diagnoses the present failure."""
    tree = _git(repository, "rev-parse", "HEAD^{tree}")
    failing = f".snapshot/evidence/{tree}/local/20261117T0900Z/summary.json"
    _write(repository, failing, '{"passed": false}\n')

    assert _gathering(repository).missing()

    assert "local" not in _ran(repository)
    assert "helm" in _ran(repository)
    local = next(entry for entry in evidence.change_report(repository, CHANGE).entries
                 if entry["kind"] == "local")
    assert (local["matches"], local["current"]) == ([failing], failing)


def test_two_owed_runs_are_collected_side_by_side(repository: Path) -> None:
    """CW-x9bt: each collect waits past its own start's marker."""
    _owing(repository, "ci.yml", "docker.yml")

    _gathering(repository).missing()

    assert [line for line in _ran(repository) if line.startswith("ci-")] == [
        "ci-start ci.yml", "ci-start docker.yml", "ci-collect ci.yml run-ci.yml",
        "ci-collect docker.yml run-docker.yml"]


def test_the_pipeline_is_collected_past_the_marker_its_start_printed(
        repository: Path) -> None:
    """CW-x9bt: the engine fills `{after}` with the start's last line, kept for the
    commit, the kind, and no argument."""
    commit = _git(repository, "rev-parse", "HEAD")

    _gathering(repository).missing()

    assert "pipeline-collect 40733870392" in _ran(repository)
    hooks = Hooks(repository, config.load(repository), {})
    assert hooks.kept_marker(CHANGE, f"{commit} pipeline") == "40733870392"


def test_each_kind_closes_with_its_line(repository: Path) -> None:
    """CW-x9bt: the kind, its argument, its identity, its result and exit status, and
    its evidence as it now stands."""
    _owing(repository, "tests.yml")
    tree, commit = (_git(repository, "rev-parse", "HEAD^{tree}"),
                    _git(repository, "rev-parse", "HEAD"))
    echoed: list[str] = []

    _gathering(repository, echoed=echoed).missing()

    closing = [line for line in echoed if line.startswith("[change-workflow] gather ")]
    assert (f"[change-workflow] gather local at tree {tree}: passed, exit 0; evidence "
            f".snapshot/evidence/{tree}/local/20261117T1003Z/summary.json") in closing
    assert (f"[change-workflow] gather ci tests.yml at commit {commit}: passed, exit 0; "
            f"evidence .snapshot/evidence/{commit}/ci-tests.yml/20261117T1003Z/summary.json"
            ) in closing
    assert f"[change-workflow] gather push at {commit}: passed, exit 0" in closing


def test_a_failing_kind_fails_the_gathering_and_the_rest_still_run(repository: Path) -> None:
    _reconfigured(repository, KINDS.replace('run = "echo local >> ../ran.log; ',
                                            'run = "echo local >> ../ran.log; exit 2; '))
    echoed: list[str] = []

    assert not _gathering(repository, echoed=echoed).missing()

    assert _ran(repository)[-3:] == ["local", "helm", "pipeline-collect 40733870392"]
    assert any(line.startswith("[change-workflow] gather local at tree ")
               and ": failed, exit 2: " in line and line.endswith("; evidence none")
               for line in echoed)


def test_a_refused_push_dispatches_nothing_and_still_runs_the_long_kinds(
        repository: Path) -> None:
    echoed: list[str] = []

    assert not _gathering(repository, pushed=1, echoed=echoed).missing()

    assert _ran(repository) == ["preflight", "local", "helm"]
    assert any("gather pipeline at commit" in line and "failed, exit 1: the guarded push"
               in line for line in echoed)


def test_only_validation_gathers(repository: Path) -> None:
    with pytest.raises(HookError, match="the implement step may not run gather"):
        _gathering(repository, step="implement").missing()


def test_a_worktree_that_is_not_heads_is_refused(repository: Path) -> None:
    """Evidence gathered on changes no commit holds would describe neither the tree
    `evidence` reads nor the commit."""
    (repository / "src/module.py").write_text("x = 2\n", "utf-8")

    with pytest.raises(HookError, match="the worktree's tree, [0-9a-f]+, is not HEAD's"):
        _gathering(repository).missing()
    assert _ran(repository) == []


def test_a_failed_preflight_gathers_nothing(repository: Path) -> None:
    _reconfigured(repository, KINDS.replace('preflight = "echo preflight >> ../ran.log"',
                                            'preflight = "echo preflight >> ../ran.log; '
                                            'exit 3"'))
    echoed: list[str] = []

    assert not _gathering(repository, echoed=echoed).missing()

    assert _ran(repository) == ["preflight"]
    assert echoed[-1] == "[change-workflow] gather: nothing gathered, since the preflight failed"


def test_an_absent_preflight_is_skipped_saying_so(repository: Path) -> None:
    _reconfigured(repository, KINDS.replace('preflight = "echo preflight >> ../ran.log"\n', ""))
    echoed: list[str] = []

    assert _gathering(repository, echoed=echoed).missing()

    commit = _git(repository, "rev-parse", "HEAD")
    assert f"[change-workflow] gather preflight at {commit}: skipped, not declared" in echoed
    assert _ran(repository)[0] == "pipeline-start"


# A start's marker: kept for its key, replaced by a later start, none for a failure.

COUNTED = evidence_kind(
    "pipeline", identity="commit",
    start="n=$(cat ../count 2>/dev/null || echo 0); n=$((n+1)); echo $n > ../count; "
          "echo marker-$n",
    collect="echo pipeline-collect {after} >> ../ran.log")


def test_a_later_start_replaces_its_marker(repository: Path) -> None:
    _reconfigured(repository, COUNTED)
    commit = _git(repository, "rev-parse", "HEAD")

    assert _gathering(repository).again("pipeline")
    assert _gathering(repository).again("pipeline")

    assert _ran(repository) == ["pipeline-collect marker-1", "pipeline-collect marker-2"]
    hooks = Hooks(repository, config.load(repository), {})
    assert hooks.kept_marker(CHANGE, f"{commit} pipeline") == "marker-2"


@pytest.mark.parametrize("start", ["echo 399; exit 1", "true"])
def test_a_start_that_failed_or_printed_nothing_keeps_no_marker_and_is_not_collected(
        repository: Path, start: str) -> None:
    _reconfigured(repository, evidence_kind(
        "pipeline", identity="commit", start=start,
        collect="echo pipeline-collect {after} >> ../ran.log"))
    commit = _git(repository, "rev-parse", "HEAD")
    echoed: list[str] = []

    passed = _gathering(repository, echoed=echoed).again("pipeline")

    hooks = Hooks(repository, config.load(repository), {})
    assert hooks.kept_marker(CHANGE, f"{commit} pipeline") is None
    if start == "true":
        # A start that printed nothing passes, and its collect is refused.
        assert not passed and _ran(repository) == []
        assert any("its collect was refused: no start of pipeline at" in line
                   for line in echoed)
    else:
        assert not passed and _ran(repository) == []
        assert any(line.startswith(f"[change-workflow] gather pipeline at commit {commit}: "
                                   "failed, exit 1: ") for line in echoed)


# Waivers: skipped unless lapsed.

def _waive(root: Path, kinds: str) -> None:
    assert main(["note", CHANGE, "orchestrator", "--by", "owner", "--waives", kinds,
                 "--decision", f"waive {kinds}", "--reason", "r"], root=root) == 0


def test_a_waived_kind_is_skipped_saying_so(repository: Path,
                                            capsys: pytest.CaptureFixture[str]) -> None:
    _waive(repository, "helm,pipeline")
    capsys.readouterr()
    echoed: list[str] = []

    assert _gathering(repository, echoed=echoed).missing()

    assert _ran(repository) == ["preflight", "local"]
    assert any(line.startswith("[change-workflow] gather helm: skipped, waived by the owner "
                               "at seq") for line in echoed)


def test_a_waiver_lapses_at_a_merge(repository: Path, capsys: pytest.CaptureFixture[str]
                                    ) -> None:
    """CW-e7lm: a merge lapses the waiver, and the gathering gathers the kind, its
    closing line and its invocation saying why."""
    _waive(repository, "helm")
    capsys.readouterr()
    echoed: list[str] = []
    gathering = _gathering(repository, lapse="the merge 1234 since helm last ran",
                           echoed=echoed)

    assert gathering.missing()

    assert "helm" in _ran(repository)
    helm = [i.entry() for i in gathering.hooks.invoked if i.kind == "helm"]
    assert helm[0]["lapsed"] == "the merge 1234 since helm last ran"
    assert any(line.startswith("[change-workflow] gather helm at tree ")
               and "passed, exit 0; the owner's waiver lapsed: the merge 1234 since helm "
                   "last ran; evidence " in line for line in echoed)


def test_a_lapsed_waiver_leaves_present_evidence_alone_saying_so(
        repository: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _waive(repository, "helm")
    capsys.readouterr()
    tree = _git(repository, "rev-parse", "HEAD^{tree}")
    _write(repository, f".snapshot/evidence/{tree}/helm/20261117T0900Z/summary.json")
    echoed: list[str] = []

    _gathering(repository, lapse="the merge 1234 since helm last ran", echoed=echoed).missing()

    assert "helm" not in _ran(repository)
    assert any(line.startswith("[change-workflow] gather helm: skipped, present; the owner's "
                               "waiver at seq") for line in echoed)


def _log(root: Path, *entries: dict) -> None:
    log = root / f"openspec/changes/{CHANGE}/reviews/workflow.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("".join(json.dumps(entry) + "\n" for entry in entries), "utf-8")


def _merged(root: Path) -> str:
    """A merge on the change's branch; its commit."""
    _git(root, "checkout", "-q", "-b", "other")
    (root / "src/other.py").write_text("y = 1\n", "utf-8")
    _git(root, "add", "--all")
    _git(root, "commit", "-q", "-m", "other")
    _git(root, "checkout", "-q", "feat/x")
    _git(root, "merge", "-q", "--no-ff", "-m", "merge other", "other")
    return _git(root, "rev-parse", "HEAD")


def _merged_again(root: Path) -> str:
    """A second merge on the change's branch; its commit."""
    _git(root, "checkout", "-q", "-b", "another")
    (root / "src/another.py").write_text("z = 1\n", "utf-8")
    _git(root, "add", "--all")
    _git(root, "commit", "-q", "-m", "another")
    _git(root, "checkout", "-q", "feat/x")
    _git(root, "merge", "-q", "--no-ff", "-m", "merge another", "another")
    return _git(root, "rev-parse", "HEAD")


def test_a_merge_since_a_kind_last_ran_is_read_from_the_log(repository: Path) -> None:
    """The kind last ran at the latest validation whose run invoked it, or the latest
    validation when none did; a merge since then lapses its waiver."""
    first = _git(repository, "rev-parse", "HEAD")
    _log(repository, {"seq": 1, "step": "validate", "commit": first,
                      "invoked": [{"hook": "gather", "kind": "helm"}]})
    assert merge_lapse(repository, CHANGE, "helm") is None

    merge = _merged(repository)
    later = _git(repository, "rev-parse", "HEAD")
    _log(repository, {"seq": 1, "step": "validate", "commit": first,
                      "invoked": [{"hook": "gather", "kind": "helm"}]},
         {"seq": 2, "step": "validate", "commit": later, "invoked": []})

    assert merge_lapse(repository, CHANGE, "helm") == (
        f"the merge {merge[:12]} since helm last ran, at {first[:12]}")
    assert merge_lapse(repository, CHANGE, "pipeline") is None
    # With no validation logged, no kind has run, and nothing lapses.
    _log(repository, {"seq": 1, "step": "design", "commit": first})
    assert merge_lapse(repository, CHANGE, "helm") is None


def test_a_commit_a_kind_last_ran_at_that_cannot_be_read_lapses_its_waiver(
        repository: Path) -> None:
    _log(repository, {"seq": 1, "step": "validate", "commit": "f" * 40})

    assert merge_lapse(repository, CHANGE, "helm") == (
        f"the commit helm last ran at, {'f' * 12}, cannot be read")


def test_a_merge_the_owner_waived_after_does_not_lapse_the_waiver(repository: Path) -> None:
    """A merge the waiver followed was the owner's to weigh: only a merge since both
    the kind's last run and the waiver lapses it."""
    first = _git(repository, "rev-parse", "HEAD")
    merge = _merged(repository)
    waiver = {"seq": 3, "by": "owner", "waives": ["helm"], "decision": "d",
              "commit": merge}
    _log(repository, {"seq": 1, "step": "validate", "commit": first,
                      "invoked": [{"hook": "gather", "kind": "helm"}]},
         {"seq": 2, "step": "validate", "commit": merge, "invoked": []}, waiver)

    assert merge_lapse(repository, CHANGE, "helm", waiver) is None

    later = _merged_again(repository)
    assert merge_lapse(repository, CHANGE, "helm", waiver) == (
        f"the merge {later[:12]} since helm last ran, at {first[:12]} and since the "
        "owner's waiver at seq 3")


def test_an_older_waiver_naming_no_commit_is_taken_at_the_line_before_it(
        repository: Path) -> None:
    first = _git(repository, "rev-parse", "HEAD")
    merge = _merged(repository)
    waiver = {"seq": 3, "by": "owner", "waives": ["helm"], "decision": "d"}
    _log(repository, {"seq": 1, "step": "validate", "commit": first,
                      "invoked": [{"hook": "gather", "kind": "helm"}]},
         {"seq": 2, "step": "validate", "commit": merge, "invoked": []}, waiver)

    assert merge_lapse(repository, CHANGE, "helm", waiver) is None


def test_a_waiver_records_the_commit_it_was_made_at(repository: Path) -> None:
    _waive(repository, "helm")

    line = read_log(log_path(repository, CHANGE))[-1]

    assert line["commit"] == _git(repository, "rev-parse", "HEAD")


def test_evidence_reports_a_lapsed_waivers_kind_as_required(
        repository: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A kind whose waiver a merge lapsed is missing or present as if unwaived, never
    `waived`, its entry naming the lapsed decision and why."""
    _log(repository, {"seq": 1, "step": "validate",
                      "commit": _git(repository, "rev-parse", "HEAD")})
    _waive(repository, "helm,pipeline")
    _merged(repository)

    helm = next(entry for entry in evidence.change_report(repository, CHANGE).entries
                if entry["kind"] == "helm")
    capsys.readouterr()
    main(["evidence", CHANGE], root=repository)
    shown = capsys.readouterr().out

    assert helm["status"] == "missing"
    assert helm["lapsed"]["seq"] == 2 and helm["lapsed"]["why"].startswith("the merge ")
    assert "waived by the owner" not in shown
    assert "the owner's waiver at seq 2 lapsed: the merge " in shown


def test_lapsed_gathers_a_kind_still_reported_waived(repository: Path) -> None:
    """The skill judges a waiver's condition: `--lapsed` gathers a kind whose waiver
    no merge lapsed."""
    _waive(repository, "helm")
    gathering = _gathering(repository)

    assert gathering.again("helm", lapsed=True)

    assert "helm" in _ran(repository)


def test_the_command_gathers_a_waived_kind_a_merge_lapsed(
        repository: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Through `cli.main`, the gathering reads the lapse from the log and Git."""
    _log(repository, {"seq": 1, "step": "validate", "commit": _git(repository, "rev-parse",
                                                                    "HEAD")})
    _waive(repository, "helm")
    _merged(repository)
    capsys.readouterr()

    main(["gather", CHANGE], root=repository, environ={UNATTENDED: "validate"})

    assert "helm" in _ran(repository)
    assert "the owner's waiver lapsed: the merge " in capsys.readouterr().out


# `gather --kind`: a new attempt, whatever is present.

def test_one_owed_workflow_is_rerun_after_an_environmental_failure(repository: Path) -> None:
    """CW-g6th's scenario: `--kind ci --owed docker.yml` starts and collects a new
    attempt of `docker.yml` alone, which `evidence` marks current."""
    _owing(repository, "tests.yml", "docker.yml")
    commit = _git(repository, "rev-parse", "HEAD")
    _write(repository, f".snapshot/evidence/{commit}/ci-tests.yml/20261117T0900Z/summary.json")
    lost = f".snapshot/evidence/{commit}/ci-docker.yml/20261117T0900Z/summary.json"
    _write(repository, lost, '{"passed": false, "runner": "lost"}\n')

    assert _gathering(repository).again("ci", "docker.yml")

    assert _ran(repository) == ["preflight", "ci-start docker.yml",
                                "ci-collect docker.yml run-docker.yml"]
    docker = next(entry for entry in evidence.change_report(repository, CHANGE).entries
                  if entry["owed"] == "docker.yml")
    rerun = f".snapshot/evidence/{commit}/ci-docker.yml/20261117T1003Z/summary.json"
    assert (docker["matches"], docker["current"]) == ([lost, rerun], rerun)


def test_a_kind_is_gathered_again_whatever_is_present(repository: Path) -> None:
    tree = _git(repository, "rev-parse", "HEAD^{tree}")
    _write(repository, f".snapshot/evidence/{tree}/local/20261117T0900Z/summary.json")

    assert _gathering(repository).again("local")

    assert _ran(repository) == ["preflight", "local"]


def test_a_waived_kind_is_refused_without_lapsed(repository: Path,
                                                 capsys: pytest.CaptureFixture[str]) -> None:
    _waive(repository, "helm")
    capsys.readouterr()

    with pytest.raises(HookError, match=r"helm is waived by the owner's decision at seq \d+: "
                                        "waive helm; gather it with --lapsed"):
        _gathering(repository).again("helm")
    gathering = _gathering(repository)
    assert gathering.again("helm", lapsed=True)
    assert _ran(repository) == ["preflight", "helm"]
    assert [i.entry().get("lapsed") for i in gathering.hooks.invoked if i.kind == "helm"] == [
        "gathered with --lapsed"]


@pytest.mark.parametrize("kind,owed,lapsed,refused", [
    ("local", "x.yml", False, "local is not owed, so it takes no --owed"),
    ("ci", "other.yml", False, "no complete section owes ci other.yml; owed: tests.yml"),
    ("local", None, True, "--lapsed gathers a waived kind, and no owner's decision waives "
                          "local"),
    ("smoke", None, False, "declares no evidence kind 'smoke'"),
])
def test_a_new_attempt_is_refused_naming_why(repository: Path, kind: str, owed: str | None,
                                             lapsed: bool, refused: str) -> None:
    _owing(repository, "tests.yml")

    # The hook runner refuses an attempt; the configuration, a kind it does not declare.
    with pytest.raises((HookError, config.ConfigError), match=refused):
        _gathering(repository).again(kind, owed, lapsed)
    assert _ran(repository) == []


def test_an_owed_kind_no_section_owes_has_nothing_to_gather(repository: Path) -> None:
    with pytest.raises(HookError, match="no complete section owes ci"):
        _gathering(repository).again("ci")


# The command.

def test_the_command_gathers_and_keeps_what_it_ran(repository: Path,
                                                   capsys: pytest.CaptureFixture[str]) -> None:
    """Through `cli.main`, a real `sh`: `--owed` and `--lapsed` need `--kind`, and
    `gather --kind` exits 0 when everything it ran passed, keeping each command it
    ran for the session's line."""
    assert main(["gather", CHANGE, "--owed", "x.yml"], root=repository, environ={}) == 2
    assert main(["gather", CHANGE, "--lapsed"], root=repository, environ={}) == 2

    assert main(["gather", CHANGE, "--kind", "local"], root=repository,
                environ={UNATTENDED: "validate", SESSION_ID: "s-1"}) == 0

    assert _ran(repository) == ["preflight", "local"]
    assert "[change-workflow] gather local at tree " in capsys.readouterr().out
    kept = kept_invocations(invocations_directory(repository), "s-1", CHANGE)
    assert [(entry["hook"], entry.get("kind"), entry.get("phase")) for entry in kept] == [
        ("gather", None, "preflight"), ("gather", "local", "run")]


def test_validation_gathers_this_repositorys_kinds(tmp_path: Path) -> None:
    """MCW-r4tx: with a complete section owing `tests.yml` and nothing present, this
    repository's own configuration starts the pipeline and the owed CI run, then runs
    the local kind, then the Helm kind after it, then collects."""
    root = tmp_path / "repository"
    root.mkdir()
    _git(root, "init", "-q", "-b", "feat/x")
    configured(root, (REPOSITORY / config.CONFIGURATION).read_text("utf-8"))
    (root / f"openspec/changes/{CHANGE}").mkdir(parents=True)
    (root / f"openspec/changes/{CHANGE}/{TASKS_FILE}").write_text(
        "## 1. A section\n\n- [x] 1.1 Done.\n  - Owed by validation (ci tests.yml): job `py`, "
        "its suite passing.\n", "utf-8")
    _git(root, "add", "--all")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q",
         "-m", "start")
    ran: list[str] = []
    configuration = config.load(root)
    hooks = Hooks(root, configuration, {UNATTENDED: "validate"}, echo=lambda _: None,
                  shell=lambda command, _: ran.append(command) or 0,
                  capture=lambda command, _: (ran.append(command) or 0, "1"))
    gathering = Gathering(hooks, CHANGE, None, push=lambda: 0,
                          report=lambda: evidence.change_report(root, CHANGE, configuration))

    assert gathering.missing()

    assert [command.split()[1] for command in ran] == [
        "check-uv-version", "run-e2e", "run-ci", "validate-local", "validate-helm",
        "fetch-e2e-logs", "validate-ci"]

