"""Converting a change's records to the workflow log's format, the only one the
next-step computation reads.

A change whose log holds a line without the format marker, or whose numbered
records have no log, is routed on by nothing until its records are converted, once,
in the checkout that holds them (`python3 scripts/run_change_step.py convert
<change>`). The conversion replaces the log whole, under its lock
(`log.replace_log`):

- each line without the marker is rewritten in place, keeping its seq, so every
  `resolves` and `reads` still names its run: a decision's string `next` and its
  `kind` become the target it names, a returned outcome's `return_to` gains its
  target in `next`, an outcome's prose `next`, which routes nothing, moves into its
  `message`, and the line gains the marker;
- one conversion line follows, `step` `convert`, naming as `triaged` every review
  with a triage file, so that none reads as a triage in progress; it names no exit;
- then the owner's direction to the node the change stands at, which the command
  proposes and the owner confirms or gives with `--next`: where the change stands
  is the owner's assertion, made while they are present, and the log's writer
  checks it as it checks every direction.

The proposal reads where the change stands from the latest routing decision after
the latest triage: a later direction whose node has not run since it; else a run of
any step logged after that triage, which leaves its triage saying nothing of the
present, so nothing is proposed; else that triage's exit — the one its recorded
outcome names, or the one the token its triage file's `## Next` begins with, or its
older `## Gate`, led to in its phase: `Advance` and a gate `Passed` the phase's
advancing exit, `Another round` the review of the same kind, `Returned` the return
its run proposed, confirmed by the direction, which resolves that run. A direction
checks no exit guard, so where a guard on the exit is not met the proposal is the
validation that remedies it, carrying the exit as its target. Nothing is proposed
for a node whose unwaivable entry guard is not met. This is the only reader of
triage files' tokens.

Nothing is written without the owner's `--confirm`, which also attests that each
triage the conversion line names and no recorded triage outcome names finished: a
triage whose interactive session closed before it recorded its outcome cannot be
told from a finished one in the older format, whose words may begin the same way. A
change already in the format is refused, and so is one with a triage in progress —
a triage file holding neither `## Next` nor `## Gate` that no recorded outcome
names — writing nothing.

Contract: openspec/specs/change-workflow/spec.md, "The next step is computed from the
files".
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from change_next_step import EXIT, Computation, Record, Route, target_label
from change_workflow import graph
from change_workflow.common import ORCHESTRATOR, STEPS, Clock, Entry, StepError, utc_now
from change_workflow.graph import (IMPLEMENTATION_TRIAGE, PRE_CLOSEOUT_REVIEW, VALIDATE, Node,
                                   TargetError, entry_refusal, node_of)
from change_workflow.log import (FORMAT, decision_line, log_path, numbered, ran, replace_log,
                                 unmarked)
from find_change import ChangeNotFound

CONVERSION = "convert"
# The target a returned outcome's `return_to`, the phase it returns to, names.
_RETURN_STEP = {"design": "design", "planning": "plan", "implementation": "round"}

# What a triage file records next, by the token its `## Next` begins with, or by
# whether its older `## Gate` begins `Passed`; any other words lead to no exit.
ADVANCE, ANOTHER_ROUND, RETURNED, OTHER = "Advance", "Another round", "Returned", "other"


def _section(text: str, heading: str) -> str | None:
    """The body of a `## <heading>` section, words after a colon on the heading's
    own line (`## Next: Advance`) beginning it; None without one. Only the bare
    heading counts: `## Next round` is another section."""
    match = re.search(rf"^## {re.escape(heading)}(?::(.*))?[ \t]*$", text, re.M)
    if match is None:
        return None
    rest = text[match.end():]
    end = re.search(r"^## ", rest, re.M)
    return (match.group(1) or "") + "\n" + (rest[:end.start()] if end else rest)


@dataclass(frozen=True)
class Reading:
    """What a triage file records next: the heading read, `## Next` or `## Gate`,
    None for neither, a triage in progress; the first line under it; its token."""

    heading: str | None
    first: str
    token: str | None


def read_triage(path: Path) -> Reading:
    text = path.read_text("utf-8")
    for heading in ("Next", "Gate"):
        if (body := _section(text, heading)) is None:
            continue
        first = next((line.strip() for line in body.splitlines() if line.strip()), "")
        words = first.lower()
        if heading == "Gate":
            token = ADVANCE if words.startswith("passed") else OTHER
        else:
            token = (ADVANCE if words.startswith("advance")
                     else ANOTHER_ROUND if words.startswith("another round")
                     else RETURNED if words.startswith("returned") else OTHER)
        return Reading(f"## {heading}", first, token)
    return Reading(None, "", None)


def rewritten(entry: Entry) -> Entry:
    """`entry` in the log's format, its seq and time kept; a line already in the
    format is kept as it is."""
    if entry.get("format") == FORMAT:
        return entry
    line = {key: value for key, value in entry.items() if key not in ("seq", "at", "format")}
    if line.get("step") == ORCHESTRATOR:
        if isinstance(line.get("next"), str):
            kind = line.pop("kind", None)
            line["next"] = {"step": line["next"], **({"kind": kind} if kind else {})}
    elif line.get("step") in STEPS:
        if isinstance(line.get("next"), str):
            prose = line.pop("next")
            line["message"] = f"{line['message']}\n\nNext: {prose}" if line.get("message") \
                else prose
        if line.get("outcome") == "returned" and "next" not in line \
                and line.get("return_to") in _RETURN_STEP:
            line["next"] = {"step": _RETURN_STEP[line["return_to"]]}
    return {"seq": entry["seq"], **({"at": entry["at"]} if "at" in entry else {}),
            "format": FORMAT, **line}


@dataclass(frozen=True)
class Triaged:
    """A review the conversion line names: its record, what its triage file was read
    to record, and whether a recorded triage outcome or an earlier conversion names
    it already; one neither names is the owner's to attest."""

    record: Record
    reading: Reading
    attested: bool


