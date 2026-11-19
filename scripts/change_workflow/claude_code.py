"""Claude Code's adapter: how a step runs as a headless Claude Code session, what
its harness writes and loads, and how its refusals and denials are read.

An unattended run is `claude -p`, in the `dontAsk` permission mode so that nothing
waits on a prompt nobody will answer, with every built-in tool a step works with
allowed and only the project's settings loaded, the owner's user and local settings
not; Claude Code's own sandbox is off, since the engine's confines the whole process,
its file tools as well as its shell (CW-x3pf). Its one command rule refuses `git
push`, beside the sandbox's own `git` (CW-j4cs): a call the rule refuses is a denial
the run records. It is told to end its turn with an outcome matching the
outcome schema, and streams its events, which `stream` reads: each tool call it was
denied, and each tool result saying the sandbox refused a write.

Claude Code writes its sessions and settings under `~/.claude`, and its global state
to `~/.claude.json`, a file in the home directory, mounted alone so that no step
writes the home directory whole. It loads `.claude/settings.json`, and
`~/.claude/settings.json` too, though a run loads only the project's: every file
whose rules or hooks it could load is protected, `.claude/settings.local.json`
among them, so no step changes what its harness lets it do (CW-r6kd).

Contract: openspec/specs/change-workflow/spec.md, CW-t6mb, CW-x3pf, CW-r6kd, CW-k5mk,
and CW-w3oa.
"""

from __future__ import annotations

import json
import os
import posixpath
import re
import subprocess
import uuid
from pathlib import Path
from typing import Any, Callable, Sequence

from .common import UNATTENDED_RUN
from .graph import STEPS
from .harness import UNATTENDED, Adapter, Model
from .outcome import harness_schema
from .steps import StepRules

HARNESS = "claude"
ADAPTER = Adapter(
    harness=HARNESS,
    steps=frozenset(STEPS),
    state=("~/.claude",),
    state_files=("~/.claude.json",),
    protected=(".claude/settings.json", ".claude/settings.local.json",
               "~/.claude/settings.json"),
    rules=("Bash(git push*)",),
)
# The built-in tools a step works with, each allowed whole: the sandbox, not a rule,
# bounds what a step writes. A tool that waits for a later turn — a monitor, a
# wake-up, a scheduled task — is no step's, since an unattended turn's end is its
# outcome, so it stays denied, and the denial is recorded.
TOOLS = ("Agent", "Task", "Bash", "Read", "Edit", "Write", "NotebookEdit", "Glob", "Grep",
         "Skill", "TodoWrite", "ToolSearch", "WebFetch", "WebSearch")
# Claude Code's own sandbox, off: the engine's confines the whole process.
_SETTINGS = json.dumps({"sandbox": {"enabled": False}})

# A file-tool rule: the tool and the path pattern inside its parentheses.
_PATH_RULE = re.compile(r"^(Read|Edit|Write|NotebookEdit)\((.*)\)$", re.S)


def _head(prompt: str, model: Model, session: str | None) -> list[str]:
    """The command's start: the prompt straight after `-p`, since the rule lists
    after it are variadic and would take a prompt placed after them as one more rule;
    then the model, and a fresh run's own session id.

    Without one, a headless child started from inside another Claude Code session
    inherits that session's id from its environment, its events and log line then
    name the parent, and resuming the recorded id reopens the parent's conversation
    instead of the step's."""
    command = ["claude", "-p", prompt, "--model", model.model]
    if not session:
        command += ["--session-id", str(uuid.uuid4())]
    if model.effort:
        command += ["--effort", model.effort]
    return command


def _tail(schema: dict[str, Any] | None, system: str, session: str | None) -> list[str]:
    """The output, the schema a step's outcome matches — a review is given none: its
    final message is the review — the system prompt, and the session it resumes."""
    command = ["--output-format", "stream-json", "--verbose"]
    if schema is not None:
        command += ["--json-schema", json.dumps(harness_schema(schema))]
    command += ["--append-system-prompt", system]
    if session:
        command += ["--resume", session]
    return command


def command(prompt: str, schema: dict[str, Any] | None, model: Model, *,
            session: str | None = None, system: str = UNATTENDED) -> list[str]:
    """The headless Claude Code command for one turn of a step on `model`, as the
    engine launches it inside the step's sandbox: every tool allowed, the adapter's
    command rules denied, the project's settings alone, and Claude Code's own
    sandbox off."""
    return [*_head(prompt, model, session),
            "--permission-mode", "dontAsk", "--setting-sources", "project",
            "--settings", _SETTINGS, *_tail(schema, system, session),
            "--allowedTools", *TOOLS, "--disallowedTools", *ADAPTER.rules]


def anchored(rule: str, root: Path) -> str:
    """`rule` with a relative path pattern anchored at `root`, any other rule as it is.

    Claude Code resolves a file-tool rule's bare or `./` pattern against the
    session's working directory at the moment of each call, not where the session
    started. A step that changes directory partway through, such as `cd` into an
    archive directory to list its reviews, would then lose every relative rule its
    table grants for the rest of the session. Written as `//<root>/<pattern>`, the
    pattern names the checkout's own files wherever the session stands. Patterns
    already absolute (`//`), home-relative (`~/`), or settings-relative (`/`) are
    left alone. A pattern reaching above the checkout, such as a sibling worktree's
    `../*-proposal/**`, has its `..` resolved here: Claude Code never matches a
    pattern holding a `..` segment.
    """
    match = _PATH_RULE.match(rule)
    if not match:
        return rule
    tool, pattern = match.groups()
    if pattern.startswith(("/", "~/")) or pattern == "~":
        return rule
    relative = pattern[2:] if pattern.startswith("./") else pattern
    return f"{tool}(/{posixpath.normpath(f'{root.resolve().as_posix()}/{relative}')})"


def table_command(prompt: str, rules: StepRules, schema: dict[str, Any] | None, model: Model,
                  *, root: Path, session: str | None = None, granted: Sequence[str] = (),
                  system: str = UNATTENDED) -> list[str]:
    """The headless Claude Code command for one turn of a step held to its rules in
    the step table, on `model`, with only the project's settings loaded. Every
    file-tool rule, granted ones too, is anchored at `root`, the checkout the run
    starts in (`anchored`)."""
    command = [*_head(prompt, model, session),
               "--permission-mode", "dontAsk", "--setting-sources", "project",
               *_tail(schema, system, session)]
    allow = [anchored(rule, root) for rule in (*rules.allow, *granted)]
    if allow:
        command += ["--allowedTools", *allow]
    if rules.deny:
        command += ["--disallowedTools", *(anchored(rule, root) for rule in rules.deny)]
    return command


def run(command: Sequence[str], cwd: Path, feed: Callable[[str], None], step: str) -> int:
    """Run a headless Claude Code turn of `step`, every command it starts seeing in
    its environment that the run is the unattended run of that step
    (`UNATTENDED_RUN`)."""
    process = subprocess.Popen(list(command), cwd=cwd, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               env={**os.environ, UNATTENDED_RUN: step},
                               text=True, encoding="utf-8", errors="replace")
    assert process.stdout is not None
    try:
        for line in process.stdout:
            feed(line)
        return process.wait()
    finally:
        # The wrapper records the run as ended, so a session it has stopped
        # watching must not go on acting.
        if process.poll() is None:
            process.kill()
            process.wait()
