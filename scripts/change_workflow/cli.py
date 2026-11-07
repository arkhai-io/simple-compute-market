"""The engine's command, `scripts/change-workflow`: each subcommand dispatched to the
module that does its work.

`start` starts a step: without `--unattended` it opens the interactive Claude Code
session of the step's skill; with it, it runs the step through the wrapper, granting
rules for that one run with `--allow`, and `--session` continues a named
implementation session. Before either it refuses what the step cannot take — an
archived change for a step whose node takes only an active one, an active change
for archive cleanup — and, for implementation and every step after it, an open
round view (`ROUND_VIEW_CLOSED`); then it opens the change's workflow log with a line
carrying the record set's format, refusing records of another format
(`log.open_log`). `start orchestrate` opens the orchestrating session on the model
and effort the workflow configuration's `models.orchestrator` names. `resume`
resumes a waiting run with the owner's answer; `review` runs a review; `stop`
sends SIGTERM to the change's run in progress — in its clone when it has one, else
in this checkout — on the owner's word, which the run
logs as `stopped`; `log` and `note` read and write the workflow log, `note --resumes`
recording the owner's direction to revisit a finished triage; `watch` follows the
steps as they run, and `denials` reports a run's denials. `record` is a
step's own last act when the owner runs it interactively: it records the step's
outcome, which the wrapper records for an unattended run. `convert` brings a
change's records into the log's format, shown first and written on the owner's
`--confirm`.

The others reach the module that holds them: `next` the next-step computation,
`find` a change's directory and records, `clone`, `clone where`, and `clone-remove`
a change's clone, `round-view` and `round-done` the round view, `history` the copy
of a change's history, `cost` its cost report, `push` the guarded push, `config`
how the repository's workflow configuration resolved, `config load` a step's
documents, or with `common` those every session reads, and `config parts`
validation's plan for a change, `run` and `openspec`
the repository's hooks and its OpenSpec command (`hooks`), `check` the
configuration's, index, task-list, push, skill, and round-view checks, a change's
default checks (`check change`), and the graph diagram's comparison with the graph
table, `hook post-compaction` the post-compaction hook, and `wait` the bounded wait
on a background command's output. `check graph` is internal: it maintains the
engine's own diagram, and no repository or runner relies on it.

Before a step starts, `start` checks the configuration whole and refuses a step
whose required fields are absent, naming them, before anything is launched or
logged (`config.require_for_step`): an unattended run also needs its step's models,
and the orchestrating session its own.

The repository is found once, from the working directory, and every subcommand acts
on it. Every exit status is one of three: 0 for success; 1 for a refusal or a failed
check, its reason on standard error; 2 for a usage error, such as a malformed or
missing argument. A subcommand that runs a step prints the line it logged on
standard output, its progress going to standard error, and exits 1 when that line
is `stopped`.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable, Mapping, Sequence

from . import clone as clones
from . import (config, cost_report, diagram, find, graph, history, hook, hooks, index,
               next_step, push, round_view, skills, tasks, wait)
from .clone import clone_of
from .common import ORCHESTRATOR, SESSION_ID, UNATTENDED_RUN, StepError, repository_root
from .convert import convert_change
from .find import ChangeNotFound, change_directory, is_archived
from .graph import KINDS, STEPS
from .log import (branch_decisions, direction, history_log_path, last_entries, log_path,
                  note_orchestrator, note_round, open_log, read_log, record_interactive)
from .records import git_head
from .review import review_and_log
from .running import drop_invocations, invocations_directory, kept_invocations, stop
from .watch import denial_report, watch
from .wrapper import Wrapper

DESCRIPTION = "Run the steps of an OpenSpec change, and keep its workflow log."
ORCHESTRATE = config.ORCHESTRATOR_STEP
# The steps `start` starts: every step the graph runs but the review, which has a
# subcommand of its own, and the orchestrating session.
STARTABLE = tuple(step for step in STEPS if step != "review") + (ORCHESTRATE,)
# The steps refused while a round view is open: implementation and every step after
# it works on the round's commits, and an open view leaves the branch at the round's
# base instead. Design and planning come before any round of the change.
ROUND_VIEW_CLOSED = frozenset({"implement", "triage", "merge", "closeout", "validate",
                               "archive-cleanup"})

# Runs an interactive session's command in the repository, returning its status.
Launch = Callable[[Sequence[str], Path], int]


def _launch(command: Sequence[str], root: Path) -> int:
    try:
        return subprocess.run(list(command), cwd=root).returncode
    except OSError as exc:
        raise StepError(f"cannot run {command[0]}: {exc}") from exc


def _taking(guard: graph.EntryGuard) -> frozenset[str]:
    """The steps every node of which carries `guard` among its entry guards."""
    nodes: dict[str, list[bool]] = {}
    for declaration in graph.TABLE:
        if declaration.runs:
            nodes.setdefault(declaration.runs, []).append(guard in declaration.entry)
    return frozenset(step for step, guarded in nodes.items() if all(guarded))


# What a step's nodes take, by their entry guards: only an active change, or only an
# archived one.
ACTIVE_ONLY = _taking(graph.NOT_ARCHIVED)
ARCHIVED_ONLY = _taking(graph.ARCHIVED)


def interactive_outcome(change: str, step: str, outcome_text: str, session: str | None,
                        environ: Mapping[str, str], root: Path,
                        head: Callable[[Path], str | None] = git_head,
                        invocations: Callable[[Path], Path | None] = invocations_directory
                        ) -> dict:
    """Record the outcome of `step`, run interactively on `change`, and return its line.

    Refused, writing nothing, inside a run the wrapper started, whose outcome the
    wrapper records, so it is never written twice; without a session id, naming the
    variable; and for an outcome that is not JSON, or that the log's writer
    refuses. What the session invoked for this change through `run`, and through
    the guarded push, that no line has taken yet is recorded as `invoked`, and
    forgotten once the line is written, so a refused record keeps it for the next.
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
    directory = invocations(root)
    invoked = kept_invocations(directory, session, change)
    line = record_interactive(log_path(root, change), step, outcome, session=session,
                              commit=head(root), invoked=invoked)
    drop_invocations(directory, session, invoked)
    return line


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


