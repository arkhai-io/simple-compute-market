"""Each step's unattended run is held to its rules and runs on its models."""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

import pytest

from change_workflow.common import ROOT, STEPS, StepError
from change_workflow.steps import STEP_TABLE, Model, load_steps
from change_workflow_fixtures import CHANGE, OPUS, SONNET

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
    """Design, triage, implementation, the merge, and closeout on Opus at high effort;
    validation and archive cleanup on Sonnet at medium; the review on Codex, then
    Claude."""
    models = {name: rules.models for name, rules in load_steps().items()}

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


def test_every_step_may_run_the_cost_report() -> None:
    assert all(_allows(rules, f"make change-cost CHANGE={CHANGE}")
               for rules in load_steps().values())


@pytest.mark.parametrize("models,problem", [
    ("", "needs a skill and models"),
    ("models = []\n", "a list of one or more models"),
    ('models = [{ harness = "claude", model = "claude-fable-5-1" }]\n', "never runs on"),
    ('models = [{ harness = "claude", model = "astra-2" }]\n', "never runs on"),
    ('models = [{ harness = "claude", model = "claude-opus-5-5" }, '
     '{ harness = "claude", model = "claude-sonnet-5-5" }]\n', "two models of one vendor"),
    ('models = [{ harness = "claude", effort = "high" }]\n', "without a model"),
    ('models = [{ harness = "codex", model = "gpt-6-sol" }]\n', "Codex runs only the review"),
    ('models = [{ harness = "gemini", model = "g" }]\n', "harness 'gemini'"),
    ('models = [{ harness = "claude", model = "m", speed = "fast" }]\n', "a key other than"),
])
def test_a_row_naming_models_the_policy_forbids_is_refused(
        tmp_path: Path, models: str, problem: str) -> None:
    table = tmp_path / "steps.toml"
    table.write_text(f'[steps.triage]\nskill = "change-triage"\n{models}', "utf-8")

    with pytest.raises(StepError, match=problem) as refused:
        load_steps(table)

    assert "triage row" in str(refused.value)


PUSHES = ["git push origin HEAD", "make push-branch", "uv run git push",
          "uv run bash -c 'git push'", "make run-e2e", "docker push registry/image",
          "helm push chart.tgz oci://registry", "make push-branch FORCE=1",
          "git -C ../workspace push"]
COMMITTING = {"design", "plan", "implement", "triage", "merge", "closeout", "archive-cleanup"}


def test_each_committing_step_pushes_only_through_the_guarded_push() -> None:
    """Validation pushes the commit it validates and dispatches the pipeline; every
    step that commits work pushes it; the review pushes nothing."""
    for name, rules in load_steps().items():
        assert "Bash(git push*)" in rules.deny
        allowed = [command for command in PUSHES if _allows(rules, command)]
        assert allowed == (["make push-branch", "make run-e2e"] if name == "validate"
                           else ["make push-branch"] if name in COMMITTING
                           else []), name


def test_only_validation_dispatches_a_ci_workflow() -> None:
    """The dispatch itself refuses a workflow off its list; the table keeps every
    other step from dispatching at all."""
    for name, rules in load_steps().items():
        assert _allows(rules, "make run-ci WORKFLOW=tests.yml") == (name == "validate"), name


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


def test_every_step_may_check_that_no_round_view_is_open() -> None:
    for name, rules in load_steps().items():
        assert _allows(rules, "make round-view-closed"), name
        assert _allows(rules, "make round-view-closed CHANGE=x"), name
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
    chained = ("make round-view-closed; echo rc=$?; git status --porcelain "
               "--untracked-files=all; git rev-parse HEAD; git branch --show-current; "
               f"python3 scripts/find_change.py {CHANGE}; gh auth status 2>&1 | head -5")

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
    assert not _allows_edit(rules, "Write", "scripts/run_change_step.py")
    assert not _allows_edit(rules, "Edit", "scripts/run_change_step.py")
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


def test_every_step_may_compute_the_next_step_and_read_the_log() -> None:
    for name, rules in load_steps().items():
        assert _allows(rules, f"python3 scripts/change_next_step.py {CHANGE}"), name
        assert _allows(rules, f"python3 scripts/run_change_step.py log {CHANGE} --last 3"), name


def test_no_step_may_edit_its_own_permissions() -> None:
    for name, rules in load_steps().items():
        assert {"Edit(.claude/**)", "Write(.claude/**)"} <= set(rules.deny), name
        assert not _allows_edit(rules, "Edit", STEP_TABLE.relative_to(ROOT).as_posix()), name
        assert not _allows_edit(rules, "Write", ".claude/settings.json"), name


@pytest.mark.parametrize("table,problem", [
    (f'[steps.design]\nskill = "change-design"\n{MODELS}deny = "Bash(git push*)"\n',
     "list of rules"),
    (f'[steps.design]\nskill = "change-design"\n{MODELS}allowed = []\n', "takes only"),
    (f'[steps.deploy]\nskill = "change-deploy"\n{MODELS}', "unknown step"),
    ('[commons]\nallow = []\n', "unknown tables"),
    ('[common]\nskill = "x"\n', "common row takes only"),
    (f'[steps.plan]\nskill = "change-plan"\n{MODELS}resume_from = "design"\n', "has no row"),
])
def test_a_malformed_step_table_is_refused(tmp_path: Path, table: str, problem: str) -> None:
    path = tmp_path / "steps.toml"
    path.write_text(table, "utf-8")

    with pytest.raises(StepError, match=problem):
        load_steps(path)
