"""Running a step unattended, and resuming a waiting run with the owner's answer.

`Wrapper.run` starts the step's skill as a headless Claude Code session on the first
available of the step's models, which the repository's workflow configuration names
in order of preference (`models.<step>`): a model whose harness is
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
appended to the workflow log, with what the run invoked as `invoked`: what each of
its attempts' sessions invoked for the change through `run`, and through the
guarded push, that no line has taken yet. A run that crashes, ends without an outcome, or ends
with one the schema rejects is logged `stopped` by the wrapper itself, and so is
a triage whose outcome does not name the records it triaged, and a finished merge
or archive cleanup whose landing record the log's writer refuses. A step
denied a tool ends `stopped` only when it cannot go on without it; one that went
on is logged with the outcome it ended with, and the orchestrating session reads
the recorded denials before the change moves on. A run whose session took further
turns after an outcome is logged with its last, the earlier ones kept beside it as
`earlier`.

A validation's exit is the target the next-step computation gives it, which the
computation does not give once the validation's own run is logged: it reads that
run, and names the owner. So an
unattended validation's target is computed before its session starts, given to the
session in its prompt, and recorded as `target` on its line; a resume of that run
reads the target from the line it resumes, never computing it again. A finished
validation is logged with that target as its exit, whatever `next` its session
gave, so a missing or mistaken one never stops a validation that finished. A
validation started with no target to give — outside the route, or resuming a line
that records none — is logged with the exit its session named.

Contract: openspec/specs/change-workflow/spec.md, CW-js86, CW-4vma, CW-1a4d,
CW-k5mk, CW-xgq3, CW-0ia3, CW-ebmo, CW-1dld, CW-tl5v, CW-yzer, CW-q5fy, and CW-5ldi.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

from . import config, next_step
from .common import ORCHESTRATOR, Clock, Entry, StepError, repository_root, utc_now
from .cost import conversation_file, measured_before, measured_cost, read_conversation
from .harness import (NETWORK_RETRIES, Runner, claude_command, missing_program, run_claude,
                      unreachable)
from .log import (Checkout, git_checkout, landing_problems, last_run, log_path, read_log,
                  record_outcome, revisit_direction, revisit_refusal)
from .outcome import load_schema, outcome_problems, triage_outcome_problems
from .records import git_head, next_transcript
from .running import (drop_invocations, invocations_directory, kept_invocations, recorded_run,
                      runs_directory, termination_deferred, termination_ends_the_run)
from .steps import Model, StepRules, load_steps
from .stream import Stream
from .subagents import subagent_denials


VALIDATE = "validate"
# The computation's steps that name validation with its target.
_VALIDATING = ("validate", "validate-and-review")


def step_prompt(rules: StepRules, change: str, arguments: str = "") -> str:
    return f"/{rules.skill} {change}" + (f" {arguments}" if arguments else "")


def target_note(target: Entry) -> str:
    """How a validation's session is told its target: labelled, as JSON."""
    return (f"Target (the wrapper computed it; this validation's exit): "
            f"{json.dumps(target, ensure_ascii=False)}")


def validation_target(root: Path, change: str,
                      compute: Callable[[Path, str], Entry] = next_step.compute) -> Entry | None:
    """The target the next-step computation gives validation of `change` now, or None
    when it names no validation with one, such as a validation started by hand
    outside the route."""
    result = compute(root, change)
    target = result.get("target")
    if result.get("step") in _VALIDATING and isinstance(target, dict) and target:
        return dict(target)
    return None


def run_outcome(status: int, result: dict[str, Any] | None, schema: dict[str, Any],
                denials: Sequence[dict[str, Any]] = (), target: Entry | None = None) -> Entry:
    """The outcome to log for a run that exited with `status` and ended with `result`,
    having been denied `denials`.

    The step's own outcome when it gave a valid one; otherwise a `stopped` the
    wrapper writes, its message the reason. Every outcome carries the run's own
    record of its denials, whatever the step said: a step ends `stopped` when it
    cannot go on without a denied tool, and one that went on is logged as it
    ended, its denials there for the orchestrating session to read. The outcome
    is checked with those denials in it, since the wrapper sets them whatever the
    step gave, and an outcome the schema rejects keeps the step's own message
    ahead of the reason, so what it said to the owner is not lost. A finished
    outcome of a run given its `target` takes that target as its exit before it is
    checked, whatever exit the step named.
    """
    denials = list(denials)
    outcome = (result or {}).get("structured_output")
    if isinstance(outcome, dict):
        outcome = {**outcome, "denials": denials}
        if target is not None and outcome.get("outcome") == "finished":
            outcome["next"] = dict(target)
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