def section_words(text: str) -> str:
    """How a skill's invocation names the sections `text` gives: `section 2`, or
    `sections 1-3`; empty for none."""
    sections = expand_sections(text)
    return (f"section {text}" if len(sections) == 1
            else f"sections {text}" if sections else "")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="change-workflow", description=DESCRIPTION)
    commands = parser.add_subparsers(dest="command", required=True)
    start = commands.add_parser(
        "start", help="start a step: an interactive session, or with --unattended a run "
                      "held to the step's permissions whose outcome is logged")
    start.add_argument("step", choices=STARTABLE)
    start.add_argument("change")
    start.add_argument("--unattended", action="store_true",
                       help="run the step headless through the wrapper and log its outcome")
    start.add_argument("--sections", default="",
                       help="implementation's sections, as `2`, `1-3`, or `1,3`")
    start.add_argument("--arguments", default="",
                       help="text added to the skill's invocation after the change")
    start.add_argument("--fresh", action="store_true",
                       help="unattended: start a fresh session for a step that resumes "
                            "another's")
    start.add_argument("--session", default="",
                       help="unattended implementation only: continue this session, one of "
                            "the change's implementation runs not waiting on the owner")
    start.add_argument("--allow", action="append", default=[],
                       help="unattended: permission rules granted for this run alone, several "
                            "separated by ';'")
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
    review.add_argument("--base", default=None,
                        help="the branch the change is read against, for this run; the "
                             "branch it lands on, as its clone recorded it, by default")
    review.add_argument("--model", default=None,
                        help="the owner's choice of reviewer for this run, outside the review "
                             "models' policy: a claude- model runs on Claude, any other on Codex, "
                             "with no fallback")
    review.add_argument("--effort", default=None,
                        help="the owner's choice of effort for this run: the given model's, or "
                             "every entry's of the review's models")
    review.add_argument("--fresh", action="store_true",
                        help="start a new reviewer session instead of continuing the last one")
    review.add_argument("--unvalidated", action="store_true",
                        help="run a pre-closeout review without a passing validation of HEAD")
    stop_ = commands.add_parser(
        "stop", help="stop the change's run in progress, in its clone when it has one, which "
                     "is logged `stopped`")
    stop_.add_argument("change")
    stop_.add_argument("--step", default=None,
                       help="the step whose run to stop, when two runs of the change are in "
                            "progress")
    record = commands.add_parser(
        "record", help="record the outcome of a step run interactively, as its last act")
    record.add_argument("change")
    record.add_argument("step")
    record.add_argument("--outcome", required=True,
                        help="the step's outcome as JSON, matching the outcome schema")
    record.add_argument("--session", default=None,
                        help=f"the session's id, where {SESSION_ID} is not set")
    convert = commands.add_parser(
        "convert", help="convert the change's records to the workflow log's format: shown, "
                        "and written on the owner's --confirm")
    convert.add_argument("change")
    convert.add_argument("--confirm", action="store_true",
                         help="write the conversion and its direction: the owner's "
                              "confirmation, attesting that each triage it flags finished")
    convert.add_argument("--decline", action="store_true",
                         help="write no direction, declining the return the conversion "
                              "proposes to confirm, which then waits for the owner")
    convert.add_argument("--next", dest="next_step", default=None,
                         help="the owner's direction in the proposal's place: the step the "
                              "change stands at")
    convert.add_argument("--kind", default=None,
                         help="the kind of review --next is, or triages; with --target, the "
                              "target's")
    convert.add_argument("--sections", default=None,
                         help="with --next implement, its sections, as `note round` takes "
                              "them; with --target, the target's")
    convert.add_argument("--target", default=None,
                         help="with --next validate, the step the validation is for")
    convert.add_argument("--reason", default=None,
                         help="the direction's reason, in place of the one the conversion "
                              "gives")
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
                          help="the owner's direction: the step the change goes to next")
    decision.add_argument("--kind", default=None,
                          help="the kind of review --next is, or triages; with --target, "
                               "the target's")
    decision.add_argument("--sections", default=None,
                          help="with --next implement, the sections it implements out of "
                               "the plan's order, as `note round` takes them; with "
                               "--target, the target's")
    decision.add_argument("--target", default=None,
                          help="with --next validate, the step the validation is for")
    decision.add_argument("--branch", default=None,
                          help="with --change, the owner's word that the change is worked on "
                               "this branch")
    decision.add_argument("--change", dest="decided_change", default=None,
                          help="the change the branch decision is for; the log's own by "
                               "default")
    decision.add_argument("--resumes", type=int, default=None,
                          help="the owner's direction to revisit the finished triage run at "
                               "this seq, which `resume` then continues with their words")
    next_ = commands.add_parser("next", help="compute the change's next step")
    next_.add_argument("change")
    next_.add_argument("--plain", action="store_true",
                       help="print the result as lines for reading rather than JSON")
    find_ = commands.add_parser("find", help="find a change's directory, or its records")
    found = find_.add_mutually_exclusive_group()
    found.add_argument("--active", action="store_true", help="refuse an archived change")
    found.add_argument("--archived", action="store_true", help="refuse an active change")
    found.add_argument("--records", action="store_true",
                       help="its records: this checkout's, else the owner's workspace's")
    find_.add_argument("--json", action="store_true",
                       help="print name, directory, archived, records, format, and base, the "
                            "branch the change lands on, as JSON")
    find_.add_argument("change")
    clone = commands.add_parser(
        "clone", help="create or finish a change's clone; `clone where <change>` prints a "
                      "usable clone's path")
    clone.add_argument("change", help="the change, or `where` followed by the change")
    clone.add_argument("where_change", nargs="?", default=None, metavar="change",
                       help=argparse.SUPPRESS)
    clone.add_argument("--branch", default=None,
                       help="the change's branch; feat/<change> by default")
    clone.add_argument("--from", dest="from_ref", default=None,
                       help="the branch the change lands on, where a new branch starts; the "
                            "workspace's checked-out branch by default")
    removing = commands.add_parser(
        "clone-remove", help="delete a merged change's clone once its history is in the "
                             "workspace")
    removing.add_argument("change")
    removing.add_argument("--base", default=None,
                          help="the branch the change landed on, for a clone that recorded "
                               "none")
    viewing = commands.add_parser(
        "round-view", help="show an implementation round as uncommitted changes")
    viewing.add_argument("change")
    viewing.add_argument("--base", default=None)
    commands.add_parser("round-done", help="return the branch to the round's commit")
    history_ = commands.add_parser(
        "history", help="copy a change's history from its clone into the workspace")
    history_.add_argument("change")
    cost = commands.add_parser("cost", help="report what a change's runs cost")
    cost.add_argument("change")
    push_ = commands.add_parser("push", help="push exactly HEAD to its own branch, once it may be")
    push_.add_argument("--remote", default=None,
                       help="the remote to push to, in place of the branch's upstream's")
    config_ = commands.add_parser(
        "config", help="list how every field of the repository's workflow configuration "
                       "resolved; `config load <step>` a step's documents, `config load "
                       "common` those every session reads; `config parts <change>` "
                       "validation's plan")
    config_.add_argument("action", nargs="?", choices=("load", "parts"), default=None)
    config_.add_argument("subject", nargs="?", default=None, metavar="step|change")
    config_.add_argument("--json", action="store_true", help="print it as JSON")
    run_ = commands.add_parser(
        "run", help="run one of the repository's hooks for a change, as the engine's hook "
                    "table allows the step")
    run_.add_argument("hook", choices=(*hooks.NAMED, hooks.VALIDATION, hooks.CLEANUP))
    run_.add_argument("change")
    run_.add_argument("part", nargs="?", default=None,
                      help="validation only: `preflight`, or the part to run")
    run_.add_argument("phase", nargs="?", default=None, choices=hooks.PHASES,
                      help="validation's part only: run, start, or collect")
    run_.add_argument("--owed", default=None,
                      help="an owed part only: the workflow its run is for")
    run_.add_argument("--base", default=None,
                      help="the branch the change lands on, for a command naming {base}; "
                           "the one its clone recorded by default")
    commands.add_parser(
        "openspec", help="run the configured OpenSpec command with the arguments given",
        add_help=False)
    check = commands.add_parser("check", help="run one of the workflow's checks")
    checks = check.add_subparsers(dest="check", required=True)
    checks.add_parser("config", help="the repository's workflow configuration, checked whole")
    change_ = checks.add_parser("change", help="pre-commit's default checks of a change, alone")
    change_.add_argument("change")
    checks.add_parser("index", help="the change index against the change directories")
    tasks_ = checks.add_parser("tasks", help="every task under its own section's heading")
    tasks_.add_argument("change")
    checks.add_parser("push", help="whether HEAD may be pushed to its own branch")
    checks.add_parser("skills", help="every agent skill loaded from its one source")
    checks.add_parser("round-view", help="fail while a round view is open")
    checks.add_parser("graph", help="where the graph's diagram departs from the graph table")
    waiting = commands.add_parser(
        "wait", help="block until a file holds a line matching a pattern, within a bound")
    waiting.add_argument("file", type=Path)
    waiting.add_argument("pattern")
    waiting.add_argument("--timeout", type=float, default=wait.DEFAULT_TIMEOUT_S)
    hook_ = commands.add_parser("hook", help="run a harness hook")
    harness_hooks = hook_.add_subparsers(dest="hook", required=True)
    harness_hooks.add_parser("post-compaction",
                             help="print what a session re-reads after its context is "
                                  "compacted")
    return parser


