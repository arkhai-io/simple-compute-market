"""Codex's plain output is condensed into a readable progress stream, and a run on
Claude is marked as the wrapper's in its environment."""

from __future__ import annotations

import sys
from pathlib import Path

from change_workflow.harness import UNATTENDED_RUN, Progress, run_claude


def test_the_process_a_claude_run_starts_sees_it_is_the_wrappers(tmp_path: Path) -> None:
    # The run's process stands in for Claude Code, whose own commands inherit its
    # environment.
    said: list[str] = []
    command = [sys.executable, "-c", f"import os; print(os.environ.get({UNATTENDED_RUN!r}))"]

    status = run_claude(command, tmp_path, said.append)

    assert (status, said) == (0, ["1\n"])


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
