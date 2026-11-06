"""The repository's hooks run through the engine, `change_workflow.hooks`: their
lists, placeholders, the hook table, the default checks, and the tier a commit's
paths give."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from change_workflow import config, hooks
from change_workflow.cli import main
from change_workflow.graph import HOOK_STEPS, STEPS
from change_workflow.hooks import Hooks
from change_workflow.log import read_log
from change_workflow.review import run_review
from change_workflow_fixtures import (CHANGE, VALID, FakeClaude, claude_review, codex_missing,
                                      configured, event_lines, make_wrapper, review_text)
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
    assert echoed[-1] == ("[change-workflow] pre-commit-functional at c0ffee: failed: "
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

    run_review(CHANGE, "implementation", root=root, runner=codex_missing, claude=claude,
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
    assert echoed[-1] == "[change-workflow] pre-commit at c0ffee: passed"
    assert runner.invoked[-1].entry()["skipped"] == "not declared"


@pytest.mark.parametrize("path,inert", [("docs/a.md", True), ("docs", True),
                                        ("docsite/a.md", False), ("openspec/x", False),
                                        ("README.md", True)])
def test_an_inert_path_is_matched_whole(path: str, inert: bool) -> None:
    assert config.inert(path, ["docs/", "README.md"]) == inert


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