def _round_view_closed(root: Path) -> None:
    try:
        round_view.check(root)
    except round_view.RoundError as exc:
        raise StepError(str(exc)) from exc


def _takes(root: Path, step: str, change: str) -> None:
    """Refuse a change `step` cannot take, before the step starts: an archived change
    for a step that takes only an active one, and an active change for one that takes
    only an archived one."""
    try:
        directory = change_directory(root, change)
    except ChangeNotFound as exc:
        raise StepError(str(exc)) from exc
    archived = is_archived(root, directory)
    if step in ACTIVE_ONLY and archived:
        raise StepError(f"change {change!r} is archived "
                        f"({directory.relative_to(root).as_posix()}); {step} takes an active "
                        "change")
    if step in ARCHIVED_ONLY and not archived:
        raise StepError(f"change {change!r} is not archived; {step} follows closeout, which "
                        "archives it")


# The merge's invocation names the branch it brings in first, after the change:
# `<change> from <branch>`.
_FROM = re.compile(r"from\s+\S")


def merge_arguments(root: Path, change: str, arguments: str) -> str:
    """The merge's arguments, naming the branch it brings in: the one given, `from
    <branch>`, or else the branch the change lands on, as its clone recorded it;
    refused, naming the argument, with neither."""
    if _FROM.match(arguments):
        return arguments
    base = find.landing_branch(root, change)
    if base is None:
        raise StepError(f"the merge brings in the branch {change} lands on, and none is "
                        "recorded, since the change has no clone that recorded one: give it "
                        "with FROM=<branch>, or --arguments 'from <branch>'")
    return " ".join(part for part in (f"from {base}", arguments) if part)


