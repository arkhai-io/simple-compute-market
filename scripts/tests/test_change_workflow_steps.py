"""Each step's unattended run is held to its rules and runs on its models."""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

import pytest

from change_workflow import config, steps
from change_workflow.common import StepError
from change_workflow.graph import HOOK_STEPS, STEPS
from change_workflow.steps import Model, load_steps
from change_workflow_fixtures import CHANGE, OPUS, SONNET

ROOT = Path(__file__).resolve().parents[2]
STEP_TABLE = ROOT / steps.STEP_TABLE

MODELS = 'models = [{ harness = "claude", model = "claude-opus-5-5", effort = "high" }]\n'


def _allows(rules, command: str) -> bool:
    """Whether a Bash command matches an allow rule and no deny rule, by glob."""
    def matches(rule_list) -> bool:
        return any(rule.startswith("Bash(") and fnmatch.fnmatchcase(command, rule[5:-1])
                   for rule in rule_list)
    return matches(rules.allow) and not matches(rules.deny)


def _allows_chain(rules, command: str) -> bool:
    """A chained command runs only when every command in it is allowed."""
    parts = [part.strip() for part in re.split(r"\s*(?:;|&&|\|\||\|)\s*", command)]
    return all(_allows(rules, part) for part in parts if part)


def _allows_edit(rules, tool: str, path: str) -> bool:
    """Whether editing `path` with `tool` matches an allow rule and no deny rule.

    As the harness's rules do: an `Edit` rule, bare or with a pattern, applies to
    every tool that edits a file, `Write` among them; a bare tool name applies to
    that tool; a `Write(pattern)` rule is not honoured, so it matches nothing here
    and no row may rely on one.
    """
    def matches(rule_list) -> bool:
        for rule in rule_list:
            name, _, rest = rule.partition("(")
            if name == "Edit" and fnmatch.fnmatchcase(path, rest[:-1] if rest else "*"):
                return True
            if name == tool and not rest:
                return True
        return False
    return matches(rules.allow) and not matches(rules.deny)


def test_the_step_table_names_each_step() -> None:
    steps = load_steps()

    assert set(steps) == set(STEPS)
    assert all(rules.skill == f"change-{name}" for name, rules in steps.items())
    assert steps["plan"].resume_from == "design"


def test_each_step_runs_on_the_models_its_work_needs() -> None:
    """This repository's configuration: design, triage, implementation, the merge, and
    closeout on Opus at high effort; validation and archive cleanup on Sonnet at
    medium; the review on Codex, then Claude."""
    configuration = config.load(ROOT)
    models = {name: configuration.step_models(name) for name in STEPS}

    assert models == {"design": (OPUS,), "plan": (OPUS,), "triage": (OPUS,),
                      "implement": (OPUS,), "merge": (OPUS,), "closeout": (OPUS,),
                      "validate": (SONNET,),
                      "archive-cleanup": (SONNET,),
                      "review": (Model("codex", "gpt-6-sol", "high"), OPUS)}


def test_a_review_on_claude_only_reads() -> None:
    rules = load_steps()["review"]
    record = f"openspec/changes/{CHANGE}/reviews/09-implementation.md"

    assert _allows(rules, "git diff dev...HEAD") and _allows(rules, "cat AGENTS.md")
    assert not any(_allows_edit(rules, tool, record) for tool in ("Edit", "Write"))
    assert not _allows(rules, "git commit -m x") and not _allows(rules, "make lock")


@pytest.mark.parametrize("reading,writing", [
    ("git diff dev...HEAD", "git diff --output=x dev...HEAD"),
    ("git show HEAD", "git show HEAD --output x"),
    ("git log -p", "git log -p --output=x"),
])
def test_no_step_writes_through_the_diff_familys_output(reading: str, writing: str) -> None:
    for name, rules in load_steps().items():
        assert _allows(rules, reading) and not _allows(rules, writing), name


def test_no_rule_names_a_make_target_the_command_stands_behind() -> None:
    """The fragment's targets carry no promise and a step reaches the workflow through
    the command, so no step's rules name the targets the command stands behind."""
    for name, rules in load_steps().items():
        for command in (f"make change-cost CHANGE={CHANGE}", "make round-view-closed",
                        "make push-branch", f"make change-history CHANGE={CHANGE}"):
            assert not _allows(rules, command), (name, command)


