"""The change's workflow log: one line per run, and the orchestrating session's notes.

`record_outcome` appends a step's outcome as a line of the change's
`reviews/workflow.jsonl`, with a sequence number, the time, the step, and the
run's session and commit. `note_round` and `note_orchestrator` append the
orchestrating session's own lines: a `round` line recording the implementation
round the owner agreed, and an `orchestrator` line recording a decision — the
orchestrating session's own routing or recovery, or the owner's, such as a
confirmed return or a repeat review — naming the run whose denials it reads, the
run it resolves, and the step it directs next, so the next-step computation
routes on it. Reading and resolving are distinct because a run can be denied a
call and still end with a question or a proposed return: its denials are read
first, and its outcome is answered or decided after. This module is the log's only
writer.

The log holds only what the change's files cannot: session ids, the owner's round
agreements, and the last outcome. Where the log and the files disagree, the files
win. It lives in the change's untracked `reviews/` directory and moves with the
change when it is archived.
"""

from __future__ import annotations

import fcntl
import json
from datetime import timezone
from pathlib import Path
from typing import Any, Sequence

from change_workflow.common import KINDS, ORCHESTRATOR, STEPS, Clock, Entry, StepError, utc_now
from change_workflow.outcome import outcome_problems
from change_workflow.records import next_number
from find_change import ChangeNotFound, change_directory

LOG = "workflow.jsonl"


class LogError(StepError):
    """The workflow log cannot be read."""


def log_path(root: Path, change: str) -> Path:
    try:
        return change_directory(root, change) / "reviews" / LOG
    except ChangeNotFound as exc:
        raise StepError(str(exc)) from exc


def _parse(path: Path, text: str) -> list[Entry]:
    entries = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            raise LogError(f"{path}:{number}: not a JSON line: {exc.msg}") from exc
        if not isinstance(entry, dict):
            raise LogError(f"{path}:{number}: not a JSON object")
        seq = entry.get("seq")
        if not isinstance(seq, int) or isinstance(seq, bool):
            raise LogError(f"{path}:{number}: has no integer seq")
        entries.append(entry)
    return entries


def read_log(path: Path) -> list[Entry]:
    """Every line of the workflow log, in order; an absent log is empty.

    A malformed line is reported with its line number, never skipped: a skipped
    line could be the last outcome, and routing on the one before it would repeat
    or skip a step.
    """
    if not path.is_file():
        return []
    with path.open(encoding="utf-8") as stream:
        # Shared, so a line being appended is never read half-written.
        fcntl.flock(stream, fcntl.LOCK_SH)
        return _parse(path, stream.read())


def last_entries(path: Path, count: int) -> list[Entry]:
    entries = read_log(path)
    return entries[-count:] if count > 0 else []


def append_entry(path: Path, entry: Entry, clock: Clock = utc_now) -> Entry:
    """Append `entry` to the log with the next `seq` and the time, and return the line.

    Several processes may append to one change's log at once, so the log is
    locked from reading the last `seq` to writing the new line; without the lock
    both could take the same number.
    """
    if reserved := {"seq", "at"} & entry.keys():
        raise StepError(f"a log line may not set {', '.join(sorted(reserved))}, which "
                        "the log assigns")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        stream.seek(0)
        text = stream.read()
        entries = _parse(path, text)
        line = {"seq": max((e["seq"] for e in entries), default=0) + 1,
                "at": clock().astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                **entry}
        stream.seek(0, 2)
        # A last line saved without its newline would otherwise be joined to this one.
        separator = "\n" if text and not text.endswith("\n") else ""
        stream.write(separator + json.dumps(line, ensure_ascii=False) + "\n")
        stream.flush()
    return line


def record_outcome(path: Path, step: str, outcome: Entry, *, session: str | None,
                   commit: str | None, extra: Entry | None = None,
                   schema: dict[str, Any] | None = None, clock: Clock = utc_now) -> Entry:
    """Append a step's outcome, refusing one that does not conform to the schema."""
    if step not in STEPS:
        raise StepError(f"unknown step {step!r}; expected one of {', '.join(STEPS)}")
    if problems := outcome_problems(outcome, schema):
        raise StepError(f"the {step} outcome does not conform to the schema: "
                        + "; ".join(problems))
    run = {"step": step, "session": session, "commit": commit}
    if clash := (extra or {}).keys() & (run.keys() | outcome.keys()):
        raise StepError(f"the {step} run's fields {', '.join(sorted(clash))} are recorded "
                        "twice")
    # The schema admits no field beyond the outcome's own, so nothing a step
    # answers can overwrite what is recorded about its run.
    return append_entry(path, {**run, **(extra or {}), **outcome}, clock)


def _section_ids(sessions: Any) -> bool:
    return (isinstance(sessions, list) and bool(sessions)
            and all(isinstance(session, list) and session
                    and all((isinstance(section, int) and not isinstance(section, bool))
                            or (isinstance(section, str) and section)
                            for section in session)
                    for session in sessions))


