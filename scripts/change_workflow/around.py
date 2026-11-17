"""The engine's actions and the repository's hooks around a step's session.

Before a step's session the engine runs its own actions for that moment
(`graph.STEP_ACTIONS`) — the gathering before validation, every kind's cleanup
before archive cleanup — and then the repository's `before-<step>` hook; after a
session that finished, its actions and then `after-<step>`. A review's and a
triage's hooks are given `{kind}`, the kind of review the run is or triages.

Each run has an inputs directory under its change's records,
`reviews/runs/<run>/`, named on its log line (`claim_inputs`), with `before/` and
`after/` beneath it. A hook is given its moment's directory as `{inputs}`. For each
action and hook the engine keeps everything it printed, and every program it ran
printed, as a log there, `<name>.log`, read only to diagnose a failure, and writes
`status.md`: each one's closing lines, exit status, and log. Every top-level
Markdown file a hook writes there is a message the step's skill reads in full as it
loads; any other file is data, read where a message directs, so a large artifact
never passes through an argument or the prompt. The evidence the gathering finds or
gathers stays at its patterns. `reviews/` is ignored by Git, so nothing here changes
the tree evidence describes, and `history` copies it with the records.

An absent or empty hook runs nothing, and `status.md` says so: the engine assumes no
build tool and probes for no target, so a declared command whose target is missing
fails as any command does. A failure before a session prevents nothing: the session
starts, and its skill reads the failure from `status.md`.

What each action and hook ran is kept under a session id of the engine's own, made
for the one action or hook, so the run's line takes exactly what ran around its
session, the push's `pre-push` included; nothing is kept under the session of
whoever started the run. The actions run as the step's unattended run
(`common.UNATTENDED_RUN`), so the engine's hook table holds them to that step.

A step the owner holds interactively runs them itself, `run before|after <step>
<change>` (`interactive`), into a directory named for its session, which `record`
names on the line it writes.

Contract: openspec/specs/change-workflow/spec.md, CW-g6th, CW-ikmm, CW-h3ks, CW-b7fl,
CW-a4fl, CW-i9np, CW-b2xr, and CW-q5fy.
"""

from __future__ import annotations

import os
import sys
import uuid
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from datetime import timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence

from . import gather, hooks
from .common import SESSION_ID, UNATTENDED_RUN, Clock, Entry, StepError, utc_now
from .config import Configuration
from .graph import AFTER, BEFORE, step_actions
from .hooks import PREFIX, Hooks
from .running import drop_invocations, invocations_directory, keep_invocations, kept_invocations

# Where a change's runs keep their inputs, under its records.
RUNS = "runs"
STATUS = "status.md"


def claim_inputs(reviews: Path, step: str, clock: Clock = utc_now) -> Path:
    """Create the run's inputs directory, `reviews/runs/<UTC start>-<step>/`, and
    return it. The create is exclusive, so two runs started in one second take
    `-2`, `-3`, and so on, and never share one."""
    stamp = clock().astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    runs = reviews / RUNS
    runs.mkdir(parents=True, exist_ok=True)
    number = 1
    while True:
        directory = runs / (f"{stamp}-{step}" + (f"-{number}" if number > 1 else ""))
        try:
            directory.mkdir()
            return directory
        except FileExistsError:
            number += 1


def named(directory: Path, reviews: Path) -> str:
    """How a run's line and its session name its inputs directory: relative to the
    change's records."""
    return directory.relative_to(reviews).as_posix()


@contextmanager
def output_to(path: Path) -> Iterator[None]:
    """Everything printed while the block runs — by this process, and by every
    program it runs, which inherit its standard output and error — appended to
    `path`. The wrapper's own standard output carries only the line a caller
    parses, so nothing an action prints may reach it."""
    sys.stdout.flush()
    sys.stderr.flush()
    with path.open("a", encoding="utf-8", buffering=1) as log:
        saved = (os.dup(1), os.dup(2))
        try:
            os.dup2(log.fileno(), 1)
            os.dup2(log.fileno(), 2)
            with redirect_stdout(log), redirect_stderr(log):
                yield
        finally:
            log.flush()
            os.dup2(saved[0], 1)
            os.dup2(saved[1], 2)
            os.close(saved[0])
            os.close(saved[1])


@dataclass
class Ran:
    """One action or hook run around a session: its name, its exit status, or why
    it ran nothing, its log, the engine's lines from it, and what it invoked."""

    name: str
    exit_status: int | None = None
    skipped: str | None = None
    log: Path | None = None
    lines: list[str] = field(default_factory=list)
    invoked: list[Entry] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return self.exit_status not in (None, 0)

    def closing(self) -> str:
        """What it came to, in one line."""
        if self.skipped is not None:
            return f"{self.name}: {self.skipped}; nothing ran"
        return f"{self.name}: {'failed' if self.failed else 'passed'}, exit {self.exit_status}"


