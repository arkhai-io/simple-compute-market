"""The repository's workflow configuration, `change_workflow.config`: its check, its
fields' kinds, how they resolved, a step's documents, and validation's plan."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from change_workflow import config
from change_workflow.cli import main
from change_workflow.config import ConfigError
from change_workflow.next_step import TASKS_FILE
from change_workflow.tasks import owed_lines
from change_workflow_fixtures import (CHANGE, CONFIGURED, MODELS, VALID, FakeClaude, configured,
                                      event_lines, make_wrapper)

REPOSITORY = Path(__file__).resolve().parents[2]


def _checked(text: str) -> config.Configuration:
    return config.check(text, Path("workflow.toml"))


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
    ("[validation.parts.local]\n", "validation.parts.local declares `run`, or `start` and "
                                   "`collect`, and not both shapes; it declares neither"),
    ("[validation.parts.local]\nrun = 'a'\nstart = 'b'\ncollect = 'c'\n",
     "it declares run, start, collect"),
    ("[validation.parts.pipeline]\nstart = 'b'\n", "it declares start"),
    ("[validation.parts.local]\nrun = []\n", "validation.parts.local.run must name a command"),
    ("[validation.parts.preflight]\nrun = 'a'\n", "no part takes the name"),
    ("[validation.parts.local]\nrun = 'a'\nretries = 2\n",
     "validation.parts.local.retries is no field"),
    ("[validation.parts.local]\nrun = 'a'\nowed = 'yes'\n",
     "validation.parts.local.owed must be true or false"),
    ("[validation.parts.helm]\nrun = 'a'\nafter = 'local'\n",
     "validation.parts.helm.after names 'local', which is no other declared part"),
    ("[validation.parts.helm]\nrun = 'a'\nafter = 'helm'\n", "which is no other declared part"),
    # Validation keeps declaration order, so a part follows only one declared before it,
    # which also refuses every cycle.
    ("[validation.parts.helm]\nrun = 'a'\nafter = 'local'\n[validation.parts.local]\nrun = 'b'\n",
     "validation.parts.helm.after names 'local', which is declared after it"),
    ("[validation.parts.a]\nrun = 'x'\nafter = 'b'\n[validation.parts.b]\nrun = 'y'\n"
     "after = 'a'\n", "validation.parts.a.after names 'b', which is declared after it"),
    # Every dispatch starts before any long part runs.
    ("[validation.parts.local]\nrun = 'a'\n[validation.parts.pipeline]\nstart = 'b'\n"
     "collect = 'c'\nafter = 'local'\n",
     "validation.parts.pipeline.after names 'local', a `run` part"),
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
    ("[validation.parts.local]\nrun = 'make WORKFLOW={owed}'\n",
     "validation.parts.local.run names {owed}, which is not available there"),
    ("[validation.parts.ci]\nowed = true\nstart = 'make run-ci W={owed} AFTER={after}'\n"
     "collect = 'make collect AFTER={after}'\n",
     "validation.parts.ci.start names {after}, which is not available there"),
    ("[validation.parts.ci]\nowed = true\nstart = 'a'\ncollect = 'b'\n"
     "cleanup = 'make clean W={owed}'\n",
     "validation.parts.ci.cleanup names {owed}, which is not available there"),
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


def test_a_part_may_follow_an_earlier_part_validation_can_keep_it_after() -> None:
    """CW-g4oz: a dispatch after an earlier dispatch, and a long part after an earlier
    part of either shape, keep declaration order and the dispatches-first rule."""
    checked = _checked("""
[validation.parts.pipeline]
start = "a"
collect = "b"

[validation.parts.ci]
start = "c"
collect = "d"
after = "pipeline"

[validation.parts.local]
run = "e"
after = "ci"

[validation.parts.helm]
run = "f"
after = "local"
""")
    assert [(part.name, part.after) for part in checked.parts or ()] == [
        ("pipeline", None), ("ci", "pipeline"), ("local", "ci"), ("helm", "local")]


def test_placeholders_fill_where_they_are_available_and_the_shells_own_pass() -> None:
    checked = _checked("""
[hooks]
pre-push = "make pre-push REMOTE={remote}"
pre-commit = ["echo ${HOME}", "awk '{print $1}' x", "make check CHANGE={change} BASE={base}"]

