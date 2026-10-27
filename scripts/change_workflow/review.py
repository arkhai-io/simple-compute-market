"""A review of a change, run read-only on the review row's models and published as
the change's next numbered record.

A review runs the `change-review` skill in Codex's read-only sandbox first, and
when Codex is unavailable, on Claude with no rule that edits; either way the
reviewer cannot change what it reviews. Its final message is the review. It is
checked for the review format before it is published as the change's next numbered
`reviews/NN-<kind>.md`, the only authoritative record of its findings; the session
goes to `reviews/transcripts/NN-<kind>.log`, a transcript no review or triage step
reads. A run whose output is not a review publishes nothing, and its output is kept
beside the transcript as `NN-<kind>.rejected.md`. A review takes its number when it
is published, so a record written beside it meanwhile is numbered first; the name is
claimed with an exclusive create, so no record is overwritten. Each published review
ends with the reviewer's session, tagged with its harness, which the next review of
the same kind continues on that harness alone; the reviewer's harness and model, and
each model passed over; and the commit it reviewed, `HEAD` when its run started. A
pre-closeout review refuses to start unless the latest validation record names
`HEAD`, or an ancestor from which `HEAD` changes only changes' records — after an
earlier pre-closeout review's triage, only paths under `openspec/` and `docs/` —
with the result `passed`; the owner may override that. The review's outcome is `finished`,
naming the record this run published and, as its exit, the triage of its kind, or
`stopped` with the runner's reason; an earlier record never counts.
"""

from __future__ import annotations

import re
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Callable

from change_workflow.common import KINDS, ROOT, Clock, Entry, StepError, utc_now
from change_workflow.cost import review_cost
from change_workflow.harness import (NETWORK_RETRIES, CodexRunner, Reached, Runner,
                                     claude_command, codex_command, missing_program,
                                     resume_command, run_claude, run_codex, unreachable)
from change_workflow.log import LOG, log_path, record_outcome
from change_workflow.records import (TRANSCRIPTS, ChangedSince, changed_since,
                                     is_documentation, is_record, next_number,
                                     validation_problem)
from change_workflow.running import recorded_run, runs_directory
from change_workflow.steps import HARNESSES, STEP_TABLE, Model, StepRules, load_steps
from change_workflow.stream import Stream, transcript_denials
from find_change import ChangeNotFound, change_directory, is_archived

DEFAULT_BASE = "dev"
SECTIONS = ("Summary", "Assessment", "Questions", "Findings", "Readiness")
FIELDS = {
    "Lens": {"direction", "consistency", "testing", "documentation", "architecture",
             "scope", "readiness"},
    "Basis": {"specification", "guidance", "evidence", "judgement"},
    "Severity": {"blocking", "should", "minor"},
    "Evidence": None,
}
_FINDING = re.compile(r"^### F\d+\b", re.M)
_FIELD = re.compile(r"^- \*\*(\w+):\*\*\s*(.*?)\s*$", re.M)
_SESSION_LINE = re.compile(r"^session id: (\S+)\s*$", re.M)
_SESSION_MARKER = re.compile(r"<!-- reviewer-session: (\S+) -->")
_REVIEWER = re.compile(r"<!-- reviewer: (\S+) (\S+)(?: (\S+))? -->")
_UNAVAILABLE_MARKER = re.compile(r"<!-- reviewer-unavailable: (\S+) (\S+): (.*?) -->")
# The reviewer was the owner's choice for the run, not the review row's.
OVERRIDE_MARKER = "<!-- reviewer-override: owner -->"
REVIEWED_COMMIT = "<!-- reviewed-commit: {} -->"
_REVIEWED_COMMIT = re.compile(r"<!-- reviewed-commit: (\S+) -->")

# What a review on Claude is told beside its prompt: nobody can answer it, and its
# final message is the review, which the wrapper checks and publishes.
REVIEW_UNATTENDED = (
    "This review runs unattended through scripts/run_change_step.py: nobody can answer a "
    "permission prompt or a question in this session. Follow the change-review skill's "
    "instructions for running unattended. Your final message is the review, in the skill's "
    "format, and nothing else; the wrapper checks it and publishes it. Run one command per "
    "Bash call.")


