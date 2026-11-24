"""Claude Code's adapter: how a step runs as a headless Claude Code session, what
its harness writes and loads, and how its refusals and denials are read.

An unattended run is `claude -p`, in the `dontAsk` permission mode so that nothing
waits on a prompt nobody will answer, with every built-in tool a step works with
allowed and only the project's settings loaded, the owner's user and local settings
not. Claude Code loads its user skill directory's skills only with the user's
settings, so the run adds the home directory as a working directory, whose
`.claude/skills/` it loads beside the project's: the installed workflow's skills,
without the owner's settings (CW-d8de). The engine's sandbox, not Claude Code's
working directories, bounds what the run writes. The skills an installed engine
ships are the ones its run must load (`shipped_skills`), which the stream holds to
the skills its `init` event lists. Claude Code's own sandbox is off, since the
engine's confines the whole process, its file tools as well as its shell (CW-x3pf). Its one command rule refuses `git
push`, beside the sandbox's own `git` (CW-j4cs): a call the rule refuses is a denial
the run records. It is told to end its turn with an outcome matching the
outcome schema, and streams its events, which `stream` reads: each tool call it was
denied, and each tool result saying the sandbox refused a write.

Claude Code writes its sessions and settings under `~/.claude`, and its global state
to `~/.claude.json`, a file in the home directory, mounted alone so that no step
writes the home directory whole. It loads `.claude/settings.json`, and
`~/.claude/settings.json` too, though a run loads only the project's: every file
whose rules or hooks it could load is protected, `.claude/settings.local.json`
among them, so no step changes what its harness lets it do; and so is its user skill
directory, `~/.claude/skills/`, where the workflow's installer writes the skills
every later step follows (CW-r6kd).

Contract: openspec/specs/change-workflow/spec.md, CW-t6mb, CW-x3pf, CW-r6kd, CW-k5mk,
CW-w3oa, and CW-d8de.
"""

from __future__ import annotations

import json
import os
import subprocess
import uuid
from pathlib import Path
from typing import Any, Callable, Sequence

from . import documents
from .common import UNATTENDED_RUN
from .graph import STEPS
from .harness import UNATTENDED, Adapter, Model
from .outcome import harness_schema

HARNESS = "claude"
ADAPTER = Adapter(
    harness=HARNESS,
    steps=frozenset(STEPS),
    state=("~/.claude",),
    state_files=("~/.claude.json",),
    protected=(".claude/settings.json", ".claude/settings.local.json",
               "~/.claude/settings.json", "~/.claude/skills/"),
    skills="~/.claude/skills/",
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


def shipped_skills(distribution: documents.Distribution = documents.RUNNING) -> frozenset[str]:
    """The skills a run's harness must load: each the installed distribution ships,
    which `change-workflow install` writes into the user skill directory; none for the
    engine run from its source tree, which nothing installs (CW-1rhd, CW-d8de)."""
    return frozenset(distribution.skills()) if distribution.installed else frozenset()


def command(prompt: str, schema: dict[str, Any] | None, model: Model, *,
            session: str | None = None, system: str = UNATTENDED,
            home: Path | None = None) -> list[str]:
    """The headless Claude Code command for one turn of a step on `model`, as the
    engine launches it inside the step's sandbox: every tool allowed, the adapter's
    command rules denied, the project's settings alone, the user skill directory's
    skills loaded from `home` (the user's by default) as a working directory's, and
    Claude Code's own sandbox off. A review is given no schema: its final message is
    the review.

    The prompt comes straight after `-p`: the tool lists are variadic, and would
    take a prompt placed after them as one more tool. A fresh run names its own
    session id. Without one, a headless child started from inside another Claude
    Code session inherits that session's id from its environment, its events and
    log line then name the parent, and resuming the recorded id reopens the
    parent's conversation instead of the step's."""
    command = ["claude", "-p", prompt, "--model", model.model]
    if not session:
        command += ["--session-id", str(uuid.uuid4())]
    if model.effort:
        command += ["--effort", model.effort]
    command += ["--permission-mode", "dontAsk", "--setting-sources", "project",
                "--add-dir", str(home or Path.home()),
                "--settings", _SETTINGS, "--output-format", "stream-json", "--verbose"]
    if schema is not None:
        command += ["--json-schema", json.dumps(harness_schema(schema))]
    command += ["--append-system-prompt", system]
    if session:
        command += ["--resume", session]
    return [*command, "--allowedTools", *TOOLS, "--disallowedTools", *ADAPTER.rules]


def run(command: Sequence[str], cwd: Path, feed: Callable[[str], None], step: str) -> int:
    """Run a headless Claude Code turn of `step`, every command it starts seeing in
    its environment that the run is the unattended run of that step
    (`UNATTENDED_RUN`). The process keeps the descriptors the sandbox reads as it
    starts, the only inheritable ones the engine opens (`sandbox.Launch`)."""
    process = subprocess.Popen(list(command), cwd=cwd, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               env={**os.environ, UNATTENDED_RUN: step}, close_fds=False,
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
