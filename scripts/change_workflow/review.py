"""A review of a change, run read-only on the review's models, which the repository's
workflow configuration names (`models.review`), and published as the change's next
numbered record.

A review runs the `change-review` skill in Codex's read-only sandbox first, and
when Codex is unavailable, on Claude with no rule that edits; either way the
reviewer cannot change what it reviews. Its final message is the review, from its
first line that is the review's title: any narration before that line is dropped,
and the transcript keeps it. The rest is checked for the review format before it
is published as the change's next numbered
`reviews/NN-<kind>.md`, the only authoritative record of its findings; the session
goes to `reviews/transcripts/NN-<kind>.log`, a transcript no review or triage step
reads. A draft the format check refuses, from a reviewer that finished, is sent
back to that reviewer's session with the problems the check found, and checked
again, as many times as the configuration's `review.format-retries` says; the
transcript keeps every attempt, and the run's line records each send-back. A run
whose output is still not a review publishes nothing, and its output is kept beside
the transcript as `NN-<kind>.rejected.md`; when the format check refused it, its
line records the reviewer's session and the problems, and the next review of the
same kind continues that session with them. A review takes its number when it
is published, so a record written beside it meanwhile is numbered first; the name is
claimed with an exclusive create, so no record is overwritten. Each published review
ends with the reviewer's session, tagged with its harness, which the next review of
the same kind continues on that harness alone; the reviewer's harness and model, and
each model passed over; and the commit it reviewed, `HEAD` when its run started. A
pre-closeout review refuses to start unless the latest validation record names
`HEAD`, or an ancestor from which `HEAD` changes only changes' records — after an
earlier pre-closeout review's triage, only those and the repository's inert paths —
with the result `passed`; the owner overrides that by `--unvalidated`, or by their
direction to the review in the workflow log, until a review of that kind has run on
it. Every review but the design's reads the change against the branch it lands on,
`--base` or the one its clone recorded, and refuses with neither. The review's
outcome is `finished`,
naming the record this run published and, as its exit, the triage of its kind, or
`stopped` with the runner's reason; an earlier record never counts.

Contract: openspec/specs/change-workflow/spec.md, CW-p2b2, CW-2nb2, CW-5e24, CW-r9d2,
CW-r8fb, CW-clhl, CW-d1sm, and CW-gqav.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Sequence

from . import config
from .common import Clock, Entry, StepError, repository_root, utc_now
from .cost import review_cost
from .find import ChangeNotFound, change_directory, is_archived, landing_branch
from .graph import ARCHIVED, KINDS, NODES, Node
from .harness import (NETWORK_RETRIES, CodexRunner, Reached, Runner, claude_command,
                      codex_command, missing_program, resume_command, run_claude, run_codex,
                      unreachable)
from .log import LOG, log_path, read_log, record_outcome, unused_direction
from .records import (TRANSCRIPTS, ChangedSince, changed_since, exempting, is_record,
                      next_number, validation_problem)
from .running import (drop_invocations, invocations_directory, kept_invocations, recorded_run,
                      runs_directory, termination_deferred, termination_ends_the_run)
from .steps import HARNESSES, STEP_TABLE, Model, StepRules, load_steps
from .stream import Stream, transcript_denials

SECTIONS = ("Summary", "Assessment", "Questions", "Findings", "Readiness")
# Each finding's fields, and the values each admits; None admits any non-empty
# value. A finding with one evident fix states `Alternatives: none — <why>`, so an
# absent field never stands for "none".
FIELDS = {
    "Lens": {"direction", "consistency", "testing", "documentation", "architecture",
             "scope", "readiness"},
    "Basis": {"specification", "guidance", "evidence", "judgement"},
    "Severity": {"blocking", "should", "minor"},
    "Evidence": None,
    "Alternatives": None,
}
_FINDING = re.compile(r"^### F\d+\b", re.M)
# A field's value is the rest of its own line: an empty field never takes the line
# after it for its value.
_FIELD = re.compile(r"^- \*\*(\w+):\*\*[ \t]*(.*?)[ \t\r]*$", re.M)
_SESSION_LINE = re.compile(r"^session id: (\S+)\s*$", re.M)
_SESSION_MARKER = re.compile(r"<!-- reviewer-session: (\S+) -->")
_REVIEWER = re.compile(r"<!-- reviewer: (\S+) (\S+)(?: (\S+))? -->")
_UNAVAILABLE_MARKER = re.compile(r"<!-- reviewer-unavailable: (\S+) (\S+): (.*?) -->")
# The reviewer was the owner's choice for the run, not the configuration's.
OVERRIDE_MARKER = "<!-- reviewer-override: owner -->"
REVIEWED_COMMIT = "<!-- reviewed-commit: {} -->"
_REVIEWED_COMMIT = re.compile(r"<!-- reviewed-commit: (\S+) -->")

# What a review on Claude is told beside its prompt: nobody can answer it, and its
# final message is the review, which the wrapper checks and publishes.
REVIEW_UNATTENDED = (
    "This review runs unattended through scripts/change-workflow: nobody can answer a "
    "permission prompt or a question in this session. Follow the change-review skill's "
    "instructions for running unattended. Your final message is the review, in the skill's "
    "format, and nothing else; the wrapper checks it and publishes it. Run one command per "
    "Bash call.")


class ReviewError(StepError):
    """The review could not be started or produced no review.

    `record` holds what the log line records of the run beside its reason: the
    models passed over, a Claude attempt's denials and transcript, and, once a
    reviewer ran, its session and what it spent.
    """

    def __init__(self, message: str, record: Entry | None = None) -> None:
        super().__init__(message)
        self.record = record or {}


def next_review_path(reviews: Path, kind: str) -> Path:
    """The next numbered review file, after every record and transcript in `reviews`.

    A failed run keeps its number through its transcript, so a later run never
    overwrites the evidence of an earlier one.
    """
    return reviews / f"{next_number(reviews):02d}-{kind}.md"


def claim_record(reviews: Path, kind: str,
                 propose: Callable[[Path, str], Path] | None = None) -> Path:
    """Create the next numbered record of `kind`, empty, and return it.

    The create is exclusive: if another writer took the proposed name in the
    meantime, the next number is tried, so no record is overwritten.
    """
    propose = propose or next_review_path
    while True:
        path = propose(reviews, kind)
        try:
            path.open("x", encoding="utf-8").close()
            return path
        except FileExistsError:
            continue


def _reviewed_head(root: Path) -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ReviewError(f"could not read HEAD, the commit under review: {exc}") from exc


def _is_title(line: str, kind: str, change: str) -> bool:
    title = line.lower()
    return title.startswith("# ") and f"{kind} review" in title and change.lower() in title


def from_title(text: str, kind: str, change: str) -> str:
    """`text` from its first line that is the title of a `kind` review of `change`.

    A reviewer may narrate before its review; that preamble is dropped here and
    kept in the transcript. Output with no such line is returned as it is, for
    `review_problems` to refuse.
    """
    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if _is_title(line.strip(), kind, change):
            return "".join(lines[index:])
    return text


def review_problems(text: str, kind: str, change: str) -> list[str]:
    """Why `text` is not a review in the `change-review` format; empty when it is."""
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return ["the output is empty"]
    if not _is_title(lines[0].strip(), kind, change):
        return [f"the first line is not the title of a {kind} review of {change}: {lines[0][:80]!r}"]
    problems = []
    positions = [text.find(f"\n## {section}\n") for section in SECTIONS]
    for section, position in zip(SECTIONS, positions):
        if position < 0:
            problems.append(f"missing section '## {section}'")
    present = [position for position in positions if position >= 0]
    if present != sorted(present):
        problems.append(f"sections are not in the order {', '.join(SECTIONS)}")
    if problems:
        return problems
    findings = text[positions[3]:positions[4]]
    starts = [match.start() for match in _FINDING.finditer(findings)] + [len(findings)]
    for start, end in zip(starts, starts[1:]):
        block = findings[start:end]
        name = block.splitlines()[0][4:].split()[0]
        fields = {key: value for key, value in _FIELD.findall(block)}
        for field, allowed in FIELDS.items():
            value = fields.get(field, "")
            if not value:
                problems.append(f"{name} has no {field}")
            elif allowed is not None and value.lower() not in allowed:
                problems.append(f"{name} has {field} {value!r}, not one of {', '.join(sorted(allowed))}")
    return problems


def checked_review(text: str, kind: str, change: str) -> tuple[str, list[str]]:
    """`text` as it would be published, from its title, and why it is not a review
    in the `change-review` format: the check a review passes before it is published,
    and the one `check review` runs for a reviewer before it answers."""
    review = from_title(text, kind, change)
    return review, review_problems(review, kind, change)


def check_review(text: str, kind: str, change: str) -> int:
    """`check review <kind> <change>`: the format check a review passes before it is
    published, run on `text` for the reviewer before it answers. Each problem goes
    to standard error, one per line, and the status is 1; with none, an OK line and
    0."""
    problems = checked_review(text, kind, change)[1]
    for problem in problems:
        print(problem, file=sys.stderr)
    if not problems:
        print(f"OK: the {kind} review of {change} passes the format check.")
    return 1 if problems else 0


def _problem_list(problems: Sequence[str]) -> str:
    return "".join(f"\n- {problem}" for problem in problems)


def correction_prompt(kind: str, change: str, problems: Sequence[str]) -> str:
    """What a reviewer whose draft the format check refused is sent back with."""
    return (f"Your {kind} review of {change} was not published: the review format check "
            f"refused it, finding:{_problem_list(problems)}\n\nWrite the complete review again, "
            "in the change-review skill's format, correcting every problem listed; your final "
            "message is the review and nothing else. Before you answer, pipe it through "
            f"`scripts/change-workflow check review {kind} {change}` until it passes.")


def refusal_prompt(kind: str, change: str, base: str | None, problems: Sequence[str]) -> str:
    """What the next review continuing a refused reviewer's session is told."""
    prompt = (f"Your last {kind} review of {change} was not published: the review format check "
              f"refused it, finding:{_problem_list(problems)}\n\nRe-read the change-review "
              "skill, which may have changed, and whatever in the change has changed since you "
              "read it. Then write the "
              f"complete {kind} review again in the skill's format, correcting every problem "
              "listed; before you answer, pipe it through "
              f"`scripts/change-workflow check review {kind} {change}` until it passes.")
    if kind != "design":
        prompt += f" Base: {base}."
    return prompt


