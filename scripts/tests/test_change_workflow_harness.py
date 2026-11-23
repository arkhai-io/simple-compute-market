"""Each harness's adapter: Claude Code's unattended command and Codex's, the state
each harness writes and the settings it loads, the steps each runs, the refusals
each reads, Codex's plain output condensed into progress, and a run marked as the
wrapper's in its environment."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import pytest

from change_workflow import adapters, claude_code, codex
from change_workflow.common import UNATTENDED_RUN
from change_workflow.graph import STEPS
from change_workflow.harness import UNATTENDED, Model, refused
from change_workflow.running import Terminated, termination_ends_the_run
from change_workflow.sandbox import missing
from change_workflow_fixtures import OPUS, option, option_rules


_MARKER = f"import os; print(os.environ.get({UNATTENDED_RUN!r}))"
_SCHEMA = {"type": "object", "properties": {"outcome": {"type": "string"}}}


def test_the_process_a_claude_run_starts_sees_the_step_it_is_the_run_of(
        tmp_path: Path) -> None:
    # The run's process stands in for Claude Code, whose own commands inherit its
    # environment.
    said: list[str] = []

    status = claude_code.run([sys.executable, "-c", _MARKER], tmp_path, said.append, "validate")

    assert (status, said) == (0, ["validate\n"])


def test_the_process_a_codex_review_starts_sees_it_is_the_reviews(tmp_path: Path) -> None:
    log = tmp_path / "review.log"

    assert codex.run([sys.executable, "-c", _MARKER], log) == 0

    assert log.read_text("utf-8") == "review\n"


_SESSION = "import os; print(os.environ.get('CLAUDE_CODE_SESSION_ID', 'none'))"


def test_a_codex_reviews_commands_keep_what_they_invoke_under_the_runs_key(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """CW-w3oa: Codex names no session in its commands' environment, so the starting
    session's is withheld from them, and the engine's key for the review's run given
    in its place where there is one."""
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "the-starting-session")
    keyed, unkeyed = tmp_path / "keyed.log", tmp_path / "unkeyed.log"

    assert codex.run([sys.executable, "-c", _SESSION], keyed, "review-codex-1") == 0
    assert codex.run([sys.executable, "-c", _SESSION], unkeyed) == 0

    assert keyed.read_text("utf-8") == "review-codex-1\n"
    assert unkeyed.read_text("utf-8") == "none\n"


# A process that writes its id to the file it is given, signals the run that
# started it as a stop would, and runs on until it is ended.
_SIGNALLING = ("import os, signal, sys, time; open(sys.argv[1], 'w').write(str(os.getpid())); "
               "os.kill(os.getppid(), signal.SIGTERM); time.sleep(60)")


def _gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


def test_a_terminated_codex_run_ends_its_reviewer(tmp_path: Path) -> None:
    """Library integration: a real reviewer process, which the run ends before it
    is logged, so nothing writes the review after the stop."""
    started = tmp_path / "reviewer.pid"

    with pytest.raises(Terminated), termination_ends_the_run():
        codex.run([sys.executable, "-c", _SIGNALLING, str(started)], tmp_path / "review.log")

    assert _gone(int(started.read_text("utf-8")))


def test_a_terminated_claude_run_ends_its_agent(tmp_path: Path) -> None:
    """Library integration: a real agent process, ended before the run is logged."""
    started = tmp_path / "agent.pid"

    with pytest.raises(Terminated), termination_ends_the_run():
        claude_code.run([sys.executable, "-c", _SIGNALLING, str(started)], tmp_path,
                        lambda _: None, "implement")

    assert _gone(int(started.read_text("utf-8")))


def test_claude_codes_command_for_a_fresh_run_allows_every_tool_but_its_rule() -> None:
    command = claude_code.command("go", _SCHEMA, OPUS)

    assert command[:5] == ["claude", "-p", "go", "--model", "claude-opus-5-5"]
    assert option(command, "--effort") == "high"
    assert option(command, "--session-id")
    assert "--resume" not in command
    assert option(command, "--permission-mode") == "dontAsk"
    assert option(command, "--setting-sources") == "project"
    assert json.loads(option(command, "--settings")) == {"sandbox": {"enabled": False}}
    assert option(command, "--append-system-prompt") == UNATTENDED
    assert json.loads(option(command, "--json-schema"))["type"] == "object"
    assert option_rules(command, "--allowedTools") == list(claude_code.TOOLS)
    assert {"Bash", "Edit", "Write", "Read", "Agent"} <= set(claude_code.TOOLS)
    assert option_rules(command, "--disallowedTools") == ["Bash(git push*)"]


def test_claude_codes_command_for_a_resumed_run_names_no_session_of_its_own() -> None:
    command = claude_code.command("The owner's answer: A.", None, Model("claude", "m"),
                                  session="s-1", system="review")

    assert option(command, "--resume") == "s-1"
    assert "--session-id" not in command
    assert "--effort" not in command
    assert "--json-schema" not in command
    assert option(command, "--append-system-prompt") == "review"


def test_claude_codes_adapter_declares_its_state_settings_and_steps() -> None:
    adapter = adapters.ADAPTERS["claude"]

    assert (adapter.state, adapter.state_files) == (("~/.claude",), ("~/.claude.json",))
    assert adapter.protected == (".claude/settings.json", ".claude/settings.local.json",
                                 "~/.claude/settings.json", "~/.claude/skills/")
    assert adapter.skills == "~/.claude/skills/"
    assert all(adapter.runs(step) for step in STEPS)
    assert adapter.rules == ("Bash(git push*)",)


@pytest.mark.parametrize("confined,mode", [(True, "danger-full-access"), (False, "read-only")],
                         ids=["confined", "unconfined"])
def test_codex_runs_without_its_own_sandbox_only_inside_the_engines(
        tmp_path: Path, confined: bool, mode: str) -> None:
    """CW-t6mb's "Codex runs a review" and "Codex runs a review without the sandbox":
    inside the engine's sandbox Codex runs without its own, whose fresh `/dev` would
    hide the system's Git the engine's `git` runs; outside it, in its own read-only
    sandbox, fresh and resumed alike."""
    draft = tmp_path / "draft.md"

    fresh = codex.command("review it", draft, tmp_path, "gpt-6", "high", confined=confined)
    resumed = codex.resume_command("abc", "again", draft, "gpt-6", confined=confined)

    assert fresh == ["codex", "exec", "--sandbox", mode, "--cd", str(tmp_path),
                     "--output-last-message", str(draft), "--model", "gpt-6",
                     "--config", 'model_reasoning_effort="high"', "review it"]
    assert resumed == ["codex", "exec", "resume", "abc", "--config", f'sandbox_mode="{mode}"',
                       "--output-last-message", str(draft), "--model", "gpt-6", "again"]


def test_codexs_adapter_declares_its_state_settings_and_the_review_alone() -> None:
    adapter = adapters.ADAPTERS["codex"]

    assert (adapter.state, adapter.state_files) == (("~/.codex",), ())
    assert adapter.protected == ("~/.codex/config.toml", "~/.codex/skills/")
    assert adapter.skills == "~/.codex/skills/"
    assert [step for step in STEPS if adapter.runs(step)] == ["review"]
    assert adapter.rules == ()


def test_every_adapters_settings_are_protected_whichever_harness_runs() -> None:
    assert adapters.HARNESSES == ("claude", "codex")
    assert set(adapters.PROTECTED) == {".claude/settings.json", ".claude/settings.local.json",
                                       "~/.claude/settings.json", "~/.claude/skills/",
                                       "~/.codex/config.toml", "~/.codex/skills/"}


def test_the_unattended_prompt_is_one_harness_neutral_paragraph() -> None:
    """The prompt says the step runs in a sandbox scoped to it, what a refused write
    means, how to stop or go on, and how to wait, and names no rule, no chain, no
    harness's permission mode, and no `-C` form."""
    lowered = UNATTENDED.lower()

    for absent in ("rule", "chain", "don't ask mode", "bash call"):
        assert absent not in lowered, absent
    assert not re.search(r"-c\b", lowered)
    for present in ("sandbox scoped to it", "read-only file system", "resource busy",
                    "`stopped`", "names the path", "change-workflow wait"):
        assert present in UNATTENDED, present
    assert "\n" not in UNATTENDED


