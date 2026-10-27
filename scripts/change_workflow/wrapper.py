"""Running a step unattended, and resuming a waiting run with the owner's answer.

`Wrapper.run` starts the step's skill as a headless Claude Code session on the first
available of the models the step's row names, in order: a model whose harness is
missing, not signed in, or at its usage limit is passed over, and the line names
each one passed over and the model that ran; a network error is retried on the
same model, never passed over. `Wrapper.resume` continues the session of a waiting
run, named by its line in the log, with the owner's answer; with steps run side by
side the last run is not necessarily the one that asked, so the run is never
inferred. An implementation run may instead continue a session the caller names,
one not waiting on the owner, with new instructions. Any run may be granted rules
for that one run, passed on its command line and recorded as `granted` on its line,
never added to the step table.

Either way the run's event stream is kept as its transcript, and its outcome is
appended to the workflow log. A run that crashes, ends without an outcome, or ends
with one the schema rejects is logged `stopped` by the wrapper itself. A step
denied a tool ends `stopped` only when it cannot go on without it; one that went
on is logged with the outcome it ended with, and the orchestrating session reads
the recorded denials before the change moves on. A run whose session took further
turns after an outcome is logged with its last, the earlier ones kept beside it as
`earlier`.

Contract: openspec/specs/change-workflow/spec.md, "Unattended step runs end with a
structured outcome".
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

from change_workflow.common import ORCHESTRATOR, ROOT, Clock, Entry, StepError, utc_now
from change_workflow.cost import (conversation_file, measured_before, measured_cost,
                                  read_conversation)
from change_workflow.harness import (NETWORK_RETRIES, Runner, claude_command, missing_program,
                                     run_claude, unreachable)
from change_workflow.log import last_run, log_path, read_log, record_outcome
from change_workflow.outcome import SCHEMA, load_schema, outcome_problems
from change_workflow.records import git_head, next_transcript
from change_workflow.running import recorded_run, runs_directory
from change_workflow.steps import STEP_TABLE, Model, StepRules, load_steps
from change_workflow.stream import Stream
from change_workflow.subagents import subagent_denials


def step_prompt(rules: StepRules, change: str, arguments: str = "") -> str:
    return f"/{rules.skill} {change}" + (f" {arguments}" if arguments else "")


def run_outcome(status: int, result: dict[str, Any] | None, schema: dict[str, Any],
                denials: Sequence[dict[str, Any]] = ()) -> Entry:
    """The outcome to log for a run that exited with `status` and ended with `result`,
    having been denied `denials`.

    The step's own outcome when it gave a valid one; otherwise a `stopped` the
    wrapper writes, its message the reason. Every outcome carries the run's own
    record of its denials, whatever the step said: a step ends `stopped` when it
    cannot go on without a denied tool, and one that went on is logged as it
    ended, its denials there for the orchestrating session to read. The outcome
    is checked with those denials in it, since the wrapper sets them whatever the
    step gave, and an outcome the schema rejects keeps the step's own message
    ahead of the reason, so what it said to the owner is not lost.
    """
    denials = list(denials)
    outcome = (result or {}).get("structured_output")
    if isinstance(outcome, dict):
        outcome = {**outcome, "denials": denials}
    if status != 0:
        detail = (result or {}).get("result")
        reason = f"exit {status}" + (f": {detail}" if isinstance(detail, str) and detail else "")
    elif result is None:
        reason = "the run ended without a result"
    elif result.get("is_error"):
        reason = f"the run ended in error: {result.get('subtype', 'unknown')}"
    elif outcome is None:
        reason = "the run ended without an outcome"
    elif problems := outcome_problems(outcome, schema):
        reason = "the run's outcome does not conform to the schema: " + "; ".join(problems)
        said = outcome.get("message") if isinstance(outcome, dict) else None
        if isinstance(said, str) and said.strip():
            return {"outcome": "stopped", "message": f"{said}\n\n{reason}", "reason": reason,
                    "denials": denials}
    else:
        return outcome
    return {"outcome": "stopped", "message": reason, "reason": reason, "denials": denials}


# The fields of an outcome a later turn of the same run would otherwise hide.
_EARLIER_FIELDS = ("outcome", "message", "next", "reason", "awaiting")


def earlier_outcomes(results: Sequence[dict[str, Any]], last: dict[str, Any] | None
                     ) -> list[Entry]:
    """The outcomes the run's turns ended with before `last`, the result its line is
    logged from.

    A finished background command, a monitor, or a wake-up the step scheduled can
    start another turn after the step reported, and that turn's outcome becomes the
    line's; the report it followed is kept beside it, so it is never lost.
    """
    earlier = []
    for result in results:
        if result is last:
            continue
        outcome = result.get("structured_output")
        if isinstance(outcome, dict) and isinstance(outcome.get("message"), str):
            earlier.append({key: outcome[key] for key in _EARLIER_FIELDS if key in outcome})
    return earlier


@dataclass
class Wrapper:
    """Runs steps of changes under one repository root, through injected seams."""

    root: Path = ROOT
    runner: Runner = run_claude
    head: Callable[[Path], str | None] = git_head
    clock: Clock = utc_now
    # Progress goes to stderr: stdout carries only the outcome line a caller parses.
    echo: Callable[[str], None] | None = lambda shown: print(shown, file=sys.stderr, flush=True)
    steps_path: Path = STEP_TABLE
    schema_path: Path = SCHEMA
    # Where Claude Code keeps a session's conversation, read for the turns it gained
    # outside the wrapper and the time of its last turn.
    conversation: Callable[[Path, str], Path] = conversation_file
    # Where a run in progress is recorded, so no round view moves its checkout.
    runs: Callable[[Path], Path | None] = runs_directory

    def run(self, step: str, change: str, *, arguments: str = "",
            sections: Sequence[int | str] | None = None, fresh: bool = False,
            granted: Sequence[str] = (), continuing: str | None = None) -> Entry:
        """Run `step`: a fresh session, or, for a step that resumes another's, the
        latest session of either, unless `fresh`; or, for implementation, the
        session `continuing` names.

        Continuing an implementation session is the owner's choice of which
        session's context the work goes to — the next section, or a fix to edits
        it made — so the session is named, never inferred, and may be any of the
        change's implementation runs not waiting on the owner. A granted rule
        applies to this run alone, as it does to a resumed run.
        """
        steps = load_steps(self.steps_path)
        if step not in steps or step == "review":
            raise StepError(f"{step!r} has no unattended Claude Code run; a review runs "
                            "through `review`, and the others are "
                            + ", ".join(name for name in steps if name != "review"))
        rules = steps[step]
        log = log_path(self.root, change)
        if sections and step != "implement":
            raise StepError("only implementation takes sections")
        session = None
        models = rules.models
        extra: Entry = {}
        if continuing is not None:
            if step != "implement":
                raise StepError("only implementation continues a session it names")
            if fresh:
                raise StepError("a run continuing a session cannot also start fresh")
            previous = continued_run(read_log(log), change, continuing)
            session, models = continuing, _session_models(previous, rules)
            extra["continues"] = previous["seq"]
        elif rules.resume_from and not fresh:
            previous = last_run(log, [rules.resume_from, step])
            if previous is not None and not previous.get("session"):
                raise StepError(f"{change}'s last {previous['step']} run (seq "
                                f"{previous['seq']}) recorded no session to resume; run "
                                f"{step} with --fresh, or {previous['step']} again")
            if previous is not None:
                session = previous["session"]
                models = _session_models(previous, rules)
        if sections:
            extra["sections"] = list(sections)
        if granted:
            extra["granted"] = list(granted)
        return self._turn(step, rules, change, log, step_prompt(rules, change, arguments),
                          models, session=session, granted=granted, extra=extra)

    def resume(self, change: str, seq: int, answer: str, granted: Sequence[str] = ()) -> Entry:
        """Resume the step session of the run at `seq` with the owner's answer.

        The run is named, never inferred: with steps run side by side, the log's
        last run is not necessarily the one that asked. It must be waiting — its
        step's latest run, ended with a question, or stopped with no decision
        line resolving it — since an answer to any other run has nowhere to go.

        A granted rule applies to this run alone: it is passed on this command line
        and noted on this run's log line, never added to the step table, so the
        step's next run is held to its table again.

        The session resumes on the model it ran on, never the next in its row: a
        session cannot move between harnesses, so a resume whose model is
        unavailable ends stopped, saying when its limit resets.
        """
        if not answer:
            raise StepError("a resumed step needs the owner's answer")
        steps = load_steps(self.steps_path)
        log = log_path(self.root, change)
        entries = read_log(log)
        previous = next((e for e in entries if e.get("seq") == seq), None)
        if previous is None:
            raise StepError(f"{change}'s workflow log has no seq {seq}")
        step = previous.get("step")
        if step not in steps or step == "review":
            raise StepError(f"seq {seq} is a {step} line, not the run of a step that can be "
                            "resumed")
        latest = last_run(log, [step])
        if latest is None or latest["seq"] != seq:
            raise StepError(f"seq {seq} is not {step}'s latest run, so it no longer waits")
        resolved = {e.get("resolves") for e in entries if e.get("outcome") == ORCHESTRATOR}
        if seq in resolved:
            raise StepError(f"seq {seq} ended {previous.get('outcome')} and a decision line "
                            "resolves it, so it no longer waits")
        if previous.get("outcome") not in ("question", "stopped"):
            raise StepError(f"seq {seq} ended {previous.get('outcome')}, not with a question "
                            "or a stop, so it is not waiting for an answer")
        if not previous.get("session"):
            raise StepError(f"{change}'s {step} run (seq {seq}) recorded no session to "
                            "resume; run the step again")
        extra = {"sections": previous["sections"]} if previous.get("sections") else {}
        if granted:
            extra["granted"] = list(granted)
        # Framed, so an answer starting with `-` is never read as a flag.
        return self._turn(step, steps[step], change, log, f"The owner's answer: {answer}",
                          _session_models(previous, steps[step]),
                          session=previous["session"], granted=granted, extra=extra)

    def _turn(self, step: str, rules: StepRules, change: str, log: Path, prompt: str,
              models: Sequence[Model], *, session: str | None, granted: Sequence[str] = (),
              extra: Entry | None = None) -> Entry:
        """Run one turn and log it, recorded as in progress in the checkout until its
        line is written, however it ends."""
        with recorded_run(self.runs(self.root), step, change, clock=self.clock):
            return self._logged_turn(step, rules, change, log, prompt, models,
                                     session=session, granted=granted, extra=extra)

    def _logged_turn(self, step: str, rules: StepRules, change: str, log: Path, prompt: str,
                     models: Sequence[Model], *, session: str | None,
                     granted: Sequence[str] = (), extra: Entry | None = None) -> Entry:
        """Run one turn on the first of `models` that is available, and log it.

        A model whose harness is missing, not signed in, or at its usage limit
        falls to the next, and each one passed over is named on the line; a
        network error is retried on the same model, and then stops the run. The
        line names the last model tried even when none could run, with
        `unavailable` saying so: a resume of that run continues its session on
        that model, never the next in the row.

        The line goes to the log where the change is when the run ends: closeout
        archives the change it runs for, moving `reviews/` while the run writes
        its transcript, and the log found before the run would name a directory
        the archive has left.
        """
        schema = load_schema(self.schema_path)
        before = self._before(log, session)
        transcript = next_transcript(log.parent, step)
        progress = transcript.with_suffix(".progress")
        named = transcript.relative_to(log.parent).as_posix()
        failure: BaseException | None = None
        passed_over: list[Entry] = []
        outcome: Entry = {}
        # The result the line is logged from, when the step gave one.
        logged: dict[str, Any] | None = None
        status: int | None = None
        stream = Stream(transcript, progress, self.clock, self.echo)
        attempts: list[Stream] = []
        model = models[0]
        for model in models:
            for attempt in range(NETWORK_RETRIES + 1):
                # Each attempt is read alone; the transcript keeps them all.
                stream = Stream(transcript, progress, self.clock, self.echo)
                attempts.append(stream)
                command = claude_command(prompt, rules, schema, model, session=session,
                                         granted=granted)
                failure, status, reached = None, None, None
                try:
                    status = self.runner(command, self.root, stream.feed)
                    reached = unreachable(stream.failure_text(status))
                except FileNotFoundError as exc:
                    if missing_program(exc, command):
                        reached = ("unavailable", f"{command[0]} is not installed")
                    else:
                        failure = exc
                except BaseException as exc:
                    # A run that could not start, or was interrupted, still ends
                    # with a line, so the log never shows its previous outcome as
                    # the latest.
                    failure = exc
                finally:
                    stream.close()
                if reached is None or reached[0] != "network" or attempt == NETWORK_RETRIES:
                    break
            if reached is not None and reached[0] == "unavailable":
                passed_over.append({**model.entry(), "reason": reached[1]})
                continue
            if failure is not None:
                reason = (f"the run did not finish: {type(failure).__name__}"
                          + (f": {failure}" if str(failure) else ""))
            elif reached is not None:
                reason = (f"{model.model} could not be reached after "
                          f"{NETWORK_RETRIES + 1} attempts: {reached[1]}")
            else:
                outcome = run_outcome(status, stream.result, schema,
                                      self._denials(stream, session))
                # A run that exited non-zero is logged from its status, so even its
                # last turn's outcome is kept as earlier.
                logged = stream.result if status == 0 else None
                break
            outcome = {"outcome": "stopped", "message": reason, "reason": reason,
                       "denials": self._denials(stream, session)}
            break
        else:
            reason = "no model of the step is available: " + "; ".join(
                f"{entry['model']}: {entry['reason']}" for entry in passed_over)
            outcome = {"outcome": "stopped", "message": reason, "reason": reason,
                       "denials": self._denials(stream, session)}
        extra = {**(extra or {}), **model.entry(), "exit_status": status, "transcript": named}
        if passed_over:
            extra["unavailable"] = passed_over
        # Every attempt's turns: a retried attempt may have reported before it failed.
        if earlier := earlier_outcomes([r for a in attempts for r in a.results], logged):
            extra["earlier"] = earlier
        extra.update(self._cost(attempts or [stream], session, before))
        try:
            log = log_path(self.root, change)
        except StepError:
            # A change found under neither name keeps the log the run started
            # with, so the run still ends with a line.
            pass
        line = record_outcome(log, step, outcome, session=stream.session or session,
                              commit=self.head(self.root), extra=extra, schema=schema,
                              clock=self.clock)
        if failure is not None and not isinstance(failure, Exception):
            raise failure
        return line

    def _denials(self, stream: Stream, session: str | None) -> list[dict[str, Any]]:
        """The run's denials: the parent's own, from its stream, then those its
        subagents met, read from their transcripts beside the conversation file."""
        ran = stream.session or session
        extra = (subagent_denials(self.conversation(self.root, ran), stream.tool_use_ids)
                 if ran else [])
        seen = {d.get("tool_use_id") for d in stream.denials if d.get("tool_use_id")}
        return stream.denials + [d for d in extra if d.get("tool_use_id") not in seen]

    def _before(self, log: Path, session: str | None) -> Entry:
        if session is None:
            return {}
        return measured_before(read_log(log), session,
                               read_conversation(self.conversation(self.root, session)),
                               self.clock())

    def _cost(self, attempts: Sequence[Stream], session: str | None, before: Entry) -> Entry:
        # Every attempt's turns were spent, a retried or passed-over one's included.
        ran = attempts[-1].session or session
        return measured_cost([r for attempt in attempts for r in attempt.results],
                             next((a.first_usage for a in attempts if a.first_usage), None),
                             before,
                             read_conversation(self.conversation(self.root, ran))
                             if ran else None)


def continued_run(entries: Sequence[Entry], change: str, session: str) -> Entry:
    """The latest implementation run of `session`, which a run may continue.

    Refused while an implementation run waits on the owner — ended with a question,
    or stopped with no decision line resolving it. Its answer goes to it through
    `resume`, which reaches only the step's latest run: a new instruction sent to
    that session would leave the question unanswered, and one sent to another
    session would make it no longer the latest, so it could never be resumed.
    """
    runs = [e for e in entries if e.get("step") == "implement"]
    named = [e for e in runs if e.get("session") == session]
    if not named:
        raise StepError(f"{change}'s workflow log has no implementation run of session "
                        f"{session}")
    latest = runs[-1]
    resolved = {e.get("resolves") for e in entries if e.get("outcome") == ORCHESTRATOR}
    if latest.get("outcome") in ("question", "stopped") and latest["seq"] not in resolved:
        raise StepError(f"implementation's last run (seq {latest['seq']}, session "
                        f"{latest.get('session')}) ended {latest['outcome']} and waits for "
                        "the owner's answer; resume it with the answer first")
    return named[-1]


def _session_models(previous: Entry, rules: StepRules) -> tuple[Model, ...]:
    """The model a run continuing `previous`'s session runs on: the one it ran on.

    A line written before runs recorded their model names none; the step's first
    model is the one such a session is continued on.
    """
    if isinstance(previous.get("model"), str) and previous["model"]:
        return (Model(previous.get("harness") or "claude", previous["model"],
                      previous.get("effort")),)
    return rules.models[:1]