def review_prompt(kind: str, change: str, base: str | None) -> str:
    prompt = f"Use the change-review skill. Review kind: {kind}. Change: {change}."
    if kind != "design":
        prompt += f" Base: {base}."
    return prompt


def continuation_prompt(kind: str, change: str, base: str | None, previous: str) -> str:
    prompt = (f"The change {change} has been revised since your review, {previous}. Re-read the "
              "change-review skill, which may have changed, and every file in the change, including "
              f"the triage records in reviews/. Then write a complete new {kind} review in the skill's "
              "format: say for each earlier finding, yours and any triaged beside it, whether the "
              "revision resolves it, and review the revised change as a whole.")
    if kind != "design":
        prompt += f" Base: {base}."
    return prompt


def tagged_session(marker: str) -> tuple[str, str]:
    """A `reviewer-session` marker's harness and session id.

    A marker carries its harness, `codex:<id>` or `claude:<id>`; one written
    before the tag existed is a Codex session, the only reviewer there was.
    """
    harness, separator, session = marker.partition(":")
    return (harness, session) if separator and harness in HARNESSES else ("codex", marker)


def prior_session(reviews: Path, kind: str) -> tuple[str, str, str] | None:
    """The reviewer's harness and session, and the record, of the latest published
    review of `kind`.

    Records are ordered by number, not by name: `101-` sorts before `94-` as text.
    The kind is matched whole, since one kind may end another's name: a glob for
    `*-closeout.md` also takes `NN-pre-closeout.md`.
    """
    record_of_kind = re.compile(rf"^(\d+)-{re.escape(kind)}\.md$")
    records = sorted((int(match.group(1)), entry) for entry in
                     (reviews.iterdir() if reviews.is_dir() else [])
                     if (match := record_of_kind.match(entry.name)))
    for _, record in reversed(records):
        # The last marker is the record's own; an earlier one may be quoted.
        if sessions := _SESSION_MARKER.findall(record.read_text("utf-8")):
            return (*tagged_session(sessions[-1]), record.stem)
    return None


