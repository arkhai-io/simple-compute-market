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
(`log.open_log`). `start orchestrate` opens the orchestrating session on the step
table's `[orchestrator]` row. `resume` resumes a waiting run with the owner's answer;
`review` runs a review; `log` and `note` read and write the workflow log; `watch`
follows the steps as they run, and `denials` reports a run's denials. `record` is a
step's own last act when the owner runs it interactively: it records the step's
outcome, which the wrapper records for an unattended run. `convert` brings a
change's records into the log's format, shown first and written on the owner's
`--confirm`.

The others reach the module that holds them: `next` the next-step computation,
`find` a change's directory and records, `clone`, `clone where`, and `clone-remove`
a change's clone, `round-view` and `round-done` the round view, `history` the copy
of a change's history, `cost` its cost report, `push` the guarded push, `check` the
index, task-list, push, skill, and round-view checks and the graph diagram's
comparison with the graph table, and `hook post-compaction` the post-compaction
hook. `check graph` is internal: it maintains the engine's own diagram, and no
repository or runner relies on it.

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
import subprocess
import sys
from pathlib import Path
from typing import Callable, Mapping, Sequence

from . import clone as clones
from . import (cost_report, diagram, find, graph, history, hook, index, next_step, push,
               round_view, skills, tasks)
from .clone import clone_of
from .common import ORCHESTRATOR, StepError, repository_root
from .convert import convert_change
from .find import ChangeNotFound, change_directory, is_archived
from .graph import KINDS, STEPS
from .harness import UNATTENDED_RUN
from .log import (branch_decisions, direction, history_log_path, last_entries, log_path,
                  note_orchestrator, note_round, open_log, read_log, record_interactive)
from .records import git_head
from .review import DEFAULT_BASE, review_and_log
from .steps import STEP_TABLE, load_orchestrator
from .watch import denial_report, watch
from .wrapper import Wrapper

DESCRIPTION = "Run the steps of an OpenSpec change, and keep its workflow log."
# Where Claude Code gives every command it starts the id of its session. The
# variable is not documented, so a run where it is unset is refused rather than
# recorded without a session, and `--session` gives the id instead.
SESSION_ID = "CLAUDE_CODE_SESSION_ID"
ORCHESTRATE = "orchestrate"
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
                       help="print name, directory, archived, and records as JSON")
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
                       help="where a new branch starts; dev by default")
    removing = commands.add_parser(
        "clone-remove", help="delete a merged change's clone once its history is in the "
                             "workspace")
    removing.add_argument("change")
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
    commands.add_parser("push", help="push exactly HEAD to its own branch, once it may be")
    check = commands.add_parser("check", help="run one of the workflow's checks")
    checks = check.add_subparsers(dest="check", required=True)
    checks.add_parser("index", help="the change index against the change directories")
    tasks_ = checks.add_parser("tasks", help="every task under its own section's heading")
    tasks_.add_argument("change")
    checks.add_parser("push", help="whether HEAD may be pushed to its own branch")
    checks.add_parser("skills", help="every agent skill loaded from its one source")
    checks.add_parser("round-view", help="fail while a round view is open")
    checks.add_parser("graph", help="where the graph's diagram departs from the graph table")
    hook_ = commands.add_parser("hook", help="run a harness hook")
    hooks = hook_.add_subparsers(dest="hook", required=True)
    hooks.add_parser("post-compaction",
                     help="print what a session re-reads after its context is compacted")
    return parser


def _round_view_closed(root: Path) -> None:
    try:
        round_view.check(root)
    except round_view.RoundError as exc:
        raise StepError(str(exc)) from exc


def _takes(root: Path, step: str, change: str) -> None:
    """Refuse a change `step` cannot take, as its make target did before it started."""
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
    arguments = " ".join(part for part in (words, args.arguments) if part)
    if args.step == ORCHESTRATE:
        model = load_orchestrator(root / STEP_TABLE)
        command = ["claude", "--model", model.model,
                   *(["--effort", model.effort] if model.effort else []),
                   f"/change-{ORCHESTRATE} {args.change}"]
        return 0 if launch(command, root) == 0 else 1
    # The log is the record set format's only authority, so it is marked before the
    # step can record anything, its ledger lines included.
    open_log(log_path(root, args.change), args.change, args.step,
             interactive=not args.unattended)
    if not args.unattended:
        # The skill a step's session opens is named for the step, so an interactive
        # session needs no step table, as no table restricts it.
        prompt = f"/change-{args.step} {args.change}" + (f" {arguments}" if arguments else "")
        return 0 if launch(["claude", prompt], root) == 0 else 1
    line = wrapper.run(args.step, args.change, arguments=arguments,
                       sections=expand_sections(args.sections), fresh=args.fresh,
                       granted=split_rules(args.allow),
                       continuing=args.session.strip() or None)
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


class _Usage(Exception):
    """An argument argparse cannot judge alone is malformed."""


def main(argv: Sequence[str] | None = None, root: Path | None = None,
         wrapper: Wrapper | None = None, environ: Mapping[str, str] = os.environ,
         launch: Launch = _launch) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    try:
        root = repository_root() if root is None else root
        return _dispatch(args, root, wrapper or Wrapper(root=root), environ, launch)
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
    """The module command line a subcommand reaches, with the arguments that command
    line took before the command held it; None for a subcommand this module runs."""
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
        "clone-remove": (clones.main, ["remove", getattr(args, "change", "")]),
        "round-view": (round_view.main, ["start", getattr(args, "change", ""),
                                         *(["--base", args.base]
                                           if getattr(args, "base", None) else [])]),
        "round-done": (round_view.main, ["done"]),
        "history": (history.main, ["sync", getattr(args, "change", "")]),
        "cost": (cost_report.main, [getattr(args, "change", "")]),
        "push": (push.main, ["push"]),
        "hook": (hook.main, None),
    }
    if args.command in simple:
        return simple[args.command]
    if args.command == "check":
        return {"index": (index.main, None), "skills": (skills.main, None),
                "tasks": (tasks.main, [getattr(args, "change", "")]),
                "push": (push.main, ["check"]),
                "round-view": (round_view.main, ["check"]),
                "graph": (_graph, None)}[args.check]
    return None


def _graph(root: Path) -> int:
    """The diagram's comparison with the graph table, on the repository's own diagram."""
    return diagram.main(root=root)


def _dispatch(args: argparse.Namespace, root: Path, wrapper: Wrapper,
              environ: Mapping[str, str], launch: Launch) -> int:
    if args.command == "start":
        return start(args, root, wrapper, launch)
    if args.command == "clone" and args.change == "where":
        return _clone_where(args, root)
    if (reached := delegated(args)) is not None:
        main_, arguments = reached
        if args.command == "push":
            _round_view_closed(root)
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
    path = (history_log_path if args.command == "log" else log_path)(wrapper.root, args.change)
    if args.command == "record":
        line = interactive_outcome(args.change, args.step, args.outcome, args.session,
                                   environ, wrapper.root, wrapper.head)
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
                                 # A branch decision is about the change whose log
                                 # holds it, which is where steps look.
                                 change=args.decided_change
                                 or (args.change if args.branch else None))
        print(json.dumps(line, ensure_ascii=False))
    return 0