@dataclass(frozen=True)
class Proposal:
    """The direction proposed, None when none is, and why; `resolves` is the
    returned run a direction confirming its return resolves, which the owner may
    decline instead."""

    target: Entry | None
    why: str
    resolves: int | None = None


@dataclass(frozen=True)
class Conversion:
    """The converted log — every line in the format, then the conversion line — the
    seqs of the lines rewritten, the reviews the conversion line names, and the
    direction proposed."""

    lines: list[Entry]
    rewritten: list[int]
    triaged: list[Triaged]
    proposal: Proposal


def _attested(entries: Sequence[Entry]) -> set[str]:
    """The records a recorded triage outcome, or an earlier conversion, names."""
    return {name for entry in entries
            if (entry.get("format") == FORMAT and entry.get("step") == "triage"
                and entry.get("outcome") in ("finished", "returned"))
            or entry.get("step") == CONVERSION
            for name in entry.get("triaged") or () if isinstance(name, str)}


def conversion(entries: Sequence[Entry], computation: Computation,
               clock: Clock = utc_now) -> Conversion:
    """The conversion of the log whose lines are `entries`, for the change
    `computation` has read; its state's log becomes the converted one, so its
    guards read it. Refused, naming why, for a change already in the format, or
    with a triage in progress."""
    state = computation.state
    if unmarked(entries) is None and (entries or not state.records):
        raise StepError(f"{state.change}'s records are in the workflow log's format already: "
                        "there is nothing to convert")
    attested = _attested(entries)
    triaged = [Triaged(record, read_triage(record.triage), record.name in attested)
               for record in state.records if record.review_kind and record.triaged]
    if in_progress := [t.record.name for t in triaged
                       if t.reading.heading is None and not t.attested]:
        raise StepError(
            f"the triage of {', '.join(in_progress)} is in progress: its triage file holds "
            "neither `## Next` nor `## Gate`, and no recorded triage outcome names it. Finish "
            "it on the code it started with, or resume it under the current skill, which "
            "records its outcome with `python3 scripts/run_change_step.py record`; then "
            "convert the change again")
    lines = [rewritten(entry) for entry in entries]
    changed = [entry["seq"] for entry in entries if entry.get("format") != FORMAT]
    lines.append(numbered(lines, {
        "step": CONVERSION, "outcome": "converted",
        "triaged": [t.record.name for t in triaged],
        "message": f"converted {state.change}'s records: {len(changed)} line(s) of its "
                   "workflow log rewritten in place"}, clock))
    state.log = lines
    return Conversion(lines, changed, triaged, _propose(lines, triaged, computation))


