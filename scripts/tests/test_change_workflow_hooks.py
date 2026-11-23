"""The repository's hooks run through the engine, `change_workflow.hooks`: their
lists, placeholders, the hook table, the default checks, and the tier a commit's
paths give."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from change_workflow import config, find, hooks, records
from change_workflow.cli import main
from change_workflow.common import SESSION_ID, StepError
from change_workflow.graph import HOOK_STEPS, STEPS
from change_workflow.codex import run as run_codex
from change_workflow.hooks import Hooks
from change_workflow.log import read_log
from change_workflow.review import review_and_log, run_review
from change_workflow.running import (drop_invocations, invocations_directory, keep_invocations,
                                     kept_invocations)
from change_workflow_fixtures import (CHANGE, NETWORK, SESSION, VALID, FakeClaude,
                                      claude_review, codex_missing, configuration_checked,
                                      configured, event_lines, evidence_kind, make_wrapper,
                                      review_text)
from change_workflow_fixtures import repository as repository_with_records

AT = datetime(2026, 11, 6, 9, 0, 0, tzinfo=timezone.utc)
UNATTENDED = "CHANGE_WORKFLOW_UNATTENDED"
FRAGMENT = Path(__file__).resolve().parents[1] / "change_workflow" / "workflow.mk"


class Shell:
    """Stands in for `sh -c`: records each command and answers with a status."""

    def __init__(self, statuses: dict[str, int] | None = None) -> None:
        self.statuses = statuses or {}
        self.commands: list[str] = []

    def __call__(self, command: str, root: Path) -> int:
        self.commands.append(command)
        return self.statuses.get(command, 0)


class InProcess:
    """Stands in for the default checks the engine holds as its own modules."""

    def __init__(self, statuses: dict[str, int] | None = None) -> None:
        self.statuses = statuses or {}
        self.checks: list[str] = []

    def __call__(self, check: str, change: str, root: Path) -> int:
        self.checks.append(check)
        return self.statuses.get(check, 0)


def _change(root: Path) -> Path:
    (root / "openspec/changes" / CHANGE).mkdir(parents=True, exist_ok=True)
    return root


def _hooks(root: Path, text: str, environ: dict[str, str] | None = None,
           shell: Shell | None = None, in_process: InProcess | None = None,
           echoed: list[str] | None = None) -> Hooks:
    _change(root)
    configured(root, text)
    checked = configuration_checked(text, root / ".agents/workflow.toml", unignored=lambda *_: [])
    return Hooks(root, checked, environ or {},
                 shell=shell or Shell(), in_process=in_process or InProcess(),
                 clock=lambda: AT, timer=lambda: 0.0, head=lambda _: "c0ffee",
                 echo=(echoed.append if echoed is not None else lambda _: None))


# A hook's commands: every one run, filled and quoted.

def test_two_checks_fail(tmp_path: Path) -> None:
    """CW-k9vd: both run, both are recorded with their statuses, and the hook fails
    naming both."""
    shell = Shell({"make check-packaging": 2, "make test": 1})
    echoed: list[str] = []
    runner = _hooks(tmp_path, "[hooks]\npre-commit-functional = ['make check-packaging', "
                              "'make test']\n", shell=shell, echoed=echoed)

    passed = runner.named("pre-commit-functional", CHANGE, None, lambda: [])

    assert not passed
    assert shell.commands == ["make check-packaging", "make test"]
    assert [(i.command, i.exit_status) for i in runner.invoked] == [
        ("make check-packaging", 2), ("make test", 1)]
    assert echoed[-1] == ("[change-workflow] pre-commit-functional at c0ffee: failed, exit 2: "
                          "make check-packaging (exit 2); make test (exit 1)")


def test_a_value_with_spaces_and_quotes_reaches_the_command_as_one_word(
        tmp_path: Path) -> None:
    """Library integration: a real `sh -c` receives the filled command."""
    runner = Hooks(_change(tmp_path), configuration_checked(
        "[hooks]\npre-archive = \"printf '[%s]' {base} > seen.txt\"\n", tmp_path), {},
        echo=lambda _: None)

    assert runner.named("pre-archive", CHANGE, "it's a \"branch\" $HOME", lambda: [])

    assert (tmp_path / "seen.txt").read_text("utf-8") == "[it's a \"branch\" $HOME]"


def test_a_command_naming_a_value_the_run_lacks_is_refused_before_anything_runs(
        tmp_path: Path) -> None:
    shell = Shell()
    runner = _hooks(tmp_path, "[hooks]\npre-archive = ['make a', 'make b BASE={base}']\n",
                    shell=shell)

    with pytest.raises(hooks.HookError, match=r"hooks.pre-archive names \{base\}.*--base"):
        runner.named("pre-archive", CHANGE, None, lambda: [])
    assert shell.commands == []


def test_each_invocation_records_its_command_status_and_timing(tmp_path: Path) -> None:
    runner = _hooks(tmp_path, "[hooks]\npre-archive = 'make check CHANGE={change}'\n")

    runner.named("pre-archive", CHANGE, None, lambda: [])

    assert [i.entry() for i in runner.invoked] == [
        {"hook": "pre-archive", "command": f"make check CHANGE={CHANGE}", "exit_status": 0,
         "started": "2026-11-06T09:00:00Z", "seconds": 0.0}]


# The hook table, and the marker naming the step.

def test_the_hook_table_names_only_steps_of_the_graph() -> None:
    assert set().union(*HOOK_STEPS.values()) <= set(STEPS)


@pytest.mark.parametrize("hook", ["pre-push", "post-clone"])
def test_the_engines_own_hooks_are_not_run_through_run(tmp_path: Path, hook: str) -> None:
    configured(_change(tmp_path), f"[hooks]\n{hook} = 'touch ran'\n")

    assert main(["run", hook, CHANGE], root=tmp_path, environ={}) == 2

    assert not (tmp_path / "ran").exists()


def test_a_make_recipe_inside_a_run_keeps_the_marker(tmp_path: Path) -> None:
    """Library integration: a real `make` including the engine's fragment, whose
    own variables must not erase the marker a recipe's commands read."""
    (tmp_path / "Makefile").write_text(
        f"include {FRAGMENT}\nshow:\n\t@printf '[%s]' \"$$CHANGE_WORKFLOW_UNATTENDED\"\n",
        "utf-8")

    shown = subprocess.run(["make", "--no-print-directory", "-s", "show"], cwd=tmp_path,
                           capture_output=True, text=True, check=True,
                           env={**os.environ, UNATTENDED: "implement"}).stdout

    assert shown == "[implement]"