def start(args: argparse.Namespace, root: Path, wrapper: Wrapper, launch: Launch) -> int:
    if not args.unattended and (args.allow or args.session or args.fresh):
        raise _Usage("--allow, --session, and --fresh qualify an unattended run; an "
                     "interactive session runs with the owner's own permissions")
    if args.step == ORCHESTRATE and (args.unattended or args.sections or args.arguments):
        raise _Usage("the orchestrating session is opened interactively, on the change alone")
    if args.sections and args.step != "implement":
        raise _Usage("only implementation takes sections")
    try:
        words = section_words(args.sections)
    except StepError as exc:
        raise _Usage(str(exc)) from exc
    _takes(root, args.step, args.change)
    if args.step in ROUND_VIEW_CLOSED:
        _round_view_closed(root)
    # Checked whole, and the fields the step needs required, before anything is
    # launched or logged.
    configuration = config.load(root)
    config.require_for_step(configuration, args.step, unattended=args.unattended)
    arguments = " ".join(part for part in (words, args.arguments) if part)
    if args.step == "merge":
        arguments = merge_arguments(root, args.change, arguments)
    if args.step == ORCHESTRATE:
        model = configuration.orchestrator_model()
        command = ["claude", "--model", model.model,
                   *(["--effort", model.effort] if model.effort else []),
                   f"/change-{ORCHESTRATE} {args.change}"]
        return _session_status(launch(command, root))
    # The log is the record set format's only authority, so it is marked before the
    # step can record anything, its ledger lines included.
    open_log(log_path(root, args.change), args.change, args.step,
             interactive=not args.unattended)
    if not args.unattended:
        # The skill a step's session opens is named for the step, so an interactive
        # session needs no step table, as no table restricts it.
        prompt = f"/change-{args.step} {args.change}" + (f" {arguments}" if arguments else "")
        return _session_status(launch(["claude", prompt], root))
    line = wrapper.run(args.step, args.change, arguments=arguments,
                       sections=expand_sections(args.sections), fresh=args.fresh,
                       granted=split_rules(args.allow),
                       continuing=args.session.strip() or None)
    return _logged(line)