def refused_session(reviews: Path, kind: str) -> tuple[str, str, list[str]] | None:
    """The reviewer's harness and session, and the problems the format check found,
    when the latest review run of `kind` in the change's log stopped on a draft the
    check refused; None otherwise.

    A refused draft is no record, so it is found from the run's line, which records
    the session that wrote it and why it was refused. Any later run of the kind,
    published or not, is the one the next review follows instead.
    """
    runs = [entry for entry in read_log(reviews / LOG)
            if entry.get("step") == "review" and entry.get("kind") == kind]
    if not runs:
        return None
    latest = runs[-1]
    refused, session = latest.get("refused"), latest.get("session")
    if latest.get("outcome") != "stopped" or not refused or not isinstance(session, str):
        return None
    return (*tagged_session(session), [str(problem) for problem in refused])


def review_models(models: Sequence[Model], model: str | None = None,
                  effort: str | None = None) -> tuple[Model, ...]:
    """The review's models in order, or the owner's own choice for one run.

    The configuration's models are held to the workflow's model policy as it is
    read. A model given for one run is the owner's choice for a review run by hand
    and is outside that policy on purpose: it replaces the whole list, with no
    fallback, since the owner chose it, and its harness is read from its name, a
    `claude-` model on Claude and any other on Codex. Its effort is the one given,
    else the configuration's for that harness. An effort given alone replaces every
    entry's. The orchestrating session gives neither, and the record says when
    either was given.
    """
    if model:
        harness = "claude" if model.startswith("claude-") else "codex"
        listed = next((entry.effort for entry in models if entry.harness == harness), None)
        return (Model(harness, model, effort or listed),)
    if effort:
        return tuple(Model(entry.harness, entry.model, effort) for entry in models)
    return tuple(models)