def test_a_harness_not_installed_is_read_from_bubblewraps_own_line() -> None:
    assert missing("bwrap: execvp claude: No such file or directory\n", ["claude", "-p"])
    # A line the run's output quotes, from a file it read, is not bubblewrap's own.
    assert not missing("cat notes.md\n> bwrap: execvp claude: No such file or directory\n",
                       ["claude"])
    assert not missing("bwrap: execvp codex: No such file or directory", ["claude"])


def test_a_refused_write_is_found_by_either_error() -> None:
    assert refused("touch: cannot touch 'x': Read-only file system") == (
        "touch: cannot touch 'x': Read-only file system")
    assert refused("ok\nmv: cannot move: Device or resource busy\n") == (
        "mv: cannot move: Device or resource busy")
    assert refused("Permission denied") is None


CODEX_REFUSED = """session id: abc
--------
exec
/bin/bash -lc 'make check-comment-hygiene' in /repo
 exited 2 in 40ms:
mkdir: cannot create directory '.cache': Read-only file system
make: *** Error 1
exec
/bin/bash -lc 'rg "Read-only file system" scripts' in /repo
 succeeded in 3ms:
scripts/change_workflow/harness.py: read-only file system
codex
The check could not write its cache: Read-only file system.
"""


def test_codex_reads_a_refusal_from_a_failed_commands_output_alone() -> None:
    assert codex.refusals(CODEX_REFUSED) == [
        {"tool": "exec", "command": "make check-comment-hygiene",
         "error": "mkdir: cannot create directory '.cache': Read-only file system"}]


def test_another_harnesss_events_end_codexs_last_command() -> None:
    # A review's attempts share a transcript: Claude Code's events after Codex's
    # failed command are not that command's output.
    failed = "exec\n/bin/bash -lc 'make check' in /repo\n exited 2 in 1ms:\nError 1\n"
    event = json.dumps({"type": "user", "message": "touch: Read-only file system"})

    assert codex.refusals(failed + event + "\n") == []


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
    progress = codex.Progress()
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
    assert len(review) == codex.Progress.MESSAGE_LINES + 1


def test_progress_always_shows_errors() -> None:
    assert _shown("model: m\nERROR: the model is not supported\n") == [
        "model: m", "ERROR: the model is not supported"]