def _session_status(status: int) -> int:
    """An interactive session's exit as the command's: 0, or 1 naming its status."""
    if status == 0:
        return 0
    print(f"ERROR: the session exited with status {status}", file=sys.stderr)
    return 1


def _logged(line: dict) -> int:
    """Print the line a run logged on standard output, for a caller to parse, and
    exit 1 when it stopped, its reason on standard error."""
    if line["outcome"] == "stopped":
        print(f"ERROR: {line.get('reason') or line.get('message', 'the run stopped')}",
              file=sys.stderr)
    print(json.dumps(line, ensure_ascii=False))
    return 1 if line["outcome"] == "stopped" else 0


def _clone_where(args: argparse.Namespace, root: Path) -> int:
    if args.where_change is None:
        raise _Usage("clone where takes the change whose clone it looks for")
    if args.branch or args.from_ref:
        raise _Usage("clone where takes no --branch or --from")
    change = args.where_change
    # An unknown change is told apart before any clone is looked for, so a
    # misspelled name is never taken for a change worked in place.
    try:
        change_directory(root, change)
    except ChangeNotFound as exc:
        raise StepError(str(exc)) from exc
    # Run in a change's clone, the clones are the workspace's.
    workspace = find.workspace_of(root) or root
    try:
        found = clones.where(workspace, change)
    except clones.CloneError as exc:
        raise StepError(str(exc)) from exc
    if found is not None:
        print(found)
    return 0


def _wait(args: argparse.Namespace) -> int:
    if args.timeout <= 0:
        raise _Usage("--timeout is a number of seconds above zero")
    try:
        pattern = re.compile(args.pattern)
    except re.error as exc:
        raise _Usage(f"the pattern is not a regular expression: {exc}") from exc
    return wait.run(args.file, pattern, timeout=args.timeout)


class _Usage(Exception):
    """An argument argparse cannot judge alone is malformed."""