def _codex_attempt(model: Model, prompt: str, continuing: str | None, draft: Path, log: Path,
                   root: Path, runner: CodexRunner) -> tuple[int | None, Reached, str | None]:
    """One run of the review in Codex: its exit status, whether its model could not
    be reached, and its session."""
    command = (resume_command(continuing, prompt, draft, model.model, model.effort) if continuing
               else codex_command(prompt, draft, root, model.model, model.effort))
    start = log.stat().st_size if log.is_file() else 0
    try:
        with termination_ends_the_run():
            status = runner(command, log)
    except FileNotFoundError as exc:
        if not missing_program(exc, command):
            raise
        return None, ("unavailable", f"{command[0]} is not installed"), None
    said = log.read_bytes()[start:].decode("utf-8", "replace") if log.is_file() else ""
    session = _SESSION_LINE.search(said)
    # Only Codex's own error lines say why it could not run: the rest of its output
    # includes the files the reviewer read, which may mention a usage limit.
    errors = "\n".join(line for line in said.splitlines()
                       if line.lstrip().lower().startswith("error"))
    return (status, unreachable(errors) if status != 0 else None,
            session.group(1) if session else None)


def _claude_attempt(model: Model, prompt: str, continuing: str | None, draft: Path, log: Path,
                    root: Path, rules: StepRules, runner: Runner, clock: Clock,
                    echo: Callable[[str], None] | None) -> tuple[int | None, Reached, str | None]:
    """One run of the review on Claude, its final message written to `draft`, as
    Codex writes its own."""
    stream = Stream(log, log.with_suffix(".progress"), clock, echo)
    command = claude_command(prompt, rules, None, model, root=root, session=continuing,
                             system=REVIEW_UNATTENDED)
    try:
        with termination_ends_the_run():
            status = runner(command, root, stream.feed, "review")
    except FileNotFoundError as exc:
        if not missing_program(exc, command):
            raise
        return None, ("unavailable", f"{command[0]} is not installed"), None
    finally:
        stream.close()
    final = (stream.result or {}).get("result")
    if not stream.failure_text(status) and isinstance(final, str):
        draft.write_text(final, "utf-8")
    return status, unreachable(stream.failure_text(status)), stream.session


def _transcript_session(log: Path, harness: str, start: int) -> str | None:
    """The session a reviewer that never returned had reported, read from its
    attempt's output, from `start` on: an earlier attempt's session is not its own."""
    said = log.read_bytes()[start:].decode("utf-8", "replace") if log.is_file() else ""
    if harness != "claude":
        sessions = _SESSION_LINE.findall(said)
        return sessions[-1] if sessions else None
    session = None
    for line in said.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and isinstance(event.get("session_id"), str):
            session = event["session_id"]
    return session