def _anchor(lines: Sequence[Entry], latest: Triaged | None) -> Entry | None:
    """The run of the latest triage: the latest recorded triage outcome naming its
    review; else the latest triage line after the run that published that review,
    or that run; else, for a review no run published, the latest triage line."""
    if latest is None:
        return None
    named = [e for e in lines if e.get("step") == "triage"
             and e.get("outcome") in ("finished", "returned")
             and latest.record.name in (e.get("triaged") or ())]
    if named:
        return named[-1]
    published = next((e for e in reversed(lines) if e.get("step") == "review"
                      and e.get("record") == latest.record.path.name), None)
    after = published["seq"] if published else 0
    triages = [e for e in lines if e.get("step") == "triage" and e["seq"] > after]
    return triages[-1] if triages else published


def _propose(lines: Sequence[Entry], triaged: Sequence[Triaged],
             computation: Computation) -> Proposal:
    state = computation.state
    latest = triaged[-1] if triaged else None
    anchor = _anchor(lines, latest)
    since = anchor["seq"] if anchor else 0
    decisions = [e for e in lines if e.get("outcome") == ORCHESTRATOR and e["seq"] > since
                 and isinstance(e.get("next"), Mapping)]
    if decisions:
        decision = decisions[-1]
        directed = f"the decision at seq {decision['seq']} directed " \
                   f"{target_label(decision['next'])}"
        try:
            node = node_of(decision["next"])
        except TargetError as exc:
            return Proposal(None, f"{directed}, which names no node: {exc}")
        if not any(e["seq"] > decision["seq"] and ran(node, e) for e in lines):
            return _checked(Proposal(dict(decision["next"]),
                                     f"{directed}, and no run of it is logged since: "
                                     f"{decision.get('decision', '')}"), computation)
    awaiting = [r.name for r in state.records if r.review_kind and not r.triaged
                and (latest is None or r.number > latest.record.number)]
    if awaiting:
        return Proposal(None, f"{awaiting[-1]} awaits its triage")
    if latest is None:
        return Proposal(None, "no review has a triage file, so no triage says where the "
                              "change stands")
    later = [e for e in lines if e.get("step") in STEPS and e["seq"] > since]
    if later:
        runs = ", ".join(f"{e['step']} at seq {e['seq']}" for e in later)
        return Proposal(None, f"runs are logged after the triage of {latest.record.name}, so "
                              f"it no longer says where the change stands: {runs}")
    return _exit_proposal(latest, anchor, computation)


def _exit_proposal(latest: Triaged, anchor: Entry | None,
                   computation: Computation) -> Proposal:
    """The direction to the exit the latest triage chose, or to the validation that
    remedies the exit's unmet guard; none where it chose no exit, or the guard has
    no step to remedy it."""
    record, reading = latest.record, latest.reading
    source = Node("triage", record.review_kind)
    line = anchor or {"seq": 0}
    if latest.record.name in (line.get("triaged") or ()):
        why = f"the triage of {record.name} at seq {line['seq']}"
        returned = line.get("outcome") == "returned"
        target = line.get("next") if isinstance(line.get("next"), Mapping) else None
        if target is None and not returned:
            return Proposal(None, f"{why} names no exit")
    else:
        why = f"{record.triage.name} records {reading.first!r} under {reading.heading}"
        returned = reading.token == RETURNED
        if reading.token == OTHER:
            return Proposal(None, f"{why}, which leads to no exit: the owner directs where "
                                  "it leads")
        target = None if returned else _node_target(
            _advancing(source, computation) if reading.token == ADVANCE
            else graph.exits(source, when=graph.ANOTHER_ROUND)[0].target)
    if returned:
        return _return_proposal(why, line, computation)
    assert target is not None
    return _guarded(why, record, source, target, line, computation)


