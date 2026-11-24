"""How this repository provides the change workflow: its committed configuration, its
local configuration template, its Makefile's own targets beside the workflow's
fragment, and its settings' post-compaction hook (`market-change-workflow`).

The workflow is reached only through its command (CW-r3ka), so nothing here imports
the engine. A test of a local field, or of what one changes, runs the command in
`installed`, a checkout holding this repository's configuration and the documents it
names, its local configuration written from the committed template as `change-workflow
install` writes it, so neither a developer's own local file nor CI's missing one is
read. A test of the Makefile dry-runs the root Makefile; one of the hook runs the
command the project's settings name, as Claude Code does.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

import workflow_command

ROOT = Path(__file__).resolve().parents[2]
CONFIGURATION = ".agents/workflow.toml"
TEMPLATE = ".agents/workflow.local.template.toml"
LOCAL = ".agents/workflow.local.toml"
# What the configuration names, copied into the installed checkout: its evidence
# guides, the documents `load` names, the engineering guidance the template points
# at, and the settings whose hook re-reads them.
COPIED = (".agents/evidence", ".gitignore", ".claude/settings.json", "AGENTS.md",
          "openspec/README.md", "docs/guidance", "docs/development/ARCHITECTURE.md",
          "docs/development/TESTING.md", "docs/development/DEPLOYMENT_AND_CONFIG.md",
          "docs/development/ROADMAP.md")
STEPS = ("design", "plan", "implement", "review", "triage", "merge", "closeout",
         "validate", "archive-cleanup")
OPUS = {"harness": "claude", "model": "claude-opus-5-5", "effort": "high"}
SONNET = {"harness": "claude", "model": "claude-sonnet-5-5", "effort": "medium"}


@pytest.fixture(scope="module")
def installed(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A checkout of this repository's configuration as `change-workflow install`
    leaves it: the committed file, the template as the local file, and what they
    name; its home directory beside it."""
    root = tmp_path_factory.mktemp("installed") / "checkout"
    for name in (CONFIGURATION, TEMPLATE, *COPIED):
        source, target = ROOT / name, root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
    shutil.copy2(ROOT / TEMPLATE, root / LOCAL)
    (root.parent / "home").mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    return root