def test_the_fragment_documents_every_step_hook_and_defines_none(tmp_path: Path) -> None:
    """CW-h3ks: each step hook is a commented target, so an adopter meets it where
    it looks, and none is a target, so none has a default."""
    lines = FRAGMENT.read_text("utf-8").splitlines()

    assert [hook for hook in config.STEP_HOOKS if f"# {hook}:" not in lines] == []
    assert [line for line in lines if line.startswith(("before-", "after-"))] == []
    (tmp_path / "Makefile").write_text(f"include {FRAGMENT}\n", "utf-8")
    missing = subprocess.run(["make", "-n", "--no-print-directory", "before-implement"],
                             cwd=tmp_path, capture_output=True, text=True,
                             env={key: value for key, value in os.environ.items()
                                  if key not in ("MAKEFLAGS", "MFLAGS", "MAKELEVEL")})
    assert missing.returncode != 0 and "No rule to make target" in missing.stderr


def test_validation_asks_for_a_functional_hook(tmp_path: Path,
                                               capsys: pytest.CaptureFixture[str]) -> None:
    """CW-u4pc: `run` refuses, naming the hook and the validate step, and runs
    nothing."""
    configured(_change(tmp_path), "[hooks]\nafter-functional-change = 'touch relocked'\n")

    assert main(["run", "after-functional-change", CHANGE], root=tmp_path,
                environ={UNATTENDED: "validate"}) == 1

    err = capsys.readouterr().err
    assert "the validate step may not run after-functional-change" in err
    assert not (tmp_path / "relocked").exists()


def test_an_interactive_run_is_unrestricted(tmp_path: Path) -> None:
    configured(_change(tmp_path), "[hooks]\nafter-functional-change = 'touch relocked'\n")

    assert main(["run", "after-functional-change", CHANGE], root=tmp_path, environ={}) == 0

    assert (tmp_path / "relocked").exists()


def test_base_is_the_branch_the_clone_recorded_unless_given(tmp_path: Path) -> None:
    """CW-s3ju: a hook's `{base}` is the branch the change lands on, as its clone
    recorded it, and `--base` overrides it for one run. Library integration: a real
    Git directory holds the marker, and a real `sh` runs the hook."""
    configured(_change(tmp_path), "[hooks]\npre-archive = \"printf '%s' {base} > seen.txt\"\n")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".git" / find.CLONE_MARKER).write_text(
        json.dumps({"change": CHANGE, "branch": f"feat/{CHANGE}", "base": "release/2.1"}),
        "utf-8")

    assert main(["run", "pre-archive", CHANGE], root=tmp_path, environ={}) == 0
    assert (tmp_path / "seen.txt").read_text("utf-8") == "release/2.1"
    assert main(["run", "pre-archive", CHANGE, "--base", "main"], root=tmp_path,
                environ={}) == 0
    assert (tmp_path / "seen.txt").read_text("utf-8") == "main"


def test_a_marker_naming_no_step_runs_no_hook(tmp_path: Path) -> None:
    runner = _hooks(tmp_path, "[hooks]\npre-archive = 'make a'\n", environ={UNATTENDED: "1"})

    with pytest.raises(hooks.HookError, match="names '1', which is no step"):
        runner.named("pre-archive", CHANGE, None, lambda: [])


def test_record_is_refused_inside_a_run_whatever_step_it_names(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "openspec/changes" / CHANGE / "reviews").mkdir(parents=True)

    assert main(["record", CHANGE, "implement", "--outcome", json.dumps(VALID["finished"]),
                 "--session", "s"], root=tmp_path,
                environ={UNATTENDED: "implement"}) == 1

    assert "the wrapper records its outcome" in capsys.readouterr().err


def test_the_wrapper_marks_each_run_and_resume_with_its_step(tmp_path: Path) -> None:
    claude = FakeClaude((event_lines(VALID["question"], session="d-1"), 0),
                        (event_lines(VALID["finished"], session="d-1"), 0))
    wrapper = make_wrapper(tmp_path, claude)

    wrapper.run("design", CHANGE)
    wrapper.resume(CHANGE, read_log(wrapper.root / "openspec/changes" / CHANGE / "reviews"
                                    / "workflow.jsonl")[-1]["seq"], "Yes.")

    assert claude.steps == ["design", "design"]


def test_a_review_on_claude_is_marked_as_the_review(tmp_path: Path) -> None:
    root = repository_with_records(tmp_path)
    claude = claude_review(review_text("implementation"))

    run_review(CHANGE, "implementation", base="dev", root=root, runner=codex_missing,
               claude=claude,
               head=lambda _: "0" * 40, changed_since=lambda *_: None, echo=None,
               unvalidated=True)

    assert claude.steps == ["review"]


