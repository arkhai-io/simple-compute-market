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
from change_workflow.harness import run_codex
from change_workflow.hooks import Hooks
from change_workflow.log import read_log
from change_workflow.review import review_and_log, run_review
from change_workflow.running import (drop_invocations, invocations_directory, keep_invocations,
                                     kept_invocations)
from change_workflow_fixtures import (CHANGE, MODELS, NETWORK, SESSION, VALID, FakeClaude,
                                      claude_review, codex_missing, configured, event_lines,
                                      make_wrapper, review_text)
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
    return Hooks(root, config.check(text, root / ".agents/workflow.toml"), environ or {},
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
    runner = Hooks(_change(tmp_path), config.check(
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
    runner = Hooks(tmp_path, config.check("", tmp_path), {}, shell=shell,
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
    runner = Hooks(root, config.check(text, root), {UNATTENDED: step} if step else {},
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


def test_with_no_inert_path_every_change_is_functional(repository: Path) -> None:
    (repository / "docs/guide.md").write_text("fixed\n", "utf-8")
    text = TIERED.replace('inert-paths = ["docs/", "openspec/"]', "")

    _, shell = _pre_commit(repository, text)

    assert shell.commands[0] == "make lock"


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


# Validation's preflight and parts, the kept marker, and the closing line.

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
cleanup = ["make record-capacity CHANGE={change}", "make -C helm teardown CHANGE={change}"]
"""


class Capture:
    """Stands in for a `start`'s command: records it, and prints the next marker."""

    def __init__(self, *printed: tuple[int, str | None]) -> None:
        self.printed = list(printed)
        self.commands: list[str] = []

    def __call__(self, command: str, root: Path) -> tuple[int, str | None]:
        self.commands.append(command)
        return self.printed.pop(0)


def _validating(root: Path, text: str = PARTS, shell: Shell | None = None,
                capture: Capture | None = None, echoed: list[str] | None = None,
                step: str | None = "validate", head: str = "c0ffee") -> Hooks:
    runner = _hooks(root, text, environ={UNATTENDED: step} if step else {}, shell=shell,
                    echoed=echoed)
    runner.capture = capture or Capture()
    runner.markers = lambda _: root / "markers"
    runner.head = lambda _: head
    return runner


def test_the_preflight_runs_and_closes(tmp_path: Path) -> None:
    shell, echoed = Shell(), []
    runner = _validating(tmp_path, shell=shell, echoed=echoed)

    assert runner.validation(CHANGE, None, "preflight")

    assert shell.commands == ["make check-uv-version"]
    assert echoed[-1] == "[change-workflow] validation preflight at c0ffee: passed, exit 0"


def test_an_absent_preflight_is_skipped_saying_so(tmp_path: Path) -> None:
    echoed: list[str] = []
    runner = _validating(tmp_path, "[validation.parts.local]\nrun = 'true'\n", echoed=echoed)

    assert runner.validation(CHANGE, None, "preflight")

    assert echoed == ["[change-workflow] validation preflight at c0ffee: skipped, not declared"]


def test_a_part_ends_with_the_engines_closing_line(tmp_path: Path) -> None:
    shell, echoed = Shell({f"make validate-helm CHANGE={CHANGE}": 2}), []
    runner = _validating(tmp_path, shell=shell, echoed=echoed)

    assert not runner.validation(CHANGE, None, "helm", "run")

    assert echoed[-1] == (
        f"[change-workflow] validation helm run at c0ffee: failed, exit 2: make validate-helm "
        f"CHANGE={CHANGE} (exit 2); evidence .snapshot/validation/")
    assert [i.entry() for i in runner.invoked] == [
        {"hook": "validation", "part": "helm", "phase": "run",
         "command": f"make validate-helm CHANGE={CHANGE}", "exit_status": 2,
         "started": "2026-11-06T09:00:00Z", "seconds": 0.0}]


def test_an_owed_parts_closing_line_names_its_workflow(tmp_path: Path) -> None:
    echoed: list[str] = []
    runner = _validating(tmp_path, capture=Capture((0, "401")), echoed=echoed)

    assert runner.validation(CHANGE, None, "ci", "start", owed="ci.yml")

    assert echoed[-1] == ("[change-workflow] validation ci ci.yml start at c0ffee: passed, "
                          "exit 0; evidence .snapshot/validation/")


@pytest.mark.parametrize("part,phase,owed,refused", [
    ("ci", "start", None, "validation.parts.ci is owed: give the workflow"),
    ("local", "run", "ci.yml", "validation.parts.local is not owed, so it takes no --owed"),
    ("local", "start", None, "declares run, so it is run with run, not start"),
    ("pipeline", "run", None, "declares start, collect, so it is run with start or collect"),
    ("smoke", "run", None, "declares no validation part 'smoke'"),
])
def test_a_part_run_another_way_than_it_declares_is_refused(
        tmp_path: Path, part: str, phase: str, owed: str | None, refused: str) -> None:
    shell = Shell()
    runner = _validating(tmp_path, shell=shell)

    with pytest.raises((hooks.HookError, config.ConfigError), match=refused):
        runner.validation(CHANGE, None, part, phase, owed)
    assert shell.commands == []


def test_only_validation_runs_its_parts(tmp_path: Path) -> None:
    with pytest.raises(hooks.HookError, match="the implement step may not run validation"):
        _validating(tmp_path, step="implement").validation(CHANGE, None, "local", "run")


@pytest.mark.parametrize("arguments", [
    ["run", "validation", CHANGE], ["run", "validation", CHANGE, "local"],
    ["run", "validation", CHANGE, "preflight", "run"],
    ["run", "pre-commit", CHANGE, "local"], ["run", "cleanup", CHANGE, "--owed", "ci.yml"],
])
def test_run_takes_each_form_alone(tmp_path: Path, arguments: list[str]) -> None:
    configured(_change(tmp_path), PARTS)

    assert main(arguments, root=tmp_path, environ={}) == 2


def test_two_owed_runs_are_collected_side_by_side(tmp_path: Path) -> None:
    """CW-x9bt: each collect waits past its own start's marker."""
    shell = Shell()
    runner = _validating(tmp_path, shell=shell, capture=Capture((0, "401"), (0, "402")))

    assert runner.validation(CHANGE, None, "ci", "start", owed="ci.yml")
    assert runner.validation(CHANGE, None, "ci", "start", owed="docker.yml")
    assert runner.validation(CHANGE, None, "ci", "collect", owed="docker.yml")
    assert runner.validation(CHANGE, None, "ci", "collect", owed="ci.yml")

    assert runner.capture.commands == ["make run-ci WORKFLOW=ci.yml",
                                       "make run-ci WORKFLOW=docker.yml"]
    assert shell.commands == ["make validate-ci WORKFLOW=docker.yml CI_AFTER_RUN=402",
                              "make validate-ci WORKFLOW=ci.yml CI_AFTER_RUN=401"]


def test_the_pipeline_is_collected(tmp_path: Path) -> None:
    """CW-x9bt: the engine fills `{after}`, with no marker passed by the skill."""
    shell = Shell()
    runner = _validating(tmp_path, shell=shell, capture=Capture((0, "40733870392")))

    runner.validation(CHANGE, None, "pipeline", "start")
    runner.validation(CHANGE, None, "pipeline", "collect")

    assert shell.commands == ["make fetch-e2e-logs E2E_AFTER_RUN=40733870392"]


def test_a_retried_start_replaces_its_marker(tmp_path: Path) -> None:
    shell = Shell()
    runner = _validating(tmp_path, shell=shell, capture=Capture((0, "401"), (0, "405")))

    runner.validation(CHANGE, None, "pipeline", "start")
    runner.validation(CHANGE, None, "pipeline", "start")
    runner.validation(CHANGE, None, "pipeline", "collect")

    assert shell.commands == ["make fetch-e2e-logs E2E_AFTER_RUN=405"]


@pytest.mark.parametrize("printed", [(1, "401"), (0, None)])
def test_a_start_that_failed_or_printed_nothing_keeps_no_marker(
        tmp_path: Path, printed: tuple[int, str | None]) -> None:
    runner = _validating(tmp_path, capture=Capture((0, "399"), printed))
    runner.validation(CHANGE, None, "pipeline", "start")

    runner.validation(CHANGE, None, "pipeline", "start")

    with pytest.raises(hooks.HookError, match="has kept a marker"):
        runner.validation(CHANGE, None, "pipeline", "collect")


def test_a_collect_with_no_marker_names_the_start_to_run(tmp_path: Path) -> None:
    shell = Shell()
    runner = _validating(tmp_path, shell=shell)

    with pytest.raises(hooks.HookError,
                       match=rf"run `scripts/change-workflow run validation {CHANGE} ci start "
                             r"--owed ci.yml` first"):
        runner.validation(CHANGE, None, "ci", "collect", owed="ci.yml")
    assert shell.commands == []


def test_a_marker_is_kept_for_its_commit(tmp_path: Path) -> None:
    started = _validating(tmp_path, capture=Capture((0, "401")), head="aaaa")
    started.validation(CHANGE, None, "pipeline", "start")

    with pytest.raises(hooks.HookError, match="at bbbb has kept a marker"):
        _validating(tmp_path, head="bbbb").validation(CHANGE, None, "pipeline", "collect")


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


# `run cleanup`: every part's cleanup, as one list.

def test_a_changes_validation_left_resources(tmp_path: Path) -> None:
    """CW-ikmm: archive cleanup runs the Helm part's cleanup, in order."""
    shell, echoed = Shell(), []
    runner = _validating(tmp_path, shell=shell, echoed=echoed, step="archive-cleanup")

    assert runner.cleanup(CHANGE, None)

    assert shell.commands == [f"make record-capacity CHANGE={CHANGE}",
                              f"make -C helm teardown CHANGE={CHANGE}"]
    assert [(i.part, i.phase) for i in runner.invoked] == [("helm", "cleanup")] * 2


def test_a_parts_cleanup_finds_nothing(tmp_path: Path) -> None:
    """CW-ikmm: a cleanup that removes nothing succeeds; one failing still lets the
    rest run, and fails the cleanup."""
    text = PARTS.replace('[validation.parts.local]\nrun = "make validate-local"',
                         '[validation.parts.local]\nrun = "make validate-local"\n'
                         'cleanup = "make dist-clean"')
    shell = Shell({"make dist-clean": 0, f"make record-capacity CHANGE={CHANGE}": 1})
    runner = _validating(tmp_path, text, shell=shell, step="archive-cleanup")

    assert not runner.cleanup(CHANGE, None)

    assert shell.commands == ["make dist-clean", f"make record-capacity CHANGE={CHANGE}",
                              f"make -C helm teardown CHANGE={CHANGE}"]


def test_no_part_declaring_a_cleanup_is_skipped_saying_so(tmp_path: Path) -> None:
    echoed: list[str] = []
    runner = _validating(tmp_path, "[validation.parts.local]\nrun = 'true'\n", echoed=echoed,
                         step="archive-cleanup")

    assert runner.cleanup(CHANGE, None)

    assert echoed == ["[change-workflow] cleanup at c0ffee: skipped, no part declares a cleanup"]


def test_only_archive_cleanup_runs_the_cleanups(tmp_path: Path) -> None:
    with pytest.raises(hooks.HookError, match="the validate step may not run cleanup"):
        _validating(tmp_path).cleanup(CHANGE, None)


# What a run invoked, kept by its session for its line.

def _ignoring_records(root: Path) -> Path:
    with (root / ".git/info/exclude").open("a", encoding="utf-8") as exclude:
        exclude.write("/openspec/changes/*/reviews/\n")
    return root


def test_validations_helm_part_fails(repository: Path) -> None:
    """CW-q5fy: library integration, a real `sh` and Git directory; the run's line
    lists the part with its resolved command and exit status 2."""
    configured(_ignoring_records(repository),
               "[validation.parts.helm]\nrun = 'exit 2'\nevidence = '.snapshot/validation/'\n"
               + MODELS)
    ran: list[int] = []

    class Validating(FakeClaude):
        """A validation run whose step runs the Helm part."""

        def __call__(self, command, cwd, feed, step) -> int:
            ran.append(main(["run", "validation", CHANGE, "helm", "run"], root=repository,
                            environ={SESSION_ID: SESSION, UNATTENDED: step}))
            return super().__call__(command, cwd, feed, step)

    line = make_wrapper(repository, Validating((event_lines(VALID["finished"]), 0))).run(
        "validate", CHANGE)

    assert ran == [1]
    (invoked,) = line["invoked"]
    assert {key: invoked[key] for key in ("hook", "part", "phase", "command", "exit_status")} \
        == {"hook": "validation", "part": "helm", "phase": "run", "command": "exit 2",
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
        'torn {"change"\n{"change": "' + CHANGE + '", "command": "a b"}\n', "utf-8")
    wrapper = make_wrapper(tmp_path, FakeClaude((event_lines(VALID["finished"]), 0)))
    wrapper.invocations = lambda _: kept

    line = wrapper.run("design", CHANGE)

    assert line["invoked"] == [{"change": CHANGE, "command": "a b"}]
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


def test_an_owed_start_and_collect_through_the_command(repository: Path,
                                                       capfd: pytest.CaptureFixture[str]
                                                       ) -> None:
    """Library integration: a real `sh` and Git directory, through `cli.main`."""
    configured(repository, """
[validation.parts.ci]
owed = true
start = "echo dispatched {owed}; echo 77"
collect = "echo waited past {after} for {owed}"
""")
    environ = {UNATTENDED: "validate"}

    assert main(["run", "validation", CHANGE, "ci", "start", "--owed", "ci.yml"],
                root=repository, environ=environ) == 0
    assert main(["run", "validation", CHANGE, "ci", "collect", "--owed", "ci.yml"],
                root=repository, environ=environ) == 0

    out = capfd.readouterr().out
    assert "dispatched ci.yml\n77\n" in out
    assert "waited past 77 for ci.yml\n" in out


def test_run_cleanup_through_the_command(repository: Path) -> None:
    configured(repository, "[validation.parts.helm]\nrun = 'true'\n"
                           "cleanup = ['touch first', 'touch second']\n")

    assert main(["run", "cleanup", CHANGE], root=repository,
                environ={UNATTENDED: "archive-cleanup"}) == 0

    assert (repository / "first").exists() and (repository / "second").exists()


def test_a_session_id_naming_another_place_is_refused(tmp_path: Path) -> None:
    with pytest.raises(StepError, match="no session id"):
        keep_invocations(tmp_path, "../elsewhere", [{"n": 1}])