def failures(ran: Sequence[Ran]) -> list[Ran]:
    return [one for one in ran if one.failed]


def _section(ran: Ran, directory: Path) -> list[str]:
    lines = [f"## {ran.name}", ""]
    if ran.skipped is not None:
        return lines + [f"{ran.skipped.capitalize()}; nothing ran.", ""]
    lines += [f"- Exit status: {ran.exit_status}"]
    if ran.log is not None:
        lines += [f"- Log: `{ran.log.relative_to(directory).as_posix()}`"]
    if ran.lines:
        lines += ["", "```text", *ran.lines, "```"]
    return lines + [""]


def write_status(directory: Path, when: str, step: str, ran: Sequence[Ran]) -> Path:
    """Append the moment's actions and hooks to `status.md` in `directory`, which a
    hook run again after a resumed session adds to rather than replaces."""
    path = directory / STATUS
    opening = [] if path.exists() else [
        f"# {when.capitalize()} {step}", "",
        f"What the engine ran {when} this run's session, in order, and what each came "
        "to. A failure here prevented nothing; each log holds what it printed, read to "
        "diagnose a failure.", ""]
    body = [line for one in ran for line in _section(one, directory)]
    with path.open("a", encoding="utf-8") as status:
        status.write("\n".join([*opening, *body]))
    return path


def _engine_lines(log: Path) -> list[str]:
    """The engine's closing lines and refusals among what a log holds."""
    if not log.is_file():
        return []
    return [line for line in log.read_text("utf-8", errors="replace").splitlines()
            if line.startswith(PREFIX) or line.startswith("ERROR:")]


def _log_name(directory: Path, name: str) -> Path:
    """`<name>.log`, or `<name>-2.log` and on for a hook run again."""
    number = 1
    while (path := directory / (f"{name}.log" if number == 1 else f"{name}-{number}.log")
           ).exists():
        number += 1
    return path


@dataclass
class Around:
    """Runs the actions and hooks around one run of a step, through injected seams."""

    root: Path
    configuration: Configuration
    change: str
    step: str
    kind: str | None = None
    base: str | None = None
    environ: Mapping[str, str] = field(default_factory=lambda: dict(os.environ))
    # Where what an action ran is kept until the run's line takes it.
    invocations: Callable[[Path], Path | None] = invocations_directory

    def environment(self, session: str) -> dict[str, str]:
        """What an action or hook runs with: the caller's environment, marked as the
        step's unattended run and keeping what it ran under `session`, the engine's
        own for it."""
        return {**{key: value for key, value in self.environ.items() if key != SESSION_ID},
                UNATTENDED_RUN: self.step, SESSION_ID: session}

    def before(self, directory: Path) -> list[Ran]:
        """Every action, then the hook, before the session; `status.md` written."""
        return self._moment(BEFORE, directory)

    def after(self, directory: Path) -> list[Ran]:
        """Every action, then the hook, after a finished session; `status.md`
        written, or added to when they run again."""
        return self._moment(AFTER, directory)

    def _moment(self, when: str, directory: Path) -> list[Ran]:
        directory.mkdir(parents=True, exist_ok=True)
        ran = [self._action(name, directory) for name in step_actions(when, self.step)]
        ran.append(self._hook(f"{when}-{self.step}", directory))
        write_status(directory, when, self.step, ran)
        return ran

    def _logged(self, name: str, directory: Path, call: Callable[[Mapping[str, str]], int]
                ) -> Ran:
        """Run `call` with its output in its log, and take what it kept."""
        session = f"{self.step}-{name}-{uuid.uuid4().hex}"
        log = _log_name(directory, name)
        with output_to(log):
            try:
                status = call(self.environment(session))
            except StepError as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                status = 1
        kept = self.invocations(self.root)
        invoked = kept_invocations(kept, session, self.change)
        drop_invocations(kept, session, invoked)
        return Ran(name, status, log=log, lines=_engine_lines(log), invoked=invoked)

    def _action(self, name: str, directory: Path) -> Ran:
        def call(environ: Mapping[str, str]) -> int:
            if name == gather.GATHER:
                return gather.main(self.change, root=self.root,
                                   configuration=self.configuration, environ=environ,
                                   base=self.base, invocations=self.invocations)
            return hooks.main(name, self.change, root=self.root,
                              configuration=self.configuration, environ=environ,
                              base=self.base, hooks=Hooks(self.root, self.configuration,
                                                          environ,
                                                          invocations=self.invocations))
        return self._logged(name, directory, call)

    def _hook(self, name: str, directory: Path) -> Ran:
        commands = self.configuration.hook(name)
        if not commands:
            return Ran(name, skipped="not declared" if commands is None else "declared empty")
        values: dict[str, Any] = {"inputs": str(directory),
                                  **({"kind": self.kind} if self.kind else {})}

        def call(environ: Mapping[str, str]) -> int:
            runner = Hooks(self.root, self.configuration, environ, invocations=self.invocations)
            try:
                return 0 if runner.engine_hook(name, runner.values(self.change, self.base,
                                                                   **values)) else 1
            finally:
                runner.keep(self.change)
        return self._logged(name, directory, call)