# pre-commit's default checks, `check change`, and `openspec`.

def test_a_repository_declares_its_own_pre_commit(tmp_path: Path) -> None:
    """CW-c8lw: the four default checks, and then `make lint`."""
    shell, in_process = Shell(), InProcess()
    runner = _hooks(tmp_path, "[hooks]\npre-commit = 'make lint'\n", shell=shell,
                    in_process=in_process)

    assert runner.named("pre-commit", CHANGE, None, lambda: [])

    assert in_process.checks == ["index", "tasks", "skills"]
    assert shell.commands == [f"openspec validate {CHANGE} --strict", "make lint"]
    assert [i.check or i.command for i in runner.invoked] == [
        "index", "tasks", "skills", "openspec", "make lint"]


def test_a_default_check_is_turned_off(tmp_path: Path) -> None:
    """CW-c8lw: `run pre-commit` skips the skills check."""
    in_process = InProcess()
    echoed: list[str] = []
    runner = _hooks(tmp_path, "[defaults]\ndisable = [{ check = 'skills', reason = "
                              "'no skills here' }]\n", in_process=in_process, echoed=echoed)

    assert runner.named("pre-commit", CHANGE, None, lambda: [])

    assert in_process.checks == ["index", "tasks"]
    assert "[change-workflow] default check skills: disabled — no skills here" in echoed


def test_a_failing_default_check_fails_pre_commit_and_the_rest_still_run(
        tmp_path: Path) -> None:
    shell = Shell()
    runner = _hooks(tmp_path, "[hooks]\npre-commit = 'make lint'\n", shell=shell,
                    in_process=InProcess({"tasks": 1}))

    assert not runner.named("pre-commit", CHANGE, None, lambda: [])

    assert shell.commands[-1] == "make lint"


def test_an_archived_change_validates_every_specification(tmp_path: Path) -> None:
    shell = Shell()
    archived = tmp_path / "openspec/changes/archive" / f"2026-11-01-{CHANGE}"
    archived.mkdir(parents=True)
    runner = Hooks(tmp_path, configuration_checked("", tmp_path), {}, shell=shell,
                   in_process=InProcess(), echo=lambda _: None)

    assert runner.check_change(CHANGE)

    assert shell.commands == ["openspec validate --specs --strict"]


def test_a_repository_pins_the_validator(tmp_path: Path) -> None:
    """CW-i2we: the default validation and `openspec archive` run the pinned
    command."""
    pinned = "[openspec]\ncommand = 'bunx @fission-ai/openspec@1.14.0'\n"
    shell = Shell()
    runner = _hooks(tmp_path, pinned, shell=shell)

    assert runner.check_change(CHANGE)
    assert hooks.run_openspec(runner.configuration, ["archive", CHANGE, "-y"], tmp_path,
                              run=shell) == 0

    assert shell.commands == [f"bunx @fission-ai/openspec@1.14.0 validate {CHANGE} --strict",
                              f"bunx @fission-ai/openspec@1.14.0 archive {CHANGE} -y"]


def test_openspec_passes_every_argument_flags_included(
        tmp_path: Path, capfd: pytest.CaptureFixture[str]) -> None:
    """Library integration: the configured command, a real `echo`, run by `sh`."""
    configured(tmp_path, "[openspec]\ncommand = 'echo pinned'\n")

    assert main(["openspec", "--version", "it's"], root=tmp_path) == 0

    assert capfd.readouterr().out == "pinned --version it's\n"


def test_an_absent_pre_commit_runs_the_defaults_and_records_its_skip(tmp_path: Path) -> None:
    echoed: list[str] = []
    runner = _hooks(tmp_path, "", echoed=echoed)

    assert runner.named("pre-commit", CHANGE, None, lambda: [])

    assert "[change-workflow] hooks.pre-commit: not declared; the default checks alone" in echoed
    assert echoed[-1] == "[change-workflow] pre-commit at c0ffee: passed, exit 0"
    assert runner.invoked[-1].entry()["skipped"] == "not declared"


@pytest.mark.parametrize("path,inert", [("docs/a.md", True), ("docs", True),
                                        ("docsite/a.md", False), ("openspec/x", False),
                                        ("README.md", True)])
def test_an_inert_path_is_matched_whole(path: str, inert: bool) -> None:
    assert records.inert(path, ["docs/", "README.md"]) == inert


@pytest.mark.parametrize("path,inert", [("README.md", True), ("tools/x/README.md", True),
                                        ("docs/a.md", True), ("tools/x/READMEs.md", False),
                                        ("tools/README.md/x.py", False),
                                        ("tools/x/readme.md", False)])
def test_an_inert_pattern_is_matched_against_the_whole_path(path: str, inert: bool) -> None:
    assert records.inert(path, ["docs/", "**/README.md"]) == inert


def test_check_change_runs_the_defaults_alone(tmp_path: Path) -> None:
    shell, in_process = Shell(), InProcess()
    runner = _hooks(tmp_path, "[hooks]\npre-commit = 'make lint'\n", shell=shell,
                    in_process=in_process)

    assert runner.check_change(CHANGE)

    assert in_process.checks == ["index", "tasks", "skills"]
    assert shell.commands == [f"openspec validate {CHANGE} --strict"]


# The tier a commit's paths give, over a real Git repository.

