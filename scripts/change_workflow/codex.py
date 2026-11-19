"""Codex's adapter: how a review runs in Codex, what its harness writes and loads, and
how its refusals are read.

A review runs in Codex's own read-only sandbox (`codex exec --sandbox read-only`),
kept inside the engine's: the reviewer must never change what it reviews, and the
two nest. Its plain output is condensed into progress. Codex writes its sessions
and state under `~/.codex`, and loads `~/.codex/config.toml`, which no step writes
(CW-r6kd). It runs only the review: a writing step needs the denial record Claude
Code keeps, and Codex keeps none. It has no command rules.

Codex records no denials. A write the engine's sandbox refused shows in the output of
the command that made it, which `refusals` reads (CW-w3oa).

Contract: openspec/specs/change-workflow/spec.md, CW-t6mb, CW-r6kd, CW-zq4h, and
CW-w3oa.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from .common import SESSION_ID, UNATTENDED_RUN, Entry, repository_root
from .harness import Adapter, refused

HARNESS = "codex"
ADAPTER = Adapter(
    harness=HARNESS,
    steps=frozenset({"review"}),
    state=("~/.codex",),
    state_files=(),
    protected=("~/.codex/config.toml",),
)
# What starts a command in Codex's output, and what ends its line.
_EXEC = "/bin/bash -lc "
_IN = " in /"


def _options(output: Path, model: str | None, effort: str | None) -> list[str]:
    options = ["--output-last-message", str(output)]
    if model:
        options += ["--model", model]
    if effort:
        options += ["--config", f'model_reasoning_effort="{effort}"']
    return options


def command(prompt: str, output: Path, root: Path, model: str | None,
            effort: str | None = None) -> list[str]:
    return ["codex", "exec", "--sandbox", "read-only", "--cd", str(root),
            *_options(output, model, effort), prompt]


def resume_command(session: str, prompt: str, output: Path, model: str | None,
                   effort: str | None = None) -> list[str]:
    # `exec resume` takes no --sandbox flag, so the read-only sandbox is set through
    # configuration; the reviewer must never be able to change what it reviews.
    return ["codex", "exec", "resume", session, "--config", 'sandbox_mode="read-only"',
            *_options(output, model, effort), prompt]


def _command_line(line: str) -> str:
    """The command an `exec` line of Codex's output runs."""
    return line[len(_EXEC):].rsplit(_IN, 1)[0].strip("'\"")


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
        if self._block == "exec" and line.startswith(_EXEC):
            return [f"$ {_command_line(line)[:150]}"]
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


def refusals(text: str) -> list[Entry]:
    """Each write the engine's sandbox refused in a Codex run's output `text`: the
    command whose output says so, and the line saying it, once per command.

    Only a failed command's own output is read, after Codex says it exited and
    before the next block: the agent's messages, and a command that succeeded, such
    as a search, may quote such an error without meeting it."""
    found: list[Entry] = []
    block, ran = "", ""
    for line in text.splitlines():
        if line.startswith("{"):
            # Another harness's event, in a transcript a review's attempts share: it
            # ends whatever Codex block came before it.
            block, ran = "", ""
            continue
        label = line.strip()
        if label in ("codex", "exec", "user", "thinking", "tokens used") and line == label:
            block = label
            continue
        if block == "exec" and line.startswith(_EXEC):
            ran = _command_line(line)
            continue
        if line.startswith(" succeeded in ") or line.startswith(" exited "):
            block = "failed" if line.startswith(" exited ") else "output"
            continue
        if block == "failed" and ran and (error := refused(line)):
            found.append({"tool": "exec", "command": ran, "error": error})
            ran = ""
    return found


def run(command: Sequence[str], log: Path) -> int:
    """Run a review in Codex, every command it starts seeing in its environment that
    it is the unattended run of the review (`UNATTENDED_RUN`). Codex names no
    session in its commands' environment, so the session of whatever started the
    review is withheld: what the reviewer runs is no part of that session's line. The
    process keeps the descriptors the sandbox reads as it starts, the only inheritable
    ones the engine opens (`sandbox.Launch`)."""
    progress = Progress()
    environment = {key: value for key, value in os.environ.items() if key != SESSION_ID}
    # Appended: a review's attempts on each of its models share one transcript.
    with log.open("a", encoding="utf-8") as stream:
        process = subprocess.Popen(list(command), cwd=repository_root(), stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   env={**environment, UNATTENDED_RUN: "review"},
                                   close_fds=False,
                                   text=True, encoding="utf-8", errors="replace")
        assert process.stdout is not None
        try:
            for line in process.stdout:
                stream.write(line)
                for shown in progress.feed(line):
                    print(shown, file=sys.stderr, flush=True)
            for shown in progress.close():
                print(shown, file=sys.stderr, flush=True)
            return process.wait()
        finally:
            # The review is logged as ended, so an unwatched reviewer must not go
            # on to write its output.
            if process.poll() is None:
                process.kill()
                process.wait()