def note_round(path: Path, sections: Any, by: str, after: int | None = None,
               clock: Clock = utc_now, commit: str | None = None) -> Entry:
    """Record the implementation round the owner agreed: its sessions, each a list
    of the sections that session implements, in order.

    `after` is the highest number among the records and transcripts in `reviews/`
    before the round, so the round's own records — the owner's notes, its
    validation and review, their triage — are those numbered above it. It is read
    from `reviews/` when the round is agreed before it starts, and given for a
    round recorded after the fact, whose records already exist. `commit` is `HEAD`
    as the round starts, the base its round view shows the round against: commits
    landing between rounds, a design revision among them, are not the round's.
    """
    if not _section_ids(sections):
        raise StepError("a round names one or more sessions, each a non-empty list of "
                        f"sections; got {sections!r}")
    if not by:
        raise StepError("a round names who agreed it")
    if after is not None and (isinstance(after, bool) or not isinstance(after, int)
                              or after < 0):
        raise StepError(f"a round's after is a record number; got {after!r}")
    return append_entry(path, {"step": ORCHESTRATOR, "outcome": "round",
                               "sections": sections, "by": by,
                               "after": next_number(path.parent) - 1 if after is None
                               else after, **({"commit": commit} if commit else {})}, clock)


def note_orchestrator(path: Path, decision: str, reason: str, *, by: str = ORCHESTRATOR,
                      resolves: int | None = None, reads: int | None = None,
                      next_step: str | None = None, kind: str | None = None,
                      branch: str | None = None, change: str | None = None,
                      clock: Clock = utc_now) -> Entry:
    """Record a decision: the orchestrating session's own routing or recovery, or
    the owner's, relayed by it.

    `reads` names the run (its `seq`) whose recorded denials the decision has
    read against the step's rules; `resolves` names the run the decision
    settles, so that run alone stops waiting on the owner: a decision clears
    nothing it does not name. They differ because a run denied a call can still
    end with a question or a proposed return, whose denials are read before the
    question is answered or the return decided; a reading alone leaves such an
    outcome waiting. A stopped run is read the same way: a reading that also
    resolved it would make `resume` refuse the one-run grant that recovers it,
    so a stop is resolved only when it is not recovered.
    `next_step` names the step the decision directs — the step a confirmed
    return goes to, the review the owner asked for again — which the next-step
    computation names until that step has run. A directed review takes its
    `kind`, without which the computation could not name one; a directed step
    of any other kind is a confirmed return, so it resolves the returned run,
    which would otherwise wait ahead of the directive. A repeat review the owner
    asks for outside a triage names no run, since no run waits on it; nor does the
    owner's direction to archive cleanup, by which they waive the validation the
    computation would name first. Only the owner gives it; archive cleanup's own
    entry checks still hold, and its validation check asks the owner and records
    the waiver in the ledger.
    `branch` and `change` record the owner's word that `change` is worked on
    `branch` though the branch is not its own, which each step's branch check
    accepts in place of asking (`branch_decisions`); only the owner gives it.
    """
    if not decision or not reason:
        raise StepError("an orchestrator line names its decision and its reason")
    if not by:
        raise StepError("an orchestrator line names who decided")
    line: Entry = {"step": ORCHESTRATOR, "outcome": ORCHESTRATOR, "by": by,
                   "decision": decision, "reason": reason}
    if branch is not None or change is not None:
        if not branch or not change:
            raise StepError("a branch decision names both the branch and the change")
        if by != "owner":
            raise StepError("a branch decision is the owner's")
        line.update(branch=branch, change=change)
    runs = {entry["seq"]: entry for entry in read_log(path) if entry.get("step") in STEPS}
    if resolves is not None:
        if resolves not in runs:
            raise StepError(f"no run has seq {resolves!r} in the workflow log; a decision "
                            "resolves a step's run")
        line["resolves"] = resolves
    if reads is not None:
        if reads not in runs:
            raise StepError(f"no run has seq {reads!r} in the workflow log; a decision "
                            "reads a step's run")
        if not runs[reads].get("denials"):
            raise StepError(f"the run at seq {reads} recorded no denial; a decision reads "
                            "a run's denials")
        line["reads"] = reads
    if next_step is not None:
        if next_step not in STEPS:
            raise StepError(f"unknown step {next_step!r}; expected one of {', '.join(STEPS)}")
        if next_step == "review" and kind is None:
            raise StepError("a decision directing a review names its kind")
        if next_step == "archive-cleanup" and resolves is None:
            if by != "owner":
                raise StepError("a decision directing archive cleanup past its validation "
                                "is the owner's waiver")
        elif next_step != "review" and resolves is None:
            raise StepError(f"a decision directing {next_step} is a confirmed return and "
                            "names the run it resolves")
        line["next"] = next_step
    if kind is not None:
        if next_step != "review":
            raise StepError("a kind goes with next = review")
        if kind not in KINDS:
            raise StepError(f"unknown review kind {kind!r}; expected one of {', '.join(KINDS)}")
        line["kind"] = kind
    return append_entry(path, line, clock)


def branch_decisions(entries: Sequence[Entry], branch: str,
                     change: str | None = None) -> list[Entry]:
    """The owner's decisions that a change is worked on `branch`, and of `change`
    when one is named."""
    return [entry for entry in entries
            if entry.get("outcome") == ORCHESTRATOR and entry.get("by") == "owner"
            and entry.get("branch") == branch
            and (change is None or entry.get("change") == change)]


def last_run(path: Path, steps: Sequence[str]) -> Entry | None:
    """The latest log line of one of `steps`, whether or not it names a session.

    A run that crashed before Claude Code reported its session names none; the
    session before it is not the one to continue, since it is not the last thing
    the step did.
    """
    for entry in reversed(read_log(path)):
        if entry.get("step") in steps:
            return entry
    return None