TIERED = """
[repository]
inert-paths = ["docs/", "openspec/"]

[hooks]
after-functional-change = "make lock"
pre-commit-functional = ["make check-packaging", "make test"]
pre-commit = "make check-repository"

[defaults]
disable = [{ check = "index", reason = "r" }, { check = "tasks", reason = "r" },
           { check = "skills", reason = "r" }, { check = "openspec", reason = "r" }]
"""


@pytest.fixture
def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A Git repository with one commit holding a document and a module."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    root = tmp_path / "repository"
    for path in ("docs/guide.md", "src/module.py", f"openspec/changes/{CHANGE}/README"):
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text("x\n", "utf-8")
    for command in (["init", "-q"], ["add", "-A"],
                    ["-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q",
                     "-m", "start"]):
        subprocess.run(["git", *command], cwd=root, check=True, capture_output=True)
    return root


def _pre_commit(root: Path, text: str = TIERED, step: str | None = None) -> tuple[bool, Shell]:
    shell = Shell()
    runner = Hooks(root, configuration_checked(text, root), {UNATTENDED: step} if step else {},
                   shell=shell, in_process=InProcess(), echo=lambda _: None)
    return runner.named("pre-commit", CHANGE, None, lambda: hooks.worktree_changes(root)), shell


def test_a_triage_fix_changes_only_documents(repository: Path) -> None:
    """CW-e1sg: `pre-commit` alone."""
    (repository / "docs/guide.md").write_text("fixed\n", "utf-8")
    (repository / "docs/new.md").write_text("new\n", "utf-8")

    passed, shell = _pre_commit(repository, step="triage")

    assert passed
    assert shell.commands == ["make check-repository"]


def test_a_functional_change_runs_the_three_hooks_in_order(repository: Path) -> None:
    (repository / "docs/guide.md").write_text("fixed\n", "utf-8")
    subprocess.run(["git", "add", "docs/guide.md"], cwd=repository, check=True)
    (repository / "src/module.py").write_text("changed\n", "utf-8")

    passed, shell = _pre_commit(repository, step="implement")

    assert passed
    assert shell.commands == ["make lock", "make check-packaging", "make test",
                              "make check-repository"]


@pytest.mark.parametrize("change", ["staged", "untracked", "renamed"])
def test_every_kind_of_worktree_change_counts(repository: Path, change: str) -> None:
    if change == "staged":
        (repository / "src/module.py").write_text("changed\n", "utf-8")
        subprocess.run(["git", "add", "src/module.py"], cwd=repository, check=True)
    elif change == "untracked":
        (repository / "src/new.py").write_text("new\n", "utf-8")
    else:
        subprocess.run(["git", "mv", "src/module.py", "docs/module.py"], cwd=repository,
                       check=True)

    assert "src/" in " ".join(hooks.worktree_changes(repository))


def test_a_clean_worktree_runs_pre_commit_alone_and_changes_nothing(repository: Path) -> None:
    """CW-y6mj: a review's clean worktree."""
    passed, shell = _pre_commit(repository, step="review")

    assert passed
    assert shell.commands == ["make check-repository"]
    assert subprocess.run(["git", "status", "--porcelain"], cwd=repository, check=True,
                          capture_output=True, text=True).stdout == ""


def test_a_design_steps_functional_change_is_refused_by_the_table(repository: Path) -> None:
    (repository / "src/module.py").write_text("changed\n", "utf-8")

    with pytest.raises(hooks.HookError,
                       match="the design step may not run after-functional-change"):
        _pre_commit(repository, step="design")


def test_a_functional_commit_without_functional_checks_is_refused(repository: Path) -> None:
    """CW-t5hz: the tier needs `pre-commit-functional`, and none is declared."""
    (repository / "src/module.py").write_text("changed\n", "utf-8")
    text = TIERED.replace('pre-commit-functional = ["make check-packaging", "make test"]\n', "")

    with pytest.raises(config.ConfigError, match="needs hooks.pre-commit-functional"):
        _pre_commit(repository, text)


def test_functional_checks_declared_empty_run_nothing(repository: Path) -> None:
    """CW-t5hz: `pre-commit-functional = []` declares the field, and a functional
    commit runs no functional checks."""
    (repository / "src/module.py").write_text("changed\n", "utf-8")
    text = TIERED.replace('["make check-packaging", "make test"]', "[]")

    passed, shell = _pre_commit(repository, text)

    assert passed
    assert shell.commands == ["make lock", "make check-repository"]


def test_a_repository_declares_no_inert_paths(repository: Path) -> None:
    """CW-n7ra's scenario: the workflow's default makes a Markdown file and a path
    under `openspec/` inert, so `pre-commit` runs alone."""
    (repository / "guides").mkdir()
    (repository / "guides/setup.md").write_text("set up\n", "utf-8")
    (repository / "openspec/specs/x").mkdir(parents=True)
    (repository / "openspec/specs/x/spec.md").write_text("spec\n", "utf-8")
    text = TIERED.replace('inert-paths = ["docs/", "openspec/"]', "")

    passed, shell = _pre_commit(repository, text)

    assert passed
    assert shell.commands == ["make check-repository"]


def test_a_repository_declares_an_empty_list(repository: Path) -> None:
    """CW-n7ra's scenario: an empty declaration replaces the default, so a Markdown
    file runs the functional hooks before `pre-commit`."""
    (repository / "guides").mkdir()
    (repository / "guides/setup.md").write_text("set up\n", "utf-8")
    text = TIERED.replace('inert-paths = ["docs/", "openspec/"]', "inert-paths = []")

    _, shell = _pre_commit(repository, text)

    assert shell.commands == ["make lock", "make check-packaging", "make test",
                              "make check-repository"]


# pre-archive and after-functional-change by name; an absent hook skipped.