def _node_target(node: Node) -> Entry:
    return {"step": node.step, **({"kind": node.kind} if node.kind else {})}


def _advancing(source: Node, computation: Computation) -> Node:
    """The node a triage that advances leads to in its phase: after an
    implementation round, the plan's next round, or the pre-closeout review once
    every section before closeout is checked."""
    if source == IMPLEMENTATION_TRIAGE and all(
            section.complete for section in computation.state.sections
            if not section.closeout):
        return PRE_CLOSEOUT_REVIEW
    return graph.exits(source, when=graph.ADVANCE)[0].target


def _return_proposal(why: str, line: Entry, computation: Computation) -> Proposal:
    """The direction confirming a return the triage's run proposed, resolving it."""
    if line.get("outcome") != "returned":
        return Proposal(None, f"{why}: a return, and no returned run of it is logged for a "
                              "direction to resolve; the owner directs where it leads")
    target = line.get("next")
    if not isinstance(target, Mapping):
        return Proposal(None, f"{why}: a return naming no target, at seq {line['seq']}")
    returning = f"{why}: a return to {target_label(target)}, proposed at seq {line['seq']}"
    if any(e.get("outcome") == ORCHESTRATOR and e.get("resolves") == line["seq"]
           for e in computation.state.log):
        return Proposal(None, f"{returning}, which a decision resolved without directing it; "
                              "the owner directs where it leads")
    return _checked(Proposal(dict(target), f"{returning}, which this direction confirms",
                             resolves=line["seq"]), computation)


def _guarded(why: str, record: Record, source: Node, target: Entry, line: Entry,
             computation: Computation) -> Proposal:
    """`target`, the exit `source`, the triage of `record`, chose; or the validation
    remedying its first unmet guard, carrying it as the validation's target. The
    guards read the triage's run as naming `record`, as a recorded outcome would."""
    chose = f"{why} chose {target_label(target)}"
    try:
        node = node_of(target)
    except TargetError as exc:
        return Proposal(None, f"{chose}, which names no node: {exc}")
    declared = graph.exits(source, target=node)
    if len(declared) > 1:
        out_of_order = target.get("step") == "implement"
        declared = [e for e in declared
                    if (e.when == graph.OUT_OF_ORDER) == out_of_order] or declared
    if not declared:
        return Proposal(None, f"{chose}, which {source.label} does not declare")
    context = computation.context(Route(EXIT, {**line, "triaged": [record.name]}, target,
                                        source))
    if isinstance(context, str):
        return Proposal(None, f"{chose}, but {context}")
    if (unmet := computation.guarded(declared[0], target, context)) is None:
        return _checked(Proposal(dict(target), chose), computation)
    if unmet.get("step") == VALIDATE.step:
        return _checked(Proposal({"step": VALIDATE.step, "target": dict(target)},
                                 f"{chose}, and {unmet['reason']}"), computation)
    remedy = "" if unmet.get("step") == graph.OWNER else f", which {unmet['step']} remedies"
    return Proposal(None, f"{chose}, and a guard on it is not met{remedy}: {unmet['reason']}")


def _checked(proposal: Proposal, computation: Computation) -> Proposal:
    """`proposal`, unless an unwaivable entry guard of a node it names is not met, as
    the log's writer would refuse it; then nothing is proposed."""
    assert proposal.target is not None
    if refusal := entry_refusal(proposal.target, computation.standing(), directed=True):
        return Proposal(None, f"{proposal.why}; but {refusal}, so nothing is proposed")
    return proposal


