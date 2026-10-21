"""The two harnesses a step runs on, and how each says it cannot serve a model.

A step runs as a headless Claude Code session (`claude -p`), held to its rules
under the `dontAsk` permission mode, told to end its turn with an outcome matching
the outcome schema, and streaming its events. A review runs first in Codex's
read-only sandbox (`codex exec`), whose plain output is condensed into progress.
A harness that is missing, not signed in, or at its usage limit cannot serve its
model, and the run falls to the next model of its row; a network error says
nothing of the model's availability, so it is retried on the same model and never
passed over.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Callable, Sequence

from change_workflow.common import ROOT
from change_workflow.outcome import harness_schema
from change_workflow.steps import Model, StepRules

# Runs a command in a directory, handing each line of its merged output to the
# callback as it arrives, and returns its exit status.
Runner = Callable[[Sequence[str], Path, Callable[[str], None]], int]
# Runs a Codex command, writing its output to the transcript, and returns its exit
# status.
CodexRunner = Callable[[Sequence[str], Path], int]
# Whether a run's model could not be reached, and what it said: `unavailable` or
# `network`, or None.
Reached = tuple[str, str] | None

# What an unattended run is told beside its skill: that nobody can answer it, and
# how it ends a turn.
UNATTENDED = (
    "This step runs unattended through scripts/run_change_step.py: nobody can answer a "
    "permission prompt or a question in this session. Follow your skill's instructions for "
    "running unattended. End every turn with an outcome matching the JSON schema you were "
    "given. Where your skill says to stop and ask the owner, end the turn with a `question` "
    "outcome; the owner's answer resumes this session. Run one command per Bash call: a "
    "chained command runs only when every command in it is allowed. If a chained command is "
    "denied, run its commands one call at a time. If a single command or any other tool call "
    "is denied, finish every part of the work that does not depend on it; if the step cannot "
    "complete without that call, end with a `stopped` outcome whose `reason` names that exact "
    "call, and otherwise go on and end as the step ends, since the denial is recorded on the "
    "outcome whatever it is. One denied call is not a denied tool. A call a deny rule refused "
    "is forbidden: no other tool does it. A call denied because no rule allows it, which the "
    "harness reports as don't ask mode, may be done instead by a tool your step's rules allow "
    "for the same work, such as the Edit tool for a shell write or Read or Grep for a shell "
    "read; name the substitute in your message. Never ask about a denial as a question.")

# The retries a run is given after a network error, on the same model: a network
# error says nothing of the model's availability, so it never falls to the next.
NETWORK_RETRIES = 2
# What a harness says when it cannot serve a model: at its usage limit, or not
# signed in. Claude says "You've hit your session limit · resets 11pm …", Codex
# "You've hit your usage limit … try again at …".
_UNAVAILABLE = re.compile(r"hit your [\w ]*limit|usage limit|not logged in|not signed in|"
                          r"please run /login|invalid api key|401 unauthorized", re.I)
_NETWORK = re.compile(r"can't reach the api server|connection error|econnrefused|econnreset|"
                      r"etimedout|enotfound|eai_again|socket hang up|fetch failed|"
                      r"network error", re.I)


def claude_command(prompt: str, rules: StepRules, schema: dict[str, Any] | None, model: Model,
                   *, session: str | None = None, granted: Sequence[str] = (),
                   system: str = UNATTENDED) -> list[str]:
    """The headless Claude Code command for one turn of a step, on `model`.

    The prompt comes straight after `-p`: the rule lists are variadic, and would
    take a prompt placed after them as one more rule. Only the project's settings
    are loaded, not the owner's user or local settings with their allow rules. A
    review is given no schema: its final message is the review.

    A fresh run names its own session id. Without one, a headless child started
    from inside another Claude Code session inherits that session's id from its
    environment, its events and log line then name the parent, and resuming the
    recorded id reopens the parent's conversation instead of the step's.
    """
    command = ["claude", "-p", prompt, "--model", model.model]
    if not session:
        command += ["--session-id", str(uuid.uuid4())]
    if model.effort:
        command += ["--effort", model.effort]
    command += ["--permission-mode", "dontAsk",
                "--setting-sources", "project",
                "--output-format", "stream-json", "--verbose"]
    if schema is not None:
        command += ["--json-schema", json.dumps(harness_schema(schema))]
    command += ["--append-system-prompt", system]
    if session:
        command += ["--resume", session]
    allow = [*rules.allow, *granted]
    if allow:
        command += ["--allowedTools", *allow]
    if rules.deny:
        command += ["--disallowedTools", *rules.deny]
    return command


def missing_program(error: FileNotFoundError, command: Sequence[str]) -> bool:
    """Whether `error` is `command`'s program failing to launch.

    Launching a program that is not installed raises `FileNotFoundError` naming the
    program. Any other file a run cannot find, such as its own transcript, is the
    run's failure and says nothing of whether the harness can serve the model.
    """
    return error.filename == command[0]


def unreachable(text: str) -> Reached:
    """Whether a failed run's output says its model could not be reached.

    `unavailable` with the line saying so — a usage limit, which names when it
    resets, or a missing sign-in — or `network` for a network error; None for any
    other failure, which is the run's own.
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for pattern, kind in ((_UNAVAILABLE, "unavailable"), (_NETWORK, "network")):
        if said := next((line for line in lines if pattern.search(line)), None):
            return kind, said
    return None