@pytest.mark.parametrize("hook,step", [("pre-archive", "closeout"),
                                       ("after-functional-change", "merge")])
def test_a_named_hook_runs_its_declared_commands(tmp_path: Path, hook: str, step: str) -> None:
    shell = Shell()
    runner = _hooks(tmp_path, f"[hooks]\n{hook} = ['make a CHANGE={{change}}', 'make b']\n",
                    environ={UNATTENDED: step}, shell=shell)

    assert runner.named(hook, CHANGE, None, lambda: [])

    assert shell.commands == [f"make a CHANGE={CHANGE}", "make b"]


@pytest.mark.parametrize("hook", ["pre-archive", "after-functional-change"])
def test_an_absent_optional_hook_is_skipped_saying_so(tmp_path: Path, hook: str) -> None:
    echoed: list[str] = []
    runner = _hooks(tmp_path, "", echoed=echoed)

    assert runner.named(hook, CHANGE, None, lambda: [])

    assert echoed == [f"[change-workflow] {hook} at c0ffee: skipped, not declared"]
    assert [i.entry() for i in runner.invoked] == [
        {"hook": hook, "skipped": "not declared", "started": "2026-11-06T09:00:00Z",
         "seconds": 0.0}]


def test_run_refuses_an_unknown_change(tmp_path: Path,
                                       capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["run", "pre-archive", "no-such-change"], root=tmp_path, environ={}) == 1
    assert "no-such-change" in capsys.readouterr().err


# The functional hooks' tree and commit, and a start's marker.

KINDS = ("[validation]\npreflight = \"make check-uv-version\"\n\n"
         + evidence_kind("local", run="make validate-local")
         + evidence_kind("helm", after="local", run="make validate-helm CHANGE={change}",
                         cleanup=["make record-capacity CHANGE={change}",
                                  "make -C helm teardown CHANGE={change}"]))
LOCAL = evidence_kind("local", run="true")


def test_a_functional_hooks_tree_is_the_tree_its_commit_then_holds(repository: Path) -> None:
    """CW-v2dq: `run pre-commit`'s functional hooks get the worktree's tree as each
    starts — after `after-functional-change` changed it, as a relock does — which the
    commit then made of exactly those changes holds, and `HEAD`'s commit. Library
    integration: a real Git repository and `sh`."""
    configured(repository, TIERED.replace(
        'pre-commit-functional = ["make check-packaging", "make test"]',
        "pre-commit-functional = \"printf '%s %s' {tree} {commit} > ../tested.txt\"").replace(
        'after-functional-change = "make lock"',
        'after-functional-change = "printf relocked > src/lock.txt"').replace(
        'pre-commit = "make check-repository"', 'pre-commit = "true"'))
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repository, check=True,
                          capture_output=True, text=True).stdout.strip()
    (repository / "src/module.py").write_text("changed\n", "utf-8")
    (repository / "src/new.py").write_text("new\n", "utf-8")

    assert main(["run", "pre-commit", CHANGE], root=repository, environ={}) == 0
    for command in (["add", "--all"], ["-c", "user.name=t", "-c", "user.email=t@example.invalid",
                                       "commit", "-q", "-m", "the changes tested"]):
        subprocess.run(["git", *command], cwd=repository, check=True, capture_output=True)

    tree = subprocess.run(["git", "rev-parse", "HEAD^{tree}"], cwd=repository, check=True,
                          capture_output=True, text=True).stdout.strip()
    assert (repository.parent / "tested.txt").read_text("utf-8") == f"{tree} {head}"


def test_only_the_functional_hooks_read_the_tree(tmp_path: Path) -> None:
    """The tree is written only for a hook naming it."""
    trees: list[Path] = []
    runner = _hooks(tmp_path, "[hooks]\npre-archive = 'make a'\n"
                              "pre-commit-functional = 'make b TREE={tree}'\n")
    runner.tree = lambda root: trees.append(root) or "t0"

    runner.hook("pre-archive", CHANGE, None)
    assert trees == []
    runner.hook("pre-commit-functional", CHANGE, None)
    assert trees == [tmp_path]
    assert runner.shell.commands == ["make a", "make b TREE=t0"]


@pytest.mark.parametrize("arguments", [
    ["run", "validation", CHANGE], ["run", "validation", CHANGE, "local", "run"],
    ["run", "pre-commit", CHANGE, "local"], ["run", "cleanup", CHANGE, "--owed", "ci.yml"],
    ["config", "parts", CHANGE],
])
def test_run_takes_each_form_alone_and_validation_has_no_run(tmp_path: Path,
                                                             arguments: list[str]) -> None:
    """`run` runs hooks alone, and `config` has no `parts`: validation gathers and
    reports evidence through `gather` and `evidence`. Each is a usage error."""
    configured(_change(tmp_path), KINDS)

    assert main(arguments, root=tmp_path, environ={}) == 2


def test_a_start_passes_its_output_through_and_keeps_its_last_line(
        tmp_path: Path, capfd: pytest.CaptureFixture[str]) -> None:
    """Library integration: a real `sh` prints the dispatch's output and its marker."""
    assert hooks.capture("printf 'dispatched\\n4073\\n\\n'", tmp_path) == (0, "4073")

    assert capfd.readouterr().out == "dispatched\n4073\n\n"