@pytest.mark.parametrize("models,problem", [
    ("[]", "must be a list of one or more models"),
    ('[{ harness = "claude", model = "claude-opus-5-5" }, '
     '{ harness = "claude", model = "claude-sonnet-5-5" }]', "two models of one vendor"),
    ('[{ harness = "claude", effort = "high" }]', r"models.triage\[0\].model must be"),
    ('[{ harness = "codex", model = "gpt-6-sol" }]', "Codex runs only the review"),
    ('[{ harness = "gemini", model = "g" }]', r"harness must be one of claude, codex"),
    ('[{ harness = "claude", model = "m", speed = "fast" }]', "speed is no field"),
])
def test_models_the_policy_forbids_are_refused_naming_the_step(models: str,
                                                                problem: str) -> None:
    """CW-zq4h: the configuration's models are held to the policy as it is read."""
    with pytest.raises(StepError, match=problem) as refused:
        config.check(f"[models]\ntriage = {models}\n", Path("workflow.toml"))

    assert "models.triage" in str(refused.value)


def test_a_row_names_two_models_of_one_vendor() -> None:
    """CW-zq4h's scenario: the engine refuses the configuration, naming the step."""
    with pytest.raises(StepError, match="for the review step"):
        config.check('[models]\nreview = [{ harness = "codex", model = "gpt-6-sol" }, '
                     '{ harness = "codex", model = "gpt-6-luna" }]\n', Path("workflow.toml"))


def test_the_step_table_holds_no_models() -> None:
    """The step table names each step's skill and rules; models are the
    configuration's."""
    assert not hasattr(load_steps()["design"], "models")


@pytest.mark.parametrize("table,field", [
    (f'[steps.design]\nskill = "change-design"\n{MODELS}', "models.design"),
    ('[orchestrator]\nmodel = "claude-opus-5-5"\neffort = "medium"\n'
     '[steps.design]\nskill = "change-design"\n', "models.orchestrator"),
])
def test_models_in_the_step_table_are_refused_naming_the_configurations_field(
        tmp_path: Path, table: str, field: str) -> None:
    """A model left in the step table is a value nothing reads, so the loader refuses
    it, naming where the configuration holds it."""
    path = tmp_path / "steps.toml"
    path.write_text(table, "utf-8")

    with pytest.raises(StepError, match=re.escape(field)):
        load_steps(path)


PUSHES = ["git push origin HEAD", "scripts/change-workflow push", "uv run git push",
          "uv run bash -c 'git push'", "make run-e2e", "docker push registry/image",
          "helm push chart.tgz oci://registry", "scripts/change-workflow push --force",
          "git -C ../workspace push"]
COMMITTING = {"design", "plan", "implement", "triage", "merge", "closeout", "archive-cleanup"}


def test_each_committing_step_pushes_only_through_the_guarded_push() -> None:
    """Validation pushes the commit it validates; every step that commits work pushes
    it; the review pushes nothing. The pipeline's dispatch is a validation part, run
    through the command, so no step names its make target."""
    for name, rules in load_steps().items():
        assert "Bash(git push*)" in rules.deny
        allowed = [command for command in PUSHES if _allows(rules, command)]
        assert allowed == (["scripts/change-workflow push"]
                           if name in COMMITTING | {"validate"} else []), name


def test_only_validation_dispatches_a_ci_workflow() -> None:
    """No step's rules name a dispatch's make target: validation dispatches through
    `run`, which the engine's hook table holds to the validate step (CW-u4pc)."""
    for name, rules in load_steps().items():
        assert not _allows(rules, "make run-ci WORKFLOW=tests.yml"), name
    assert _allows(load_steps()["validate"],
                   f"scripts/change-workflow run validation {CHANGE} ci start --owed tests.yml")
    assert HOOK_STEPS["validation"] == {"validate"}