def _directed(made: Conversion, path: Path, *, given: Entry | None, decline: bool,
              reason: str | None, clock: Clock) -> list[Entry]:
    """The converted log with the owner's direction after it: the one given, else
    the one proposed; none when the owner declines a proposed return."""
    proposal = made.proposal
    if decline:
        if proposal.resolves is None:
            raise StepError("--decline declines a proposed return, and none is proposed: "
                            "confirm the proposal, or give the direction with --next")
        if given is not None:
            raise StepError("--decline writes no direction, so it takes no --next")
        return made.lines
    target = given if given is not None else proposal.target
    if target is None:
        raise StepError(f"no direction is proposed, since {proposal.why}: give the node the "
                        "change stands at with --next")
    why = reason or (f"{proposal.why}; confirmed at conversion" if given is None
                     else "given by the owner at conversion, in place of the proposal: "
                          + (f"{target_label(proposal.target)}, since {proposal.why}"
                             if proposal.target else f"none, since {proposal.why}"))
    line = decision_line(path, made.lines, f"the change stands at {target_label(target)}",
                         why, by="owner", directs=dict(target),
                         resolves=proposal.resolves if given is None else None)
    return [*made.lines, numbered(made.lines, line, clock)]


def _shown(made: Conversion, *, given: Entry | None, decline: bool) -> list[str]:
    """The conversion as the owner reads it before confirming."""
    shown = [f"{len(made.rewritten)} line(s) of the workflow log are rewritten in place"
             + (f", seq {', '.join(map(str, made.rewritten))}" if made.rewritten else ""),
             "the conversion line names these reviews as triaged, each with what its triage "
             "file was read to record; confirming attests that each flagged * finished, "
             "since no recorded triage outcome names it:"]
    shown += [f"  {' ' if t.attested else '*'} {t.record.name}: "
              + (f"{t.reading.heading}: {t.reading.first}" if t.reading.heading
                 else "named by a recorded triage outcome") for t in made.triaged] or ["  none"]
    proposal = made.proposal
    if given is not None:
        shown.append(f"direction given: {json.dumps(given, ensure_ascii=False)}, in place of "
                     + (f"the proposal {json.dumps(proposal.target, ensure_ascii=False)}"
                        if proposal.target else "no proposal")
                     + f" ({proposal.why})")
    elif proposal.target is not None:
        shown.append(f"proposed direction: {json.dumps(proposal.target, ensure_ascii=False)}"
                     + (f", resolving seq {proposal.resolves}" if proposal.resolves else "")
                     + f" — {proposal.why}")
    else:
        shown.append(f"no direction is proposed: {proposal.why}; give the node the change "
                     "stands at with --next")
    if decline:
        shown.append("--decline: the return is not confirmed, and no direction is written")
    shown.append("nothing is written: run again with --confirm to write the conversion"
                 + ("" if decline or (given is None and proposal.target is None)
                    else " and the direction")
                 + (", or with --confirm --decline to write it declining the return"
                    if proposal.resolves and not decline and given is None else ""))
    return shown


def convert_change(root: Path, change: str, *, confirm: bool = False, decline: bool = False,
                   given: Entry | None = None, reason: str | None = None,
                   clock: Clock = utc_now, replace: Callable[[Path, Path], Any] = os.replace,
                   **seams: Any) -> list[str]:
    """Convert `change`'s records: shown for the owner's confirmation, or, with
    `confirm`, written, and the lines appended returned as JSON. `seams` are the
    next-step computation's, whose readings the proposal's guards use."""
    path = log_path(root, change)
    computation = Computation(root, change, **seams)
    try:
        # Read before the log is locked for its replacement: nothing may read the
        # log by its name while that lock is held.
        computation.read()
    except ChangeNotFound as exc:
        raise StepError(str(exc)) from exc
    if not confirm:
        return _shown(conversion(computation.state.log, computation, clock), given=given,
                      decline=decline)
    before: list[int] = []

    def rewrite(entries: list[Entry]) -> list[Entry]:
        before.append(len(entries))
        return _directed(conversion(entries, computation, clock), path, given=given,
                         decline=decline, reason=reason, clock=clock)

    lines = replace_log(path, rewrite, replace=replace)
    return [json.dumps(line, ensure_ascii=False) for line in lines[before[0]:]]