def run_claude(command: Sequence[str], cwd: Path, feed: Callable[[str], None]) -> int:
    process = subprocess.Popen(list(command), cwd=cwd, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, encoding="utf-8", errors="replace")
    assert process.stdout is not None
    try:
        for line in process.stdout:
            feed(line)
        return process.wait()
    finally:
        # The wrapper records the run as ended, so a session it can no longer
        # watch must not go on acting.
        if process.poll() is None:
            process.kill()
            process.wait()


def _options(output: Path, model: str | None, effort: str | None) -> list[str]:
    options = ["--output-last-message", str(output)]
    if model:
        options += ["--model", model]
    if effort:
        options += ["--config", f'model_reasoning_effort="{effort}"']
    return options


def codex_command(prompt: str, output: Path, root: Path, model: str | None,
                  effort: str | None = None) -> list[str]:
    return ["codex", "exec", "--sandbox", "read-only", "--cd", str(root),
            *_options(output, model, effort), prompt]


def resume_command(session: str, prompt: str, output: Path, model: str | None,
                   effort: str | None = None) -> list[str]:
    # `exec resume` takes no --sandbox flag, so the read-only sandbox is set through
    # configuration; the reviewer must never be able to change what it reviews.
    return ["codex", "exec", "resume", session, "--config", 'sandbox_mode="read-only"',
            *_options(output, model, effort), prompt]


class Progress:
    """Condense Codex's plain session output into a readable progress stream.

    The transcript keeps everything; the terminal gets the session header, each
    command as one line, failed commands, errors, and the agent's messages, with
    long messages — the final review among them — cut short. Command output, which
    is mostly the files the reviewer reads, is never shown.
    """

    HEADER_KEYS = ("model:", "reasoning effort:", "sandbox:", "session id:")
    MESSAGE_LINES = 4

    def __init__(self) -> None:
        self._block = "header"
        self._message: list[str] = []

    def feed(self, line: str) -> list[str]:
        line = line.rstrip("\n")
        if line.startswith("ERROR:"):
            return [line]
        label = line.strip()
        if label in ("codex", "exec", "user", "thinking", "tokens used") and line == label:
            shown = self._flush()
            self._block = label
            return shown
        if line.startswith(" succeeded in ") or line.startswith(" exited "):
            self._block = "output"
            return [f"  ✗{line}"] if line.startswith(" exited ") else []
        if self._block == "header":
            return [line] if line.startswith(self.HEADER_KEYS) else []
        if self._block == "exec" and line.startswith("/bin/bash -lc "):
            command = line[len("/bin/bash -lc "):].rsplit(" in /", 1)[0].strip("'\"")
            return [f"$ {command[:150]}"]
        if self._block == "codex":
            self._message.append(line)
        elif self._block == "tokens used" and label:
            self._block = "done"
            return [f"tokens used: {label}"]
        return []

    def close(self) -> list[str]:
        return self._flush()

    def _flush(self) -> list[str]:
        lines = [line for line in self._message if line.strip()]
        self._message = []
        if not lines:
            return []
        shown = [f"» {line}" for line in lines[:self.MESSAGE_LINES]]
        if len(lines) > self.MESSAGE_LINES:
            shown.append(f"» … ({len(lines) - self.MESSAGE_LINES} more lines in the transcript)")
        return shown


def run_codex(command: Sequence[str], log: Path) -> int:
    progress = Progress()
    # Appended: a review's attempts on each of its models share one transcript.
    with log.open("a", encoding="utf-8") as stream:
        process = subprocess.Popen(list(command), cwd=ROOT, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, encoding="utf-8", errors="replace")
        assert process.stdout is not None
        for line in process.stdout:
            stream.write(line)
            for shown in progress.feed(line):
                print(shown, file=sys.stderr, flush=True)
        for shown in progress.close():
            print(shown, file=sys.stderr, flush=True)
        return process.wait()