HOOK_COMMANDS = {
    "validate": [f"validation {CHANGE} preflight", f"validation {CHANGE} local run",
                 f"validation {CHANGE} pipeline start", f"validation {CHANGE} pipeline collect"],
    "archive-cleanup": [f"cleanup {CHANGE}", f"pre-commit {CHANGE}"],
    "closeout": [f"pre-archive {CHANGE}", f"pre-commit {CHANGE}"],
    "implement": [f"pre-commit {CHANGE}", f"after-functional-change {CHANGE}"],
}


def test_every_step_runs_the_repositorys_hooks_through_the_command() -> None:
    """Each step reaches a hook through `run`, which holds it to the engine's table;
    the rules that ran a hook's commands directly are gone, while the grants for
    engineering work stay (CW-u4pc)."""
    steps = load_steps()
    for name, rules in steps.items():
        for command in HOOK_COMMANDS.get(name, [f"pre-commit {CHANGE}"]):
            assert _allows(rules, f"scripts/change-workflow run {command}"), (name, command)
    for command in ("make validate-local", f"make validate-helm CHANGE={CHANGE}", "make run-e2e",
                    "make fetch-e2e-logs E2E_AFTER_RUN=1", "make dist-clean",
                    "make check-uv-version", "make validate-ci WORKFLOW=tests.yml"):
        assert not _allows(steps["validate"], command), command
    for command in (f"make record-capacity CHANGE={CHANGE}",
                    f"make -C helm teardown CHANGE={CHANGE}"):
        assert not _allows(steps["archive-cleanup"], command), command
    for name in ("implement", "triage", "merge"):
        for command in ("make test", "make lock", "make check-packaging",
                        "uv run pytest -q scripts/tests"):
            assert _allows(steps[name], command), (name, command)


def test_openspec_runs_through_the_configured_command() -> None:
    """The steps that validate or archive a change run OpenSpec through the command,
    which runs the configured `openspec.command` (CW-i2we); no rule pins a version."""
    for name, rules in load_steps().items():
        runs = name in ("design", "plan", "triage", "closeout")
        assert _allows(rules, f"scripts/change-workflow openspec validate {CHANGE} --strict") \
            == runs, name
        for pinned in (f"bunx @fission-ai/openspec@1.14.0 validate {CHANGE} --strict",
                       f"npx --yes @fission-ai/openspec@1.14.0 validate {CHANGE} --strict"):
            assert not _allows(rules, pinned), (name, pinned)


def test_every_step_may_read_the_configurations_resolution() -> None:
    for name, rules in load_steps().items():
        for command in ("config load design", f"config parts {CHANGE}", "config --json"):
            assert _allows(rules, f"scripts/change-workflow {command}"), (name, command)


def test_no_step_may_edit_the_configuration() -> None:
    """CW-z5me: no step changes what its own hooks run, while a workflow change may
    still edit the skills beside the configuration."""
    for name, rules in load_steps().items():
        assert {"Edit(.agents/workflow.toml)", "Write(.agents/workflow.toml)"} <= set(rules.deny)
        assert not any(_allows_edit(rules, tool, ".agents/workflow.toml")
                       for tool in ("Edit", "Write")), name
    assert _allows_edit(load_steps()["implement"], "Edit", ".agents/skills/change-plan/SKILL.md")


def test_every_step_that_commits_its_work_may_commit_and_no_other() -> None:
    for name, rules in load_steps().items():
        commits = name in COMMITTING
        assert _allows(rules, "git add scripts/x.py") == commits, name
        assert _allows(rules, "git commit -m x") == commits, name


def test_triage_and_implementation_may_pull_from_the_workspace_with_ff_only() -> None:
    for name, rules in load_steps().items():
        pulls = name in ("triage", "implement")
        assert _allows(rules, f"git pull --ff-only workspace feat/{CHANGE}") == pulls, name
        assert not _allows(rules, f"git pull workspace feat/{CHANGE}"), name
        assert not _allows(rules, f"git pull --no-rebase workspace feat/{CHANGE}"), name
        assert not _allows(rules, f"git pull --ff-only origin feat/{CHANGE}"), name


def test_no_step_runs_git_in_another_checkout() -> None:
    """A wildcard after `git -C` would also span a push no deny rule names in that
    form, and a step already runs in the checkout it reads."""
    for name, rules in load_steps().items():
        assert not _allows(rules, "git -C ../workspace status"), name
        assert not _allows(rules, "git -C ../workspace log --oneline"), name


