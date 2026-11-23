"""What the engine needs of a harness, which each harness's adapter states, and what
every adapter shares: a model a step runs on, how a harness says it cannot serve
one, and the error a write the sandbox refused fails with.

Each harness the workflow runs a step on has an adapter (CW-t6mb), and the engine
reaches the harness only through it: Claude Code's (`claude_code`), which runs every
step, and Codex's (`codex`), which runs only the review. An adapter states its
unattended launch inside the step's sandbox with the harness's own prompts off, the
state its harness writes — directories, and files it writes alone, whose directory
is the home directory no step writes whole — the settings files its harness loads,
which the sandbox keeps read-only whether or not they exist (CW-r6kd), how it reads
the run's refusals and denials from its events, the steps it can run, any
command rules of its harness refusing work beside the sandbox, and its harness's
user skill directory, where the workflow's installer writes its skills and which
the adapter protects with the installer's manifest in it. `adapters` holds them
by harness.

A harness that is missing, not signed in, or at its usage limit cannot serve its
model, and the run falls to the step's next model; a network error says nothing of
the model's availability, so it is retried on the same model and never passed over.

A write outside a step's scope fails as a read-only file system, and one replacing a
protected file, which the sandbox mounts on its own, fails busy (CW-w3oa): each
adapter finds those errors in its run's events with `refused`, Claude Code's in the
tool results of its event stream (`stream`), Codex's in its commands' output.

Contract: openspec/specs/change-workflow/spec.md, CW-t6mb, CW-zq4h, and CW-w3oa.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol, Sequence

from .common import Entry


@dataclass(frozen=True)
class Model:
    """One model a step may run on: its harness, its name, and its effort."""

    harness: str
    model: str
    effort: str | None = None

    def entry(self) -> Entry:
        """The model as a log line records it."""
        return {"harness": self.harness, "model": self.model,
                **({"effort": self.effort} if self.effort else {})}


@dataclass(frozen=True)
class Adapter:
    """What the engine needs of one harness beside its commands, which its module
    gives: the steps it can run; the state its harness writes, as directories and as
    files it writes alone; the settings files its harness loads and its user skill
    directory, which no step writes; any command rules of its harness refusing work
    beside the sandbox; and the user skill directory itself, where the workflow's
    installer writes. Paths are `[sandbox]` entries: from the checkout's root, or
    from the home directory where they begin with `~`; a directory's ends in `/`."""

    harness: str
    steps: frozenset[str]
    state: tuple[str, ...]
    state_files: tuple[str, ...]
    protected: tuple[str, ...]
    skills: str
    rules: tuple[str, ...] = ()

    def runs(self, step: str) -> bool:
        return step in self.steps


class Runner(Protocol):
    """Runs a step's command in a directory, marked as the unattended run of `step`,
    handing each line of its merged output to the callback as it arrives, and
    returns its exit status."""

    def __call__(self, command: Sequence[str], cwd: Path, feed: Callable[[str], None],
                 step: str) -> int: ...


# Runs a Codex command, writing its output to the transcript, its commands keeping
# what they invoke under the engine's key for the attempt where one is given, and
# returns its exit status.
CodexRunner = Callable[[Sequence[str], Path, str | None], int]
# Whether a run's model could not be reached, and what it said: `unavailable` or
# `network`, or None.
Reached = tuple[str, str] | None

# What an unattended run is told beside its skill, whatever its harness: that nobody
# can answer it, that it runs in a sandbox scoped to its step, how it treats a write
# the sandbox refuses, how it waits, and how it ends a turn (CW-4yhk, CW-b5cf).
UNATTENDED = (
    "This step runs unattended through scripts/change-workflow: nobody can answer a "
    "question in this session. Follow your skill's instructions for running unattended. "
    "The step runs in a sandbox scoped to it, which lets it write only the paths its step "
    "may change: a write that fails as a read-only file system, or as a device or resource "
    "busy, is outside its scope. If the step cannot go on without that write, end with a "
    "`stopped` outcome whose `reason` names the path; otherwise go on within the scope, and "
    "say in your message what you did instead. The write is recorded on the run's line "
    "whatever you say, as is any call the harness denies. Never ask about either as a "
    "question. Wait on a background command with `scripts/change-workflow wait`, never by "
    "following its output, and never end your turn, schedule a wake-up, or start a monitor "
    "to wait for a background command or subagent: run a subagent in the foreground. End "
    "every turn with an outcome matching the JSON schema you were given; where your skill "
    "says to stop and ask the owner, end the turn with a `question` outcome, and the owner's "
    "answer resumes this session. A turn that starts after you have reported ends the run "
    "in your report's place.")

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
# The errors a write the sandbox refused fails with: outside the scope, a read-only
# file system; replacing a protected file mounted on its own, busy, which a shell
# tool says as the C library does and a Node.js tool as libuv does.
_REFUSED = re.compile(r"read-only file system|device or resource busy|resource busy or locked",
                      re.I)


def refused(text: str) -> str | None:
    """The first line of `text` saying a write was refused by the sandbox, or None."""
    return next((line.strip() for line in text.splitlines() if _REFUSED.search(line)), None)


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