@pytest.mark.skipif(shutil.which("make") is None, reason="needs make")
def test_a_start_run_from_a_session_a_make_started_keeps_its_marker(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        capfd: pytest.CaptureFixture[str]) -> None:
    """CW-x9bt, library integration: a session started by a make target inherits its
    recursion state; a declared `make` dispatch run from it, by a real `sh` and
    `make`, still ends with its marker rather than make's "Leaving directory"."""
    (tmp_path / "Makefile").write_text("dispatch:\n\t@echo dispatched\n\t@echo 4073\n", "utf-8")
    monkeypatch.setenv("MAKELEVEL", "1")
    monkeypatch.setenv("MAKEFLAGS", "w")

    assert hooks.capture("make dispatch", tmp_path) == (0, "4073")
    assert "directory" not in capfd.readouterr().out


def test_a_declared_command_keeps_the_callers_variables_but_not_makes_recursion() -> None:
    """A variable given on the outer make's command line reaches the command, as make
    exports it; the variables that make a `make` act as a sub-make do not."""
    shown = hooks.command_environment({"HELM_CONTEXT": "kind", "MAKELEVEL": "2",
                                       "MAKEFLAGS": "w -- HELM_CONTEXT=kind", "MFLAGS": "-w",
                                       "MAKEOVERRIDES": "${-*-command-variables-*-}"})
    assert shown == {"HELM_CONTEXT": "kind"}


# `run cleanup`: every kind's cleanup, as one list.

def _cleaning(root: Path, text: str = KINDS, shell: Shell | None = None,
              echoed: list[str] | None = None, step: str = "archive-cleanup") -> Hooks:
    return _hooks(root, text, environ={UNATTENDED: step}, shell=shell, echoed=echoed)


def test_a_changes_validation_left_resources(tmp_path: Path) -> None:
    """CW-ikmm: archive cleanup runs the Helm kind's cleanup, in order."""
    shell, echoed = Shell(), []
    runner = _cleaning(tmp_path, shell=shell, echoed=echoed)

    assert runner.cleanup(CHANGE, None)

    assert shell.commands == [f"make record-capacity CHANGE={CHANGE}",
                              f"make -C helm teardown CHANGE={CHANGE}"]
    assert [(i.kind, i.phase) for i in runner.invoked] == [("helm", "cleanup")] * 2


def test_a_kinds_cleanup_finds_nothing(tmp_path: Path) -> None:
    """CW-ikmm: a cleanup that removes nothing succeeds; one failing still lets the
    rest run, and fails the cleanup."""
    text = KINDS.replace('run = "make validate-local"',
                         'run = "make validate-local"\ncleanup = "make dist-clean"')
    shell = Shell({"make dist-clean": 0, f"make record-capacity CHANGE={CHANGE}": 1})
    runner = _cleaning(tmp_path, text, shell=shell)

    assert not runner.cleanup(CHANGE, None)

    assert shell.commands == ["make dist-clean", f"make record-capacity CHANGE={CHANGE}",
                              f"make -C helm teardown CHANGE={CHANGE}"]


def test_a_cleanup_is_given_the_checkouts_tree_and_commit(tmp_path: Path) -> None:
    """CW-v2dq: a kind's cleanup is one of its commands, given the tree and the
    commit."""
    shell = Shell()
    runner = _cleaning(tmp_path, evidence_kind("helm", run="true",
                                               cleanup="make clean TREE={tree} AT={commit}"),
                       shell=shell)
    runner.tree = lambda _: "t0"

    assert runner.cleanup(CHANGE, None)

    assert shell.commands == ["make clean TREE=t0 AT=c0ffee"]


def test_no_kind_declaring_a_cleanup_is_skipped_saying_so(tmp_path: Path) -> None:
    echoed: list[str] = []
    runner = _cleaning(tmp_path, LOCAL, echoed=echoed)

    assert runner.cleanup(CHANGE, None)

    assert echoed == ["[change-workflow] cleanup at c0ffee: skipped, no kind declares a cleanup"]


def test_only_archive_cleanup_runs_the_cleanups(tmp_path: Path) -> None:
    with pytest.raises(hooks.HookError, match="the validate step may not run cleanup"):
        _cleaning(tmp_path, step="validate").cleanup(CHANGE, None)


# What a run invoked, kept by its session for its line.

def _ignoring_records(root: Path) -> Path:
    with (root / ".git/info/exclude").open("a", encoding="utf-8") as exclude:
        exclude.write("/openspec/changes/*/reviews/\n")
    return root


def test_validations_helm_kind_fails(repository: Path) -> None:
    """CW-q5fy: library integration, a real `sh` and Git directory; the run's line
    lists the kind its gathering before the session ran, with its resolved command
    and exit status 2."""
    configured(_ignoring_records(repository), evidence_kind("helm", run="exit 2"))
    # The gathering describes HEAD, so the configuration is committed.
    for command in (["add", "--all"], ["-c", "user.name=t", "-c", "user.email=t@example.invalid",
                                       "commit", "-q", "-m", "configure"]):
        subprocess.run(["git", *command], cwd=repository, check=True, capture_output=True)

    line = make_wrapper(repository, FakeClaude((event_lines(VALID["finished"]), 0))).run(
        "validate", CHANGE)

    (invoked,) = [entry for entry in line["invoked"] if entry.get("kind") == "helm"]
    assert {key: invoked[key] for key in ("hook", "kind", "phase", "command", "exit_status")} \
        == {"hook": "gather", "kind": "helm", "phase": "run", "command": "exit 2",
            "exit_status": 2}