def test_no_step_may_open_or_close_a_round_view_by_its_make_target() -> None:
    for name, rules in load_steps().items():
        assert not _allows(rules, "make round-view CHANGE=x"), name
        assert not _allows(rules, "make round-done"), name


READ_ONLY = ["ls -la .agents", "cat AGENTS.md", "head -5 x.log", "tail -n 20 x.log",
             "wc -l x.log", "grep -n seq workflow.jsonl", "echo rc=$?", "diff a b",
             "find . -name '*.md'"]
WRITING_FINDS = ["find . -name '*.pyc' -delete", "find . -name x -exec rm {} \\;",
                 "find . -execdir rm {} \\;", "find . -ok rm {} \\;", "find . -fprint out",
                 "find . -fprintf out %p", "find . -fls out"]


def test_every_step_may_run_the_read_only_utilities_but_not_a_find_that_writes() -> None:
    for name, rules in load_steps().items():
        assert all(_allows(rules, command) for command in READ_ONLY), name
        assert not any(_allows(rules, command) for command in WRITING_FINDS), name


def test_validation_may_run_its_skills_commands_one_per_call_or_chained() -> None:
    rules = load_steps()["validate"]
    chained = ("scripts/change-workflow check round-view; echo rc=$?; git status --porcelain "
               "--untracked-files=all; git rev-parse HEAD; git branch --show-current; "
               f"scripts/change-workflow find {CHANGE}; gh auth status 2>&1 | head -5")

    assert _allows_chain(rules, chained)
    assert _allows(rules, "gh run view 38723279321 --json headSha,conclusion,jobs")
    assert not _allows_chain(rules, "git status; make lock")


def test_a_step_row_without_a_skill_is_refused(tmp_path: Path) -> None:
    table = tmp_path / "steps.toml"
    table.write_text('[steps.design]\nallow = ["Read"]\n', "utf-8")

    with pytest.raises(StepError, match="needs a skill"):
        load_steps(table)


def test_validation_may_not_relock_or_commit() -> None:
    rules = load_steps()["validate"]

    assert {"Bash(make lock*)", "Bash(git commit*)", "Bash(git add*)"} <= set(rules.deny)


def test_validation_may_write_only_its_own_record() -> None:
    """The record is admitted by an `Edit(path)` rule, which covers every editing
    tool, since a `Write(path)` rule is not honoured. A bare `Edit` deny would
    cover the record too, so the row relies on no allow rule naming anything
    else instead."""
    rules = load_steps()["validate"]
    record = "openspec/changes/shape-bounds/reviews/07-validation.md"

    assert _allows_edit(rules, "Write", record)
    assert _allows_edit(rules, "Edit", record)
    assert not _allows_edit(rules, "Write", "openspec/changes/shape-bounds/reviews/08-closeout.md")
    assert not _allows_edit(rules, "Write", "scripts/change-workflow")
    assert not _allows_edit(rules, "Edit", "scripts/change-workflow")
    assert "Edit" not in rules.deny
    assert not any(rule.startswith("Write(") for rule in rules.allow)


def test_archive_cleanup_may_write_only_the_index_and_its_pull_request_draft() -> None:
    rules = load_steps()["archive-cleanup"]
    archived = f"openspec/changes/archive/2026-10-20-{CHANGE}"

    assert _allows_edit(rules, "Write", f"{archived}/reviews/pull-request.md")
    assert _allows_edit(rules, "Edit", f"{archived}/reviews/pull-request.md")
    assert _allows_edit(rules, "Edit", "openspec/changes/README.md")
    assert not _allows_edit(rules, "Write", f"{archived}/specs/pools/spec.md")
    assert not any(rule.startswith("Write(") for rule in rules.allow)