def _unpublished_record(log: Path, reviews: Path, ran: Model | None, session: str | None,
                        passed_over: list[Entry], claude_ran: bool, spent: bool,
                        started: datetime) -> Entry:
    """What the line of a run that published nothing records beside its reason."""
    record: Entry = {"unavailable": passed_over} if passed_over else {}
    if claude_ran and log.is_file():
        record["transcript"] = log.relative_to(reviews).as_posix()
        record["denials"] = transcript_denials(log)
    if ran is not None and spent:
        tagged = f"{ran.harness}:{session}" if session else None
        if tagged:
            record["session"] = tagged
        # The reviewer ran, and what it spent is spent whatever it produced.
        record.update(review_cost(log, reviews / LOG, tagged, ran.harness, started))
    return record


def _marker_text(text: str) -> str:
    """`text` on one line, safe inside an HTML comment."""
    return " ".join(text.split()).replace("-->", "->")


def run_review(change: str, kind: str, *, base: str | None = None, model: str | None = None,
               effort: str | None = None, fresh: bool = False, root: Path | None = None,
               runner: CodexRunner = run_codex, claude: Runner = run_claude,
               unvalidated: bool = False, head: Callable[[Path], str] = _reviewed_head,
               changed_since: ChangedSince = changed_since, steps_path: Path | None = None,
               clock: Clock = utc_now,
               echo: Callable[[str], None] | None = lambda shown: print(
                   shown, file=sys.stderr, flush=True),
               interrupted: Callable[[Entry], None] = lambda _: None,
               sent_back: Callable[[list[str]], None] = lambda _: None) -> Path:
    """Run the review on the first available of its models, and publish it.

    A review continues the previous reviewer's session only on the same harness,
    since a session cannot move between harnesses; on another it starts fresh. A
    reviewer whose last run of the kind the format check refused is continued in
    preference to the last published record's, with the problems it was refused
    for. A draft the format check refuses is sent back to the reviewer's session,
    up to the configuration's `review.format-retries` times, `sent_back` given the
    problems each time; only a reviewer that finished and wrote a draft is sent
    back, never one that was unavailable, unreachable, or exited non-zero. The
    record names the reviewer's harness and model, and each model passed over. The
    change and the step table are the repository's the command runs in, unless
    `root` and `steps_path` name others. A reviewer interrupted, or whose runner
    failed, is passed on as it was raised, once `interrupted` is given what its log
    line records beside its reason.
    """
    started = clock()
    root = repository_root() if root is None else root
    steps_path = repository_root() / STEP_TABLE if steps_path is None else steps_path
    if kind not in KINDS:
        raise ReviewError(f"unknown review kind {kind!r}; expected one of {', '.join(KINDS)}")
    try:
        directory = change_directory(root, change)
    except ChangeNotFound as exc:
        raise ReviewError(str(exc)) from exc
    # A review whose node needs the archive — the closeout review, which reads the
    # specifications as the archive merged them, and the review of a merge after the
    # archive — is refused before it; the table's entry guard says which.
    if ARCHIVED in NODES[Node("review", kind)].entry and not is_archived(root, directory):
        raise ReviewError(f"{change} is not archived; a {kind} review reads the archived "
                          "change, so finish closeout, which archives it, first")
    reviews = directory / "reviews"
    try:
        configuration = config.load(root)
        models = configuration.step_models("review")
        retries = configuration.review_format_retries()
    except config.ConfigError as exc:
        raise ReviewError(str(exc)) from exc
    # Every review but the design's reads the change against the branch it lands
    # on: the one given for this run, or the one its clone recorded.
    base = base or landing_branch(root, change)
    if kind != "design" and base is None:
        raise ReviewError(f"a {kind} review reads {change} against the branch it lands on, "
                          "and none is recorded, since the change has no clone that recorded "
                          "one: give it with --base <branch> (REVIEW_BASE=<branch>)")
    reviewed = head(root)
    # The owner's direction to this review, not yet used by a run of it, overrides
    # the validation check as `--unvalidated` does: the check is the review's
    # waivable entry guard.
    directed = unused_direction(read_log(reviews / LOG))
    if directed is not None and directed["next"] == {"step": "review", "kind": kind}:
        unvalidated = True
    if kind == "pre-closeout" and not unvalidated:
        # After an earlier pre-closeout review, as the next-step computation reads
        # it, closeout is next and its own checks read the documentation again.
        earlier = any(entry.name.endswith(".triage.md")
                      for entry in reviews.glob("[0-9]*-pre-closeout*.md"))
        exempt = exempting(configuration.inert_paths) if earlier else is_record
        if problem := validation_problem(reviews, reviewed, root, changed_since, exempt=exempt):
            raise ReviewError(f"a pre-closeout review needs a passing validation of HEAD: "
                              f"{problem}; validate first, or override it: UNVALIDATED=1, or "
                              "the owner's direction to this review in the workflow log")
    steps = load_steps(steps_path)
    if "review" not in steps:
        raise ReviewError(f"{steps_path} has no review row naming the review's skill and "
                          "rules")
    transcripts = reviews / TRANSCRIPTS
    transcripts.mkdir(parents=True, exist_ok=True)
    provisional = f"pending-{kind}-{uuid.uuid4().hex[:12]}"
    log = transcripts / f"{provisional}.log"
    draft = transcripts / f"{provisional}.rejected.md"
    prior = None if fresh else prior_session(reviews, kind)
    refused = None if fresh else refused_session(reviews, kind)
    status: int | None = None
    reached: Reached = None
    session: str | None = None
    passed_over: list[Entry] = []
    ran: Model | None = None
    claude_ran = False
    finished = False
    interruption: BaseException | None = None
    sent: list[list[str]] = []
    # Where the latest attempt's output starts in the transcript.
    attempt_start = 0

    def attempt(model: Model, prompt: str, continuing: str | None
                ) -> tuple[int | None, Reached, str | None]:
        """One run of the reviewer on `model`, retried on a network error."""
        nonlocal attempt_start, claude_ran
        result: tuple[int | None, Reached, str | None] = (None, None, None)
        for _ in range(NETWORK_RETRIES + 1):
            draft.unlink(missing_ok=True)
            attempt_start = log.stat().st_size if log.is_file() else 0
            if model.harness == "codex":
                result = _codex_attempt(model, prompt, continuing, draft, log, root, runner)
            else:
                claude_ran = True
                result = _claude_attempt(model, prompt, continuing, draft, log, root,
                                         steps["review"], claude, clock, echo)
            if result[1] is None or result[1][0] != "network":
                break
        return result

    try:
        # A stop's SIGTERM ends the review as an interrupt does while a reviewer
        # runs (each attempt's runner call): the reviewer's process is ended, and
        # nothing is published.
        for ran in review_models(models, model, effort):
            if refused and refused[0] == ran.harness:
                continuing: str | None = refused[1]
                prompt = refusal_prompt(kind, change, base, refused[2])
            elif prior and prior[0] == ran.harness:
                continuing = prior[1]
                prompt = continuation_prompt(kind, change, base, prior[2])
            else:
                continuing, prompt = None, review_prompt(kind, change, base)
            status, reached, session = attempt(ran, prompt, continuing)
            if reached is None or reached[0] != "unavailable":
                break
            passed_over.append({**ran.entry(), "reason": reached[1]})
        # A reviewer that finished with a draft the format check refuses is sent
        # back to correct it, in the session that wrote it, on the same model.
        while (ran is not None and reached is None and status == 0 and session
               and draft.is_file() and len(sent) < retries):
            problems = checked_review(draft.read_text("utf-8"), kind, change)[1]
            if not problems:
                break
            sent.append(problems)
            sent_back(problems)
            status, reached, resumed = attempt(ran, correction_prompt(kind, change, problems),
                                               session)
            session = resumed or session
        finished = True
    except BaseException as exc:
        interruption = exc
    finally:
        # Numbered now, after every record written while the reviewer ran; an
        # interrupted run keeps its number too, through its transcript, and
        # leaves no empty record behind.
        output = claim_record(reviews, kind)
        if log.with_suffix(".progress").is_file():
            log.with_suffix(".progress").rename(transcripts / output.with_suffix(".progress").name)
        if log.is_file():
            log = log.rename(transcripts / output.with_suffix(".log").name)
        if draft.is_file():
            draft = draft.rename(transcripts / output.with_suffix(".rejected.md").name)
        if not finished:
            output.unlink()
    if interruption is not None:
        # The reviewer never returned its session, so it is read back from what
        # its attempt had written to the transcript. Whatever reading the record
        # meets, the interruption is passed on.
        try:
            interrupted(_unpublished_record(
                log, reviews, ran,
                _transcript_session(log, ran.harness, attempt_start) if ran else None,
                passed_over, claude_ran, ran is not None, started))
        except Exception:
            interrupted({})
        raise interruption
    text = draft.read_text("utf-8") if draft.is_file() else ""
    format_refused = False
    if reached is not None and reached[0] == "unavailable" and sent:
        problems = [f"{ran.model if ran else 'the reviewer'} became unavailable when its review "
                    f"was sent back for correction: {reached[1]}"]
    elif reached is not None and reached[0] == "unavailable":
        problems = ["no reviewer is available: " + "; ".join(
            f"{entry['harness']} {entry['model']}: {entry['reason']}" for entry in passed_over)]
    elif reached is not None:
        problems = [f"{ran.model if ran else 'the reviewer'} could not be reached after "
                    f"{NETWORK_RETRIES + 1} attempts: {reached[1]}"]
    elif status != 0:
        problems = [f"the reviewer exited {status}"]
    else:
        # The review starts at its title; a rejected run's draft keeps everything.
        text, problems = checked_review(text, kind, change)
        format_refused = bool(problems)
    if problems or ran is None:
        output.unlink()
        if not text.strip():
            draft.unlink(missing_ok=True)
        record = _unpublished_record(log, reviews, ran, session, passed_over, claude_ran,
                                     reached is None or reached[0] == "network", started)
        reason = "the reviewer produced no review: " + "; ".join(problems)
        if format_refused:
            # Marks the stop as the format check's refusal, which the next review of
            # the kind continues, in the session that wrote the draft.
            record["refused"] = problems
            reason += (f" (the format check refused it after {len(sent)} send-back"
                       f"{'s' if len(sent) != 1 else ''} for correction)" if sent
                       else " (the format check refused it)")
            if draft.is_file():
                record["rejected"] = draft.relative_to(reviews).as_posix()
                reason += f"; its draft is kept as {draft.relative_to(root)}"
            if "session" in record:
                reason += "; the next review of this kind continues the refused session"
        raise ReviewError(reason + (f"; see {log.relative_to(root)}" if log.is_file() else ""),
                          record)
    markers = [f"<!-- reviewer-session: {ran.harness}:{session} -->"] if session else []
    markers.append(f"<!-- reviewer: {ran.harness} {ran.model}"
                   + (f" {ran.effort}" if ran.effort else "") + " -->")
    if model or effort:
        markers.append(OVERRIDE_MARKER)
    markers += [f"<!-- reviewer-unavailable: {entry['harness']} {entry['model']}: "
                f"{_marker_text(entry['reason'])} -->" for entry in passed_over]
    markers.append(REVIEWED_COMMIT.format(reviewed))
    output.write_text(text.rstrip("\n") + "\n\n" + "\n".join(markers) + "\n", "utf-8")
    draft.unlink()
    return output


