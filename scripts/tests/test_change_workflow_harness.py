"""Codex's plain output is condensed into a readable progress stream, a run on
Claude is marked as the wrapper's in its environment, and its file-tool rules are
anchored at the checkout it starts in."""

from __future__ import annotations

import sys
from pathlib import Path

from change_workflow.harness import UNATTENDED_RUN, Progress, anchored, claude_command, run_claude
from change_workflow.steps import Model, StepRules


def test_the_process_a_claude_run_starts_sees_it_is_the_wrappers(tmp_path: Path) -> None:
    # The run's process stands in for Claude Code, whose own commands inherit its
    # environment.
    said: list[str] = []
    command = [sys.executable, "-c", f"import os; print(os.environ.get({UNATTENDED_RUN!r}))"]

    status = run_claude(command, tmp_path, said.append)

    assert (status, said) == (0, ["1\n"])


def test_relative_file_rules_are_anchored_at_the_checkout(tmp_path: Path) -> None:
    # A step that changes directory partway through must keep the files its table
    # grants: a bare or ./ pattern would otherwise resolve against the new
    # working directory.
    root = tmp_path.resolve().as_posix()

    assert anchored("Edit(openspec/changes/README.md)", tmp_path) == \
        f"Edit(/{root}/openspec/changes/README.md)"
    assert anchored("Write(./docs/**)", tmp_path) == f"Write(/{root}/docs/**)"
    assert anchored("Read(**/*.py)", tmp_path) == f"Read(/{root}/**/*.py)"


def test_a_rule_reaching_above_the_checkout_is_anchored_without_dot_dot(tmp_path: Path) -> None:
    # Claude Code never matches a pattern holding `..`, so a sibling worktree's
    # rule must reach it by its resolved path.
    checkout = tmp_path / "changes" / "a-change"
    checkout.mkdir(parents=True)
    parent = (tmp_path / "changes").resolve().as_posix()

    assert anchored("Edit(../*-proposal/openspec/**)", checkout) == \
        f"Edit(/{parent}/*-proposal/openspec/**)"
    assert anchored("Read(../*-proposal/**)", checkout) == f"Read(/{parent}/*-proposal/**)"


def test_other_rules_pass_unchanged(tmp_path: Path) -> None:
    for rule in ("Read", "Grep", "Bash(make check-*)", "Edit(//etc/hosts)",
                 "Edit(~/notes.md)", "Edit(/openspec/**)", "WebFetch(domain:github.com)"):
        assert anchored(rule, tmp_path) == rule


def test_the_command_anchors_table_granted_and_deny_rules(tmp_path: Path) -> None:
    rules = StepRules(skill="change-validate", allow=("Read", "Edit(openspec/**)"),
                      deny=("Edit(.claude/**)",))
    model = Model(harness="claude", model="claude-sonnet-5-5", effort=None)
    root = tmp_path.resolve().as_posix()

    command = claude_command("go", rules, None, model, root=tmp_path,
                             granted=("Edit(docs/x.md)",))

    allowed = command[command.index("--allowedTools") + 1:command.index("--disallowedTools")]
    assert allowed == ["Read", f"Edit(/{root}/openspec/**)", f"Edit(/{root}/docs/x.md)"]
    assert command[command.index("--disallowedTools") + 1:] == [f"Edit(/{root}/.claude/**)"]


CODEX_SESSION = """Reading additional input from stdin...
OpenAI Codex v0.157.0
--------
workdir: /repo
model: gpt-6-sol
sandbox: read-only
session id: abc
--------
user
Use the change-review skill.
codex
I'll load the guidance first.
exec
/bin/bash -lc 'cat AGENTS.md' in /repo
 succeeded in 0ms:
# Repository Engineering Guidance
exec
/bin/bash -lc 'rg missing' in /repo
 exited 1 in 4ms:
codex
# Design review — shape-bounds
one
two
three
four
five
tokens used
83,133
# Design review — shape-bounds
"""


def _shown(text: str) -> list[str]:
    progress = Progress()
    shown = [out for line in text.splitlines(keepends=True) for out in progress.feed(line)]
    return shown + progress.close()


def test_progress_shows_commands_and_messages_not_file_contents() -> None:
    shown = _shown(CODEX_SESSION)

    assert shown[:3] == ["model: gpt-6-sol", "sandbox: read-only", "session id: abc"]
    assert "» I'll load the guidance first." in shown
    assert "$ cat AGENTS.md" in shown
    assert "  ✗ exited 1 in 4ms:" in shown
    assert not any("Repository Engineering Guidance" in line for line in shown)
    assert not any("Use the change-review skill" in line for line in shown)
    assert shown[-1] == "tokens used: 83,133"


def test_progress_cuts_long_messages_short() -> None:
    shown = _shown(CODEX_SESSION)

    review = [line for line in shown if line.startswith("» ") and "load the guidance" not in line]
    assert review[0] == "» # Design review — shape-bounds"
    assert review[-1] == "» … (2 more lines in the transcript)"
    assert len(review) == Progress.MESSAGE_LINES + 1


def test_progress_always_shows_errors() -> None:
    assert _shown("model: m\nERROR: the model is not supported\n") == [
        "model: m", "ERROR: the model is not supported"]
