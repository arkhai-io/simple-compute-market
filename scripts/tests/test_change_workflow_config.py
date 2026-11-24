"""The repository's workflow configuration, `change_workflow.config`: its check, its
fields' kinds, its evidence kinds, how they resolved, and a step's documents."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

from change_workflow import config, documents
from change_workflow.cli import main
from change_workflow.common import StepError
from change_workflow.config import ConfigError
from change_workflow.harness import Model
from change_workflow.scope import REPOSITORY as REPOSITORY_SOURCE
from change_workflow.scope import Scope, within
from change_workflow_fixtures import (ACCEPTED, CHANGE, CONFIGURED, LOCAL_CONFIGURED, MODELS,
                                      OPUS, SONNET, VALID, FakeClaude, as_installed,
                                      configuration_checked,
                                      configured, event_lines, evidence_kind, make_wrapper)

REPOSITORY = Path(__file__).resolve().parents[2]
# The workflow's own guidance, which `config load` prints after the engineering
# guidance and before the repository's documents, whole outside this checkout.
WORKFLOW_GUIDANCE = [str(path) for path in
                     sorted(documents.path(documents.GUIDANCE).rglob("*.md"))]


def _checked(text: str) -> config.Configuration:
    return configuration_checked(text, Path("workflow.toml"))


def _models_checked(models: str) -> config.Configuration:
    """`models`, a local configuration's tables, checked beside the least committed
    configuration."""
    return config.check(ACCEPTED, Path("workflow.toml"), local=models)


def _every_directory_ignored(root: Path, directories: list[str]) -> list[str]:
    return []


def _kinds_checked(root: Path, text: str,
                   unignored: config.Unignored = _every_directory_ignored
                   ) -> config.Configuration:
    """`text` checked as the configuration of a repository at `root` holding every
    test kind's guide, Git's ignoring doubled by `unignored`."""
    configured(root, text)
    return configuration_checked(text, root / config.CONFIGURATION, unignored=unignored)


# This repository's four kinds, in the shape its configuration declares them.
FOUR_KINDS = ("[validation]\npreflight = \"make check-uv-version\"\n\n"
              + evidence_kind("pipeline", identity="commit", start="make run-e2e",
                              collect="make fetch-e2e-logs AFTER={after} COMMIT={commit}")
              + evidence_kind("ci", required="owed", identity="commit",
                              start="make run-ci WORKFLOW={owed}",
                              collect="make validate-ci WORKFLOW={owed} AFTER={after}")
              + evidence_kind("local", run="make validate-local TREE={tree}")
              + evidence_kind("helm", run="make validate-helm CHANGE={change} TREE={tree}",
                              after="local", cleanup="make teardown CHANGE={change}"))


# Every refusal names the field it found.

@pytest.mark.parametrize("text,named", [
    ("[hook]\npre-commit = 'x'\n", "hook is no table the workflow defines"),
    ("[hooks]\npre-comit = 'x'\n", "hooks.pre-comit is no field the workflow defines"),
    ("[repository]\nprotected = ['main']\n", "repository.protected is no field"),
    ("[repository]\nprotected-branches = 'main'\n", "repository.protected-branches must be a "
                                                    "list"),
    ("[hooks]\npre-commit = 3\n", "hooks.pre-commit must be a command or a list"),
    ("[hooks]\npre-commit = ['make x', '']\n", "hooks.pre-commit must be a command"),
    ("[load]\ncommon = 'AGENTS.md'\n", "load.common must be a list"),
    ("[load]\ndeploy = ['x.md']\n", "load.deploy is no field"),
    ("[openspec]\ncommand = ['openspec']\n", "openspec.command must be a non-empty string"),
    # Models and the pointer are the local configuration's.
    ("[models]\nimplement = [{ harness = 'claude', model = 'm' }]\n",
     ".agents/workflow.toml declares [models], which belongs in .agents/workflow.local.toml"),
    ("[guidance]\nengineering = { none = 'x' }\n",
     ".agents/workflow.toml declares [guidance], which belongs in .agents/workflow.local.toml"),
    # Validation's kinds are under `evidence`; `parts` is no field the workflow defines.
    ("[validation.parts.local]\nrun = 'a'\n", "validation.parts is no field the workflow "
                                              "defines; validation takes preflight, evidence"),
    ("[defaults]\ndisable = [{ check = 'lint', reason = 'r' }]\n",
     "defaults.disable[0] names 'lint', which is no default check"),
    ("[defaults]\ndisable = [{ check = 'skills', reason = ' ' }]\n",
     "defaults.disable[0] turns off skills without a reason"),
    ("[defaults]\ndisable = ['skills']\n", "defaults.disable[0] must be a table naming a check"),
    ("[hooks]\npre-commit = 'make {target}'\n",
     "hooks.pre-commit names {target}, which is no placeholder the workflow fills"),
    ("[hooks]\npre-commit = 'make CHANGE={change} REMOTE={remote}'\n",
     "hooks.pre-commit names {remote}, which is not available there"),
    # The guarded push pushes a branch, not a change: it has the remote alone.
    ("[hooks]\npre-push = 'make pre-push REMOTE={remote} CHANGE={change}'\n",
     "hooks.pre-push names {change}, which is not available there"),
    ("[hooks]\npre-push = ['make pre-push BASE={base}']\n",
     "hooks.pre-push names {base}, which is not available there"),
    # The tree and the commit are the functional hooks' and a kind's alone.
    ("[hooks]\npre-commit = 'make check TREE={tree}'\n",
     "hooks.pre-commit names {tree}, which is not available there"),
    ("[hooks]\npre-archive = 'make check COMMIT={commit}'\n",
     "hooks.pre-archive names {commit}, which is not available there"),
    # A step hook takes its run's inputs; a review's and a triage's also its kind.
    ("[hooks]\npre-commit = 'make check INPUTS={inputs}'\n",
     "hooks.pre-commit names {inputs}, which is not available there"),
    ("[hooks]\nbefore-implement = 'make refresh KIND={kind}'\n",
     "hooks.before-implement names {kind}, which is not available there"),
    ("[hooks]\nafter-validate = 'make report TREE={tree}'\n",
     "hooks.after-validate names {tree}, which is not available there"),
    # A step hook names a step a run is logged as; a round is no step.
    ("[hooks]\nbefore-round = 'make x'\n",
     "hooks.before-round names no step; a step hook is before- or after- one of: "),
    ("[hooks]\nafter-implementation = 'make x'\n", "hooks.after-implementation names no step"),
    ("[openspec]\ncommand = 'bunx openspec@{change}'\n",
     "openspec.command names {change}, which is not available there"),
    ("[hooks\n", "is not TOML"),
    ("[review]\nformat-retries = -1\n", "review.format-retries must be a whole number"),
    ("[review]\nformat-retries = true\n", "review.format-retries must be a whole number"),
    ("[review]\nformat-retries = '1'\n", "review.format-retries must be a whole number"),
    ("[review]\nretries = 1\n", "review.retries is no field the workflow defines"),
])
def test_a_malformed_configuration_is_refused_naming_the_field(text: str, named: str) -> None:
    with pytest.raises(ConfigError) as refused:
        _checked(text)
    assert named in str(refused.value)


# An evidence kind: what the engine reads of it, refused naming the field.

def test_a_four_kind_configuration_is_read(tmp_path: Path) -> None:
    """CW-g4oz: each kind's requirement, pattern, shape, `after`, cleanup, and guide,
    in declaration order, the identity its pattern keys read from the pattern."""
    checked = _kinds_checked(tmp_path, FOUR_KINDS)

    assert [(kind.name, kind.required, kind.identity, kind.shape, kind.after)
            for kind in checked.kinds or ()] == [
        ("pipeline", "always", "commit", "start, collect", None),
        ("ci", "owed", "commit", "start, collect", None),
        ("local", "always", "tree", "run", None),
        ("helm", "always", "tree", "run", "local")]
    helm = checked.kind("helm")
    assert helm.evidence == ".snapshot/evidence/{tree}/helm/*/summary.json"
    assert (helm.guide, helm.cleanup) == (".agents/evidence/helm.md",
                                          ("make teardown CHANGE={change}",))
    assert checked.kind("ci").owed and not helm.owed
    assert checked.evidence() == [".snapshot/evidence/"]
    assert checked.preflight == ("make check-uv-version",)


@pytest.mark.parametrize("pattern,directory", [
    (".snapshot/evidence/{tree}/local/*/summary.json", ".snapshot/evidence/"),
    (".snapshot/evidence/{commit}/ci-{owed}/*/summary.json", ".snapshot/evidence/"),
    ("out/{tree}.json", "out/"),
    ("out/run-*/{tree}/x.json", "out/"),
    ("{tree}/x.json", ""),
])
def test_a_patterns_fixed_directory_ends_at_its_first_unfixed_segment(pattern: str,
                                                                      directory: str) -> None:
    assert config.fixed_directory(pattern) == directory


def _without(text: str, line: str) -> str:
    return "\n".join(kept for kept in text.splitlines() if not kept.startswith(line)) + "\n"


@pytest.mark.parametrize("text,named", [
    # An undefined key, and a wrong type.
    (evidence_kind("local", run="a", retries="2"),
     "validation.evidence.local.retries is no field the workflow defines"),
    (evidence_kind("local", run=3), "validation.evidence.local.run must be a command"),
    ("[validation]\nevidence = 'local'\n", "validation.evidence must be a table of evidence "
                                           "kinds"),
    # The requirement, always or owed.
    (evidence_kind("local", required="sometimes", run="a"),
     "validation.evidence.local.required must be one of always, owed; got 'sometimes'"),
    (_without(evidence_kind("local", run="a"), "required"),
     "validation.evidence.local.required must be one of always, owed; got None"),
    # `run`, or `start` and `collect`.
    (evidence_kind("local"), "validation.evidence.local declares `run`, or `start` and "
                             "`collect`, and not both shapes; it declares neither"),
    (evidence_kind("local", run="a", start="b", collect="c"), "it declares run, start, collect"),
    (evidence_kind("pipeline", start="b"), "validation.evidence.pipeline declares `run`, or "
                                           "`start` and `collect`, and not both shapes; it "
                                           "declares start"),
    (evidence_kind("local", run=[]), "validation.evidence.local.run must name a command"),
    # An `after` validation could keep: an earlier kind, a dispatch never after a long
    # kind; declaration order also refuses every cycle.
    (evidence_kind("helm", run="a", after="local"),
     "validation.evidence.helm.after names 'local', which is no other declared kind"),
    (evidence_kind("helm", run="a", after="helm"), "which is no other declared kind"),
    (evidence_kind("helm", run="a", after="local") + evidence_kind("local", run="b"),
     "validation.evidence.helm.after names 'local', which is declared after it"),
    (evidence_kind("local", run="a") + evidence_kind("pipeline", start="b", collect="c",
                                                     after="local"),
     "validation.evidence.pipeline.after names 'local', a `run` kind, but every `start` is "
     "dispatched before any `run` kind runs"),
    # The pattern: exactly one identity, `{owed}` exactly when owed, nothing else.
    (evidence_kind("local", run="a").replace("{tree}", "latest"),
     "validation.evidence.local.evidence must hold exactly one of {tree} and {commit}, the "
     "identity its evidence describes; it holds neither"),
    (evidence_kind("local", run="a").replace("{tree}", "{tree}/{commit}"),
     "it holds {tree} and {commit}"),
    (evidence_kind("ci", required="owed", start="a", collect="b").replace("-{owed}", ""),
     "validation.evidence.ci.evidence must hold {owed}"),
    (evidence_kind("local", run="a").replace("/local/", "/local-{owed}/"),
     "validation.evidence.local.evidence names {owed}, which is not available there"),
    (evidence_kind("local", run="a").replace("{tree}", "{tree}-{change}"),
     "validation.evidence.local.evidence names {change}, which is not available there"),
    (evidence_kind("local", run="a").replace(".snapshot/evidence/", "{tree}/"),
     "validation.evidence.local.evidence must begin with a fixed directory"),
    (evidence_kind("local", run="a").replace(".snapshot/", "../"),
     "validation.evidence.local.evidence must be a path from the repository's root"),
    (evidence_kind("local", run="a").replace('".snapshot/', '"/snapshot/'),
     "validation.evidence.local.evidence must be a path from the repository's root"),
    (_without(evidence_kind("local", run="a"), "evidence"),
     "validation.evidence.local.evidence is required"),
    # A guide, a file with something in it.
    (_without(evidence_kind("local", run="a"), "guide"),
     "validation.evidence.local.guide is required"),
    (evidence_kind("local", run="a").replace("evidence/local.md", "evidence/missing.md"),
     "validation.evidence.local.guide names .agents/evidence/missing.md, which does not exist"),
    (evidence_kind("local", run="a").replace("evidence/local.md", "evidence"),
     "validation.evidence.local.guide names .agents/evidence, which is no file"),
    (evidence_kind("local", run="a").replace('".agents/evidence/local.md"', '"/etc/guide.md"'),
     "validation.evidence.local.guide must be a path from the repository's root"),
    (evidence_kind("local", run="a").replace('".agents/evidence/local.md"',
                                             '".agents/../outside.md"'),
     "validation.evidence.local.guide must be a path from the repository's root"),
    # A kind's commands take the tree and the commit; only an owed kind's take
    # `{owed}`, and only a `collect` takes `{after}`.
    (evidence_kind("local", run="make WORKFLOW={owed}"),
     "validation.evidence.local.run names {owed}, which is not available there"),
    (evidence_kind("ci", required="owed", start="make run-ci W={owed} AFTER={after}",
                   collect="make collect"),
     "validation.evidence.ci.start names {after}, which is not available there"),
    (evidence_kind("ci", required="owed", start="a", collect="b",
                   cleanup="make clean W={owed}"),
     "validation.evidence.ci.cleanup names {owed}, which is not available there"),
    (evidence_kind("helm", run="a", cleanup="make clean AFTER={after}"),
     "validation.evidence.helm.cleanup names {after}, which is not available there"),
    (evidence_kind("local", run="make KIND={kind}"),
     "validation.evidence.local.run names {kind}, which is not available there"),
])
def test_a_malformed_kind_is_refused_naming_the_field(tmp_path: Path, text: str,
                                                      named: str) -> None:
    """CW-w8ne, CW-g4oz, CW-t3ev, CW-r5qk, CW-k7gd: every refusal of an evidence kind
    names its field."""
    with pytest.raises(ConfigError) as refused:
        _kinds_checked(tmp_path, text)

    assert named in str(refused.value)


def test_a_kind_naming_an_empty_guide_is_refused(tmp_path: Path) -> None:
    """CW-k7gd's scenario "A kind names no guide": an empty guide, whitespace alone,
    leaves validation nothing to assess the kind's evidence by."""
    text = evidence_kind("local", run="a")
    configured(tmp_path, text)
    (tmp_path / ".agents/evidence/local.md").write_text(" \n\n", "utf-8")

    with pytest.raises(ConfigError) as refused:
        configuration_checked(text, tmp_path / config.CONFIGURATION,
                              unignored=_every_directory_ignored)

    assert ("validation.evidence.local.guide names .agents/evidence/local.md, which is empty"
            in str(refused.value))