def review_outcome(path: Path, kind: str) -> tuple[Entry, str | None, str | None, Entry]:
    """A published review's outcome, naming the triage of its `kind` as its exit, with
    its reviewer session, its reviewed commit, and what the line records of its
    reviewer.

    Each is read back from the markers the record ends with, so the line names what
    this run published and nothing an earlier record says. A review on Claude also
    carries the run's own record of its denials, read from its transcript.
    """
    text = path.read_text("utf-8")
    # The last of each, since a review may quote an earlier record's markers; the
    # models passed over are read from the record's own closing block alone.
    sessions = _SESSION_MARKER.findall(text)
    commits = _REVIEWED_COMMIT.findall(text)
    reviewers = _REVIEWER.findall(text)
    closing = text.rstrip("\n").rsplit("\n\n", 1)[-1]
    outcome: Entry = {"outcome": "finished", "next": {"step": "triage", "kind": kind},
                      "message": f"{path.name} written; triage is next"}
    extra: Entry = {}
    if reviewers:
        harness, model, effort = reviewers[-1]
        extra = Model(harness, model, effort or None).entry()
    if OVERRIDE_MARKER in closing.splitlines():
        extra["override"] = True
    if passed_over := [{"harness": harness, "model": model, "reason": reason}
                       for harness, model, reason in _UNAVAILABLE_MARKER.findall(closing)]:
        extra["unavailable"] = passed_over
        outcome["message"] = (f"{path.name} written by {extra.get('harness', 'a reviewer')} "
                              f"{extra.get('model', '')}, "
                              + "; ".join(f"{e['harness']} {e['model']} being unavailable"
                                          for e in passed_over)
                              + "; triage is next")
    if extra.get("harness") == "claude":
        transcript = path.parent / TRANSCRIPTS / path.with_suffix(".log").name
        extra["transcript"] = transcript.relative_to(path.parent).as_posix()
        outcome["denials"] = transcript_denials(transcript)
    session = "{}:{}".format(*tagged_session(sessions[-1])) if sessions else None
    return outcome, session, commits[-1] if commits else None, extra