def test_the_merge_merges_a_fetched_branch_and_never_abandons_a_merge() -> None:
    """Whichever branch the change lands on, from origin or, in a clone, the owner's
    workspace; a merge stopped at its conflicts stays in progress for the owner, so
    nothing the step may run abandons it or moves the branch."""
    rules = load_steps()["merge"]

    for remote, branch in (("origin", "dev"), ("origin", "release/2.1"),
                           ("workspace", "feat/prerequisite")):
        assert _allows(rules, f"git fetch {remote} {branch}")
        assert _allows(rules, f"git merge --no-edit {remote}/{branch}")
    assert _allows(rules, "make lock") and _allows(rules, "git commit -m x")
    for command in ("git merge --abort", "git merge --quit", "git merge origin/main",
                    "git merge --no-edit HEAD~3", "git pull origin dev",
                    "git checkout --theirs uv.lock", "git reset --hard ORIG_HEAD",
                    "make run-e2e"):
        assert not _allows(rules, command), command


def test_every_step_may_reach_the_workflow_through_its_command() -> None:
    """Every step computes the next step, reads the log, finds a change's records,
    records an interactive outcome, and checks the index and the round view, through
    the command; none opens or closes a round view, which is the owner's."""
    for name, rules in load_steps().items():
        for command in (f"next {CHANGE}", f"log {CHANGE} --last 3",
                        f"log {CHANGE} --branch feat/x", f"find --records {CHANGE}",
                        f"find --json {CHANGE}", f"cost {CHANGE}",
                        f"record {CHANGE} plan --outcome '{{}}'", "check index",
                        "check round-view"):
            assert _allows(rules, f"scripts/change-workflow {command}"), (name, command)
        assert {"Bash(scripts/change-workflow round-view*)",
                "Bash(scripts/change-workflow round-done*)"} <= set(rules.deny), name
        for command in (f"round-view {CHANGE}", "round-done"):
            assert not _allows(rules, f"scripts/change-workflow {command}"), (name, command)


def test_every_step_that_pushes_may_push_through_the_command() -> None:
    for name, rules in load_steps().items():
        assert _allows(rules, "scripts/change-workflow push") == (name != "review"), name


def test_a_steps_own_workflow_commands_are_the_ones_its_skill_runs() -> None:
    steps = load_steps()
    assert _allows(steps["validate"], "scripts/change-workflow check push")
    # Closeout runs any of the workflow's checks.
    assert _allows(steps["closeout"], f"scripts/change-workflow check tasks {CHANGE}")
    assert _allows(steps["closeout"], "scripts/change-workflow check push")
    assert _allows(steps["archive-cleanup"], f"scripts/change-workflow history {CHANGE}")
    # Planning checks the task list it writes.
    assert _allows(steps["plan"], f"scripts/change-workflow check tasks {CHANGE}")
    for name in ("design", "plan", "implement", "triage", "merge", "archive-cleanup",
                 "review"):
        assert not _allows(steps[name], "scripts/change-workflow check push"), name
    for name in ("design", "implement", "triage", "merge", "archive-cleanup", "review"):
        assert not _allows(steps[name], f"scripts/change-workflow check tasks {CHANGE}"), name
    for name in ("design", "plan", "implement", "triage", "merge", "validate", "closeout",
                 "review"):
        assert not _allows(steps[name], f"scripts/change-workflow history {CHANGE}"), name


def test_no_step_may_edit_its_own_permissions() -> None:
    for name, rules in load_steps().items():
        assert {"Edit(.claude/**)", "Write(.claude/**)"} <= set(rules.deny), name
        assert not _allows_edit(rules, "Edit", STEP_TABLE.relative_to(ROOT).as_posix()), name
        assert not _allows_edit(rules, "Write", ".claude/settings.json"), name


@pytest.mark.parametrize("table,problem", [
    ('[steps.design]\nskill = "change-design"\ndeny = "Bash(git push*)"\n',
     "list of rules"),
    ('[steps.design]\nskill = "change-design"\nallowed = []\n', "takes only"),
    ('[steps.deploy]\nskill = "change-deploy"\n', "unknown step"),
    ('[commons]\nallow = []\n', "unknown tables"),
    ('[common]\nskill = "x"\n', "common row takes only"),
    ('[steps.plan]\nskill = "change-plan"\nresume_from = "design"\n', "has no row"),
])
def test_a_malformed_step_table_is_refused(tmp_path: Path, table: str, problem: str) -> None:
    path = tmp_path / "steps.toml"
    path.write_text(table, "utf-8")

    with pytest.raises(StepError, match=problem):
        load_steps(path)