class ReviewError(StepError):
    """The review could not be started or produced no review.

    `record` holds what the log line records of the run beside its reason: the
    models passed over, and a Claude attempt's denials and transcript.
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


def review_problems(text: str, kind: str, change: str) -> list[str]:
    """Why `text` is not a review in the `change-review` format; empty when it is."""
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return ["the output is empty"]
    title = lines[0].lower()
    if not (title.startswith("# ") and f"{kind} review" in title and change.lower() in title):
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


def review_prompt(kind: str, change: str, base: str) -> str:
    prompt = f"Use the change-review skill. Review kind: {kind}. Change: {change}."
    if kind != "design":
        prompt += f" Base: {base}."
    return prompt


def continuation_prompt(kind: str, change: str, base: str, previous: str) -> str:
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


def review_models(rules: StepRules, model: str | None = None,
                  effort: str | None = None) -> tuple[Model, ...]:
    """The review's models in order, or the owner's own choice for one run.

    The step table is the workflow's policy, and the loader holds it to that. A
    model given for one run is the owner's choice for a review run by hand and is
    outside that policy on purpose, a forbidden model included: it replaces the
    whole list, with no fallback, since the owner chose it, and its harness is read
    from its name, a `claude-` model on Claude and any other on Codex. Its effort
    is the one given, else the table's for that harness. An effort given alone
    replaces every entry's. The orchestrating session gives neither, and the record
    says when either was given.
    """
    if model:
        harness = "claude" if model.startswith("claude-") else "codex"
        table = next((entry.effort for entry in rules.models if entry.harness == harness), None)
        return (Model(harness, model, effort or table),)
    if effort:
        return tuple(Model(entry.harness, entry.model, effort) for entry in rules.models)
    return rules.models


def _codex_attempt(model: Model, prompt: str, continuing: str | None, draft: Path, log: Path,
                   root: Path, runner: CodexRunner) -> tuple[int | None, Reached, str | None]:
    """One run of the review in Codex: its exit status, whether its model could not
    be reached, and its session."""
    command = (resume_command(continuing, prompt, draft, model.model, model.effort) if continuing
               else codex_command(prompt, draft, root, model.model, model.effort))
    start = log.stat().st_size if log.is_file() else 0
    try:
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
    command = claude_command(prompt, rules, None, model, session=continuing,
                             system=REVIEW_UNATTENDED)
    try:
        status = runner(command, root, stream.feed)
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


def _marker_text(text: str) -> str:
    """`text` on one line, safe inside an HTML comment."""
    return " ".join(text.split()).replace("-->", "->")


def run_review(change: str, kind: str, *, base: str = DEFAULT_BASE, model: str | None = None,
               effort: str | None = None, fresh: bool = False, root: Path = ROOT,
               runner: CodexRunner = run_codex, claude: Runner = run_claude,
               unvalidated: bool = False, head: Callable[[Path], str] = _reviewed_head,
               changed_since: ChangedSince = changed_since, steps_path: Path = STEP_TABLE,
               clock: Clock = utc_now,
               echo: Callable[[str], None] | None = lambda shown: print(
                   shown, file=sys.stderr, flush=True)) -> Path:
    """Run the review on the first available of its row's models, and publish it.

    A review continues the previous reviewer's session only on the same harness,
    since a session cannot move between harnesses; on another it starts fresh. The
    record names the reviewer's harness and model, and each model passed over.
    """
    started = clock()
    if kind not in KINDS:
        raise ReviewError(f"unknown review kind {kind!r}; expected one of {', '.join(KINDS)}")
    try:
        directory = change_directory(root, change)
    except ChangeNotFound as exc:
        raise ReviewError(str(exc)) from exc
    # The closeout review reads the specifications as the archive merged them;
    # before the archive there is only the delta to read.
    if kind == "closeout" and not is_archived(root, directory):
        raise ReviewError(f"{change} is not archived; a closeout review reads the archived "
                          "change, so finish closeout, which archives it, first")
    reviews = directory / "reviews"
    reviewed = head(root)
    if kind == "pre-closeout" and not unvalidated:
        # After an earlier pre-closeout review, as the next-step computation reads
        # it, closeout is next and its own checks read the documentation again.
        earlier = any(entry.name.endswith(".triage.md")
                      for entry in reviews.glob("[0-9]*-pre-closeout*.md"))
        if problem := validation_problem(reviews, reviewed, root, changed_since,
                                         exempt=is_documentation if earlier else is_record):
            raise ReviewError(f"a pre-closeout review needs a passing validation of HEAD: "
                              f"{problem}; validate first, or set UNVALIDATED=1 to override")
    steps = load_steps(steps_path)
    if "review" not in steps:
        raise ReviewError(f"{steps_path} has no review row naming the review's models")
    transcripts = reviews / TRANSCRIPTS
    transcripts.mkdir(parents=True, exist_ok=True)
    provisional = f"pending-{kind}-{uuid.uuid4().hex[:12]}"
    log = transcripts / f"{provisional}.log"
    draft = transcripts / f"{provisional}.rejected.md"
    prior = None if fresh else prior_session(reviews, kind)
    status: int | None = None
    reached: Reached = None
    session: str | None = None
    passed_over: list[Entry] = []
    ran: Model | None = None
    claude_ran = False
    finished = False
    try:
        for ran in review_models(steps["review"], model, effort):
            continuing = prior[1] if prior and prior[0] == ran.harness else None
            prompt = (continuation_prompt(kind, change, base, prior[2]) if prior and continuing
                      else review_prompt(kind, change, base))
            for attempt in range(NETWORK_RETRIES + 1):
                draft.unlink(missing_ok=True)
                if ran.harness == "codex":
                    status, reached, session = _codex_attempt(ran, prompt, continuing, draft, log,
                                                              root, runner)
                else:
                    claude_ran = True
                    status, reached, session = _claude_attempt(
                        ran, prompt, continuing, draft, log, root, steps["review"], claude,
                        clock, echo)
                if reached is None or reached[0] != "network":
                    break
            if reached is None or reached[0] != "unavailable":
                break
            passed_over.append({**ran.entry(), "reason": reached[1]})
        finished = True
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
    text = draft.read_text("utf-8") if draft.is_file() else ""
    if reached is not None and reached[0] == "unavailable":
        problems = ["no reviewer is available: " + "; ".join(
            f"{entry['harness']} {entry['model']}: {entry['reason']}" for entry in passed_over)]
    elif reached is not None:
        problems = [f"{ran.model if ran else 'the reviewer'} could not be reached after "
                    f"{NETWORK_RETRIES + 1} attempts: {reached[1]}"]
    elif status != 0:
        problems = [f"the reviewer exited {status}"]
    else:
        problems = review_problems(text, kind, change)
    if problems or ran is None:
        output.unlink()
        if not text.strip():
            draft.unlink(missing_ok=True)
        record: Entry = {"unavailable": passed_over} if passed_over else {}
        if claude_ran and log.is_file():
            record["transcript"] = log.relative_to(reviews).as_posix()
            record["denials"] = transcript_denials(log)
        if ran is not None and (reached is None or reached[0] == "network"):
            # The reviewer ran, and what it spent is spent whatever it produced.
            record.update(review_cost(log, reviews / LOG,
                                      f"{ran.harness}:{session}" if session else None,
                                      ran.harness, started))
        raise ReviewError("the reviewer produced no review: " + "; ".join(problems)
                          + (f"; see {log.relative_to(root)}" if log.is_file() else ""),
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


def review_and_log(change: str, kind: str, *, root: Path = ROOT, clock: Clock = utc_now,
                   **options: Any) -> Entry:
    """Run a review and log its outcome, recorded as in progress in the checkout
    until its line is written, since a round view moving the checkout would change
    the commit it reads.

    It is `finished` only when this run published its own record, named with the
    commit it reviewed; any other end is `stopped` with the runner's reason, so an
    earlier record of the same kind never stands in for this run's.
    """
    runs = options.pop("runs", runs_directory)
    with recorded_run(runs(root), "review", change, clock=clock):
        return _review_and_log(change, kind, root=root, clock=clock, **options)


def _review_and_log(change: str, kind: str, *, root: Path, clock: Clock,
                    **options: Any) -> Entry:
    log = log_path(root, change)
    head = options.get("head", _reviewed_head)
    started = clock()
    # The owner's choice of reviewer marks every line of the run, however it ends.
    override: Entry = {"override": True} if options.get("model") or options.get("effort") else {}

    def stopped(reason: str, record: Entry | None = None) -> Entry:
        try:
            commit = head(root)
        except ReviewError:
            commit = None
        record = {**(record or {}), **override}
        denials = record.pop("denials", [])
        return record_outcome(log, "review", {"outcome": "stopped", "message": reason,
                                              "reason": reason, "denials": denials},
                              session=None, commit=commit, extra={"kind": kind, **record},
                              clock=clock)

    try:
        path = run_review(change, kind, root=root, clock=clock, **options)
    except ReviewError as exc:
        return stopped(str(exc), exc.record)
    except BaseException as exc:
        # A reviewer that could not start, or was interrupted, still ends with a
        # line; an interrupt is passed on once it is written.
        line = stopped(f"the review did not finish: {type(exc).__name__}"
                       + (f": {exc}" if str(exc) else ""))
        if not isinstance(exc, Exception):
            raise
        return line
    outcome, session, commit, reviewer = review_outcome(path, kind)
    reviewer.update(review_cost(path.parent / TRANSCRIPTS / path.with_suffix(".log").name,
                                log, session, reviewer.get("harness"), started))
    return record_outcome(log, "review", outcome, session=session, commit=commit,
                          extra={"kind": kind, "record": path.name, **reviewer}, clock=clock)