[validation.parts.ci]
owed = true
start = "make run-ci WORKFLOW={owed}"
collect = "make validate-ci WORKFLOW={owed} AFTER={after}"
""")

    assert checked.hook("pre-commit") == ("echo ${HOME}", "awk '{print $1}' x",
                                          "make check CHANGE={change} BASE={base}")
    assert checked.part("ci").owed


@pytest.mark.parametrize("command", [["config"], ["config", "--json"], ["check", "config"],
                                     ["config", "load", "design"],
                                     ["config", "parts", CHANGE]])
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
    assert config.missing(loaded, config.PRE_COMMIT_FUNCTIONAL, config.PARTS,
                          config.PROTECTED_BRANCHES, "models.implement") == [
        "hooks.pre-commit-functional", "validation.parts", "repository.protected-branches",
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


def test_validation_needs_one_part_however_empty_its_table(tmp_path: Path) -> None:
    checked = _checked("[validation]\nparts = {}\n")

    with pytest.raises(ConfigError, match="validate needs .*validation.parts"):
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

[validation.parts.helm]
run = "make validate-helm CHANGE={change}"
cleanup = ["make teardown"]
""")

    assert main(["config", "--json"], root=tmp_path) == 0

    shown = json.loads(capsys.readouterr().out)
    fields = {entry["field"]: entry for entry in shown["fields"]}
    assert (shown["file"], shown["exists"]) == (".agents/workflow.toml", True)
    assert fields["repository.protected-branches"] == {
        "field": "repository.protected-branches", "status": "declared", "value": []}
    assert fields["repository.inert-paths"] == {"field": "repository.inert-paths",
                                                "status": "absent"}
    assert fields["hooks.pre-commit-functional"]["value"] == ["make test"]
    assert fields["defaults.skills"] == {"field": "defaults.skills", "status": "disabled",
                                         "reason": "this repository keeps no agent skills"}
    assert fields["defaults.openspec"]["status"] == "default"
    assert fields["defaults.openspec"]["value"].startswith("openspec validate <change> --strict")
    assert fields["defaults.tasks"]["value"] == "scripts/change-workflow check tasks <change>"
    assert fields["openspec.command"] == {"field": "openspec.command", "status": "default",
                                          "value": "openspec"}
    assert fields["validation.parts.helm.cleanup"]["value"] == ["make teardown"]
    assert fields["validation.parts.helm.after"]["status"] == "absent"
    assert fields["models.implement"]["status"] == "absent"
    assert fields["review.format-retries"] == {"field": "review.format-retries",
                                               "status": "default", "value": 1}


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


# `config parts <change>`: validation's plan.

PARTS = """
[validation]
preflight = "make check-uv-version"

[validation.parts.pipeline]
start = "make run-e2e"
collect = "make fetch-e2e-logs E2E_AFTER_RUN={after}"
evidence = ".snapshot/e2e-logs/"

[validation.parts.ci]
owed = true
start = "make run-ci WORKFLOW={owed}"
collect = "make validate-ci WORKFLOW={owed} CI_AFTER_RUN={after}"
evidence = ".snapshot/validation/"

[validation.parts.local]
run = "make validate-local"
evidence = ".snapshot/validation/"

[validation.parts.helm]
after = "local"
run = "make validate-helm CHANGE={change}"
evidence = ".snapshot/validation/"
"""

TASKS = """# Tasks

## 1. Hooks

- [x] 1.1 Run them.
- [x] 1.2 Verification: the suite passes. End-to-end: none.
  Owed by validation: `ci.yml`, job `lint` — passes.

## 2. Images

- [x] 2.1 Build them.

Owed by validation: `docker.yml`, job `build` — builds.

## 3. Charts

- [ ] 3.1 Render them.
  Owed by validation: `helm.yml`, job `render` — renders.

## 4. Closeout

- [ ] 4.1 Archive.
"""


def _change(root: Path, tasks: str) -> None:
    directory = root / "openspec/changes" / CHANGE
    directory.mkdir(parents=True)
    (directory / TASKS_FILE).write_text(tasks, "utf-8")


def test_two_sections_owe_ci_workflows(tmp_path: Path,
                                       capsys: pytest.CaptureFixture[str]) -> None:
    """CW-g4oz: the `ci` part listed twice, by workflow; an owed line under an
    incomplete section owes nothing yet."""
    configured(tmp_path, PARTS)
    _change(tmp_path, TASKS)

    assert main(["config", "parts", CHANGE, "--json"], root=tmp_path) == 0

    shown = json.loads(capsys.readouterr().out)
    assert shown["preflight"] == ["make check-uv-version"]
    assert [(run["name"], run["shape"], run["after"], run["sections"])
            for run in shown["runs"]] == [
        ("pipeline", "start-collect", None, []),
        ("ci ci.yml", "start-collect", None, ["1"]),
        ("ci docker.yml", "start-collect", None, ["2"]),
        ("local", "run", None, []),
        ("helm", "run", "local", []),
    ]
    assert shown["runs"][1]["owed"] == "ci.yml"
    assert shown["runs"][0]["evidence"] == ".snapshot/e2e-logs/"