def triage_outcome(outcome: Entry, reviews: Path) -> Entry:
    """A triage's outcome as it is logged: as the step gave it when it names what it
    triaged, or when it ends without an exit; otherwise `stopped`, naming why.

    A finished or returned triage is what the next-step computation routes the
    triaged review on, so one that names no record, or one that is not a review's
    with its triage file, would leave that review's triage in progress or route
    another's. The step's own message is kept ahead of the reason.
    """
    if not (problems := triage_outcome_problems(outcome, reviews)):
        return outcome
    reason = "the triage's outcome does not name what it triaged: " + "; ".join(problems)
    return {"outcome": "stopped", "message": f"{outcome['message']}\n\n{reason}",
            "reason": reason, "denials": outcome.get("denials", [])}


def landed_outcome(outcome: Entry, step: str, log: Path, commit: str | None,
                   checkout: Checkout) -> Entry:
    """A merge's or archive cleanup's outcome as it is logged: as the step gave it
    when the log's writer accepts its landing record, or when it ends without an
    exit; otherwise `stopped`, naming why, the step's own message kept ahead of the
    reason. A refusal would otherwise leave the run without a line."""
    if not (problems := landing_problems(read_log(log), step, outcome, commit, checkout,
                                         log.parent)):
        return outcome
    reason = f"the {step} outcome's landing is refused: " + "; ".join(problems)
    return {"outcome": "stopped", "message": f"{outcome['message']}\n\n{reason}",
            "reason": reason, "denials": outcome.get("denials", [])}


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


def _with_subagent(streamed: dict[str, Any], found: dict[str, Any]) -> dict[str, Any]:
    """A denial the parent's stream reported, marked with the subagent whose
    transcript also records it, and given that transcript's reason when the
    stream gave none."""
    reason = {"reason": found["reason"]} if "reason" in found and "reason" not in streamed else {}
    marked = {"subagent": found["subagent"]} if "subagent" in found else {}
    return {**streamed, **reason, **marked}