def test_an_evidence_directory_git_does_not_ignore_is_refused(tmp_path: Path) -> None:
    """CW-g1gn: the check names the kind whose directory Git does not ignore; the
    directories are given to Git once, each once."""
    asked: list[list[str]] = []

    def unignored(root: Path, directories: list[str]) -> list[str]:
        asked.append(list(directories))
        return [d for d in directories if d == "reports/"]

    with pytest.raises(ConfigError) as refused:
        _kinds_checked(tmp_path, evidence_kind("local", run="a")
                       + evidence_kind("helm", run="b").replace(".snapshot/evidence/",
                                                                "reports/"),
                       unignored)

    assert asked == [[".snapshot/evidence/", "reports/"]]
    assert ("validation.evidence.helm.evidence lies under reports/, which Git does not ignore"
            in str(refused.value))


def test_an_evidence_pattern_under_a_tracked_directory(tmp_path: Path,
                                                       capsys: pytest.CaptureFixture[str]
                                                       ) -> None:
    """CW-g1gn's scenario: `reports/{tree}/*.json` with `reports/` not ignored is
    refused by every reader, through Git itself; `.snapshot/` ignored passes."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    configured(tmp_path, evidence_kind("local", run="a"))
    assert main(["config"], root=tmp_path) == 0
    capsys.readouterr()
    text = (evidence_kind("local", run="a")
            .replace(".snapshot/evidence/{tree}/local/*/summary.json", "reports/{tree}/*.json"))
    configured(tmp_path, text)

    for command in (["config"], ["config", "--json"], ["check", "config"]):
        assert main(command, root=tmp_path) == 1
        err = capsys.readouterr().err
        assert "validation.evidence.local.evidence lies under reports/" in err


def test_outside_a_git_checkout_no_evidence_directory_is_refused(tmp_path: Path) -> None:
    """Outside a checkout nothing is tracked, so no pattern can change a tree."""
    assert config.git_unignored(tmp_path, ["reports/"]) == []


@pytest.mark.parametrize("text", [
    # The functional hooks and a kind's commands take the tree and the commit.
    "[hooks]\npre-commit-functional = 'make check TREE={tree} COMMIT={commit}'\n"
    "after-functional-change = 'make lock TREE={tree}'\n",
    evidence_kind("local", run="make validate TREE={tree} COMMIT={commit} CHANGE={change}"),
    evidence_kind("pipeline", identity="commit", start="make run COMMIT={commit}",
                  collect="make fetch AFTER={after} TREE={tree}",
                  cleanup="make clean TREE={tree} COMMIT={commit}"),
    # Every step's hooks take their inputs, a review's and a triage's their kind.
    "[hooks]\nbefore-validate = 'make warm INPUTS={inputs} CHANGE={change}'\n"
    "after-archive-cleanup = 'true'\n",
    "[hooks]\nbefore-review = 'make brief KIND={kind} INPUTS={inputs}'\n"
    "after-triage = 'make tell KIND={kind}'\nbefore-implement = []\n",
])
def test_placeholders_are_accepted_where_they_are_available(tmp_path: Path, text: str) -> None:
    """CW-v2dq and CW-h3ks: `{tree}` and `{commit}` in the functional hooks and a
    kind's commands, `{inputs}` in a step hook, `{kind}` in a review's and a
    triage's, and a step hook for each step a run is logged as."""
    _kinds_checked(tmp_path, text)


def test_placeholders_fill_where_they_are_available_and_the_shells_own_pass(
        tmp_path: Path) -> None:
    checked = _kinds_checked(tmp_path, """
[hooks]
pre-push = "make pre-push REMOTE={remote}"
pre-commit = ["echo ${HOME}", "awk '{print $1}' x", "make check CHANGE={change} BASE={base}"]
""" + evidence_kind("ci", required="owed", identity="commit",
                    start="make run-ci WORKFLOW={owed}",
                    collect="make validate-ci WORKFLOW={owed} AFTER={after}"))

    assert checked.hook("pre-commit") == ("echo ${HOME}", "awk '{print $1}' x",
                                          "make check CHANGE={change} BASE={base}")
    assert checked.kind("ci").owed


@pytest.mark.parametrize("command", [["config"], ["config", "--json"], ["check", "config"],
                                     ["config", "load", "design"], ["evidence", CHANGE],
                                     ["gather", CHANGE]])
def test_a_key_is_misspelled(tmp_path: Path, capsys: pytest.CaptureFixture[str],
                             command: list[str]) -> None:
    """CW-w8ne: every subcommand reading the file refuses, naming the field."""
    configured(tmp_path, "[hooks]\npre-comit = 'make check'\n")
    (tmp_path / "openspec/changes" / CHANGE).mkdir(parents=True)

    assert main(command, root=tmp_path) == 1

    captured = capsys.readouterr()
    assert "hooks.pre-comit" in captured.err
    assert captured.out == ""