def _command(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    """The workflow's command run in `root`, its home the installed checkout's."""
    environ = {**os.environ, "HOME": str(root.parent / "home")}
    return subprocess.run([str(workflow_command.COMMAND), *arguments], cwd=root,
                          env=environ, stdin=subprocess.DEVNULL, capture_output=True,
                          text=True, check=False)


def _resolved(root: Path) -> dict[str, Any]:
    done = _command(root, "config", "--json")
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def _fields(root: Path) -> dict[str, Any]:
    """Each field `config --json` resolves, by name, to its value."""
    return {entry["field"]: entry.get("value") for entry in _resolved(root)["fields"]}


# The configuration.

def test_the_repositorys_own_configuration_passes_its_check(installed: Path) -> None:
    done = _command(installed, "check", "config")

    assert done.returncode == 0, done.stderr
    assert "passes its check" in done.stdout
    assert _fields(installed)["repository.protected-branches"] == ["main", "dev"]


def test_this_repositorys_template_is_read_as_a_local_configuration(installed: Path) -> None:
    """MCW-iqh1: the template points at `docs/guidance/engineering/` and names a model
    for every step and the orchestrating session; read whole beside the committed
    configuration, it leaves no field missing."""
    resolved = _resolved(installed)

    assert resolved["local"] == {"file": LOCAL, "exists": True}
    assert resolved["guidance"]["engineering"] == {
        "path": str(installed / "docs/guidance/engineering")}
    assert [entry["field"] for entry in resolved["fields"]
            if entry["status"] == "missing"] == []


def test_the_local_configuration_is_ignored_by_git() -> None:
    ignored = subprocess.run(["git", "check-ignore", LOCAL], cwd=ROOT, capture_output=True,
                             text=True)

    assert ignored.stdout == f"{LOCAL}\n"
    assert subprocess.run(["git", "check-ignore", "-q", TEMPLATE], cwd=ROOT).returncode == 1


def test_each_step_runs_on_the_models_its_work_needs(installed: Path) -> None:
    """Design, planning, triage, implementation, the merge, and closeout on Opus at
    high effort; validation and archive cleanup on Sonnet at medium; the review on
    Codex, then Claude."""
    fields = _fields(installed)

    assert {step: fields[f"models.{step}"] for step in STEPS} == {
        "design": [OPUS], "plan": [OPUS], "triage": [OPUS], "implement": [OPUS],
        "merge": [OPUS], "closeout": [OPUS], "validate": [SONNET],
        "archive-cleanup": [SONNET],
        "review": [{"harness": "codex", "model": "gpt-6-sol", "effort": "high"}, OPUS]}


def test_this_repositorys_orchestrator_is_opus_at_medium_effort(installed: Path) -> None:
    # The orchestrating session relays and routes rather than judging: it needs a
    # large context for a change's relayed turns, not a high effort.
    assert _fields(installed)["models.orchestrator"] == {
        "model": "claude-opus-5-5", "effort": "medium"}


def test_the_repository_declares_every_hook(installed: Path) -> None:
    """MCW-r4tx: this repository relocks after a functional change, runs its own
    closing checks before every commit, clears the wheelhouse, checks packaging and
    runs every suite before a functional commit — the local kind's own run, so it
    leaves `local` evidence for the tree it tested — checks packaging and the
    change's architecture rows before the archive, and runs its pre-push checks as
    one target."""
    fields = _fields(installed)

    assert fields["hooks.after-functional-change"] == ["make lock"]
    assert fields["hooks.pre-commit"] == [
        "make check-repository CHANGE={change} CHANGE_BASE={base}"]
    assert fields["hooks.pre-commit-functional"] == ["make validate-local TREE={tree}"]
    assert fields["hooks.pre-commit-functional"] == fields["validation.evidence.local.run"]
    assert fields["hooks.pre-archive"] == ["make check-packaging",
                                           "make check-architecture-change CHANGE={change}"]
    assert fields["hooks.pre-push"] == ["make pre-push REMOTE={remote}"]
    assert fields["hooks.post-clone"] == ["make init"]


def test_the_repository_declares_its_kinds_for_the_gathering(installed: Path) -> None:
    """MCW-r4tx's kinds, as declared: the uv version's preflight; the pipeline and the
    owed CI run each dispatched by a `start` and collected by a `collect`; and the
    Helm kind after the local kind. The order a gathering runs them in from these
    declarations is the workflow's own to prove, on its fixture kinds."""
    fields = _fields(installed)

    assert fields["validation.preflight"] == ["make check-uv-version"]
    kinds = [name.split(".")[2] for name in fields
             if name.startswith("validation.evidence.") and name.endswith(".required")]
    assert kinds == ["pipeline", "ci", "local", "helm"]
    assert fields["validation.evidence.helm.after"] == "local"
    assert [fields[f"validation.evidence.{kind}.start"][0].split()[1]
            for kind in ("pipeline", "ci")] == ["run-e2e", "run-ci"]
    assert [fields[f"validation.evidence.{kind}.collect"][0].split()[1]
            for kind in ("pipeline", "ci")] == ["fetch-e2e-logs", "validate-ci"]
    assert fields["validation.evidence.ci.required"] == "owed"


def test_every_table_of_the_repositorys_file_says_who_uses_it() -> None:
    """Each table of this repository's file has a comment beside it naming the engine
    operation or the skill that uses its fields; each evidence kind has one saying
    what it is, under the comment naming who runs the kinds."""
    text = (ROOT / CONFIGURATION).read_text("utf-8")
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


# The steps' scopes this configuration gives.

def _writes(scope: dict[str, Any], path: Path) -> bool:
    """Whether a step of `scope` writes the host's `path`: the private `/tmp` is the
    sandbox's own, writing no host path, though the test's home lies under the
    host's `/tmp`."""
    def within(inner: Path, outer: str) -> bool:
        return inner == Path(outer) or Path(outer) in inner.parents

    return (any(within(path, open_["path"]) for open_ in scope["writable"]
                if not open_.get("private"))
            and not any(within(path, guarded["path"]) for guarded in scope["protected"]))


def test_design_and_planning_write_the_repositorys_documents(installed: Path) -> None:
    """MCW-s4bx's "Design edits the roadmap": the configuration gives design `docs/`,
    and planning too, beside their baseline."""
    scopes = _resolved(installed)["scopes"]
    roadmap = installed / "docs/development/ROADMAP.md"

    for step in ("design", "plan"):
        assert _writes(scopes[step], roadmap), step
        assert [path["source"] for path in scopes[step]["writable"]
                if path["path"] == str(installed / "docs")] == ["repository"], step
    assert not _writes(scopes["archive-cleanup"], roadmap)


def test_every_step_writes_the_tool_state_its_suites_and_deployments_need(
        installed: Path) -> None:
    """MCW-s4bx's "Implementation syncs an environment", "Design validates the change"
    and "A review runs the repository's checks": uv's Pythons, and the cluster client's
    cache, the cloud CLI's configuration, Docker's client configuration, and npm's
    cache, which the configured OpenSpec command's `npx` writes, for every step, the
    review included, since each lies outside the checkout; and nothing protected
    beyond the engine's and the adapters'."""
    scopes = _resolved(installed)["scopes"]
    home = installed.parent / "home"
    tools = [home / ".local/share/uv/python", home / ".kube/cache", home / ".config/gcloud",
             home / ".docker", home / ".npm/_cacache", home / ".cache/uv"]

    for step in STEPS:
        assert [_writes(scopes[step], tool) for tool in tools] == [True] * len(tools), step
        assert not any(path["source"] == "repository"
                       for path in scopes[step]["protected"]), step
    assert _fields(installed)["sandbox.protected"] == []


def test_no_step_writes_the_configuration_or_the_harnesss_settings(installed: Path) -> None:
    """Each step's scope, as a run on its first model starts, keeps both
    configuration files and the harness's settings read-only, while a step that
    writes the checkout writes the skills beside the configuration."""
    scopes = _resolved(installed)["scopes"]
    home = installed.parent / "home"
    settings = [installed / CONFIGURATION, installed / LOCAL,
                installed / ".claude/settings.json", installed / ".claude/settings.local.json",
                home / ".claude/settings.json", home / ".codex/config.toml"]

    for step in STEPS:
        assert not any(_writes(scopes[step], path) for path in settings), step
    assert _writes(scopes["implement"], installed / ".agents/skills/change-plan/SKILL.md")


# The documents a session reads, and the hook that re-reads them.

def test_config_load_reads_the_templates_engineering_guidance_and_load_common(
        installed: Path) -> None:
    """With the template's pointer, `config load common` opens with this repository's
    engineering guidance, every Markdown file of `docs/guidance/engineering/`, and
    reaches `load.common`, which opens with `AGENTS.md`, after the documents the
    distribution ships, each document once."""
    done = _command(installed, "config", "load", "common")
    assert done.returncode == 0, done.stderr
    lines = done.stdout.splitlines()

    engineering = sorted(path.relative_to(installed).as_posix() for path in
                         (installed / "docs/guidance/engineering").rglob("*.md"))
    common = lines.index("AGENTS.md")
    assert lines[:len(engineering)] == engineering
    assert len(engineering) < common
    assert all(Path(line).is_absolute() for line in lines[len(engineering):common])
    assert len(lines) == len(set(lines))


def _post_compaction_hook() -> str:
    """The command the project's settings run for the post-compaction hook."""
    settings = json.loads((ROOT / ".claude/settings.json").read_text("utf-8"))
    [entry] = [entry for entry in settings["hooks"]["SessionStart"]
               if entry.get("matcher") == "compact"]
    [hook] = entry["hooks"]
    return hook["command"]


def test_the_post_compaction_hook_describes_the_project_from_any_directory(
        tmp_path: Path) -> None:
    # Claude Code runs the hook from the session's working directory, which may be
    # outside any repository or in another checkout, such as a change's clone; the
    # hook describes the project all the same.
    outside = tmp_path / "outside"
    outside.mkdir()
    other = tmp_path / "other"
    subprocess.run(["git", "init", "-q", "-b", "elsewhere", str(other)], check=True)
    branch = subprocess.run(["git", "branch", "--show-current"], cwd=ROOT,
                            capture_output=True, text=True, check=True).stdout.strip()
    environ = {**os.environ, "CLAUDE_PROJECT_DIR": str(ROOT),
               "GIT_CEILING_DIRECTORIES": str(tmp_path)}
    for where in (outside, other):
        ran = subprocess.run(["sh", "-c", _post_compaction_hook()], cwd=where, env=environ,
                             capture_output=True, text=True, check=False)
        assert (ran.returncode, ran.stderr) == (0, "")
        assert f"Checked-out branch: {branch or '(detached HEAD)'}\n" in ran.stdout


def test_this_repositorys_hook_names_its_configured_documents(installed: Path) -> None:
    loaded = _command(installed, "config", "load", "common")
    hook = _command(installed, "hook", "post-compaction")

    assert loaded.returncode == 0 and hook.returncode == 0, loaded.stderr + hook.stderr
    for document in loaded.stdout.splitlines():
        assert f"- {document}\n" in hook.stdout


# The root Makefile: the workflow's fragment included, beside the repository's own
# targets.

COMMAND = "change-workflow"


def _make_n(*arguments: str) -> list[str]:
    """`make -n` of a target of the root Makefile, with no step variable inherited
    from the caller.

    A make that ran these tests passes its own command-line variables down through
    MAKEFLAGS, so those are dropped too.
    """
    env = {key: value for key, value in os.environ.items()
           if key not in ("UNATTENDED", "SECTION", "SECTIONS", "FRESH", "HELM_ALL_SCENARIOS",
                          "WRITE", "ARGUMENTS", "SESSION_ID", "FROM", "BASE", "BRANCH",
                          "REVIEW_BASE", "REVIEW_MODEL", "REVIEW_EFFORT", "UNVALIDATED",
                          "CHANGE_WORKFLOW", "CHANGE_BASE", "CHANGE",
                          "MAKEFLAGS", "MFLAGS", "MAKEOVERRIDES", "MAKELEVEL")}
    output = subprocess.run(["make", "-n", "--no-print-directory", *arguments], cwd=ROOT,
                            capture_output=True, text=True, check=True, env=env).stdout
    return output.splitlines()


@pytest.mark.parametrize("target,variables,commands", [
    # The fragment's targets are the root Makefile's, calling the installed command.
    ("design", [], [f'{COMMAND} start design "X"']),
    # The owner's complete closing check is the workflow's whole pre-commit, whose
    # hook is this repository's check-repository; each reads the branch the change
    # lands on, which the clone recorded, unless CHANGE_BASE names another.
    ("check-change", [], [f'{COMMAND} run pre-commit "X"']),
    ("check-change", ["CHANGE_BASE=release"], [f'{COMMAND} run pre-commit "X" --base "release"']),
    ("check-repository", [], ['python3 scripts/check_change.py "X"']),
    ("check-repository", ["CHANGE_BASE=release"],
     ['python3 scripts/check_change.py "X" --base "release"']),
    # The workflow's two checks this repository runs alone through its own targets.
    ("check-spec-index", [], [f'{COMMAND} check spec-index "X"']),
    ("check-decision-destinations", [], [f'{COMMAND} check decisions "X"']),
])
def test_the_root_makefile_runs_the_command_through_the_fragment(
        target: str, variables: list[str], commands: list[str]) -> None:
    assert _make_n(target, "CHANGE=X", *variables) == commands


@pytest.mark.parametrize("target,variables,commands", [
    ("run-e2e", [], [f"{COMMAND} check round-view", "python3 scripts/ci_evidence.py pipeline"]),
    ("run-ci", ["WORKFLOW=tests.yml"],
     [f"{COMMAND} check round-view", 'python3 scripts/ci_evidence.py dispatch "tests.yml"']),
    ("pre-push", ["REMOTE=origin"], []),
])
def test_validations_dispatches_and_the_pre_push_checks_run_the_repositorys_scripts(
        target: str, variables: list[str], commands: list[str]) -> None:
    printed = _make_n(target, *variables)

    if commands:
        assert printed == commands
    else:
        assert any("check_public_content.py --pre-push \"origin\"" in line for line in printed)
        assert any("check_secrets.py --pre-push \"origin\"" in line for line in printed)


@pytest.mark.parametrize("target", ["run-e2e", "validate-local", "run-ci"])
def test_a_repository_target_refuses_while_a_round_view_is_open(target: str) -> None:
    # The repository's own targets that read or publish HEAD keep the fragment's
    # round-view check as their first prerequisite.
    assert _make_n(target, "WORKFLOW=tests.yml")[0] == f"{COMMAND} check round-view"