def test_an_interactive_record_takes_what_its_session_invoked(
        repository: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Library integration: `run` keeps by the session, `record` takes it onto the
    line, and nothing is left kept."""
    configured(_ignoring_records(repository), "[hooks]\npre-archive = ['true', 'false']\n")
    session = {SESSION_ID: "5e55-1011"}

    assert main(["run", "pre-archive", CHANGE], root=repository, environ=session) == 1
    assert main(["record", CHANGE, "design", "--outcome", json.dumps(
        {**VALID["finished"], "next": {"step": "review", "kind": "design"}})],
        root=repository, environ=session) == 0

    line = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert [(i["command"], i["exit_status"]) for i in line["invoked"]] == [
        ("true", 0), ("false", 1)]
    assert kept_invocations(invocations_directory(repository), "5e55-1011") == []


def test_a_refused_record_keeps_the_invocations_for_the_next(repository: Path) -> None:
    configured(repository, "[hooks]\npre-archive = 'true'\n")
    session = {SESSION_ID: "5e55-1011"}
    main(["run", "pre-archive", CHANGE], root=repository, environ=session)

    assert main(["record", CHANGE, "design", "--outcome", "not json"], root=repository,
                environ=session) == 1

    assert len(kept_invocations(invocations_directory(repository), "5e55-1011")) == 1


def test_a_run_outside_any_session_keeps_nothing(repository: Path) -> None:
    configured(repository, "[hooks]\npre-archive = 'true'\n")

    assert main(["run", "pre-archive", CHANGE], root=repository, environ={}) == 0

    kept = invocations_directory(repository)
    assert kept is not None and not kept.exists()


def test_a_sessions_invocations_are_kept_in_order_and_dropped_as_a_line_takes_them(
        tmp_path: Path) -> None:
    keep_invocations(tmp_path, "s", [{"change": "a", "n": 1}, {"n": 2}])
    keep_invocations(tmp_path, "s", [{"change": "b", "n": 3}, {"change": "a", "n": 4}])
    keep_invocations(tmp_path, "other", [{"n": 9}])

    taken = kept_invocations(tmp_path, "s", "a")
    assert taken == [{"change": "a", "n": 1}, {"n": 2}, {"change": "a", "n": 4}]
    drop_invocations(tmp_path, "s", taken)
    assert kept_invocations(tmp_path, "s") == [{"change": "b", "n": 3}]
    drop_invocations(tmp_path, "s", [{"change": "b", "n": 3}])
    # Emptied, never removed, so an append waiting on its lock lands where it is read.
    assert (tmp_path / "s.jsonl").read_text("utf-8") == ""
    assert kept_invocations(tmp_path, "other") == [{"n": 9}]


class Acting(FakeClaude):
    """A run whose step does something, `action(step)`, before it ends."""

    def __init__(self, action, *runs) -> None:
        super().__init__(*runs)
        self.action = action

    def __call__(self, command, cwd, feed, step) -> int:
        self.action(step)
        return super().__call__(command, cwd, feed, step)


def _session_lines(session: str, outcome: dict | None = None, said: str | None = None
                   ) -> list[str]:
    """A run's events under `session`: ending with `outcome`, or an error saying
    `said`."""
    if said is None:
        return event_lines(outcome, session=session)
    return [json.dumps(event) + "\n" for event in (
        {"type": "system", "subtype": "init", "session_id": session},
        {"type": "result", "subtype": "success", "is_error": True, "session_id": session,
         "result": said, "permission_denials": []})]


def test_a_resumed_turns_line_takes_only_what_its_session_invoked_since(
        tmp_path: Path) -> None:
    kept = tmp_path / "kept"
    turns = iter([1, 2])
    claude = Acting(lambda _: keep_invocations(kept, "d-1", [{"change": CHANGE,
                                                              "turn": next(turns)}]),
                    (_session_lines("d-1", VALID["question"]), 0),
                    (_session_lines("d-1", VALID["finished"]), 0))
    wrapper = make_wrapper(tmp_path, claude)
    wrapper.invocations = lambda _: kept

    first = wrapper.run("design", CHANGE)
    second = wrapper.resume(CHANGE, first["seq"], "Yes.")

    assert [entry["turn"] for entry in first["invoked"]] == [1]
    assert [entry["turn"] for entry in second["invoked"]] == [2]


def test_a_retried_attempts_invocations_are_the_runs_too(tmp_path: Path) -> None:
    kept = tmp_path / "kept"
    sessions = iter(["s-a", "s-b"])
    claude = Acting(lambda _: keep_invocations(kept, next(sessions), [{"change": CHANGE}]),
                    (_session_lines("s-a", said=NETWORK), 1),
                    (_session_lines("s-b", VALID["finished"]), 0))
    wrapper = make_wrapper(tmp_path, claude)
    wrapper.invocations = lambda _: kept

    line = wrapper.run("design", CHANGE)

    assert len(line["invoked"]) == 2
    assert kept_invocations(kept, "s-a") == kept_invocations(kept, "s-b") == []


def test_a_review_on_claude_records_what_it_invoked(tmp_path: Path) -> None:
    root = repository_with_records(tmp_path)
    kept = tmp_path / "kept"
    reviewer = Acting(lambda _: keep_invocations(kept, "c-1", [{"change": CHANGE,
                                                                "hook": "pre-commit"}]),
                      (claude_review(review_text("implementation")).runs[0]))

    line = review_and_log(CHANGE, "implementation", base="dev", root=root,
                          runner=codex_missing,
                          claude=reviewer, head=lambda _: "0" * 40,
                          changed_since=lambda *_: None, echo=None, unvalidated=True,
                          runs=lambda _: None, invocations=lambda _: kept)

    assert line["invoked"] == [{"change": CHANGE, "hook": "pre-commit"}]
    assert kept_invocations(kept, "c-1") == []


def test_invocations_that_cannot_be_read_never_stop_a_line(tmp_path: Path) -> None:
    kept = tmp_path / "kept"
    kept.mkdir()
    (kept / f"{SESSION}.jsonl").write_text(
        'torn {"change"\n{"change": "' + CHANGE + '", "command": "a\u2028b"}\n', "utf-8")
    wrapper = make_wrapper(tmp_path, FakeClaude((event_lines(VALID["finished"]), 0)))
    wrapper.invocations = lambda _: kept

    line = wrapper.run("design", CHANGE)

    assert line["invoked"] == [{"change": CHANGE, "command": "a\u2028b"}]
    assert (kept / f"{SESSION}.jsonl").read_text("utf-8") == 'torn {"change"\n'


def test_a_hook_whose_invocations_cannot_be_kept_still_reports_its_result(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    runner = _hooks(tmp_path, "[hooks]\npre-archive = 'make a'\n",
                    environ={SESSION_ID: "../elsewhere"})
    runner.invocations = lambda _: tmp_path / "kept"

    assert hooks.main("pre-archive", CHANGE, root=tmp_path,
                      configuration=runner.configuration, environ=runner.environ,
                      hooks=runner) == 0

    assert "could not be kept" in capsys.readouterr().err


def test_a_codex_review_sees_no_session_of_whatever_started_it(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(SESSION_ID, "the-orchestrators")
    log = tmp_path / "review.log"

    assert run_codex([sys.executable, "-c",
                      f"import os; print(os.environ.get({SESSION_ID!r}))"], log) == 0

    assert log.read_text("utf-8") == "None\n"


def test_run_cleanup_through_the_command(repository: Path) -> None:
    configured(repository, evidence_kind("helm", run="true",
                                         cleanup=["touch first", "touch second"]))

    assert main(["run", "cleanup", CHANGE], root=repository,
                environ={UNATTENDED: "archive-cleanup"}) == 0

    assert (repository / "first").exists() and (repository / "second").exists()


def test_a_session_id_naming_another_place_is_refused(tmp_path: Path) -> None:
    with pytest.raises(StepError, match="no session id"):
        keep_invocations(tmp_path, "../elsewhere", [{"n": 1}])


# Running a test as HEAD holds it against an earlier commit.

BEFORE = 'test-before = "python3 {test}"\n'


def _git(root: Path, *arguments: str) -> str:
    return subprocess.run(["git", "-C", str(root), *arguments], check=True,
                          capture_output=True, text=True).stdout.strip()


def _fixed_repository(root: Path) -> str:
    """A repository whose first commit holds a broken module and whose second fixes
    it and adds the test proving the fix; the first commit's name."""
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "t")
    (root / "module.py").write_text("def answer():\n    return 41\n", "utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "broken")
    broken = _git(root, "rev-parse", "HEAD")
    (root / "module.py").write_text("def answer():\n    return 42\n", "utf-8")
    (root / "tests").mkdir()
    (root / "tests/check.py").write_text(
        "import sys\nsys.path.insert(0, '.')\nfrom module import answer\n"
        "assert answer() == 42\n", "utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "fixed")
    return broken


def _before(root: Path, echoed: list[str], step: str | None = "triage") -> Hooks:
    runner = _hooks(root, f"[hooks]\n{BEFORE}", environ={UNATTENDED: step} if step else {},
                    shell=hooks.shell, echoed=echoed)
    return runner


def test_a_test_written_with_the_fix_fails_before_it(tmp_path: Path) -> None:
    broken = _fixed_repository(tmp_path)
    echoed: list[str] = []
    runner = _before(tmp_path, echoed)
    status = _git(tmp_path, "status", "--porcelain")

    assert runner.test_before(CHANGE, None, broken, ["tests/check.py"])
    assert runner.test_before(CHANGE, None, _git(tmp_path, "rev-parse", "HEAD"),
                              ["tests/check.py"])

    assert echoed[0].startswith(f"[change-workflow] test-before tests/check.py at {broken}: "
                                "failed, exit 1")
    assert echoed[1].endswith("passed, exit 0")
    # The scratch worktree is gone, and the change's own is untouched.
    assert _git(tmp_path, "worktree", "list").count("\n") == 0
    assert _git(tmp_path, "status", "--porcelain") == status


def test_test_before_refuses_a_commit_that_does_not_exist(tmp_path: Path) -> None:
    _fixed_repository(tmp_path)
    runner = _before(tmp_path, [])

    with pytest.raises(hooks.HookError, match="no worktree at nothing-here"):
        runner.test_before(CHANGE, None, "nothing-here", ["tests/check.py"])
    assert _git(tmp_path, "worktree", "list").count("\n") == 0


@pytest.mark.parametrize("tests,commit,refused", [
    ([], "HEAD", "names the test files"),
    (["tests/missing.py"], "HEAD", "is no file of this checkout"),
    (["../escape.py"], "HEAD", "is no file of this checkout"),
    (["tests/check.py"], None, "give it with --at"),
])
def test_test_before_refuses_what_it_cannot_run(tmp_path: Path, tests: list[str],
                                                commit: str | None, refused: str) -> None:
    _fixed_repository(tmp_path)

    with pytest.raises(hooks.HookError, match=refused):
        _before(tmp_path, []).test_before(CHANGE, None, commit, tests)


def test_only_implementation_and_triage_run_tests_before(tmp_path: Path) -> None:
    _fixed_repository(tmp_path)

    with pytest.raises(hooks.HookError, match="the validate step may not run test-before"):
        _before(tmp_path, [], step="validate").test_before(CHANGE, None, "HEAD",
                                                           ["tests/check.py"])
