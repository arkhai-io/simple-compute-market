"""The repository's workflow configuration, `change_workflow.config`: its check, its
fields' kinds, its evidence kinds, how they resolved, and a step's documents."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from change_workflow import config
from change_workflow.cli import main
from change_workflow.config import ConfigError
from change_workflow_fixtures import (CHANGE, CONFIGURED, MODELS, VALID, FakeClaude, configured,
                                      event_lines, evidence_kind, make_wrapper)

REPOSITORY = Path(__file__).resolve().parents[2]


def _checked(text: str) -> config.Configuration:
    return config.check(text, Path("workflow.toml"))


def _every_directory_ignored(root: Path, directories: list[str]) -> list[str]:
    return []


def _kinds_checked(root: Path, text: str,
                   unignored: config.Unignored = _every_directory_ignored
                   ) -> config.Configuration:
    """`text` checked as the configuration of a repository at `root` holding every
    test kind's guide, Git's ignoring doubled by `unignored`."""
    configured(root, text)
    return config.check(text, root / config.CONFIGURATION, unignored=unignored)


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
    ("[models]\nimplement = { model = 'm' }\n", "models.implement must be a list"),
    ("[models]\nimplement = [{ harness = 'gemini', model = 'm' }]\n",
     "models.implement[0].harness must be one of"),
    ("[models]\norchestrator = { model = 'm', harness = 'claude' }\n",
     "models.orchestrator.harness is no field"),
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
        config.check(text, tmp_path / config.CONFIGURATION, unignored=_every_directory_ignored)

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


def test_with_no_file_every_step_is_refused_its_protected_branches_and_models(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    claude = FakeClaude((event_lines(VALID["finished"]), 0))
    wrapper = make_wrapper(tmp_path, claude)
    (tmp_path / ".agents/workflow.toml").unlink()

    assert main(["start", "design", CHANGE, "--unattended"], root=tmp_path,
                wrapper=wrapper) == 1

    assert ("design needs repository.protected-branches, models.design, which "
            ".agents/workflow.toml does not declare (there is no such file)"
            in capsys.readouterr().err)
    assert claude.commands == []


def test_validation_needs_one_kind_however_empty_its_table(tmp_path: Path) -> None:
    checked = _checked("[validation]\nevidence = {}\n")

    with pytest.raises(ConfigError, match="validate needs .*validation.evidence"):
        config.require_for_step(checked, "validate")


def test_an_interactive_step_needs_no_models(tmp_path: Path) -> None:
    """Only an unattended run runs on the configured models; the owner's interactive
    session runs on their own."""
    checked = _checked(CONFIGURED.replace(MODELS, ""))

    config.require_for_step(checked, "implement")
    with pytest.raises(ConfigError, match="models.implement"):
        config.require_for_step(checked, "implement", unattended=True)
    with pytest.raises(ConfigError, match="models.orchestrator"):
        config.require_for_step(checked, "orchestrate")


def test_a_fable_model_is_accepted() -> None:
    """A repository that never wants a model does not list it; none is forbidden."""
    checked = _checked('[models]\nimplement = [{ harness = "claude", '
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

""" + evidence_kind("helm", run="make validate-helm CHANGE={change}", cleanup=["make teardown"]))

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
    assert fields["defaults.tasks"]["value"] == "scripts/change-workflow check tasks <change>"
    assert fields["openspec.command"] == {"field": "openspec.command", "status": "default",
                                          "value": "openspec"}
    assert fields["validation.evidence.helm.cleanup"]["value"] == ["make teardown"]
    assert fields["validation.evidence.helm.after"]["status"] == "absent"
    assert fields["validation.evidence.helm.required"]["value"] == "always"
    assert fields["models.implement"]["status"] == "absent"
    assert fields["review.format-retries"] == {"field": "review.format-retries",
                                               "status": "default", "value": 1}


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
        "AGENTS.md", "openspec/README.md", "docs/development/ROADMAP.md"]
    assert main(["config", "load", "plan"], root=tmp_path) == 0
    assert capsys.readouterr().out.splitlines() == ["AGENTS.md", "openspec/README.md"]


def test_config_load_takes_a_step(tmp_path: Path) -> None:
    assert main(["config", "load", "deploy"], root=tmp_path) == 2
    assert main(["config", "load"], root=tmp_path) == 2


def test_a_session_that_is_no_step_loads_the_common_documents(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The orchestrating session and a guidance review run no step of the graph, so
    `config load common` prints `load.common` alone for them."""
    configured(tmp_path, """
[load]
common = ["AGENTS.md", "openspec/README.md"]
design = ["docs/development/ROADMAP.md"]
""")

    assert main(["config", "load", "common"], root=tmp_path) == 0
    assert capsys.readouterr().out.splitlines() == ["AGENTS.md", "openspec/README.md"]


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

    assert capsys.readouterr().out.splitlines() == ["AGENTS.md", "docs/missing.md"]


def test_an_absent_or_empty_list_loads_nothing(tmp_path: Path) -> None:
    assert config.load(tmp_path).documents("design", tmp_path) == []
    assert _checked("[load]\ncommon = []\n").documents("design", tmp_path) == []


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
    loaded = config.load(REPOSITORY)

    assert loaded.exists
    assert config.missing(loaded, config.PRE_COMMIT_FUNCTIONAL, config.EVIDENCE,
                          config.PROTECTED_BRANCHES, f"models.{config.ORCHESTRATOR}",
                          *(f"models.{step}" for step in config.STEPS)) == []
    assert main(["check", "config"], root=REPOSITORY) == 0
    assert "passes its check" in capsys.readouterr().out


def test_the_repository_declares_every_hook() -> None:
    """MCW-r4tx: this repository relocks after a functional change, runs its own
    closing checks before every commit, clears the wheelhouse, checks packaging and
    runs every suite before a functional commit, checks packaging and the change's
    architecture rows before the archive, and runs its pre-push checks as one
    target."""
    loaded = config.load(REPOSITORY)

    assert loaded.hook("after-functional-change") == ("make lock",)
    assert loaded.hook("pre-commit") == (
        "make check-repository CHANGE={change} CHANGE_BASE={base}",)
    assert loaded.hook("pre-commit-functional") == ("make dist-clean", "make check-packaging",
                                                    "make test")
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