def main(argv: Sequence[str] | None = None, root: Path | None = None,
         wrapper: Wrapper | None = None, environ: Mapping[str, str] = os.environ,
         launch: Launch = _launch, send: Callable[[int, int], None] = os.kill) -> int:
    given = list(sys.argv[1:] if argv is None else argv)
    if given[:1] == ["openspec"]:
        # Every argument is OpenSpec's, flags included, so none is parsed here.
        try:
            root = repository_root() if root is None else root
            return hooks.run_openspec(config.load(root), given[1:], root)
        except StepError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    try:
        root = repository_root() if root is None else root
        return _dispatch(args, root, wrapper or Wrapper(root=root), environ, launch, send)
    except _Usage as exc:
        parser.print_usage(sys.stderr)
        print(f"change-workflow: error: {exc}", file=sys.stderr)
        return 2
    except StepError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


# A module's command line and the arguments a subcommand hands it; None for a module
# whose command line takes the repository alone.
Delegated = tuple[Callable[..., int], list[str] | None]


def delegated(args: argparse.Namespace) -> Delegated | None:
    """The module command line a subcommand reaches, with the arguments it hands that
    command line; None for a subcommand this module runs."""
    if args.command == "next":
        return next_step.main, [args.change, *(["--plain"] if args.plain else [])]
    if args.command == "find":
        if args.json and args.records:
            raise _Usage("--json prints the records of this checkout alone, so it takes no "
                         "--records")
        flag = [f"--{name}" for name in ("active", "archived", "records") if getattr(args, name)]
        return find.main, [*flag, *(["--json"] if args.json else []), args.change]
    if args.command == "clone" and args.change != "where":
        if args.where_change is not None:
            raise _Usage("clone takes one change, or `where` followed by the change")
        return clones.main, ["create", args.change,
                             *(["--branch", args.branch] if args.branch else []),
                             *(["--from", args.from_ref] if args.from_ref else [])]
    simple: dict[str, Delegated] = {
        "clone-remove": (clones.main, ["remove", getattr(args, "change", ""),
                                       *(["--base", args.base]
                                         if getattr(args, "base", None) else [])]),
        "round-view": (round_view.main, ["start", getattr(args, "change", ""),
                                         *(["--base", args.base]
                                           if getattr(args, "base", None) else [])]),
        "round-done": (round_view.main, ["done"]),
        "history": (history.main, ["sync", getattr(args, "change", "")]),
        "cost": (cost_report.main, [getattr(args, "change", "")]),
        "push": (push.main, ["push", *(["--remote", args.remote]
                                       if getattr(args, "remote", None) else [])]),
        "hook": (hook.main, None),
    }
    if args.command in simple:
        return simple[args.command]
    if args.command == "check":
        return {"index": (index.main, None), "skills": (skills.main, None),
                "tasks": (tasks.main, [getattr(args, "change", "")]),
                "push": (push.main, ["check"]),
                "round-view": (round_view.main, ["check"]),
                "config": (config.main, ["check"]),
                "graph": (_graph, None)}[args.check]
    if args.command == "config" and args.action != "parts":
        if args.action == "load":
            if args.subject is None or args.json:
                raise _Usage("config load takes the step whose documents it prints, or "
                             "`common`, and no --json")
            return config.main, ["load", args.subject]
        if args.subject is not None:
            raise _Usage("config alone takes no argument; `config load <step>` and `config "
                         "parts <change>` take one")
        return config.main, ["show", *(["--json"] if args.json else [])]
    return None


def _config_parts(args: argparse.Namespace, root: Path) -> int:
    """Validation's plan for the change: the configuration's parts, an owed part
    once per workflow its complete sections owe."""
    if args.subject is None:
        raise _Usage("config parts takes the change whose plan it prints")
    configuration = config.load(root)
    try:
        directory = change_directory(root, args.subject)
    except ChangeNotFound as exc:
        raise StepError(str(exc)) from exc
    runs = config.plan(configuration, tasks.owed_lines(directory / next_step.TASKS_FILE))
    print(config.plan_json(configuration, runs) if args.json
          else "\n".join(config.plan_lines(configuration, runs)))
    return 0


def _graph(root: Path) -> int:
    """The diagram's comparison with the graph table, on the repository's own diagram."""
    return diagram.main(root=root)