def test_a_misspelled_key_refuses_a_step_before_it_is_launched(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    claude = FakeClaude()
    configured(tmp_path, "[hooks]\npre-comit = 'make check'\n")

    assert main(["start", "design", CHANGE, "--unattended"], root=tmp_path,
                wrapper=make_wrapper(tmp_path, claude)) == 1

    assert "hooks.pre-comit" in capsys.readouterr().err
    assert claude.commands == []
    assert not (tmp_path / "openspec/changes" / CHANGE / "reviews").exists()


def test_a_placeholder_is_used_where_it_is_unavailable(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """CW-v2dq: the configuration's check refuses, naming the field and the
    placeholder."""
    configured(tmp_path, "[hooks]\npre-commit = 'make check REMOTE={remote}'\n")

    assert main(["check", "config"], root=tmp_path) == 1

    err = capsys.readouterr().err
    assert "hooks.pre-commit" in err and "{remote}" in err


def test_no_file_reads_as_every_field_absent(tmp_path: Path,
                                             capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["check", "config"], root=tmp_path) == 0
    assert "does not exist; every field is absent" in capsys.readouterr().out

    loaded = config.load(tmp_path)
    assert not loaded.exists
    assert config.missing(loaded, config.PRE_COMMIT_FUNCTIONAL, config.EVIDENCE,
                          config.PROTECTED_BRANCHES, "models.implement") == [
        "hooks.pre-commit-functional", "validation.evidence", "repository.protected-branches",
        "models.implement"]


# A required field refuses only the steps that need it.

def _checkout(path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    return path


def test_no_functional_checks_are_declared(tmp_path: Path,
                                           capsys: pytest.CaptureFixture[str]) -> None:
    """CW-t5hz: `start implement` refuses before launching a session, naming the
    field."""
    claude = FakeClaude()
    configured(_checkout(tmp_path), CONFIGURED.replace("pre-commit-functional = []\n", ""))

    assert main(["start", "implement", CHANGE, "--sections", "1", "--unattended"],
                root=tmp_path, wrapper=make_wrapper(tmp_path, claude)) == 1

    assert "implement needs hooks.pre-commit-functional, which" in capsys.readouterr().err
    assert claude.commands == []
    assert not (tmp_path / "openspec/changes" / CHANGE / "reviews").exists()


def test_a_missing_field_refuses_an_interactive_session_too(tmp_path: Path) -> None:
    launched: list[list[str]] = []
    configured(_checkout(tmp_path), "[hooks]\npre-commit-functional = []\n")
    (tmp_path / "openspec/changes" / CHANGE).mkdir(parents=True)

    assert main(["start", "validate", CHANGE], root=tmp_path,
                launch=lambda command, root: launched.append(list(command)) or 0) == 1

    assert launched == []


def test_a_repository_declares_no_functional_checks_on_purpose(tmp_path: Path) -> None:
    """CW-t5hz: an explicit empty value declares the field, so implementation
    starts."""
    claude = FakeClaude((event_lines(VALID["finished"]), 0))
    configured(_checkout(tmp_path), CONFIGURED)

    assert main(["start", "implement", CHANGE, "--sections", "1", "--unattended"],
                root=tmp_path, wrapper=make_wrapper(tmp_path, claude)) == 0

    assert len(claude.commands) == 1


def test_with_no_files_every_step_is_refused_its_protected_branches_pointer_and_models(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Each missing field is named with the file it belongs in, a local one with
    `change-workflow install`."""
    claude = FakeClaude((event_lines(VALID["finished"]), 0))
    wrapper = make_wrapper(tmp_path, claude)
    (tmp_path / ".agents/workflow.toml").unlink()
    (tmp_path / config.LOCAL).unlink()

    assert main(["start", "design", CHANGE, "--unattended"], root=tmp_path,
                wrapper=wrapper) == 1

    assert ("design needs repository.protected-branches, which .agents/workflow.toml does not "
            "declare (there is no such file); an empty value declares it deliberately; and "
            "guidance.engineering, models.design, which .agents/workflow.local.toml does not "
            "declare (there is no such file): run `change-workflow install`"
            in capsys.readouterr().err)
    assert claude.commands == []


def test_validation_needs_one_kind_however_empty_its_table(tmp_path: Path) -> None:
    checked = _checked("[validation]\nevidence = {}\n")

    with pytest.raises(ConfigError, match="validate needs .*validation.evidence"):
        config.require_for_step(checked, "validate")


def test_an_interactive_step_needs_no_models(tmp_path: Path) -> None:
    """Only an unattended run runs on the configured models; the owner's interactive
    session runs on their own."""
    checked = config.check(CONFIGURED, Path("workflow.toml"),
                           local='[guidance]\nengineering = { none = "none here" }\n')

    config.require_for_step(checked, "implement")
    with pytest.raises(ConfigError, match="models.implement"):
        config.require_for_step(checked, "implement", unattended=True)
    with pytest.raises(ConfigError, match="models.orchestrator"):
        config.require_for_step(checked, "orchestrate")


def test_a_fable_model_is_accepted() -> None:
    """A repository that never wants a model does not list it; none is forbidden."""
    checked = _models_checked('[models]\nimplement = [{ harness = "claude", '
                              'model = "claude-fable-5-1", effort = "high" }]\n'
                              'orchestrator = { model = "claude-fable-5-1" }\n')

    assert checked.step_models("implement")[0].model == "claude-fable-5-1"
    assert checked.orchestrator_model().model == "claude-fable-5-1"


# `config`: every field and how it resolved.

def test_an_optional_hook_is_absent(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """CW-o6kc: `config` lists `pre-archive` as absent."""
    configured(tmp_path, "[hooks]\npre-commit = ['make lint', 'make docs']\n")

    assert main(["config"], root=tmp_path) == 0

    lines = capsys.readouterr().out.splitlines()
    assert next(line for line in lines if line.startswith("hooks.pre-archive ")).split() == [
        "hooks.pre-archive", "absent"]
    assert next(line for line in lines if line.startswith("hooks.pre-commit ")).split(
        None, 2) == ["hooks.pre-commit", "declared", "make lint; make docs"]


def test_config_as_json_gives_each_field_its_status_and_value(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    configured(tmp_path, """
[repository]
protected-branches = []

[hooks]
pre-commit-functional = "make test"

[defaults]
disable = [{ check = "skills", reason = "this repository keeps no agent skills" }]

""" + evidence_kind("helm", run="make validate-helm CHANGE={change}", cleanup=["make teardown"]),
               local=None)

    assert main(["config", "--json"], root=tmp_path) == 0

    shown = json.loads(capsys.readouterr().out)
    fields = {entry["field"]: entry for entry in shown["fields"]}
    assert (shown["file"], shown["exists"]) == (".agents/workflow.toml", True)
    assert fields["repository.protected-branches"] == {
        "field": "repository.protected-branches", "status": "declared", "value": []}
    assert fields["repository.inert-paths"] == {"field": "repository.inert-paths",
                                                "status": "default",
                                                "value": ["openspec/", "**/*.md"]}
    assert fields["hooks.pre-commit-functional"]["value"] == ["make test"]
    assert fields["defaults.skills"] == {"field": "defaults.skills", "status": "disabled",
                                         "reason": "this repository keeps no agent skills"}
    assert fields["defaults.openspec"]["status"] == "default"
    assert fields["defaults.openspec"]["value"].startswith("openspec validate <change> --strict")
    assert fields["defaults.tasks"]["value"] == "change-workflow check tasks <change>"
    assert fields["openspec.command"] == {"field": "openspec.command", "status": "default",
                                          "value": "openspec"}
    assert fields["validation.evidence.helm.cleanup"]["value"] == ["make teardown"]
    assert fields["validation.evidence.helm.after"]["status"] == "absent"
    assert fields["validation.evidence.helm.required"]["value"] == "always"
    assert fields["models.implement"]["status"] == "missing"
    assert fields["review.format-retries"] == {"field": "review.format-retries",
                                               "status": "default", "value": 1}


def test_config_as_json_names_the_workflows_version_and_each_document_by_role(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """CW-lm42: `config --json` names each of the distribution's documents by role,
    whatever repository it runs in, with its version; run from this tree, each is the
    tree's own file."""
    _checkout(tmp_path)

    assert main(["config", "--json"], root=tmp_path) == 0

    workflow = json.loads(capsys.readouterr().out)["workflow"]
    assert workflow == documents.RUNNING.described()
    assert list(workflow) == ["version", *documents.ROLES]
    assert workflow["diagrams"].endswith("/diagrams/")
    assert all(Path(path).is_relative_to(REPOSITORY) and Path(path).exists()
               for role, path in workflow.items() if role != "version")


def test_config_as_json_names_every_kinds_guide_and_each_step_hook(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """CW-o6kc: `config --json` lists each kind's fields, its guide among them, and
    each step's hooks as declared or absent. Library integration: a real Git
    checkout ignoring `.snapshot/`, the guides read from it."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    configured(tmp_path, FOUR_KINDS + "\n[hooks]\nbefore-validate = 'make warm'\n")

    assert main(["config", "--json"], root=tmp_path) == 0

    fields = {entry["field"]: entry for entry in json.loads(capsys.readouterr().out)["fields"]}
    assert {name: fields[f"validation.evidence.{name}.guide"]["value"]
            for name in ("pipeline", "ci", "local", "helm")} == {
        name: f".agents/evidence/{name}.md" for name in ("pipeline", "ci", "local", "helm")}
    assert fields["validation.evidence.ci.evidence"] == {
        "field": "validation.evidence.ci.evidence", "status": "declared",
        "value": ".snapshot/evidence/{commit}/ci-{owed}/*/summary.json"}
    assert fields["validation.evidence.local.start"]["status"] == "absent"
    assert fields["hooks.before-validate"] == {"field": "hooks.before-validate",
                                               "status": "declared", "value": ["make warm"]}
    assert [name for name, entry in fields.items()
            if name.startswith(("hooks.before-", "hooks.after-"))
            and name != "hooks.after-functional-change" and entry["status"] == "absent"] == [
        hook for step in config.STEPS for hook in (f"hooks.before-{step}", f"hooks.after-{step}")
        if hook != "hooks.before-validate"]


@pytest.mark.parametrize("text,inert_paths", [
    # CW-n7ra: with no declaration, the workflow's default.
    ("", ("openspec/", "**/*.md")),
    ("[repository]\nprotected-branches = []\n", ("openspec/", "**/*.md")),
    ('[repository]\ninert-paths = ["docs/", "assets/"]\n', ("docs/", "assets/")),
    # An empty declaration replaces the default too: no path is inert.
    ("[repository]\ninert-paths = []\n", ()),
])
def test_a_declaration_of_inert_paths_replaces_the_default(text: str,
                                                           inert_paths: tuple[str, ...]) -> None:
    assert _checked(text).repository_inert_paths() == inert_paths


def test_with_no_file_the_inert_paths_are_the_default(tmp_path: Path) -> None:
    assert config.load(tmp_path).repository_inert_paths() == config.DEFAULT_INERT_PATHS


def test_a_review_may_send_a_refused_draft_back_never() -> None:
    checked = _checked("[review]\nformat-retries = 0\n")

    assert checked.review_format_retries() == 0


def test_a_disabled_default_is_listed_with_its_reason(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    configured(tmp_path, "[defaults]\ndisable = [{ check = 'tasks', reason = 'no plans' }]\n")

    assert main(["config"], root=tmp_path) == 0

    line = next(line for line in capsys.readouterr().out.splitlines()
                if line.startswith("defaults.tasks"))
    assert line.split(None, 2) == ["defaults.tasks", "disabled", "— no plans"]


# `config load <step>`: a step's documents.

def test_design_loads_the_roadmap(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """CW-l7hn: the common documents and the roadmap for design, only the common
    ones for planning."""
    configured(tmp_path, """
[load]
common = ["AGENTS.md", "openspec/README.md"]
design = ["docs/development/ROADMAP.md", "AGENTS.md"]
""")

    assert main(["config", "load", "design"], root=tmp_path) == 0
    assert capsys.readouterr().out.splitlines() == [
        *WORKFLOW_GUIDANCE, "AGENTS.md", "openspec/README.md", "docs/development/ROADMAP.md"]
    assert main(["config", "load", "plan"], root=tmp_path) == 0
    assert capsys.readouterr().out.splitlines() == [*WORKFLOW_GUIDANCE, "AGENTS.md",
                                                    "openspec/README.md"]


def test_config_load_takes_a_step(tmp_path: Path) -> None:
    assert main(["config", "load", "deploy"], root=tmp_path) == 2
    assert main(["config", "load"], root=tmp_path) == 2


def test_a_session_that_is_no_step_loads_the_common_documents(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The orchestrating session and a guidance review run no step of the graph, so
    `config load common` prints the workflow's guidance and `load.common` alone for
    them."""
    configured(tmp_path, """
[load]
common = ["AGENTS.md", "openspec/README.md"]
design = ["docs/development/ROADMAP.md"]
""")

    assert main(["config", "load", "common"], root=tmp_path) == 0
    assert capsys.readouterr().out.splitlines() == [*WORKFLOW_GUIDANCE, "AGENTS.md",
                                                    "openspec/README.md"]


def _guidance(root: Path, *paths: str) -> None:
    for path in paths:
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text("# x\n", "utf-8")


def test_a_directory_entry_expands_in_sorted_order_in_its_place(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """CW-l7hn's scenario "A directory entry": the Markdown files beneath it,
    recursively, in sorted path order, where the directory was; files of another
    kind are not documents, and a document named twice is printed once."""
    configured(tmp_path, """
[load]
common = ["AGENTS.md", "docs/guidance/", "openspec/README.md"]
design = ["docs/guidance/workflow/closeout.md", "docs/ROADMAP.md"]
""")
    _guidance(tmp_path, "docs/guidance/workflow/closeout.md", "docs/guidance/README.md",
              "docs/guidance/engineering/comments.md", "docs/guidance/engineering/a/deep.md",
              "docs/guidance/engineering/diagram.svg")

    assert main(["config", "load", "design"], root=tmp_path) == 0

    assert capsys.readouterr().out.splitlines() == [
        *WORKFLOW_GUIDANCE,
        "AGENTS.md", "docs/guidance/README.md", "docs/guidance/engineering/a/deep.md",
        "docs/guidance/engineering/comments.md", "docs/guidance/workflow/closeout.md",
        "openspec/README.md", "docs/ROADMAP.md"]


def _unreadable(root: Path) -> None:
    _guidance(root, "docs/guidance/closed/x.md")
    (root / "docs/guidance/closed").chmod(0)
    if os.access(root / "docs/guidance/closed", os.R_OK):
        (root / "docs/guidance/closed").chmod(0o755)
        pytest.skip("this user reads a directory whatever its mode, as root does")


@pytest.mark.parametrize("arrange,named", [
    (lambda root: None, "docs/guidance/, which does not exist"),
    (lambda root: _guidance(root, "docs/guidance"), "docs/guidance/, which is a file"),
    (lambda root: _guidance(root, "docs/guidance/notes.txt"),
     "docs/guidance/, which holds no Markdown file"),
    (lambda root: (root / "docs/guidance/empty").mkdir(parents=True),
     "docs/guidance/, which holds no Markdown file"),
    (_unreadable, "docs/guidance/, which cannot be read"),
])
def test_a_directory_entry_naming_nothing_is_refused_naming_it(
        tmp_path: Path, capsys: pytest.CaptureFixture[str], arrange, named: str) -> None:
    """CW-l7hn's scenario "A directory entry names nothing": refused as an error,
    naming the entry, with no partial list printed."""
    configured(tmp_path, '[load]\ncommon = ["AGENTS.md", "docs/guidance/"]\n')
    arrange(tmp_path)

    try:
        assert main(["config", "load", "common"], root=tmp_path) == 1
    finally:
        if (tmp_path / "docs/guidance/closed").exists():
            (tmp_path / "docs/guidance/closed").chmod(0o755)

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("ERROR: load names the directory ")
    assert named in captured.err


def test_a_literal_entry_naming_no_file_is_still_printed(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A literal entry resolves as it always has: the engine does not look for its
    file, so an adopting repository's configuration means what it meant."""
    configured(tmp_path, '[load]\ncommon = ["AGENTS.md", "docs/missing.md"]\n')

    assert main(["config", "load", "common"], root=tmp_path) == 0

    assert capsys.readouterr().out.splitlines() == [*WORKFLOW_GUIDANCE, "AGENTS.md",
                                                    "docs/missing.md"]


def test_an_absent_or_empty_list_loads_the_workflows_guidance_alone(tmp_path: Path) -> None:
    applying_none = '[guidance]\nengineering = { none = "none here" }\n'

    for text in (ACCEPTED, ACCEPTED + "[load]\ncommon = []\n"):
        checked = config.check(text, Path("workflow.toml"), local=applying_none)
        assert checked.documents("design", tmp_path) == WORKFLOW_GUIDANCE


def test_with_no_pointer_the_documents_are_refused(tmp_path: Path,
                                                   capsys: pytest.CaptureFixture[str]) -> None:
    """CW-hu0z's pointer is required: with none, a session would read no engineering
    guidance, so `config load` refuses, naming it and `change-workflow install`, as
    every session reads the list, interactive ones too."""
    _checkout(tmp_path)
    configured(tmp_path, CONFIGURED, local=None)

    assert main(["config", "load", "plan"], root=tmp_path) == 1
    assert capsys.readouterr().err == (
        "ERROR: the documents a session reads needs guidance.engineering, which "
        ".agents/workflow.local.toml does not declare (there is no such file): run "
        "`change-workflow install` to write it where the checkout has none, or declare "
        "them there\n")


# `[sandbox]`: what a repository adds to a step's scope.

@pytest.mark.parametrize("text,named", [
    ("[sandbox]\nwritable = ['docs/']\n", "sandbox.writable must be a table of path lists"),
    ("[sandbox]\nwritable.common = 'docs/'\n", "sandbox.writable.common must be a list"),
    ("[sandbox]\nprotected = '.claude/'\n", "sandbox.protected must be a list"),
    ("[sandbox]\nreadable = []\n", "sandbox.readable is no field the workflow defines; "
                                   "sandbox takes writable, protected"),
    ("[sandbox]\nwritable.review = ['docs/']\n", "sandbox.writable.review is refused"),
    ("[sandbox]\nwritable.deploy = ['docs/']\n", "sandbox.writable.deploy names no step"),
    ("[sandbox]\nwritable.round = ['docs/']\n", "sandbox.writable.round names no step"),
    ("[sandbox]\nwritable.common = ['~/.cache/*']\n",
     "sandbox.writable.common names ~/.cache/*, a pattern outside the checkout"),
    ("[sandbox]\nprotected = ['.claude/*.json']\n",
     "sandbox.protected names .claude/*.json, a pattern"),
    ("[sandbox]\nwritable.design = ['.git/config']\n",
     "sandbox.writable.design names .git/config, which is or lies under the protected path "
     ".git/config"),
    ("[sandbox]\nwritable.merge = ['/usr/lib/git-core/git']\n",
     "sandbox.writable.merge names /usr/lib/git-core/git, which is or lies under the "
     "protected path /usr/lib/git-core/git"),
    ("[sandbox]\nwritable.plan = ['secrets/key']\nprotected = ['secrets/']\n",
     "sandbox.writable.plan names secrets/key, which is or lies under the protected path "
     "secrets/"),
    ("[sandbox]\nwritable.design = ['/tmp/']\n",
     "sandbox.writable.design names /tmp/, which is or holds the host's temporary "
     "directory; every step writes a private /tmp of its own"),
    ("[sandbox]\nwritable.merge = ['/']\n",
     "sandbox.writable.merge names /, which is or holds the host's temporary directory"),
])
def test_a_malformed_sandbox_table_is_refused_naming_the_field(text: str, named: str) -> None:
    with pytest.raises(ConfigError) as refused:
        _checked(text)
    assert named in str(refused.value)


def test_an_absent_sandbox_table_adds_nothing() -> None:
    checked = _checked("")

    assert (checked.sandbox_writable, checked.sandbox_protected) == ({}, None)
    assert all(checked.repository_writable(step) == () for step in config.STEPS)


def test_common_paths_are_every_steps_the_reviews_only_outside_its_checkout(
        tmp_path: Path) -> None:
    """The review writes the common paths outside its checkout, such as a tool's cache,
    and none inside it, every file it reviews staying read-only."""
    root, home = tmp_path / "checkout", tmp_path / "home"
    checked = _checked("[sandbox]\nwritable.common = ['~/.local/share/uv', 'build/', "
                       f"'{root}/out', '/var/cache/x']\n"
                       "writable.design = ['docs/', '~/.local/share/uv']\n")

    assert checked.repository_writable("design", root, home) == (
        "~/.local/share/uv", "build/", f"{root}/out", "/var/cache/x", "docs/")
    assert checked.repository_writable("plan") == (
        "~/.local/share/uv", "build/", f"{root}/out", "/var/cache/x")
    assert checked.repository_writable("review", root, home) == ("~/.local/share/uv",
                                                                 "/var/cache/x")
    assert checked.repository_writable("review") == ()


def test_a_common_path_linked_into_the_checkout_stays_out_of_the_reviews_scope(
        tmp_path: Path) -> None:
    """A path from the home directory whose link leads into the checkout is inside it,
    where the sandbox would mount it."""
    root, home = tmp_path / "checkout", tmp_path / "home"
    (root / "build").mkdir(parents=True)
    home.mkdir()
    (home / "build").symlink_to(root / "build")
    checked = _checked("[sandbox]\nwritable.common = ['~/build']\n")

    assert checked.repository_writable("review", root, home) == ()
    assert checked.repository_writable("implement", root, home) == ("~/build",)


def test_a_common_path_holding_the_checkout_stays_out_of_the_reviews_scope(
        tmp_path: Path) -> None:
    """A directory holding the checkout would make every file the review reads
    writable, so it is no path outside the checkout."""
    home = tmp_path / "home"
    root = home / "code/checkout"
    root.mkdir(parents=True)
    checked = _checked(f"[sandbox]\nwritable.common = ['~/code', '~', '{tmp_path}', "
                       "'~/.npm']\n")

    assert checked.repository_writable("review", root, home) == ("~/.npm",)


def _git_checkout(root: Path, text: str) -> Path:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / ".agents").mkdir(parents=True, exist_ok=True)
    return configured(root, text)


def test_a_repository_gives_design_its_documents(tmp_path: Path) -> None:
    """CW-h2zt's "A repository gives design its documents": design's scope lists
    `docs/`, and planning's does not. Library integration: a real Git checkout."""
    root = _git_checkout(tmp_path, "[sandbox]\nwritable.design = ['docs/']\n")
    loaded = config.load(root)

    design = {path.path: path.source for path in loaded.scope("design", root).writable}
    plan = {path.path for path in loaded.scope("plan", root).writable}
    assert design[root / "docs"] == "repository"
    assert root / "docs" not in plan


REFUSED_OPENING = ("sandbox.writable.common names .agents/workflow.toml, which is or lies "
                   "under the protected path .agents/workflow.toml")


@pytest.mark.parametrize("command", [["check", "config"], ["config", "--json"], ["config"],
                                     ["config", "load", "design"]], ids=" ".join)
def test_a_repository_opens_a_protected_path(tmp_path: Path, capsys: pytest.CaptureFixture[str],
                                             command: list[str]) -> None:
    """CW-h2zt's "A repository opens a protected path": every reader refuses, naming
    the field and the protected path, the commands driven in process."""
    configured(tmp_path, "[sandbox]\nwritable.common = ['.agents/workflow.toml']\n")

    assert main(command, root=tmp_path) == 1

    assert REFUSED_OPENING in capsys.readouterr().err


REFUSED_TEMPORARY = ("sandbox.writable.common names /tmp, which is or holds the host's "
                     "temporary directory; every step writes a private /tmp of its own, "
                     "which it would hide")


@pytest.mark.parametrize("command", [["check", "config"], ["config", "--json"], ["config"],
                                     ["config", "load", "design"]], ids=" ".join)
def test_a_repository_opens_the_hosts_temporary_directory(
        tmp_path: Path, capsys: pytest.CaptureFixture[str], command: list[str]) -> None:
    """CW-h2zt's "A repository opens the host's temporary directory": every reader
    refuses, naming the field and `/tmp`, the commands driven in process."""
    configured(tmp_path, "[sandbox]\nwritable.common = ['/tmp']\n")

    assert main(command, root=tmp_path) == 1

    assert REFUSED_TEMPORARY in capsys.readouterr().err


def test_a_path_under_the_hosts_temporary_directory_is_admitted(tmp_path: Path) -> None:
    """A repository may name a path under `/tmp`, which the sandbox mounts at its own
    path inside the private one. Library integration: a real Git checkout."""
    root = _git_checkout(tmp_path, "[sandbox]\nwritable.implement = ['/tmp/shared-cache']\n")

    found = config.load(root).scope("implement", root)

    assert {(path.path, path.source) for path in found.writable} >= {
        (Path("/tmp/shared-cache"), "repository"), (Path("/tmp"), "engine")}


def test_a_writable_path_linked_into_a_protected_directory_is_refused(tmp_path: Path) -> None:
    """The check compares a path where its links lead, as the sandbox mounts it.
    Library integration: real links on the file system."""
    root = tmp_path / "checkout"
    (root / "data/subdir").mkdir(parents=True)
    (root / "alias").symlink_to(root / "data/subdir")
    with pytest.raises(ConfigError, match="sandbox.writable.design names alias, which is or "
                                          "lies under the protected path data/"):
        configuration_checked("[sandbox]\nwritable.design = ['alias']\nprotected = ['data/']\n",
                              root / config.CONFIGURATION, home=tmp_path / "home")


def test_a_writable_path_under_a_protected_home_path_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="sandbox.writable.common names ~/.ssh/keys, which "
                                          "is or lies under the protected path ~/.ssh/"):
        configuration_checked("[sandbox]\nwritable.common = ['~/.ssh/keys']\n"
                              "protected = ['~/.ssh/']\n",
                              tmp_path / config.CONFIGURATION, home=tmp_path / "home")


def test_a_repository_opens_a_directory_holding_a_protected_path(tmp_path: Path) -> None:
    """CW-h2zt's "A repository opens a directory holding a protected path": design's
    scope lists `.agents/` writable and `.agents/workflow.toml` protected inside it.
    Library integration: a real Git checkout."""
    root = _git_checkout(tmp_path, "[sandbox]\nwritable.design = ['.agents/']\n")

    found = config.load(root).scope("design", root)

    assert root / ".agents" in {path.path for path in found.writable}
    assert root / ".agents/workflow.toml" in {path.path for path in found.protected}


def test_config_lists_each_steps_scope_with_each_paths_source(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """CW-o6kc's "The orchestrating session reads a step's scope": `config --json`
    gives planning's scope, its `openspec/` and `.git/` from the engine, the state of
    the adapter of its first model's harness, Claude Code's, and `docs/` from the
    repository, and `config` lists the same. Library integration: a real Git
    checkout."""
    root = _git_checkout(tmp_path, CONFIGURED + "\n[sandbox]\nwritable.plan = ['docs/']\n")
    (root / "openspec").mkdir()

    assert main(["config", "--json"], root=root) == 0

    shown = json.loads(capsys.readouterr().out)
    fields = {entry["field"]: entry for entry in shown["fields"]}
    assert fields["sandbox.writable.plan"] == {"field": "sandbox.writable.plan",
                                               "status": "declared", "value": ["docs/"]}
    assert fields["sandbox.writable.common"]["status"] == "absent"
    assert set(shown["scopes"]) == set(config.STEPS)
    plan = {(entry["entry"], entry["source"]) for entry in shown["scopes"]["plan"]["writable"]}
    assert {("openspec/", "engine"), (".git/", "engine"), ("docs/", "repository"),
            ("~/.claude", "adapter"), ("~/.claude.json", "adapter")} <= plan
    docs = next(entry for entry in shown["scopes"]["plan"]["writable"]
                if entry["entry"] == "docs/")
    assert docs == {"path": str(root / "docs"), "source": "repository", "entry": "docs/",
                    "absent": True}
    state = next(entry for entry in shown["scopes"]["plan"]["writable"]
                 if entry["entry"] == "~/.claude.json")
    assert (state["path"], state["file"]) == (str(Path.home() / ".claude.json"), True)
    # Every step's temporary entry is its private `/tmp`, from the engine.
    for step, found in shown["scopes"].items():
        assert {"path": "/tmp", "source": "engine", "entry": "<temporary directory>",
                "private": True} in found["writable"], step
    protected = {(entry["entry"], entry["source"])
                 for entry in shown["scopes"]["plan"]["protected"]}
    assert protected == {(".agents/workflow.toml", "engine"),
                         (".agents/workflow.local.toml", "engine"), (".git/config", "engine"),
                         ("/usr/bin/git", "engine"), ("/usr/lib/git-core/git", "engine"),
                         (".claude/settings.json", "adapter"),
                         (".claude/settings.local.json", "adapter"),
                         ("~/.claude/settings.json", "adapter"),
                         ("~/.claude/skills/", "adapter")}
    # The review's first model is Codex's, so its scope holds Codex's state.
    review = {(entry["entry"], entry["source"])
              for entry in shown["scopes"]["review"]["writable"]}
    assert ("~/.codex", "adapter") in review
    guarded = {entry["entry"] for entry in shown["scopes"]["review"]["protected"]}
    assert "~/.codex/config.toml" in guarded
    assert not any(".claude" in entry for entry, _ in review)
    assert not any(".claude" in entry for entry in guarded)

    assert main(["config"], root=root) == 0

    lines = capsys.readouterr().out.splitlines()
    assert [line.split() for line in lines if line.startswith("scope.plan.writable")
            and "openspec" in line] == [["scope.plan.writable", "engine", "openspec"]]
    assert ["scope.plan.writable", "repository", "docs", "(absent)"] in [
        line.split() for line in lines]
    assert ["scope.plan.protected", "engine", ".agents/workflow.toml"] in [
        line.split() for line in lines]
    assert ["scope.plan.writable", "adapter", "~/.claude"] in [line.split() for line in lines]
    assert ["scope.review.writable", "engine", "/tmp", "(private)"] in [
        line.split() for line in lines]


@pytest.mark.parametrize("models,problem", [
    ("[]", "must be a list of one or more models"),
    ('[{ harness = "claude", model = "claude-opus-5-5" }, '
     '{ harness = "claude", model = "claude-sonnet-5-5" }]', "two models of one vendor"),
    ('[{ harness = "claude", effort = "high" }]', r"models.triage\[0\].model must be"),
    ('[{ harness = "codex", model = "gpt-6-sol" }]', "which the codex adapter cannot run"),
    ('[{ harness = "gemini", model = "g" }]', r"harness must be one of claude, codex"),
    ('[{ harness = "claude", model = "m", speed = "fast" }]', "speed is no field"),
])
def test_models_the_policy_forbids_are_refused_naming_the_step(models: str,
                                                                problem: str) -> None:
    """CW-zq4h: the configuration's models are held to the policy as it is read."""
    with pytest.raises(StepError, match=problem) as refused:
        _models_checked(f"[models]\ntriage = {models}\n")

    assert "models.triage" in str(refused.value)


def test_a_row_names_two_models_of_one_vendor() -> None:
    """CW-zq4h's "A row names two models of one vendor": refused, naming the step."""
    with pytest.raises(StepError, match="for the design step"):
        _models_checked('[models]\ndesign = [{ harness = "claude", model = "claude-opus-5-5" }, '
                        '{ harness = "claude", model = "claude-sonnet-5-5" }]\n')


def test_a_harness_whose_adapter_runs_only_reviews() -> None:
    """CW-zq4h's "A harness whose adapter runs only reviews": a Codex model for
    implementation is refused, naming implementation; for the review it is read."""
    with pytest.raises(StepError, match="models.implement names a codex model for the "
                                        "implement step, which the codex adapter cannot "
                                        "run; it runs only: review"):
        _models_checked('[models]\nimplement = [{ harness = "codex", model = "gpt-6-sol" }]\n')

    read = _models_checked('[models]\nreview = [{ harness = "codex", model = "gpt-6-sol" }]\n')
    assert read.step_models("review")[0].harness == "codex"


def test_a_repository_cannot_open_an_adapters_settings(tmp_path: Path) -> None:
    """Every adapter's settings files are protected whichever harness runs the step,
    so no repository's writable path opens one."""
    with pytest.raises(ConfigError, match="sandbox.writable.design names "
                                          ".claude/settings.json, which is or lies under "
                                          "the protected path .claude/settings.json"):
        configuration_checked("[sandbox]\nwritable.design = ['.claude/settings.json']\n",
                              tmp_path / config.CONFIGURATION, home=tmp_path / "home")


# A waiver names the kinds the configuration declares.

def test_a_waiver_names_declared_kinds(tmp_path: Path,
                                       capsys: pytest.CaptureFixture[str]) -> None:
    configured(tmp_path, FOUR_KINDS)
    (tmp_path / "openspec/changes" / CHANGE).mkdir(parents=True)

    assert main(["note", CHANGE, "orchestrator", "--by", "owner", "--waives", "smoke",
                 "--decision", "d", "--reason", "r"], root=tmp_path) != 0
    assert "does not declare: smoke" in capsys.readouterr().err


def test_the_repositorys_own_configuration_passes_its_check(
        capsys: pytest.CaptureFixture[str]) -> None:
    loaded = as_installed(REPOSITORY)

    assert config.load(REPOSITORY).exists
    assert config.missing(loaded, config.PRE_COMMIT_FUNCTIONAL, config.EVIDENCE,
                          config.PROTECTED_BRANCHES, f"models.{config.ORCHESTRATOR}",
                          *(f"models.{step}" for step in config.STEPS)) == []
    assert main(["check", "config"], root=REPOSITORY) == 0
    assert "passes its check" in capsys.readouterr().out


def test_each_step_runs_on_the_models_its_work_needs() -> None:
    """This repository's configuration: design, triage, implementation, the merge, and
    closeout on Opus at high effort; validation and archive cleanup on Sonnet at
    medium; the review on Codex, then Claude."""
    loaded = as_installed(REPOSITORY)

    assert {name: loaded.step_models(name) for name in config.STEPS} == {
        "design": (OPUS,), "plan": (OPUS,), "triage": (OPUS,), "implement": (OPUS,),
        "merge": (OPUS,), "closeout": (OPUS,), "validate": (SONNET,),
        "archive-cleanup": (SONNET,), "review": (Model("codex", "gpt-6-sol", "high"), OPUS)}


def _repository_scope(step: str, home: Path) -> Scope:
    return as_installed(REPOSITORY).scope(step, REPOSITORY, home=home)


def _writes(found: Scope, path: Path) -> bool:
    """Whether a step of scope `found` writes the host's `path`: the private `/tmp` is
    the sandbox's own, writing no host path, though the test's home lies under the
    host's `/tmp`."""
    return (any(within(path, open_.path) for open_ in found.writable if not open_.private)
            and not any(within(path, guarded.path) for guarded in found.protected))


def test_design_and_planning_write_the_repositorys_documents(tmp_path: Path) -> None:
    """MCW-s4bx's "Design edits the roadmap": the configuration gives design `docs/`,
    and planning too, beside their baseline."""
    roadmap = REPOSITORY / "docs/development/ROADMAP.md"

    for step in ("design", "plan"):
        found = _repository_scope(step, tmp_path / "home")
        assert _writes(found, roadmap), step
        assert [path.source for path in found.writable
                if path.path == REPOSITORY / "docs"] == [REPOSITORY_SOURCE], step
    assert not _writes(_repository_scope("archive-cleanup", tmp_path / "home"), roadmap)


def test_every_step_writes_the_tool_state_its_suites_and_deployments_need(
        tmp_path: Path) -> None:
    """MCW-s4bx's "Implementation syncs an environment", "Design validates the change"
    and "A review runs the repository's checks": uv's Pythons, and the cluster client's
    cache, the cloud CLI's configuration, Docker's client configuration, and npm's
    cache, which the configured OpenSpec command's `npx` writes, for every step, the
    review included, since each lies outside the checkout; and nothing protected
    beyond the engine's and the adapters'."""
    home = tmp_path / "home"
    tools = [home / ".local/share/uv/python", home / ".kube/cache", home / ".config/gcloud",
             home / ".docker", home / ".npm/_cacache", home / ".cache/uv"]

    for step in config.STEPS:
        found = _repository_scope(step, home)
        writes = [_writes(found, tool) for tool in tools]
        assert writes == [True] * len(tools), step
        assert not any(path.source == REPOSITORY_SOURCE for path in found.protected), step
    assert config.load(REPOSITORY).sandbox_protected == ()


def test_no_step_writes_the_configuration_or_the_harnesss_settings(tmp_path: Path) -> None:
    """CW-z5me: no step changes what its own hooks run or what its harness loads. The
    configuration and each adapter's settings files are read-only in every step's
    scope, whichever harness runs it, while a step that writes the checkout writes the
    skills beside the configuration."""
    home = tmp_path / "home"
    settings = [REPOSITORY / ".agents/workflow.toml", REPOSITORY / ".claude/settings.json",
                REPOSITORY / ".claude/settings.local.json", home / ".claude/settings.json",
                home / ".codex/config.toml"]
    loaded = config.load(REPOSITORY)

    for step in config.STEPS:
        for harness in (model["harness"] for model in loaded.models[step]):
            found = loaded.scope(step, REPOSITORY, harness, home=home)
            assert not any(_writes(found, path) for path in settings), (step, harness)
    assert _writes(_repository_scope("implement", home),
                   REPOSITORY / ".agents/skills/change-plan/SKILL.md")


def test_the_repository_declares_every_hook() -> None:
    """MCW-r4tx: this repository relocks after a functional change, runs its own
    closing checks before every commit, clears the wheelhouse, checks packaging and
    runs every suite before a functional commit — the local kind's own run, so it
    leaves `local` evidence for the tree it tested — checks packaging and the
    change's architecture rows before the archive, and runs its pre-push checks as
    one target."""
    loaded = config.load(REPOSITORY)

    assert loaded.hook("after-functional-change") == ("make lock",)
    assert loaded.hook("pre-commit") == (
        "make check-repository CHANGE={change} CHANGE_BASE={base}",)
    assert loaded.hook("pre-commit-functional") == ("make validate-local TREE={tree}",)
    assert loaded.hook("pre-commit-functional") == loaded.kind("local").run
    assert loaded.hook("pre-archive") == ("make check-packaging",
                                          "make check-architecture-change CHANGE={change}")
    assert loaded.hook("pre-push") == ("make pre-push REMOTE={remote}",)
    assert loaded.hook("post-clone") == ("make init",)


def test_every_table_of_the_repositorys_file_says_who_uses_it() -> None:
    """Each table of this repository's file has a comment beside it naming the engine
    operation or the skill that uses its fields; each evidence kind has one saying
    what it is, under the comment naming who runs the kinds."""
    text = (REPOSITORY / config.CONFIGURATION).read_text("utf-8")
    lines = text.splitlines()
    users = ("Engine", "engine", "change-")
    assert "for change-validate: validation's evidence kinds" in text
    for index, line in enumerate(lines):
        if not line.startswith("["):
            continue
        above = []
        for earlier in reversed(lines[:index]):
            if not earlier.startswith("#"):
                break
            above.append(earlier)
        below = []
        for later in lines[index + 1:]:
            if not later.startswith("#"):
                break
            below.append(later)
        if line.startswith("[validation.evidence."):
            assert below, line
        else:
            assert any(user in comment for comment in above + below for user in users), line


# `[workflow] version`: the range of workflow versions the repository accepts.

@pytest.mark.parametrize("text,specifiers", [
    (">=0.1, <0.2", [(">=", (0, 1)), ("<", (0, 2))]),
    ("==0.1.0", [("==", (0, 1, 0))]),
    ("~=0.4.1,!=0.4.3", [("~=", (0, 4, 1)), ("!=", (0, 4, 3))]),
    (" <= 2 , > 1.9 ", [("<=", (2,)), (">", (1, 9))]),
])
def test_a_range_is_read_as_its_specifiers(text: str, specifiers: list) -> None:
    assert config.version_range("workflow.version", text) == specifiers


@pytest.mark.parametrize("text,named", [
    ("0.1", "got '0.1'"),
    (">=0.1, <0.2.*", "got '<0.2.*'"),
    (">=0.1rc1", "got '>=0.1rc1'"),
    ("=>0.1", "got '=>0.1'"),
    (">=0.1,", "got ''"),
    ("~=1", "~= compares with two release numbers or more"),
    ("", "must be a non-empty string"),
])
def test_a_malformed_range_is_refused_naming_the_field(text: str, named: str) -> None:
    with pytest.raises(ConfigError, match="workflow.version") as refused:
        config.version_range("workflow.version", text)
    assert named in str(refused.value)


@pytest.mark.parametrize("version,admitted", [
    ("0.1.0", True), ("0.1.7", True), ("0.1", True), ("0.2.0", False), ("0.0.9", False),
    ("0.1.3", False), ("0.1.0.dev1", False), ("0.1.1rc1", True), ("unknown", False),
])
def test_a_range_admits_a_version_by_its_release_numbers_a_pre_release_first(
        version: str, admitted: bool) -> None:
    specifiers = config.version_range("workflow.version", ">=0.1, <0.2, !=0.1.3")

    assert config.admits(specifiers, version) is admitted


@pytest.mark.parametrize("version,admitted", [
    ("0.4.1", True), ("0.4.9", True), ("0.5.0", False), ("0.4.0", False), ("0.4", False)])
def test_a_compatible_release_stays_within_its_series(version: str, admitted: bool) -> None:
    assert config.admits(config.version_range("v", "~=0.4.1"), version) is admitted


def test_an_engine_outside_the_range_refuses_before_reading_a_later_versions_table() -> None:
    text = '[workflow]\nversion = ">=0.5, <0.6"\n\n[release]\nchannel = "stable"\n'

    with pytest.raises(ConfigError) as refused:
        config.check(text, Path("workflow.toml"), installed=lambda: "0.4.2")

    message = str(refused.value)
    assert "the installed workflow is 0.4.2, outside the range >=0.5, <0.6" in message
    assert "install a version the range admits" in message
    assert "release" not in message
    assert config.check('[workflow]\nversion = ">=0.4, <0.5"\n', Path("workflow.toml"),
                        installed=lambda: "0.4.2").version_range == ">=0.4, <0.5"


def test_the_installed_version_is_too_old(tmp_path: Path,
                                          capsys: pytest.CaptureFixture[str]) -> None:
    """CW-f8yy's scenario: `config load design` refuses, naming the engine's version,
    the range, and the fix, and does not report the table only the later version
    defines as unknown."""
    configured(tmp_path, '[workflow]\nversion = ">=0.5, <0.6"\n\n[release]\nchannel = "x"\n')

    assert main(["config", "load", "design"], root=tmp_path) == 1

    err = capsys.readouterr().err
    assert (f"the installed workflow is {documents.version()}, outside the range >=0.5, <0.6 "
            "that .agents/workflow.toml accepts") in err
    assert "run `change-workflow install`" in err
    assert "no table the workflow defines" not in err


def test_an_engine_within_the_range_reads_the_rest(tmp_path: Path,
                                                   capsys: pytest.CaptureFixture[str]) -> None:
    configured(tmp_path, CONFIGURED.replace(
        ACCEPTED, f'[workflow]\nversion = "=={documents.version()}"\n'))

    assert main(["config", "--json"], root=tmp_path) == 0

    fields = {entry["field"]: entry for entry in json.loads(capsys.readouterr().out)["fields"]}
    assert fields["workflow.version"] == {"field": "workflow.version", "status": "declared",
                                          "value": f"=={documents.version()}"}


# The local configuration, `.agents/workflow.local.toml`.

def _local(root: Path, text: str) -> None:
    (root / config.LOCAL).parent.mkdir(parents=True, exist_ok=True)
    (root / config.LOCAL).write_text(text, "utf-8")


def _engineering(root: Path, directory: str = "guides/engineering") -> Path:
    for name in ("tests.md", "imports/at-module-level.md"):
        (root / directory / name).parent.mkdir(parents=True, exist_ok=True)
        (root / directory / name).write_text(f"# {name}\n", "utf-8")
    return root / directory


COMMITTED = """
[repository]
protected-branches = ["main"]

[sandbox]
writable.common = ["~/.cache/shared"]
"""


def test_config_as_json_reports_a_missing_local_configuration(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """CW-4pm4's "CI reads the workflow's roles": with no local file, `config --json`
    exits 0, reports the local file absent, each required local field as missing,
    `guidance.engineering` as null, and the committed fields and the distribution's
    in full."""
    _checkout(tmp_path)
    configured(tmp_path, COMMITTED, local=None)

    assert main(["config", "--json"], root=tmp_path) == 0

    shown = json.loads(capsys.readouterr().out)
    fields = {entry["field"]: entry for entry in shown["fields"]}
    assert shown["local"] == {"file": ".agents/workflow.local.toml", "exists": False}
    assert shown["guidance"] == {"engineering": None}
    assert fields["guidance.engineering"] == {"field": "guidance.engineering",
                                              "status": "missing"}
    assert {fields[f"models.{step}"]["status"] for step in (*config.STEPS, "orchestrator")} == {
        "missing"}
    committed = {field: entry for field, entry in fields.items()
                 if not field.startswith(("models.", "guidance."))}
    assert committed == {entry["field"]: entry
                         for entry in config.resolution(config.load(tmp_path))
                         if not entry["field"].startswith(("models.", "guidance."))}
    assert fields["repository.protected-branches"]["value"] == ["main"]
    assert fields["sandbox.writable.common"]["value"] == ["~/.cache/shared"]
    assert shown["workflow"] == documents.RUNNING.described()
    assert shown["roles"] == [role.shown() for role in config.ROLES]
    assert main(["config"], root=tmp_path) == 0
    assert capsys.readouterr().out.splitlines()[1] == (
        ".agents/workflow.local.toml: no such file; every local field is missing")


# The configuration's tables, committed and local, each with its keys.
TABLES = {table: {*config._TABLES.get(table, ()), *config._LOCAL_TABLES.get(table, ())}
          for table in {*config._TABLES, *config._LOCAL_TABLES}}
_FIELD = re.compile(rf"^(?:{'|'.join(TABLES)})\.[a-z<][\w.<>-]*$")
_CODE = re.compile(r"`([^`]+)`")


def _companion_roles(markdown: str) -> list[tuple[str, set[str]]]:
    """The companion's table of roles: each row's role and the configuration fields its
    "Provided through" cell names in code."""
    section = markdown.split("### What an adopting repository provides\n", 1)[1]
    section = re.split(r"^#{2,4} ", section, maxsplit=1, flags=re.M)[0]
    rows = [[cell.strip() for cell in line.strip().strip("|").split("|")]
            for line in section.splitlines()
            if line.startswith("| ") and not line.startswith(("| Role |", "|---"))]
    return [(cells[0], {code for code in _CODE.findall(cells[-1]) if _FIELD.match(code)})
            for cells in rows]


def test_the_companions_table_of_roles_is_the_roles_config_lists() -> None:
    """CW-ora1: the distribution's companion states each role `roles` lists, in its
    order, by the same name, its provisions naming exactly the fields `roles` gives
    it. Content check over the distribution's own companion."""
    stated = _companion_roles(documents.path(documents.COMPANION).read_text("utf-8"))

    assert stated == [(role.name, set(role.fields)) for role in config.ROLES]


def test_a_roles_fields_are_the_configurations() -> None:
    """Each field a role names is a key of a table the configuration defines, a
    `<step>` key every step's, so a role never names a field no repository can
    declare."""
    def defined(field: str) -> bool:
        table, _, rest = field.partition(".")
        key = rest.split(".")[0]
        keys = TABLES.get(table, set())
        return set(config.STEPS) <= keys if key == "<step>" else key in keys

    assert [field for role in config.ROLES for field in role.fields if not defined(field)] == []


def test_the_table_of_roles_is_read_under_its_heading_alone() -> None:
    """Only the roles table's rows are read, each provision's configuration fields
    and none of its other code, so a role the two state differently is compared."""
    stated = _companion_roles("### What an adopting repository provides\n\n"
                              "| Role | Used by | Provided through |\n|---|---|---|\n"
                              "| A new role | every step | `hooks.pre-commit` and `run` |\n"
                              "\n#### The engine's own assumptions\n\n| Not | a | role |\n")

    assert stated == [("A new role", {"hooks.pre-commit"})]


def test_an_empty_local_configuration_reads_as_none(tmp_path: Path) -> None:
    configured(tmp_path, COMMITTED)
    _local(tmp_path, "")

    loaded = config.load(tmp_path)

    assert not loaded.local_exists
    assert config.missing(loaded, config.GUIDANCE_ENGINEERING) == [config.GUIDANCE_ENGINEERING]


def test_the_local_configuration_gives_the_models_the_pointer_and_more_writable_paths(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _checkout(tmp_path)
    configured(tmp_path, COMMITTED)
    _engineering(tmp_path)
    _local(tmp_path, '[guidance]\nengineering = { path = "guides/engineering/" }\n'
           + MODELS + '\n[sandbox]\nwritable.common = ["~/.cache/mine"]\n'
           'writable.implement = ["build/"]\n')

    assert main(["config", "--json"], root=tmp_path) == 0

    shown = json.loads(capsys.readouterr().out)
    fields = {entry["field"]: entry for entry in shown["fields"]}
    assert shown["local"] == {"file": ".agents/workflow.local.toml", "exists": True}
    assert fields["models.design"]["status"] == "declared"
    assert fields["sandbox.writable.common"]["value"] == ["~/.cache/shared", "~/.cache/mine"]
    assert fields["sandbox.writable.implement"]["value"] == ["build/"]
    assert shown["guidance"] == {"engineering": {
        "path": str(tmp_path / "guides/engineering")}}
    assert fields["guidance.engineering"]["value"] == shown["guidance"]["engineering"]


@pytest.mark.parametrize("text,named", [
    ("[repository]\nprotected-branches = []\n",
     ".agents/workflow.local.toml declares [repository], which belongs in "
     ".agents/workflow.toml"),
    ("[sandbox]\nprotected = ['x/']\n",
     "declares sandbox.protected, which belongs in .agents/workflow.toml"),
    ("[guidance]\nworkflow = { path = 'x/' }\n",
     "guidance.workflow is no field the workflow defines"),
    ("[colour]\n", "colour is no table the workflow defines"),
    ("[models\n", ".agents/workflow.local.toml is not TOML"),
    ("[sandbox]\nwritable.common = ['.agents/workflow.toml']\n",
     "is or lies under the protected path .agents/workflow.toml"),
    ("[models]\nimplement = { model = 'm' }\n", "models.implement must be a list"),
    ("[models]\nimplement = [{ harness = 'gemini', model = 'm' }]\n",
     "models.implement[0].harness must be one of"),
    ("[models]\norchestrator = { model = 'm', harness = 'claude' }\n",
     "models.orchestrator.harness is no field"),
])
def test_a_malformed_local_configuration_is_refused_naming_the_field(
        tmp_path: Path, text: str, named: str) -> None:
    configured(tmp_path, COMMITTED, local=None)
    _local(tmp_path, text)

    with pytest.raises(ConfigError) as refused:
        config.load(tmp_path)
    assert named in str(refused.value)


def test_a_local_writable_path_under_a_committed_protected_path_is_refused(
        tmp_path: Path) -> None:
    configured(tmp_path, '[sandbox]\nprotected = ["secrets/"]\n')
    _local(tmp_path, '[sandbox]\nwritable.common = ["secrets/cache/"]\n')

    with pytest.raises(ConfigError, match="lies under the protected path secrets/"):
        config.load(tmp_path)


# The engineering-guidance pointer.

def test_a_developer_points_at_the_repositorys_engineering_guidance(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """CW-hu0z's first scenario: `config load plan` prints the pointer's Markdown
    files first, then the workflow's guidance, then the repository's; `config
    --json` gives the pointer's absolute directory."""
    _checkout(tmp_path)
    configured(tmp_path, '[load]\ncommon = ["AGENTS.md"]\nplan = ["PLAN.md"]\n')
    _engineering(tmp_path, "docs/guidance/engineering")
    _local(tmp_path, '[guidance]\nengineering = { path = "docs/guidance/engineering/" }\n')

    assert main(["config", "load", "plan"], root=tmp_path) == 0
    assert capsys.readouterr().out.splitlines() == [
        "docs/guidance/engineering/imports/at-module-level.md",
        "docs/guidance/engineering/tests.md", *WORKFLOW_GUIDANCE, "AGENTS.md", "PLAN.md"]
    assert main(["config", "--json"], root=tmp_path) == 0
    assert json.loads(capsys.readouterr().out)["guidance"]["engineering"] == {
        "path": str(tmp_path / "docs/guidance/engineering")}


def test_a_pointer_from_home_is_printed_whole(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _engineering(home, ".guidance")
    checked = configuration_checked("", tmp_path / "repo/.agents/workflow.toml",
                                    root=tmp_path / "repo", home=home,
                                    local='[guidance]\nengineering = { path = "~/.guidance/" }\n')

    assert checked.engineering == config.Engineering(entry="~/.guidance/",
                                                     path=home / ".guidance")
    assert checked.documents("plan", tmp_path / "repo")[:2] == [
        str(home / ".guidance/imports/at-module-level.md"), str(home / ".guidance/tests.md")]


def test_a_repository_applies_no_engineering_guidance(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """CW-hu0z's second scenario."""
    _checkout(tmp_path)
    configured(tmp_path, '[load]\ncommon = ["AGENTS.md"]\n')
    _local(tmp_path, "[guidance]\nengineering = { none = \"the workflow's own repository "
           "applies only its guidance\" }\n")

    assert main(["config", "load", "plan"], root=tmp_path) == 0
    assert capsys.readouterr().out.splitlines() == [*WORKFLOW_GUIDANCE, "AGENTS.md"]
    assert main(["config", "--json"], root=tmp_path) == 0
    assert json.loads(capsys.readouterr().out)["guidance"]["engineering"] == {
        "none": "the workflow's own repository applies only its guidance"}


@pytest.mark.parametrize("pointer,named", [
    ('{ path = "guides/missing/" }', "guidance.engineering names guides/missing/, which "
                                     "does not exist"),
    ('{ path = "guides/file.md" }', "guidance.engineering names guides/file.md, which is a "
                                    "file"),
    ('{ path = "guides/empty/" }', "guidance.engineering names guides/empty/, which holds no "
                                   "Markdown file"),
    ('{ none = " " }', "guidance.engineering declares none without a reason"),
    ('{ path = "guides/engineering/", none = "x" }',
     "guidance.engineering must be a table holding exactly one of path"),
    ('{ distribution = "arkhai-engineering-guidance" }',
     "guidance.engineering must be a table holding exactly one of path"),
    ('"guides/engineering/"', "guidance.engineering must be a table holding exactly one"),
    ('{ path = "/etc/guidance/" }', "guidance.engineering.path must be a directory from the "
                                    "checkout's root or from `~`"),
])
def test_a_pointer_that_names_no_guidance_is_refused(tmp_path: Path, pointer: str,
                                                     named: str) -> None:
    _engineering(tmp_path)
    (tmp_path / "guides/file.md").write_text("# x\n", "utf-8")
    (tmp_path / "guides/empty").mkdir()
    (tmp_path / "guides/empty/notes.txt").write_text("x\n", "utf-8")
    _local(tmp_path, f"[guidance]\nengineering = {pointer}\n")

    with pytest.raises(ConfigError) as refused:
        config.load(tmp_path)
    assert named in str(refused.value)


@pytest.mark.parametrize("entry", ["docs/guidance/", "docs/guidance/engineering/",
                                   "docs/guidance/engineering/tests.md",
                                   "docs/guidance/engineering/imports/"])
def test_a_load_entry_repeats_the_pointer(tmp_path: Path, entry: str) -> None:
    """CW-hu0z's third scenario, and the entries that are the pointer's directory or
    lie beneath it: the check refuses, naming the entry and the pointer."""
    configured(tmp_path, f'[load]\ncommon = ["AGENTS.md", "{entry}"]\n')
    _engineering(tmp_path, "docs/guidance/engineering")
    _local(tmp_path, '[guidance]\nengineering = { path = "docs/guidance/engineering/" }\n')

    with pytest.raises(ConfigError) as refused:
        config.load(tmp_path)
    assert (f"load.common names {entry}, which overlaps the directory "
            "docs/guidance/engineering/ that guidance.engineering points at") in str(refused.value)


def test_a_load_entry_beside_the_pointer_is_admitted(tmp_path: Path) -> None:
    configured(tmp_path, '[load]\ncommon = ["docs/guidance/repository/", "docs/guidance.md"]\n')
    _engineering(tmp_path, "docs/guidance/engineering")
    _engineering(tmp_path, "docs/guidance/repository")
    _local(tmp_path, '[guidance]\nengineering = { path = "docs/guidance/engineering/" }\n')

    assert config.load(tmp_path).engineering is not None


def test_this_repositorys_template_is_read_as_a_local_configuration(tmp_path: Path) -> None:
    """MCW-iqh1: the template points at `docs/guidance/engineering/` and names a model
    for every step and the orchestrating session; it is read whole beside this
    repository's committed configuration."""
    template = (REPOSITORY / ".agents/workflow.local.template.toml").read_text("utf-8")
    committed = (REPOSITORY / config.CONFIGURATION).read_text("utf-8")

    checked = config.check(committed, REPOSITORY / config.CONFIGURATION, root=REPOSITORY,
                           local=template)

    assert checked.engineering == config.Engineering(
        entry="docs/guidance/engineering/", path=REPOSITORY / "docs/guidance/engineering")
    assert set(checked.models) == {*config.STEPS, "orchestrator"}
    assert config.missing(checked, *(f"models.{step}" for step in config.STEPS),
                          config.GUIDANCE_ENGINEERING) == []


def test_the_local_configuration_is_ignored_by_git() -> None:
    ignored = subprocess.run(["git", "check-ignore", ".agents/workflow.local.toml"],
                             cwd=REPOSITORY, capture_output=True, text=True)

    assert ignored.stdout == ".agents/workflow.local.toml\n"
    assert subprocess.run(["git", "check-ignore", "-q", ".agents/workflow.local.template.toml"],
                          cwd=REPOSITORY).returncode == 1


# The shape enforced: each key in its one file, the range and the pointer required.

def test_models_are_committed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """CW-4pm4's "Models are committed": every subcommand reading the configuration
    refuses, naming the local file as where `[models]` belongs."""
    _checkout(tmp_path)
    configured(tmp_path, CONFIGURED + MODELS)

    for command in (["config", "--json"], ["check", "config"], ["config", "load", "design"]):
        assert main(command, root=tmp_path) == 1
        assert (".agents/workflow.toml declares [models], which belongs in "
                ".agents/workflow.local.toml") in capsys.readouterr().err


def test_no_range_is_declared(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """CW-f8yy's "No range is declared": every subcommand reading the configuration
    refuses, naming the field."""
    _checkout(tmp_path)
    configured(tmp_path, CONFIGURED)
    (tmp_path / config.CONFIGURATION).write_text(
        CONFIGURED.replace(ACCEPTED, ""), "utf-8")

    for command in (["config", "--json"], ["check", "config"], ["config", "load", "plan"]):
        assert main(command, root=tmp_path) == 1
        assert ".agents/workflow.toml declares no workflow.version" in capsys.readouterr().err


def test_with_no_committed_file_no_range_is_asked_for(tmp_path: Path) -> None:
    """A checkout with no committed configuration declares nothing, the range among
    every other committed field, and is not refused for it, a local file beside it or
    not."""
    assert config.load(tmp_path).version_range is None
    _local(tmp_path, LOCAL_CONFIGURED)

    loaded = config.load(tmp_path)

    assert (loaded.exists, loaded.local_exists, loaded.version_range) == (False, True, None)
    assert "design" in loaded.models


def test_ci_checks_the_configuration(tmp_path: Path,
                                     capsys: pytest.CaptureFixture[str]) -> None:
    """CW-4pm4's "CI checks the configuration": with no local file, `check config`
    checks every committed field, reports the local fields as missing, and exits 0."""
    _checkout(tmp_path)
    configured(tmp_path, CONFIGURED, local=None)

    assert main(["check", "config"], root=tmp_path) == 0

    ok, missing = capsys.readouterr().out.splitlines()
    assert ok == "OK: .agents/workflow.toml passes its check."
    assert missing.startswith("MISSING: .agents/workflow.local.toml does not exist, so lacks "
                              "guidance.engineering, models.orchestrator, models.design")
    assert missing.endswith("; a step needing one refuses until `change-workflow install` "
                            "writes the file or they are declared there.")
    (tmp_path / config.CONFIGURATION).write_text(CONFIGURED + "[colour]\n", "utf-8")
    assert main(["check", "config"], root=tmp_path) == 1


def test_a_complete_local_configuration_is_reported_whole(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _checkout(tmp_path)
    configured(tmp_path, CONFIGURED)

    assert main(["check", "config"], root=tmp_path) == 0
    assert capsys.readouterr().out == "OK: .agents/workflow.toml passes its check.\n"


# The engineering sections the shipped skills cite, reported against the pointer.

def _guided(root: Path, files: dict[str, str]) -> Path:
    """`root`, a Git checkout configured, its local pointer naming `guides/`, which
    holds `files`, each path's text."""
    _checkout(root)
    configured(root, CONFIGURED, local='[guidance]\nengineering = { path = "guides/" }\n'
                                       + MODELS)
    for name, text in files.items():
        (root / "guides" / name).parent.mkdir(parents=True, exist_ok=True)
        (root / "guides" / name).write_text(text, "utf-8")
    return root


def test_a_users_guidance_lacks_a_cited_section(tmp_path: Path,
                                                 capsys: pytest.CaptureFixture[str]) -> None:
    """CW-7x0z's scenario: a section a skill cites that no file beneath the pointer
    heads is reported, naming the skills citing it, and `check config` exits 0."""
    _guided(tmp_path, {"rules.md": "# Our rules\n\n## Citations resolve\n"})

    assert main(["check", "config"], root=tmp_path) == 0

    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "OK: .agents/workflow.toml passes its check."
    (imports,) = [line for line in lines if '"Imports go at module level"' in line]
    assert imports.startswith('UNRESOLVED: the engineering guidance\'s section "Imports go at '
                              'module level", which ')
    assert "change-implement" in imports
    assert imports.endswith(" cites, heads no file beneath guides/")
    assert not any('"Citations resolve"' in line for line in lines)


def test_a_cited_section_name_repeats(tmp_path: Path,
                                      capsys: pytest.CaptureFixture[str]) -> None:
    """CW-7x0z's scenario: a cited name two files beneath the pointer each head does
    not resolve, and is reported naming both files; `check config` exits 0."""
    _guided(tmp_path, {"testing.md": "# Testing\n\n## Test levels\n",
                       "levels/test-levels.md": "# Test levels\n"})

    assert main(["check", "config"], root=tmp_path) == 0

    (levels,) = [line for line in capsys.readouterr().out.splitlines()
                 if '"Test levels"' in line]
    assert levels.startswith('AMBIGUOUS: the engineering guidance\'s section "Test levels", '
                             "which ")
    assert "change-implement" in levels
    assert levels.endswith(" cites, heads a section in each of guides/levels/test-levels.md, "
                           "guides/testing.md, so the citation names none of them")


def test_a_pointer_applying_none_reports_no_cited_section(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _checkout(tmp_path)
    configured(tmp_path, CONFIGURED)

    assert main(["check", "config"], root=tmp_path) == 0
    shown = capsys.readouterr().out
    assert "UNRESOLVED" not in shown and "AMBIGUOUS" not in shown