def _times(count: int) -> str:
    return "once" if count == 1 else f"{count} times"


def review_and_log(change: str, kind: str, *, root: Path | None = None,
                   clock: Clock = utc_now, **options: Any) -> Entry:
    """Run a review and log its outcome, recorded as in progress in the checkout
    until its line is written, since a round view moving the checkout would change
    the commit it reads.

    It is `finished` only when this run published its own record, named with the
    commit it reviewed; any other end is `stopped` with the runner's reason, so an
    earlier record of the same kind never stands in for this run's. A stop's
    SIGTERM is held for as long as the run is recorded and ends it only while its
    reviewer runs, so a review published before the signal is logged `finished`.
    """
    root = repository_root() if root is None else root
    runs = options.pop("runs", runs_directory)
    with termination_deferred(), recorded_run(runs(root), "review", change, clock=clock):
        return _review_and_log(change, kind, root=root, clock=clock, **options)


def _review_and_log(change: str, kind: str, *, root: Path, clock: Clock,
                    invocations: Callable[[Path], Path | None] = invocations_directory,
                    **options: Any) -> Entry:
    log = log_path(root, change)
    head = options.get("head", _reviewed_head)
    started = clock()
    # The owner's choice of reviewer marks every line of the run, however it ends.
    override: Entry = {"override": True} if options.get("model") or options.get("effort") else {}

    def logged(outcome: Entry, session: str | None, commit: str | None, extra: Entry) -> Entry:
        """The line, with what a reviewer on Claude invoked through `run`: a Codex
        reviewer's commands see no session of their own, so keep nothing."""
        ran = session.removeprefix("claude:") if session and session.startswith(
            "claude:") else None
        directory = invocations(root)
        invoked = kept_invocations(directory, ran, change)
        line = record_outcome(log, "review", outcome, session=session, commit=commit,
                              extra={**extra, **({"invoked": invoked} if invoked else {})},
                              clock=clock)
        drop_invocations(directory, ran, invoked)
        return line

    def stopped(reason: str, record: Entry | None = None) -> Entry:
        try:
            commit = head(root)
        except ReviewError:
            commit = None
        record = {**(record or {}), **override}
        denials = record.pop("denials", [])
        session = record.pop("session", None)
        return logged({"outcome": "stopped", "message": reason, "reason": reason,
                       "denials": denials}, session, commit, {"kind": kind, **record})

    interrupted: list[Entry] = []
    # The problems of each draft sent back for correction, recorded however the run
    # ends, so the owner is told of every send-back.
    sent: list[list[str]] = []
    try:
        path = run_review(change, kind, root=root, clock=clock,
                          interrupted=interrupted.append, sent_back=sent.append, **options)
    except ReviewError as exc:
        return stopped(str(exc), {**exc.record, **({"sent_back": sent} if sent else {})})
    except BaseException as exc:
        # A reviewer that could not start, or was interrupted, still ends with a
        # line, recording what the reviewer had reported; an interrupt is passed
        # on once it is written.
        line = stopped(f"the review did not finish: {type(exc).__name__}"
                       + (f": {exc}" if str(exc) else ""),
                       {**(interrupted[0] if interrupted else {}),
                        **({"sent_back": sent} if sent else {})})
        if not isinstance(exc, Exception):
            raise
        return line
    outcome, session, commit, reviewer = review_outcome(path, kind)
    if sent:
        reviewer["sent_back"] = sent
        outcome["message"] += (
            f" The review failed the format check and was sent back to its reviewer for "
            f"correction {_times(len(sent))} ("
            + "; ".join(", ".join(problems) for problems in sent)
            + "); the corrected review passed.")
    reviewer.update(review_cost(path.parent / TRANSCRIPTS / path.with_suffix(".log").name,
                                log, session, reviewer.get("harness"), started))
    return logged(outcome, session, commit, {"kind": kind, "record": path.name, **reviewer})