def test_the_plan_reads_as_lines(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    configured(tmp_path, PARTS)
    _change(tmp_path, TASKS)

    assert main(["config", "parts", CHANGE], root=tmp_path) == 0

    assert [line.split() for line in capsys.readouterr().out.splitlines()] == [
        ["preflight", "make", "check-uv-version"],
        ["pipeline", "start,", "collect", "evidence", ".snapshot/e2e-logs/"],
        ["ci", "ci.yml", "start,", "collect", "owed", "by", "section", "1", "evidence",
         ".snapshot/validation/"],
        ["ci", "docker.yml", "start,", "collect", "owed", "by", "section", "2", "evidence",
         ".snapshot/validation/"],
        ["local", "run", "evidence", ".snapshot/validation/"],
        ["helm", "run", "after", "local", "evidence", ".snapshot/validation/"],
    ]


def test_no_section_owes_ci_evidence(tmp_path: Path,
                                     capsys: pytest.CaptureFixture[str]) -> None:
    """CW-g4oz: an owed part with no owing complete section is listed not owed."""
    configured(tmp_path, PARTS)
    _change(tmp_path, "# Tasks\n\n## 1. Hooks\n\n- [x] 1.1 Run them.\n")

    assert main(["config", "parts", CHANGE, "--json"], root=tmp_path) == 0

    runs = json.loads(capsys.readouterr().out)["runs"]
    assert [(run["name"], run["not_owed"]) for run in runs] == [
        ("pipeline", False), ("ci", True), ("local", False), ("helm", False)]


def test_two_lines_owing_one_workflow_are_one_run(tmp_path: Path) -> None:
    tasks = tmp_path / TASKS_FILE
    tasks.write_text("## 1. A\n\n- [x] 1.1 x.\n  Owed by validation: `ci.yml`, job a\n\n"
                     "## 2. B\n\n- [x] 2.1 y.\n  Owed by validation: `ci.yml`, job b\n", "utf-8")

    runs = config.plan(_checked(PARTS), owed_lines(tasks))

    assert [(run.name, run.sections) for run in runs if run.part.owed] == [
        ("ci ci.yml", ("1", "2"))]


def test_a_plan_without_parts_is_refused(tmp_path: Path,
                                         capsys: pytest.CaptureFixture[str]) -> None:
    _change(tmp_path, TASKS)

    assert main(["config", "parts", CHANGE], root=tmp_path) == 1

    assert "validation needs validation.parts" in capsys.readouterr().err


def test_the_repositorys_own_configuration_passes_its_check(
        capsys: pytest.CaptureFixture[str]) -> None:
    loaded = config.load(REPOSITORY)

    assert loaded.exists
    assert config.missing(loaded, config.PRE_COMMIT_FUNCTIONAL, config.PARTS,
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
    operation or the skill that uses its fields; each validation part has one
    saying what it is, under the comment naming who runs the parts."""
    text = (REPOSITORY / config.CONFIGURATION).read_text("utf-8")
    lines = text.splitlines()
    users = ("Engine", "engine", "change-")
    assert "for change-validate: validation's parts" in text
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
        if line.startswith("[validation.parts."):
            assert below, line
        else:
            assert any(user in comment for comment in above + below for user in users), line


def test_validation_runs_this_repositorys_parts(tmp_path: Path,
                                               capsys: pytest.CaptureFixture[str]) -> None:
    """MCW-r4tx: with a complete section owing `tests.yml`, the plan starts the
    pipeline and the owed CI run, then runs the local part, then the Helm part after
    it, from this repository's own file."""
    configured(tmp_path, (REPOSITORY / config.CONFIGURATION).read_text("utf-8"))
    _change(tmp_path, "## 1. A section\n\n- [x] 1.1 Done.\n  - Owed by validation: "
                      "`tests.yml`, job `py`, its suite passing.\n")

    assert main(["config", "parts", CHANGE, "--json"], root=tmp_path) == 0

    shown = json.loads(capsys.readouterr().out)
    assert shown["preflight"] == ["make check-uv-version"]
    assert [(run["name"], run["shape"], run["after"]) for run in shown["runs"]] == [
        ("pipeline", "start-collect", None),
        ("ci tests.yml", "start-collect", None),
        ("local", "run", None),
        ("helm", "run", "local"),
    ]