def _dispatch(args: argparse.Namespace, root: Path, wrapper: Wrapper,
              environ: Mapping[str, str], launch: Launch,
              send: Callable[[int, int], None] = os.kill) -> int:
    if args.command == "start":
        return start(args, root, wrapper, launch)
    if args.command == "clone" and args.change == "where":
        return _clone_where(args, root)
    if args.command == "config" and args.action == "parts":
        return _config_parts(args, root)
    if args.command == "run":
        if args.hook == hooks.VALIDATION:
            if args.part is None or (args.part == hooks.PREFLIGHT) != (args.phase is None):
                raise _Usage("run validation takes `preflight`, or a part and its phase")
        elif (args.part, args.phase, args.owed) != (None, None, None):
            raise _Usage(f"run {args.hook} takes the change alone")
        # The branch the change lands on, for a command naming `{base}`: the one
        # given, or the one its clone recorded.
        base = args.base or find.landing_branch(root, args.change)
        return hooks.main(args.hook, args.change, root=root, configuration=config.load(root),
                          environ=environ, base=base, part=args.part, phase=args.phase,
                          owed=args.owed)
    if args.command == "check" and args.check == "change":
        configuration = config.load(root)
        try:
            change_directory(root, args.change)
        except ChangeNotFound as exc:
            raise StepError(str(exc)) from exc
        return 0 if hooks.Hooks(root, configuration, environ).check_change(args.change) else 1
    if args.command == "wait":
        return _wait(args)
    if (reached := delegated(args)) is not None:
        main_, arguments = reached
        if args.command == "push":
            _round_view_closed(root)
            return push.main(arguments, root=root, environ=environ)
        return main_(root) if arguments is None else main_(arguments, root=root)
    if args.command == "watch":
        # A change worked in its own clone writes its progress files there, and the
        # workspace receives them only when archive cleanup copies the change's
        # history, so from the workspace its clone is followed.
        watched = clone_of(wrapper.root, args.change) or wrapper.root
        log_path(watched, args.change)
        try:
            watch(lambda: log_path(watched, args.change).parent,
                  echo=lambda line: print(line, flush=True))
        except KeyboardInterrupt:
            pass
        return 0
    if args.command == "stop":
        # A change worked in its own clone runs its steps there, and each run is
        # recorded in the checkout it runs in.
        checkout = clone_of(wrapper.root, args.change) or wrapper.root
        stopped = stop(wrapper.runs(checkout), args.change, args.step, send)
        print(f"Sent SIGTERM to {stopped.describe()}; the run logs itself `stopped`.")
        return 0
    path = (history_log_path if args.command == "log" else log_path)(wrapper.root, args.change)
    if args.command == "record":
        line = interactive_outcome(args.change, args.step, args.outcome, args.session,
                                   environ, wrapper.root, wrapper.head, wrapper.invocations)
        print(json.dumps(line, ensure_ascii=False))
        return 0
    if args.command == "convert":
        if args.next_step is None and (args.kind, args.sections, args.target) != (
                None, None, None):
            raise _Usage("--kind, --sections, and --target qualify --next")
        given = (direction(args.next_step, args.kind,
                           parse_sections(args.sections) if args.sections is not None
                           else None, args.target)
                 if args.next_step is not None else None)
        for shown in convert_change(wrapper.root, args.change, confirm=args.confirm,
                                    decline=args.decline, given=given,
                                    reason=args.reason, head=wrapper.head):
            print(shown)
        return 0
    if args.command == "review":
        _round_view_closed(root)
        line = review_and_log(args.change, args.kind, root=wrapper.root, base=args.base,
                              model=args.model or None, effort=args.effort or None,
                              fresh=args.fresh, unvalidated=args.unvalidated)
        if line["outcome"] != "stopped":
            print(f"Review written to {line['record']}", file=sys.stderr)
        return _logged(line)
    if args.command == "resume":
        return _logged(wrapper.resume(args.change, args.seq, args.answer,
                                      split_rules(args.allow)))
    if args.command == "log":
        if args.branch:
            found = branch_decisions(read_log(path), args.branch, args.change)
            entries = found[-args.last:] if args.last > 0 else []
        else:
            entries = last_entries(path, args.last)
        for entry in entries:
            print(json.dumps(entry, ensure_ascii=False))
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
                                 sections=(parse_sections(args.sections)
                                           if args.sections is not None else None),
                                 target=args.target,
                                 branch=args.branch,
                                 resumes=args.resumes,
                                 # A branch decision is about the change whose log
                                 # holds it, which is where steps look.
                                 change=args.decided_change
                                 or (args.change if args.branch else None))
        print(json.dumps(line, ensure_ascii=False))
    return 0