@dataclass
class Wrapper:
    """Runs steps of changes under one repository root, through injected seams."""

    root: Path = field(default_factory=repository_root)
    runner: Runner = run_claude
    head: Callable[[Path], str | None] = git_head
    clock: Clock = utc_now
    # Progress goes to stderr: stdout carries only the outcome line a caller parses.
    echo: Callable[[str], None] | None = lambda shown: print(shown, file=sys.stderr, flush=True)
    # The step table and the outcome schema; None reads the repository's own.
    steps_path: Path | None = None
    schema_path: Path | None = None
    # Where Claude Code keeps a session's conversation, read for the turns it gained
    # outside the wrapper and the time of its last turn.
    conversation: Callable[[Path, str], Path] = conversation_file
    # Where a run in progress is recorded, so no round view moves its checkout.
    runs: Callable[[Path], Path | None] = runs_directory
    # Where a session's invocations through `run` and the guarded push wait for its
    # line.
    invocations: Callable[[Path], Path | None] = invocations_directory
    # What the log's writer reads of the checkout a run ran in, for a change, to check
    # a merge's or archive cleanup's landing record.
    checkout: Callable[[Path, str], Checkout] = git_checkout
    # The target the next-step computation gives a validation as it starts.
    target: Callable[[Path, str], Entry | None] = validation_target

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
        models = config.load(self.root).step_models(step)
        extra: Entry = {}
        if continuing is not None:
            if step != "implement":
                raise StepError("only implementation continues a session it names")
            if fresh:
                raise StepError("a run continuing a session cannot also start fresh")
            previous = continued_run(read_log(log), change, continuing)
            session, models = continuing, _session_models(previous, models)
            extra["continues"] = previous["seq"]
        elif rules.resume_from and not fresh:
            previous = last_run(log, [rules.resume_from, step])
            if previous is not None and not previous.get("session"):
                raise StepError(f"{change}'s last {previous['step']} run (seq "
                                f"{previous['seq']}) recorded no session to resume; run "
                                f"{step} with --fresh, or {previous['step']} again")
            if previous is not None:
                session = previous["session"]
                models = _session_models(previous, models)
        if sections:
            extra["sections"] = list(sections)
        if granted:
            extra["granted"] = list(granted)
        target = self.target(self.root, change) if step == VALIDATE else None
        if target is not None:
            extra["target"] = target
            arguments = " ".join(part for part in (arguments, target_note(target)) if part)
        return self._turn(step, rules, change, log, step_prompt(rules, change, arguments),
                          models, session=session, granted=granted, extra=extra,
                          target=target)

    def resume(self, change: str, seq: int, answer: str, granted: Sequence[str] = ()) -> Entry:
        """Resume the step session of the run at `seq` with the owner's answer.

        The run is named, never inferred: with steps run side by side, the log's
        last run is not necessarily the one that asked. It must be waiting — its
        step's latest run, ended with a question, or stopped with no decision
        line resolving it — since an answer to any other run has nowhere to go.
        The one finished run that may be resumed is a triage the owner revisits:
        named by their unused direction (`revisit_direction`), and still the
        latest triage of the reviews it triaged (`revisit_refusal`). Its line
        records the run it `resumes`, which uses the direction.

        A granted rule applies to this run alone: it is passed on this command line
        and noted on this run's log line, never added to the step table, so the
        step's next run is held to its table again.

        The session resumes on the model it ran on, never the step's next one: a
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
        revisited = (previous.get("outcome") == "finished"
                     and revisit_direction(entries, seq) is not None)
        if revisited:
            if refusal := revisit_refusal(entries, seq):
                raise StepError(f"the revisit is refused: {refusal}")
        else:
            latest = last_run(log, [step])
            if latest is None or latest["seq"] != seq:
                raise StepError(f"seq {seq} is not {step}'s latest run, so it no longer waits")
            resolved = {e.get("resolves") for e in entries if e.get("outcome") == ORCHESTRATOR}
            if seq in resolved:
                raise StepError(f"seq {seq} ended {previous.get('outcome')} and a decision line "
                                "resolves it, so it no longer waits")
            if previous.get("outcome") not in ("question", "stopped"):
                raise StepError(f"seq {seq} ended {previous.get('outcome')}, not with a "
                                "question or a stop, so it is not waiting for an answer"
                                + ("; a finished triage is resumed only on the owner's "
                                   "direction to revisit it, `note --by owner --resumes "
                                   f"{seq}`" if step == "triage" else ""))
        if not previous.get("session"):
            raise StepError(f"{change}'s {step} run (seq {seq}) recorded no session to "
                            "resume; run the step again")
        extra: Entry = {"sections": previous["sections"]} if previous.get("sections") else {}
        if revisited:
            # Marks the direction used: it resumes the run once.
            extra["resumes"] = seq
        if granted:
            extra["granted"] = list(granted)
        # The resumed run's own line names it: the computation, reading that run,
        # would name the owner instead.
        target = previous.get("target") if step == VALIDATE else None
        target = dict(target) if isinstance(target, dict) and target else None
        # Framed, so an answer starting with `-` is never read as a flag.
        prompt = f"The owner's answer: {answer}"
        if target is not None:
            extra["target"] = target
            prompt += f"\n\n{target_note(target)}"
        return self._turn(step, steps[step], change, log, prompt,
                          _session_models(previous, config.load(self.root).step_models(step)),
                          session=previous["session"], granted=granted, extra=extra,
                          target=target)

    def _turn(self, step: str, rules: StepRules, change: str, log: Path, prompt: str,
              models: Sequence[Model], *, session: str | None, granted: Sequence[str] = (),
              extra: Entry | None = None, target: Entry | None = None) -> Entry:
        """Run one turn and log it, recorded as in progress in the checkout until its
        line is written, however it ends.

        A stop's SIGTERM is held from before the record is written until after it
        is removed, and ends the run only while its agent runs, so a run is never
        killed with its line unwritten."""
        with termination_deferred(), recorded_run(self.runs(self.root), step, change,
                                                  clock=self.clock):
            return self._logged_turn(step, rules, change, log, prompt, models,
                                     session=session, granted=granted, extra=extra,
                                     target=target)

    def _logged_turn(self, step: str, rules: StepRules, change: str, log: Path, prompt: str,
                     models: Sequence[Model], *, session: str | None,
                     granted: Sequence[str] = (), extra: Entry | None = None,
                     target: Entry | None = None) -> Entry:
        """Run one turn on the first of `models` that is available, and log it.

        A model whose harness is missing, not signed in, or at its usage limit
        falls to the next, and each one passed over is named on the line; a
        network error is retried on the same model, and then stops the run. The
        line names the last model tried even when none could run, with
        `unavailable` saying so: a resume of that run continues its session on
        that model, never the step's next one.

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
        attempts: list[Stream] = []
        outcome, status, failure, model, stream, passed_over, logged = (
            self._attempt_models(step, rules, prompt, schema, models, session, granted,
                                 transcript, progress, attempts, target))
        extra = {**(extra or {}), **model.entry(), "exit_status": status, "transcript": named}
        if passed_over:
            extra["unavailable"] = passed_over
        # Every attempt's turns: a retried attempt may have reported before it failed.
        if earlier := earlier_outcomes([r for a in attempts for r in a.results], logged):
            extra["earlier"] = earlier
        extra.update(self._cost(attempts or [stream], session, before))
        ran = stream.session or session
        directory = self.invocations(self.root)
        # Every attempt's session: a retried or passed-over attempt ran under a
        # session of its own, and what it invoked is this run's too.
        sessions = list(dict.fromkeys(s for s in (session, *(a.session for a in attempts), ran)
                                      if s))
        taken = {s: kept_invocations(directory, s, change) for s in sessions}
        if invoked := [entry for s in sessions for entry in taken[s]]:
            extra["invoked"] = invoked
        try:
            log = log_path(self.root, change)
        except StepError:
            # A change found under neither name keeps the log the run started
            # with, so the run still ends with a line.
            pass
        if step == "triage":
            outcome = triage_outcome(outcome, log.parent)
        commit = self.head(self.root)
        checkout = self.checkout(self.root, change)
        outcome = landed_outcome(outcome, step, log, commit, checkout)
        line = record_outcome(log, step, outcome, session=ran, commit=commit, extra=extra,
                              schema=schema, checkout=checkout, clock=self.clock)
        # Forgotten only once the line holds them; a resumed turn's line takes only
        # what the session invoked since.
        for s in sessions:
            drop_invocations(directory, s, taken[s])
        if failure is not None and not isinstance(failure, Exception):
            raise failure
        return line

    def _attempt_models(self, step: str, rules: StepRules, prompt: str, schema: dict[str, Any],
                        models: Sequence[Model], session: str | None,
                        granted: Sequence[str], transcript: Path, progress: Path,
                        attempts: list[Stream], target: Entry | None = None,
                        ) -> tuple[Entry, int | None, BaseException | None, Model, Stream,
                                   list[Entry], dict[str, Any] | None]:
        """Run the turn of `step` on the first available of `models`, marked as that
        step's unattended run: its outcome, exit status, any failure, the model last
        tried, its stream, the models passed over, and the result the outcome was
        logged from, when the step gave one. Every attempt's stream is appended to
        `attempts`. A finished outcome takes `target`, when given, as its exit."""
        failure: BaseException | None = None
        passed_over: list[Entry] = []
        outcome: Entry = {}
        # The result the line is logged from, when the step gave one.
        logged: dict[str, Any] | None = None
        status: int | None = None
        stream = Stream(transcript, progress, self.clock, self.echo)
        model = models[0]
        for model in models:
            for attempt in range(NETWORK_RETRIES + 1):
                # Each attempt is read alone; the transcript keeps them all.
                stream = Stream(transcript, progress, self.clock, self.echo)
                attempts.append(stream)
                command = claude_command(prompt, rules, schema, model, root=self.root,
                                         session=session, granted=granted)
                failure, status, reached = None, None, None
                try:
                    with termination_ends_the_run():
                        status = self.runner(command, self.root, stream.feed, step)
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
                                      self._denials(stream, session), target)
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
        return outcome, status, failure, model, stream, passed_over, logged

    def _denials(self, stream: Stream, session: str | None) -> list[dict[str, Any]]:
        """The run's denials: the parent's own, from its stream, then those its
        subagents met, read from their transcripts beside the conversation file.

        The harness may also report a subagent's denial on the parent's stream,
        unmarked; that entry is kept once and given the subagent its transcript
        names, and the transcript's reason when the stream gave none, so the
        denial is never read as the parent's own call."""
        ran = stream.session or session
        extra = (subagent_denials(self.conversation(self.root, ran), stream.tool_use_ids)
                 if ran else [])
        found = {d["tool_use_id"]: d for d in extra if d.get("tool_use_id")}
        streamed = [_with_subagent(d, found[d["tool_use_id"]])
                    if d.get("tool_use_id") in found else d for d in stream.denials]
        seen = {d.get("tool_use_id") for d in stream.denials if d.get("tool_use_id")}
        return streamed + [d for d in extra if d.get("tool_use_id") not in seen]

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


def _session_models(previous: Entry, models: Sequence[Model]) -> tuple[Model, ...]:
    """The model a run continuing `previous`'s session runs on: the one it ran on.

    A line written before runs recorded their model names none; the step's first
    model is the one such a session is continued on.
    """
    if isinstance(previous.get("model"), str) and previous["model"]:
        return (Model(previous.get("harness") or "claude", previous["model"],
                      previous.get("effort")),)
    return tuple(models[:1])
