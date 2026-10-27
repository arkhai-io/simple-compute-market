"""The command line of `scripts/run_change_step.py`, each command dispatched to the
module that does its work.

`run` and `resume` run a step through the wrapper, either granting rules for that
one run with `--allow`; `run --session` continues a named implementation session; `review` runs a review, `log` and `note` read and write the
workflow log, `watch` follows the steps as they run, and `denials` reports a run's
denials. `record` is a step's own last act when the owner runs it interactively:
it records the step's outcome, which the wrapper records for an unattended run. A
command that runs a step prints the line it logged on stdout, its progress going to
stderr, and exits non-zero when that line is `stopped`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Callable, Mapping, Sequence

from check_change_index import index_rows
from change_workflow.common import KINDS, ORCHESTRATOR, ROOT, StepError
from change_workflow.harness import UNATTENDED_RUN
from change_workflow.log import (branch_decisions, history_log_path, last_entries, log_path,
                                 note_orchestrator, note_round, read_log, record_interactive)
from change_workflow.records import git_head
from change_workflow.review import DEFAULT_BASE, review_and_log
from change_workflow.watch import denial_report, watch
from change_workflow.wrapper import Wrapper

DESCRIPTION = "Run a step of an OpenSpec change unattended, and keep the change's workflow log."
# Where Claude Code gives every command it starts the id of its session. The
# variable is not documented, so a run where it is unset is refused rather than
# recorded without a session, and `--session` gives the id instead.
SESSION_ID = "CLAUDE_CODE_SESSION_ID"


def interactive_outcome(change: str, step: str, outcome_text: str, session: str | None,
                        environ: Mapping[str, str], root: Path,
                        head: Callable[[Path], str | None] = git_head) -> dict:
    """Record the outcome of `step`, run interactively on `change`, and return its line.

    Refused, writing nothing, inside a run the wrapper started, whose outcome the
    wrapper records, so it is never written twice; without a session id, naming the
    variable; and for an outcome that is not JSON, or that the log's writer
    refuses.
    """
    if environ.get(UNATTENDED_RUN):
        raise StepError(f"this run is the wrapper's ({UNATTENDED_RUN} is set), and the "
                        "wrapper records its outcome; record only a run held interactively")
    session = session or environ.get(SESSION_ID)
    if not session:
        raise StepError(f"{SESSION_ID} is not set, so the run's session is unknown; give it "
                        "with --session")
    try:
        outcome = json.loads(outcome_text)
    except json.JSONDecodeError as exc:
        raise StepError(f"--outcome is not JSON: {exc}") from exc
    return record_interactive(log_path(root, change), step, outcome, session=session,
                              commit=head(root))


def expand_sections(text: str) -> list[int | str]:
    """`1-3` as `[1, 2, 3]`, and `1,3` as `[1, 3]`; a name such as `5B` kept as it is."""
    sections: list[int | str] = []
    for part in (part.strip() for part in text.split(",")):
        low, _, high = part.partition("-")
        if high and low.isascii() and low.isdigit() and high.isascii() and high.isdigit():
            if int(low) > int(high):
                raise StepError(f"the section range {part} runs backwards")
            sections += range(int(low), int(high) + 1)
        elif part:
            sections.append(int(part) if part.isascii() and part.isdigit() else part)
    return sections


def parse_sections(text: str) -> list[list[int | str]]:
    """`1,2;3` as `[[1, 2], [3]]`: sessions separated by `;`, sections by `,`."""
    return [[int(section) if section.isascii() and section.isdigit() else section
             for section in (part.strip() for part in session.split(",")) if section]
            for session in text.split(";") if session.strip()]


def split_rules(values: Sequence[str]) -> list[str]:
    """Each `--allow` value split on `;`, each part trimmed and empty ones dropped:
    `make`'s `ALLOW` holds several rules so separated. No rule loses by it, since
    the harness matches each command of a chain on its own, so a rule holding `;`
    could never match."""
    return [rule.strip() for value in values for rule in value.split(";") if rule.strip()]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="run a step unattended and log its outcome")
    run.add_argument("step")
    run.add_argument("change")
    run.add_argument("--sections", default="",
                     help="implementation's sections, as `2`, `1-3`, or `1,3`")
    run.add_argument("--arguments", default="",
                     help="text added to the skill's invocation after the change")
    run.add_argument("--fresh", action="store_true",
                     help="start a fresh session for a step that resumes another's")
    run.add_argument("--session", default="",
                     help="implementation only: continue this session, one of the change's "
                          "implementation runs not waiting on the owner")
    run.add_argument("--allow", action="append", default=[],
                     help="permission rules granted for this run alone, several separated "
                          "by ';'")
    resume = commands.add_parser("resume", help="resume a waiting run with the owner's answer")
    resume.add_argument("change")
    resume.add_argument("--seq", type=int, required=True,
                        help="the waiting run's line in the workflow log")
    resume.add_argument("--answer", required=True)
    resume.add_argument("--allow", action="append", default=[],
                        help="permission rules granted for this run alone, several separated "
                             "by ';'")
    review = commands.add_parser(
        "review", help="review a change, read-only, on the first available of the review's "
                       "models")
    review.add_argument("change")
    review.add_argument("--kind", required=True, choices=KINDS)
    review.add_argument("--base", default=DEFAULT_BASE)
    review.add_argument("--model", default=None,
                        help="the owner's choice of reviewer for this run, outside the review "
                             "row's policy: a claude- model runs on Claude, any other on Codex, "
                             "with no fallback")
    review.add_argument("--effort", default=None,
                        help="the owner's choice of effort for this run: the given model's, or "
                             "every entry's of the review row")
    review.add_argument("--fresh", action="store_true",
                        help="start a new reviewer session instead of continuing the last one")
    review.add_argument("--unvalidated", action="store_true",
                        help="run a pre-closeout review without a passing validation of HEAD")
    record = commands.add_parser(
        "record", help="record the outcome of a step run interactively, as its last act")
    record.add_argument("change")
    record.add_argument("step")
    record.add_argument("--outcome", required=True,
                        help="the step's outcome as JSON, matching the outcome schema")
    record.add_argument("--session", default=None,
                        help=f"the session's id, where {SESSION_ID} is not set")
    log = commands.add_parser("log", help="print the last lines of the change's workflow log")
    log.add_argument("change")
    log.add_argument("--last", type=int, default=10)
    log.add_argument("--branch", default=None,
                     help="only the owner's decisions that the change is worked on this "
                          "branch")
    watch_ = commands.add_parser(
        "watch", help="follow the progress of the change's steps as they run")
    watch_.add_argument("change")
    denials = commands.add_parser(
        "denials", help="print a run's denials with the tool calls it made after each")
    denials.add_argument("change")
    denials.add_argument("seq", type=int, help="the run's line in the workflow log")
    note = commands.add_parser("note", help="append an orchestrator line to the workflow log")
    note.add_argument("change")
    kinds = note.add_subparsers(dest="kind", required=True)
    round_ = kinds.add_parser("round", help="the implementation round the owner agreed")
    round_.add_argument("--sections", required=True,
                        help="sessions separated by ';', each a ','-separated list of sections")
    round_.add_argument("--by", default="owner")
    round_.add_argument("--after", type=int, default=None,
                        help="the highest record number before the round, for a round "
                             "recorded after the fact")
    decision = kinds.add_parser(ORCHESTRATOR, help="a decision: the orchestrating session's "
                                                   "own, or the owner's, relayed")
    decision.add_argument("--decision", required=True)
    decision.add_argument("--reason", required=True)
    decision.add_argument("--by", default=ORCHESTRATOR, help="who decided: owner or orchestrator")
    decision.add_argument("--resolves", type=int, default=None,
                          help="the seq of the run the decision settles")
    decision.add_argument("--reads", type=int, default=None,
                          help="the seq of the run whose denials the decision has read")
    decision.add_argument("--next", dest="next_step", default=None,
                          help="the step the decision directs next")
    decision.add_argument("--kind", default=None, help="the review kind when --next is review")
    decision.add_argument("--branch", default=None,
                          help="with --change, the owner's word that the change is worked on "
                               "this branch")
    decision.add_argument("--change", dest="decided_change", default=None,
                          help="the change the branch decision is for; the log's own by "
                               "default")
    return parser


def main(argv: Sequence[str] | None = None, root: Path = ROOT,
         wrapper: Wrapper | None = None, environ: Mapping[str, str] = os.environ) -> int:
    args = _parser().parse_args(argv)
    wrapper = wrapper or Wrapper(root=root)
    try:
        path = (history_log_path if args.command == "log" else log_path)(wrapper.root,
                                                                          args.change)
        if args.command == "record":
            line = interactive_outcome(args.change, args.step, args.outcome, args.session,
                                       environ, wrapper.root, wrapper.head)
            print(json.dumps(line, ensure_ascii=False))
            return 0
        if args.command == "run":
            sections = expand_sections(args.sections)
            words = (f"section {args.sections}" if len(sections) == 1
                     else f"sections {args.sections}" if sections else "")
            arguments = " ".join(part for part in (words, args.arguments) if part)
            line = wrapper.run(args.step, args.change, arguments=arguments,
                               sections=sections, fresh=args.fresh,
                               granted=split_rules(args.allow),
                               continuing=args.session.strip() or None)
            print(json.dumps(line, ensure_ascii=False))
            return 1 if line["outcome"] == "stopped" else 0
        if args.command == "review":
            line = review_and_log(args.change, args.kind, root=wrapper.root, base=args.base,
                                  model=args.model or None, effort=args.effort or None,
                                  fresh=args.fresh, unvalidated=args.unvalidated)
            if line["outcome"] == "stopped":
                print(f"ERROR: {line['reason']}", file=sys.stderr)
            else:
                print(f"Review written to {line['record']}", file=sys.stderr)
            print(json.dumps(line, ensure_ascii=False))
            return 1 if line["outcome"] == "stopped" else 0
        if args.command == "resume":
            line = wrapper.resume(args.change, args.seq, args.answer, split_rules(args.allow))
            print(json.dumps(line, ensure_ascii=False))
            return 1 if line["outcome"] == "stopped" else 0
        if args.command == "log":
            if args.branch:
                found = branch_decisions(read_log(path), args.branch, args.change)
                entries = found[-args.last:] if args.last > 0 else []
            else:
                entries = last_entries(path, args.last)
            for entry in entries:
                print(json.dumps(entry, ensure_ascii=False))
        elif args.command == "watch":
            try:
                watch(lambda: log_path(wrapper.root, args.change).parent,
                      echo=lambda line: print(line, flush=True))
            except KeyboardInterrupt:
                pass
        elif args.command == "denials":
            entry = next((e for e in read_log(path) if e.get("seq") == args.seq), None)
            if entry is None:
                raise StepError(f"{args.change}'s workflow log has no seq {args.seq}")
            for shown in denial_report(path.parent, entry):
                print(shown)
        elif args.kind == "round":
            # A round recorded after the fact started at a commit no longer HEAD.
            line = note_round(path, parse_sections(args.sections), args.by, args.after,
                              commit=None if args.after is not None else git_head(root))
            print(json.dumps(line, ensure_ascii=False))
        else:
            line = note_orchestrator(path, args.decision, args.reason, by=args.by,
                                     resolves=args.resolves, reads=args.reads,
                                     next_step=args.next_step, kind=args.kind,
                                     branch=args.branch,
                                     # A branch decision is about the change whose
                                     # log holds it, which is where steps look.
                                     change=args.decided_change
                                     or (args.change if args.branch else None),
                                     status=next((row.status for row in
                                                  index_rows(wrapper.root)
                                                  if row.name == args.change), None))
            print(json.dumps(line, ensure_ascii=False))
    except StepError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0