def session_inputs(reviews: Path, session: str, step: str) -> Path:
    """The inputs directory of a step a session holds interactively,
    `reviews/runs/session-<session>-<step>/`: found again by `run after` and by
    `record`, which names it on the line, from the session alone."""
    if not session or "/" in session or session in (".", ".."):
        raise StepError(f"{session!r} is no session id a directory can be named for")
    return reviews / RUNS / f"session-{session}-{step}"


def interactive(when: str, step: str, change: str, *, root: Path, reviews: Path,
                configuration: Configuration, environ: Mapping[str, str],
                base: str | None = None, kind: str | None = None, clock: Clock = utc_now,
                invocations: Callable[[Path], Path | None] = invocations_directory) -> int:
    """`run before|after <step> <change>`: what the wrapper runs around an
    unattended run's session, run by a step the owner holds, into its session's
    inputs directory, or a new one outside a session; what ran is kept for the
    session's line. Held to its step: an unattended run's marker naming another step
    refuses it. A review run interactively is no run, so it runs no hooks, and says
    so. 0 when everything passed, 1 when anything failed or it was refused."""
    marker = environ.get(UNATTENDED_RUN)
    if marker and marker != step:
        print(f"ERROR: this is the {marker} step's run, so it may not run what comes "
              f"{when} {step}", file=sys.stderr)
        return 1
    if step == "review":
        print(f"{PREFIX} {when}-review: skipped, a review run interactively is no run, so "
              "it runs no hooks")
        return 0
    session = environ.get(SESSION_ID)
    if session:
        run = session_inputs(reviews, session, step)
        run.mkdir(parents=True, exist_ok=True)
    else:
        run = claim_inputs(reviews, step, clock)
    around = Around(root, configuration, change, step, kind=kind, base=base,
                    environ=environ, invocations=invocations)
    ran = around.before(run / BEFORE) if when == BEFORE else around.after(run / AFTER)
    keep_invocations(invocations(root), session,
                     [entry for one in ran for entry in one.invoked])
    for one in ran:
        print(f"{PREFIX} {one.closing()}")
    print(f"{PREFIX} inputs: reviews/{named(run / when, reviews)} — read {STATUS} and every "
          "top-level Markdown file there")
    return 1 if failures(ran) else 0


def inputs_note(directory: Path, reviews: Path) -> str:
    """How a session is told its run's inputs, labelled, as the target is."""
    return (f"Inputs (the engine ran the actions and hooks before this session; read "
            f"{STATUS} and every top-level Markdown file there): reviews/"
            f"{named(directory, reviews)}")


def after_failure_note(step: str, directory: Path, reviews: Path, ran: Sequence[Ran]) -> str:
    """What a finished session is resumed with when a hook after it failed."""
    shown = "; ".join(one.closing() for one in failures(ran))
    return (f"The engine ran what follows a finished {step}, and it failed: {shown}. "
            f"Read reviews/{named(directory, reviews)}/{STATUS} and the logs it names, fix "
            f"what it found if your step can, and end with your outcome again; the hook "
            "runs once more after a finished outcome, and a second failure goes to the "
            "owner as a question.")


def after_question(step: str, directory: Path, reviews: Path, ran: Sequence[Ran],
                   said: str | None) -> Entry:
    """The run's outcome when a hook after it failed a second time: a question to the
    owner naming the hook, the session's own report kept beside it."""
    failed = failures(ran)
    names = ", ".join(one.name for one in failed)
    message = (f"{names} failed again after the {step} session was resumed with its "
               f"failure: " + "; ".join(one.closing() for one in failed)
               + f". See reviews/{named(directory, reviews)}/{STATUS} and the logs it names."
               + (f"\n\nThe session's last report: {said}" if said else ""))
    return {"outcome": "question", "message": message,
            "awaiting": f"the owner's decision on the failing {names}"}
