#!/usr/bin/env python3
"""Run a step of an OpenSpec change unattended, and keep the change's workflow log.

`run` starts the step's skill as a headless Claude Code session (`claude -p`),
held to the step's permissions in `.claude/change-steps.toml` under the `dontAsk`
permission mode, told to end its turn with an outcome matching the outcome schema,
and streaming its events. `resume` continues the session of a waiting run, named
by its line in the log, with the owner's answer, optionally granting a rule for
that one run; with steps run side by side the last run is not necessarily the one
that asked, so the run is never inferred. Either way the run's event
stream is kept as `reviews/transcripts/NN-<step>.jsonl`, with a progress file of
its tool calls beside it, and its outcome is appended to the workflow log. A run
that crashes, ends without an outcome, or ends with one the schema rejects is
logged `stopped` by the wrapper itself. Every line's `denials` are the run's own
record of denied tools, never the step's account of them: each denial as the
harness lists it, with the harness's reason for it, gathered over every turn of
the run, since a background task finishing can wake a session for another turn
after its first `result` event. A step denied a tool ends `stopped` only when it
cannot go on without it; one that went on is logged with the outcome it ended
with, and the orchestrating session reads the recorded denials (`denials`) before
the change moves on.

A review runs in Codex instead, through `review`: the `change-review` skill in a
read-only sandbox, so the reviewer cannot change what it reviews. Its final
message is the review. It is checked for the review format before it is published
as the change's next numbered `reviews/NN-<kind>.md`, the only authoritative record
of its findings; the session goes to `reviews/transcripts/NN-<kind>.log`, a
transcript no review or triage step reads. A run whose output is not a review
publishes nothing, and its output is kept beside the transcript as
`NN-<kind>.rejected.md`. A review takes its number when it is published, so a
record written beside it meanwhile is numbered first; the name is claimed with an
exclusive create, so no record is overwritten. Each published review ends with the
reviewer's session, which the next review of the same kind continues, and the
commit it reviewed, `HEAD` when its run started. A pre-closeout review refuses to
start unless the latest validation record names `HEAD`, or an ancestor from which
`HEAD` changes only changes' records, with the result `passed`; the owner may
override that. The review's outcome is `finished`, naming the record this run
published, or `stopped` with the runner's reason; an earlier record never counts.

A step's outcome conforms to `.agents/change-outcome.schema.json`: `finished`,
`question`, `returned`, `blocked`, or `stopped`, each with the step's `message` to
the owner. `record_outcome` appends one as a line of the change's
`reviews/workflow.jsonl`, with a sequence number, the time, the step, and the
run's session and commit. `note` appends the orchestrating session's own lines: a
`round` line recording the implementation round the owner agreed, and an
`orchestrator` line recording a decision — the orchestrating session's own
routing or recovery, or the owner's, such as a confirmed return or a repeat
review — naming the run whose denials it reads, the run it resolves, and the
step it directs next, so the next-step computation routes on it. Reading and
resolving are distinct because a run can be denied a call and still end with a
question or a proposed return: its denials are read first, and its outcome is
answered or decided after. This module is the log's only writer.

The log holds only what the change's files cannot: session ids, the owner's round
agreements, and the last outcome. Where the log and the files disagree, the files
win. It lives in the change's untracked `reviews/` directory and moves with the
change when it is archived.

Contract: openspec/specs/change-workflow/spec.md, "Unattended step runs end with a
structured outcome".
"""

from __future__ import annotations

import argparse
import fcntl
import json
import re
import subprocess
import sys
import time
import tomllib
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from find_change import ChangeNotFound, change_directory, is_archived  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / ".agents" / "change-outcome.schema.json"
STEP_TABLE = ROOT / ".claude" / "change-steps.toml"
CHANGES = Path("openspec/changes")
LOG = "workflow.jsonl"
TRANSCRIPTS = "transcripts"
STEPS = ("design", "plan", "review", "triage", "implement", "validate", "closeout",
         "archive-cleanup")
ORCHESTRATOR = "orchestrator"

Clock = Callable[[], datetime]
Entry = dict[str, Any]
# Runs a command in a directory, handing each line of its merged output to the
# callback as it arrives, and returns its exit status.
Runner = Callable[[Sequence[str], Path, Callable[[str], None]], int]

# What an unattended run is told beside its skill: that nobody can answer it, and
# how it ends a turn.
UNATTENDED = (
    "This step runs unattended through scripts/run_change_step.py: nobody can answer a "
    "permission prompt or a question in this session. Follow your skill's instructions for "
    "running unattended. End every turn with an outcome matching the JSON schema you were "
    "given. Where your skill says to stop and ask the owner, end the turn with a `question` "
    "outcome; the owner's answer resumes this session. Run one command per Bash call: a "
    "chained command runs only when every command in it is allowed. If a chained command is "
    "denied, run its commands one call at a time. If a single command or any other tool call "
    "is denied, finish every part of the work that does not depend on it; if the step cannot "
    "complete without that call, end with a `stopped` outcome whose `reason` names that exact "
    "call, and otherwise go on and end as the step ends, since the denial is recorded on the "
    "outcome whatever it is. One denied call is not a denied tool. Never do by another tool "
    "what a denied call would have done, and never ask about a denial as a question.")


class StepError(RuntimeError):
    """The step could not be run or recorded."""


class LogError(StepError):
    """The workflow log cannot be read."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def load_schema(path: Path = SCHEMA) -> dict[str, Any]:
    return json.loads(path.read_text("utf-8"))


_TYPES: dict[str, Callable[[Any], bool]] = {
    "object": lambda value: isinstance(value, dict),
    "array": lambda value: isinstance(value, list),
    "string": lambda value: isinstance(value, str),
    # JSON has no separate boolean among numbers; Python's bool is an int.
    "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
}
# Keywords that describe a schema rather than constrain a value.
_ANNOTATIONS = {"$schema", "title", "description"}


def schema_problems(value: Any, schema: dict[str, Any], path: str = "outcome") -> list[str]:
    """Why `value` does not conform to `schema`; empty when it does.

    Only the keywords the outcome schema uses are understood. Any other keyword
    raises, so a schema edit that this check cannot enforce fails loudly instead of
    being ignored: the scripts run on the standard library alone, without a JSON
    Schema package.
    """
    unknown = set(schema) - _ANNOTATIONS - {
        "type", "properties", "required", "additionalProperties", "enum", "const",
        "minLength", "items", "allOf", "if", "then"}
    if unknown:
        raise StepError(f"the outcome schema uses {', '.join(sorted(unknown))}, "
                        "which this check does not enforce")
    if "type" in schema and not (isinstance(schema["type"], str) and schema["type"] in _TYPES):
        raise StepError(f"the outcome schema uses type {schema['type']!r}, "
                        "which this check does not enforce")
    if "type" in schema and not _TYPES[schema["type"]](value):
        return [f"{path} is not of type {schema['type']}"]
    problems: list[str] = []
    if "const" in schema and value != schema["const"]:
        problems.append(f"{path} is {value!r}, not {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        problems.append(f"{path} is {value!r}, not one of {', '.join(map(str, schema['enum']))}")
    if "minLength" in schema and isinstance(value, str) and len(value) < schema["minLength"]:
        problems.append(f"{path} is shorter than {schema['minLength']}")
    if isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value):
            problems += schema_problems(item, schema["items"], f"{path}[{index}]")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        problems += [f"{path} has no {key}" for key in schema.get("required", [])
                     if key not in value]
        if schema.get("additionalProperties") is False:
            problems += [f"{path} has {key}, which the schema does not define"
                         for key in value if key not in properties]
        for key, item in value.items():
            if key in properties:
                problems += schema_problems(item, properties[key], f"{path}.{key}")
    for part in schema.get("allOf", []):
        problems += schema_problems(value, part, path)
    if "if" in schema and not schema_problems(value, schema["if"], path):
        problems += schema_problems(value, schema.get("then", {}), path)
    return problems


def harness_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """The outcome schema as Claude Code is given it through `--json-schema`.

    Claude Code makes the schema a tool's input schema, and the API refuses a top-level
    `allOf`, `anyOf`, or `oneOf` there, so the per-outcome requirements are left out:
    the property descriptions still name them, and the wrapper checks the full schema
    when the run ends, logging an outcome that misses one as `stopped`.
    """
    return {key: value for key, value in schema.items() if key not in ("allOf", "anyOf", "oneOf")}


def outcome_problems(outcome: Any, schema: dict[str, Any] | None = None) -> list[str]:
    """Why `outcome` is not a step outcome; empty when it is."""
    return schema_problems(outcome, schema if schema is not None else load_schema())


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


def append_entry(path: Path, entry: Entry, clock: Clock = _utc_now) -> Entry:
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
                   schema: dict[str, Any] | None = None, clock: Clock = _utc_now) -> Entry:
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
               clock: Clock = _utc_now) -> Entry:
    """Record the implementation round the owner agreed: its sessions, each a list
    of the sections that session implements, in order.

    `after` is the highest number among the records and transcripts in `reviews/`
    before the round, so the round's own records — the owner's notes, its
    validation and review, their triage — are those numbered above it. It is read
    from `reviews/` when the round is agreed before it starts, and given for a
    round recorded after the fact, whose records already exist.
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
                               else after}, clock)


def note_orchestrator(path: Path, decision: str, reason: str, *, by: str = ORCHESTRATOR,
                      resolves: int | None = None, reads: int | None = None,
                      next_step: str | None = None, kind: str | None = None,
                      clock: Clock = _utc_now) -> Entry:
    """Record a decision: the orchestrating session's own routing or recovery, or
    the owner's, relayed by it.

    `reads` names the run (its `seq`) whose recorded denials the decision has
    read against the step's rules; `resolves` names the run the decision
    settles, so that run alone stops waiting on the owner: a decision clears
    nothing it does not name. They differ because a run denied a call can still
    end with a question or a proposed return, whose denials are read before the
    question is answered or the return decided; a reading alone leaves such an
    outcome waiting, and a stopped run is read and resolved by one line.
    `next_step` names the step the decision directs — the step a confirmed
    return goes to, the review the owner asked for again — which the next-step
    computation names until that step has run. A directed review takes its
    `kind`, without which the computation could not name one; a directed step
    of any other kind is a confirmed return, so it resolves the returned run,
    which would otherwise wait ahead of the directive. A repeat review after a
    failed gate names no run: a failed gate is a state of the triage file.
    """
    if not decision or not reason:
        raise StepError("an orchestrator line names its decision and its reason")
    if not by:
        raise StepError("an orchestrator line names who decided")
    line: Entry = {"step": ORCHESTRATOR, "outcome": ORCHESTRATOR, "by": by,
                   "decision": decision, "reason": reason}
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
        if next_step != "review" and resolves is None:
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


@dataclass(frozen=True)
class StepRules:
    """A step's skill and the permission rules an unattended run of it is held to."""

    skill: str
    allow: tuple[str, ...]
    deny: tuple[str, ...]
    # The step whose last session this step resumes, rather than starting fresh.
    resume_from: str | None = None


def load_steps(path: Path = STEP_TABLE) -> dict[str, StepRules]:
    """Each step's rules, `common`'s added to its own."""
    try:
        table = tomllib.loads(path.read_text("utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise StepError(f"cannot read the step table {path}: {exc}") from exc
    if unknown := set(table) - {"common", "steps"}:
        raise StepError(f"{path} has unknown tables: {', '.join(sorted(unknown))}")
    common = table.get("common", {})
    if set(common) - {"allow", "deny"}:
        raise StepError(f"{path}'s common row takes only allow and deny")
    steps = {}
    for name, row in table.get("steps", {}).items():
        if name not in STEPS:
            raise StepError(f"{path} names an unknown step {name!r}")
        if "skill" not in row or set(row) - {"skill", "allow", "deny", "resume_from"}:
            raise StepError(f"{path}'s {name} row needs a skill and takes only skill, "
                            "allow, deny, and resume_from")
        steps[name] = StepRules(
            skill=row["skill"],
            allow=(*_rules(path, common, "allow"), *_rules(path, row, "allow")),
            deny=(*_rules(path, common, "deny"), *_rules(path, row, "deny")),
            resume_from=row.get("resume_from"))
    for name, rules in steps.items():
        if rules.resume_from is not None and rules.resume_from not in steps:
            raise StepError(f"{path}'s {name} row resumes {rules.resume_from!r}, which has "
                            "no row")
    return steps


def _rules(path: Path, row: dict[str, Any], key: str) -> tuple[str, ...]:
    # A string here would be spread into characters, silently dropping its rule.
    rules = row.get(key, [])
    if not isinstance(rules, list) or not all(isinstance(rule, str) and rule for rule in rules):
        raise StepError(f"{path}: {key} must be a list of rules")
    return tuple(rules)


_NUMBERED = re.compile(r"^(\d+)-")


def next_number(reviews: Path) -> int:
    """The number after every numbered record and transcript in `reviews`."""
    entries = [entry for directory in (reviews, reviews / TRANSCRIPTS) if directory.is_dir()
               for entry in directory.iterdir()]
    return max((int(match.group(1)) for entry in entries
                if (match := _NUMBERED.match(entry.name))), default=0) + 1


def next_transcript(reviews: Path, step: str) -> Path:
    """Claim `reviews/transcripts/NN-<step>.jsonl`, numbered after every record.

    The number follows every numbered file in `reviews/` and its transcripts, as a
    review record's does, and the create is exclusive, so no run overwrites
    another's transcript.
    """
    transcripts = reviews / TRANSCRIPTS
    transcripts.mkdir(parents=True, exist_ok=True)
    while True:
        path = transcripts / f"{next_number(reviews):02d}-{step}.jsonl"
        try:
            path.open("x", encoding="utf-8").close()
            return path
        except FileExistsError:
            continue


def claude_command(prompt: str, rules: StepRules, schema: dict[str, Any], *,
                   session: str | None = None, granted: Sequence[str] = ()) -> list[str]:
    """The headless Claude Code command for one turn of a step.

    The prompt comes straight after `-p`: the rule lists are variadic, and would
    take a prompt placed after them as one more rule. Only the project's settings
    are loaded, not the owner's user or local settings with their allow rules.
    """
    command = ["claude", "-p", prompt, "--permission-mode", "dontAsk",
               "--setting-sources", "project",
               "--output-format", "stream-json", "--verbose",
               "--json-schema", json.dumps(harness_schema(schema)),
               "--append-system-prompt", UNATTENDED]
    if session:
        command += ["--resume", session]
    allow = [*rules.allow, *granted]
    if allow:
        command += ["--allowedTools", *allow]
    if rules.deny:
        command += ["--disallowedTools", *rules.deny]
    return command


def step_prompt(rules: StepRules, change: str, arguments: str = "") -> str:
    return f"/{rules.skill} {change}" + (f" {arguments}" if arguments else "")


def _tool_summary(tool: dict[str, Any]) -> str:
    return _call_summary(tool.get("input"))


def _call_summary(given: Any) -> str:
    """One line for a tool call's input: the field that says what it did."""
    given = given if isinstance(given, dict) else {}
    for key in ("command", "file_path", "path", "pattern", "skill", "description", "prompt"):
        if isinstance(given.get(key), str):
            summary = " ".join(given[key].split())
            return summary if len(summary) <= 120 else summary[:119] + "…"
    return ""


class Stream:
    """The run's event stream: written whole to the transcript, its tool calls to
    the progress file, and read for the run's session, its final result, and every
    tool call it was denied.

    A run has one `result` event per turn, and a background task finishing can
    wake the session for another turn, so the last result is the run's end but
    its `permission_denials` are only its own turn's; the denials are gathered
    from every result, keyed by the call, and each takes the reason the harness
    gave in its `permission_denied` event, which says whether the call lacked an
    allow rule or met a deny rule.
    """

    def __init__(self, transcript: Path, progress: Path, clock: Clock = _utc_now,
                 echo: Callable[[str], None] | None = None) -> None:
        self.transcript = transcript
        self.progress = progress
        self.clock = clock
        self.echo = echo
        self.session: str | None = None
        self.result: dict[str, Any] | None = None
        self._denials: dict[str, dict[str, Any]] = {}
        self._reasons: dict[str, str] = {}

    @property
    def denials(self) -> list[dict[str, Any]]:
        """Every denial the run recorded, in order, each with the harness's reason."""
        return [{**denial, **({"reason": self._reasons[key]} if key in self._reasons else {})}
                for key, denial in self._denials.items()]

    def feed(self, line: str) -> None:
        with self.transcript.open("a", encoding="utf-8") as stream:
            stream.write(line if line.endswith("\n") else line + "\n")
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return
        if not isinstance(event, dict):
            return
        if isinstance(event.get("session_id"), str):
            self.session = event["session_id"]
        if event.get("type") == "result":
            self.result = event
            denials = event.get("permission_denials")
            for denial in denials if isinstance(denials, list) else []:
                if isinstance(denial, dict):
                    self._denials.setdefault(_denial_key(denial), denial)
        if event.get("type") == "system" and event.get("subtype") == "permission_denied":
            if isinstance(event.get("tool_use_id"), str) and isinstance(
                    event.get("decision_reason_type"), str):
                self._reasons[event["tool_use_id"]] = event["decision_reason_type"]
        message = event.get("message") if event.get("type") == "assistant" else None
        content = message.get("content") if isinstance(message, dict) else None
        for item in content if isinstance(content, list) else []:
            if isinstance(item, dict) and item.get("type") == "tool_use":
                at = self.clock().astimezone(timezone.utc).strftime("%H:%M:%SZ")
                shown = f"{at} {item.get('name', '?')} {_tool_summary(item)}".rstrip()
                with self.progress.open("a", encoding="utf-8") as stream:
                    stream.write(shown + "\n")
                if self.echo:
                    self.echo(shown)


def _denial_key(denial: dict[str, Any]) -> str:
    """What identifies a denied call: its tool use id, or the call itself."""
    if isinstance(denial.get("tool_use_id"), str):
        return denial["tool_use_id"]
    return json.dumps(denial, sort_keys=True, ensure_ascii=False)


def run_outcome(status: int, result: dict[str, Any] | None, schema: dict[str, Any],
                denials: Sequence[dict[str, Any]] = ()) -> Entry:
    """The outcome to log for a run that exited with `status` and ended with `result`,
    having been denied `denials`.

    The step's own outcome when it gave a valid one; otherwise a `stopped` the
    wrapper writes, its message the reason. Every outcome carries the run's own
    record of its denials, whatever the step said: a step ends `stopped` when it
    cannot go on without a denied tool, and one that went on is logged as it
    ended, its denials there for the orchestrating session to read.
    """
    denials = list(denials)
    outcome = (result or {}).get("structured_output")
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
    else:
        return {**outcome, "denials": denials}
    return {"outcome": "stopped", "message": reason, "reason": reason, "denials": denials}


def _run_claude(command: Sequence[str], cwd: Path, feed: Callable[[str], None]) -> int:
    process = subprocess.Popen(list(command), cwd=cwd, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, encoding="utf-8", errors="replace")
    assert process.stdout is not None
    try:
        for line in process.stdout:
            feed(line)
        return process.wait()
    finally:
        # The wrapper records the run as ended, so a session it can no longer
        # watch must not go on acting.
        if process.poll() is None:
            process.kill()
            process.wait()


def _git_head(root: Path) -> str | None:
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
                          text=True)
    return head.stdout.strip() if head.returncode == 0 else None


def newest_progress(reviews: Path) -> Path | None:
    """The progress file a step of the change wrote to last, if any."""
    files = list((reviews / TRANSCRIPTS).glob("*.progress"))
    return max(files, key=lambda f: f.stat().st_mtime_ns) if files else None


def watch(reviews: Path, echo: Callable[[str], None] = print,
          sleep: Callable[[float], None] = time.sleep, polls: int | None = None,
          backlog: int = 10) -> None:
    """Follow the change's newest progress file, moving to each newer one as a step starts.

    The file being followed when watching begins shows only its last `backlog`
    lines; a file that appears later is shown from its start, since it is a new
    run. `polls` bounds the loop for tests; the command runs until interrupted.
    """
    current: Path | None = None
    shown = 0
    polled = 0
    while polls is None or polled < polls:
        polled += 1
        newest = newest_progress(reviews)
        if newest is not None and newest != current:
            lines = newest.read_text("utf-8").splitlines()
            shown = max(len(lines) - backlog, 0) if current is None else 0
            current = newest
            echo(f"== {newest.name}")
        if current is not None:
            lines = current.read_text("utf-8").splitlines()
            for line in lines[shown:]:
                echo(line)
            shown = len(lines)
        sleep(1.0)


def denial_report(reviews: Path, entry: Entry) -> list[str]:
    """Each denial on a run's log line, with the tool calls the run made after it.

    Read from the run's transcript, for the orchestrating session's reading of a
    denial: the call as the harness recorded it, the harness's reason, and what
    the run did next, which shows whether a later call did the denied call's work
    by another means. The step's message is never consulted.
    """
    denials = entry.get("denials")
    denials = [d for d in denials if isinstance(d, dict)] if isinstance(denials, list) else []
    if not denials:
        return [f"seq {entry.get('seq')}: the {entry.get('step')} run recorded no denial"]
    transcript = entry.get("transcript")
    if not isinstance(transcript, str) or not transcript:
        raise StepError(f"seq {entry.get('seq')} is a {entry.get('step')} line with no "
                        "transcript to read")
    path = reviews / transcript
    if not path.is_file():
        raise StepError(f"seq {entry.get('seq')}'s transcript {transcript} is not in {reviews}")
    calls: list[tuple[Any, str]] = []
    for line in path.read_text("utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict) or event.get("type") != "assistant":
            continue
        message = event.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        for item in content if isinstance(content, list) else []:
            if isinstance(item, dict) and item.get("type") == "tool_use":
                calls.append((item.get("id"),
                              f"{item.get('name', '?')} {_tool_summary(item)}".rstrip()))
    shown: list[str] = []
    for denial in denials:
        call = f"{denial.get('tool_name', '?')} {_call_summary(denial.get('tool_input'))}".rstrip()
        reason = denial.get("reason")
        shown.append(f"denied: {call} ({reason if reason else 'reason not recorded'})")
        key = denial.get("tool_use_id")
        index = next((i for i, (id_, _) in enumerate(calls) if key is not None and id_ == key),
                     None)
        if index is None:
            shown.append("  the call is not in the transcript; every call of the run:")
            after = calls
        elif not calls[index + 1:]:
            shown.append("  no call after it")
            after = []
        else:
            shown.append("  calls after it:")
            after = calls[index + 1:]
        shown += [f"    {text}" for _, text in after]
    return shown


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


@dataclass
class Wrapper:
    """Runs steps of changes under one repository root, through injected seams."""

    root: Path = ROOT
    runner: Runner = _run_claude
    head: Callable[[Path], str | None] = _git_head
    clock: Clock = _utc_now
    # Progress goes to stderr: stdout carries only the outcome line a caller parses.
    echo: Callable[[str], None] | None = lambda shown: print(shown, file=sys.stderr, flush=True)
    steps_path: Path = STEP_TABLE
    schema_path: Path = SCHEMA

    def run(self, step: str, change: str, *, arguments: str = "",
            sections: Sequence[int | str] | None = None, fresh: bool = False) -> Entry:
        """Run `step`: a fresh session, or, for a step that resumes another's, the
        latest session of either, unless `fresh`."""
        steps = load_steps(self.steps_path)
        if step not in steps:
            raise StepError(f"{step!r} has no unattended Claude Code run; expected one of "
                            + ", ".join(steps))
        rules = steps[step]
        log = log_path(self.root, change)
        if sections and step != "implement":
            raise StepError("only implementation takes sections")
        session = None
        if rules.resume_from and not fresh:
            previous = last_run(log, [rules.resume_from, step])
            if previous is not None and not previous.get("session"):
                raise StepError(f"{change}'s last {previous['step']} run (seq "
                                f"{previous['seq']}) recorded no session to resume; run "
                                f"{step} with --fresh, or {previous['step']} again")
            session = previous["session"] if previous else None
        extra = {"sections": list(sections)} if sections else {}
        return self._turn(step, rules, log, step_prompt(rules, change, arguments),
                          session=session, extra=extra)

    def resume(self, change: str, seq: int, answer: str, granted: Sequence[str] = ()) -> Entry:
        """Resume the step session of the run at `seq` with the owner's answer.

        The run is named, never inferred: with steps run side by side, the log's
        last run is not necessarily the one that asked. It must be waiting — its
        step's latest run, ended with a question, or stopped with no decision
        line resolving it — since an answer to any other run has nowhere to go.

        A granted rule applies to this run alone: it is passed on this command line
        and noted on this run's log line, never added to the step table, so the
        step's next run is held to its table again.
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
        if step not in steps:
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
        return self._turn(step, steps[step], log, f"The owner's answer: {answer}",
                          session=previous["session"], granted=granted, extra=extra)

    def _turn(self, step: str, rules: StepRules, log: Path, prompt: str, *,
              session: str | None, granted: Sequence[str] = (),
              extra: Entry | None = None) -> Entry:
        schema = load_schema(self.schema_path)
        transcript = next_transcript(log.parent, step)
        progress = transcript.with_suffix(".progress")
        stream = Stream(transcript, progress, self.clock, self.echo)
        command = claude_command(prompt, rules, schema, session=session, granted=granted)
        failure: BaseException | None = None
        try:
            status: int | None = self.runner(command, self.root, stream.feed)
            outcome = run_outcome(status, stream.result, schema, stream.denials)
        except BaseException as exc:
            # A run that could not start, or was interrupted, still ends with a
            # line, so the log never shows its previous outcome as the latest.
            failure, status = exc, None
            reason = (f"the run did not finish: {type(exc).__name__}"
                      + (f": {exc}" if str(exc) else ""))
            outcome = {"outcome": "stopped", "message": reason, "reason": reason,
                       "denials": stream.denials}
        extra = {**(extra or {}), "exit_status": status,
                 "transcript": transcript.relative_to(log.parent).as_posix()}
        line = record_outcome(log, step, outcome, session=stream.session or session,
                              commit=self.head(self.root), extra=extra, schema=schema,
                              clock=self.clock)
        if failure is not None and not isinstance(failure, Exception):
            raise failure
        return line


KINDS = ("design", "implementation", "pre-closeout", "closeout")
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
REVIEWED_COMMIT = "<!-- reviewed-commit: {} -->"
_REVIEWED_COMMIT = re.compile(r"<!-- reviewed-commit: (\S+) -->")
_VALIDATION_COMMIT = re.compile(r"^- \*\*Commit:\*\*\s*([0-9a-f]{7,40})\b", re.M)
_VALIDATION_RESULT = re.compile(r"^- \*\*Result:\*\*\s*(\w+)", re.M)

# Runs a Codex command, writing its output to the transcript, and returns its exit
# status.
CodexRunner = Callable[[Sequence[str], Path], int]


class ReviewError(StepError):
    """The review could not be started or produced no review."""


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


# The paths a commit changes since an earlier one, or None when that commit is not
# an ancestor of it.
ChangedSince = Callable[[Path, str, str], list[str] | None]


def _changed_since(root: Path, commit: str, head: str) -> list[str] | None:
    if subprocess.run(["git", "merge-base", "--is-ancestor", commit, head], cwd=root,
                      capture_output=True).returncode != 0:
        return None
    # Without --no-renames a file moved under a change's records would be listed
    # only at its new path, hiding the code it removed.
    diff = subprocess.run(["git", "diff", "--name-only", "--no-renames", "-z", commit, head],
                          cwd=root, capture_output=True, text=True)
    return [path for path in diff.stdout.split("\0") if path] if diff.returncode == 0 else None


# A change's records: its ledger and its reviews, whether the change is active or
# under its dated archive directory. A closeout triage edits an archived change's
# ledger, so the archive must count, or that edit would read as a fix.
_RECORD = re.compile(
    rf"^{re.escape(str(CHANGES))}/(?:archive/)?(?!archive/)[^/]+/(interventions\.jsonl$|reviews/)")


def validation_problem(reviews: Path, head: str, root: Path | None = None,
                       changed_since: ChangedSince = _changed_since) -> str | None:
    """Why the latest validation record does not clear `head` for closeout, if it does not.

    A validation of an ancestor clears `head` when the two commits differ only in
    changes' records; without `root` to compare them in, only `head` itself does.
    """
    records = [(int(match.group(1)), entry) for entry in
               (reviews.glob("[0-9]*-validation.md") if reviews.is_dir() else [])
               if (match := _NUMBERED.match(entry.name))]
    if not records:
        return "the change has no validation record"
    record = max(records)[1]
    text = record.read_text("utf-8")
    commit = _VALIDATION_COMMIT.search(text)
    result = _VALIDATION_RESULT.search(text)
    if not commit:
        return f"{record.name} validates no commit, not HEAD {head[:12]}"
    validated = commit.group(1)
    if not head.startswith(validated):
        changed = changed_since(root, validated, head) if root else None
        if changed is None:
            return f"{record.name} validates {validated[:12]}, not HEAD {head[:12]}"
        if others := [path for path in changed if not _RECORD.match(path)]:
            return (f"{record.name} validates {validated[:12]}, and HEAD {head[:12]} also "
                    f"changes {', '.join(others[:3])}" + (" …" if len(others) > 3 else ""))
    if not result or result.group(1).lower() != "passed":
        return f"{record.name}'s result is {result.group(1) if result else 'missing'}, not passed"
    return None


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


def prior_session(reviews: Path, kind: str) -> tuple[str, str] | None:
    """The reviewer session and record of the latest published review of `kind`."""
    records = sorted(reviews.glob(f"[0-9]*-{kind}.md")) if reviews.is_dir() else []
    for record in reversed(records):
        # The last marker is the record's own; an earlier one may be quoted.
        if sessions := _SESSION_MARKER.findall(record.read_text("utf-8")):
            return sessions[-1], record.stem
    return None


def _options(output: Path, model: str | None, effort: str | None) -> list[str]:
    options = ["--output-last-message", str(output)]
    if model:
        options += ["--model", model]
    if effort:
        options += ["--config", f'model_reasoning_effort="{effort}"']
    return options


def codex_command(prompt: str, output: Path, root: Path, model: str | None,
                  effort: str | None = None) -> list[str]:
    return ["codex", "exec", "--sandbox", "read-only", "--cd", str(root),
            *_options(output, model, effort), prompt]


def resume_command(session: str, prompt: str, output: Path, model: str | None,
                   effort: str | None = None) -> list[str]:
    # `exec resume` takes no --sandbox flag, so the read-only sandbox is set through
    # configuration; the reviewer must never be able to change what it reviews.
    return ["codex", "exec", "resume", session, "--config", 'sandbox_mode="read-only"',
            *_options(output, model, effort), prompt]


class Progress:
    """Condense Codex's plain session output into a readable progress stream.

    The transcript keeps everything; the terminal gets the session header, each
    command as one line, failed commands, errors, and the agent's messages, with
    long messages — the final review among them — cut short. Command output, which
    is mostly the files the reviewer reads, is never shown.
    """

    HEADER_KEYS = ("model:", "reasoning effort:", "sandbox:", "session id:")
    MESSAGE_LINES = 4

    def __init__(self) -> None:
        self._block = "header"
        self._message: list[str] = []

    def feed(self, line: str) -> list[str]:
        line = line.rstrip("\n")
        if line.startswith("ERROR:"):
            return [line]
        label = line.strip()
        if label in ("codex", "exec", "user", "thinking", "tokens used") and line == label:
            shown = self._flush()
            self._block = label
            return shown
        if line.startswith(" succeeded in ") or line.startswith(" exited "):
            self._block = "output"
            return [f"  ✗{line}"] if line.startswith(" exited ") else []
        if self._block == "header":
            return [line] if line.startswith(self.HEADER_KEYS) else []
        if self._block == "exec" and line.startswith("/bin/bash -lc "):
            command = line[len("/bin/bash -lc "):].rsplit(" in /", 1)[0].strip("'\"")
            return [f"$ {command[:150]}"]
        if self._block == "codex":
            self._message.append(line)
        elif self._block == "tokens used" and label:
            self._block = "done"
            return [f"tokens used: {label}"]
        return []

    def close(self) -> list[str]:
        return self._flush()

    def _flush(self) -> list[str]:
        lines = [line for line in self._message if line.strip()]
        self._message = []
        if not lines:
            return []
        shown = [f"» {line}" for line in lines[:self.MESSAGE_LINES]]
        if len(lines) > self.MESSAGE_LINES:
            shown.append(f"» … ({len(lines) - self.MESSAGE_LINES} more lines in the transcript)")
        return shown


def _run_codex(command: Sequence[str], log: Path) -> int:
    progress = Progress()
    with log.open("w", encoding="utf-8") as stream:
        process = subprocess.Popen(list(command), cwd=ROOT, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, encoding="utf-8", errors="replace")
        assert process.stdout is not None
        for line in process.stdout:
            stream.write(line)
            for shown in progress.feed(line):
                print(shown, file=sys.stderr, flush=True)
        for shown in progress.close():
            print(shown, file=sys.stderr, flush=True)
        return process.wait()


def run_review(change: str, kind: str, *, base: str = DEFAULT_BASE, model: str | None = None,
               effort: str | None = None, fresh: bool = False, root: Path = ROOT,
               runner: CodexRunner = _run_codex, unvalidated: bool = False,
               head: Callable[[Path], str] = _reviewed_head,
               changed_since: ChangedSince = _changed_since) -> Path:
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
        if problem := validation_problem(reviews, reviewed, root, changed_since):
            raise ReviewError(f"a pre-closeout review needs a passing validation of HEAD: "
                              f"{problem}; validate first, or set UNVALIDATED=1 to override")
    transcripts = reviews / TRANSCRIPTS
    transcripts.mkdir(parents=True, exist_ok=True)
    provisional = f"pending-{kind}-{uuid.uuid4().hex[:12]}"
    log = transcripts / f"{provisional}.log"
    draft = transcripts / f"{provisional}.rejected.md"
    prior = None if fresh else prior_session(reviews, kind)
    if prior:
        session, previous = prior
        command = resume_command(session, continuation_prompt(kind, change, base, previous),
                                 draft, model, effort)
    else:
        command = codex_command(review_prompt(kind, change, base), draft, root, model, effort)
    status: int | None = None
    try:
        status = runner(command, log)
    finally:
        # Numbered now, after every record written while the reviewer ran; an
        # interrupted run keeps its number too, through its transcript, and
        # leaves no empty record behind.
        output = claim_record(reviews, kind)
        if log.is_file():
            log = log.rename(transcripts / output.with_suffix(".log").name)
        if draft.is_file():
            draft = draft.rename(transcripts / output.with_suffix(".rejected.md").name)
        if status is None:
            output.unlink()
    text = draft.read_text("utf-8") if draft.is_file() else ""
    problems = [f"the reviewer exited {status}"] if status != 0 else review_problems(text, kind, change)
    if problems:
        output.unlink()
        if not text.strip():
            draft.unlink(missing_ok=True)
        raise ReviewError("the reviewer produced no review: " + "; ".join(problems)
                          + f"; see {log.relative_to(root)}")
    session = _SESSION_LINE.search(log.read_text("utf-8")) if log.is_file() else None
    text = text.rstrip("\n") + "\n"
    if session:
        text += f"\n<!-- reviewer-session: {session.group(1)} -->\n"
    text += REVIEWED_COMMIT.format(reviewed) + "\n"
    output.write_text(text, "utf-8")
    draft.unlink()
    return output


def review_outcome(path: Path) -> tuple[Entry, str | None, str | None]:
    """A published review's outcome, with its reviewer session and reviewed commit.

    Both are read back from the markers the record ends with, so the line names
    what this run published and nothing an earlier record says.
    """
    text = path.read_text("utf-8")
    # The last of each, since a review may quote an earlier record's markers.
    sessions = _SESSION_MARKER.findall(text)
    commits = _REVIEWED_COMMIT.findall(text)
    outcome = {"outcome": "finished", "next": "triage",
               "message": f"{path.name} written; triage is next"}
    return (outcome, f"codex:{sessions[-1]}" if sessions else None,
            commits[-1] if commits else None)


def review_and_log(change: str, kind: str, *, root: Path = ROOT, clock: Clock = _utc_now,
                   **options: Any) -> Entry:
    """Run a review and log its outcome.

    It is `finished` only when this run published its own record, named with the
    commit it reviewed; any other end is `stopped` with the runner's reason, so an
    earlier record of the same kind never stands in for this run's.
    """
    log = log_path(root, change)
    head = options.get("head", _reviewed_head)

    def stopped(reason: str) -> Entry:
        try:
            commit = head(root)
        except ReviewError:
            commit = None
        return record_outcome(log, "review", {"outcome": "stopped", "message": reason,
                                              "reason": reason, "denials": []},
                              session=None, commit=commit, extra={"kind": kind}, clock=clock)

    try:
        path = run_review(change, kind, root=root, **options)
    except ReviewError as exc:
        return stopped(str(exc))
    except BaseException as exc:
        # A reviewer that could not start, or was interrupted, still ends with a
        # line; an interrupt is passed on once it is written.
        line = stopped(f"the review did not finish: {type(exc).__name__}"
                       + (f": {exc}" if str(exc) else ""))
        if not isinstance(exc, Exception):
            raise
        return line
    outcome, session, commit = review_outcome(path)
    return record_outcome(log, "review", outcome, session=session, commit=commit,
                          extra={"kind": kind, "record": path.name}, clock=clock)


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


def main(argv: Sequence[str] | None = None, root: Path = ROOT,
         wrapper: Wrapper | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
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
    resume = commands.add_parser("resume", help="resume a waiting run with the owner's answer")
    resume.add_argument("change")
    resume.add_argument("--seq", type=int, required=True,
                        help="the waiting run's line in the workflow log")
    resume.add_argument("--answer", required=True)
    resume.add_argument("--allow", action="append", default=[],
                        help="a permission rule granted for this run alone")
    review = commands.add_parser("review", help="review a change in Codex, read-only")
    review.add_argument("change")
    review.add_argument("--kind", required=True, choices=KINDS)
    review.add_argument("--base", default=DEFAULT_BASE)
    review.add_argument("--model", default=None)
    review.add_argument("--effort", default=None)
    review.add_argument("--fresh", action="store_true",
                        help="start a new reviewer session instead of continuing the last one")
    review.add_argument("--unvalidated", action="store_true",
                        help="run a pre-closeout review without a passing validation of HEAD")
    log = commands.add_parser("log", help="print the last lines of the change's workflow log")
    log.add_argument("change")
    log.add_argument("--last", type=int, default=10)
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
    args = parser.parse_args(argv)
    wrapper = wrapper or Wrapper(root=root)
    try:
        path = log_path(wrapper.root, args.change)
        if args.command == "run":
            sections = expand_sections(args.sections)
            words = (f"section {args.sections}" if len(sections) == 1
                     else f"sections {args.sections}" if sections else "")
            arguments = " ".join(part for part in (words, args.arguments) if part)
            line = wrapper.run(args.step, args.change, arguments=arguments,
                               sections=sections, fresh=args.fresh)
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
            line = wrapper.resume(args.change, args.seq, args.answer, args.allow)
            print(json.dumps(line, ensure_ascii=False))
            return 1 if line["outcome"] == "stopped" else 0
        if args.command == "log":
            for entry in last_entries(path, args.last):
                print(json.dumps(entry, ensure_ascii=False))
        elif args.command == "watch":
            try:
                watch(path.parent, echo=lambda line: print(line, flush=True))
            except KeyboardInterrupt:
                pass
        elif args.command == "denials":
            entry = next((e for e in read_log(path) if e.get("seq") == args.seq), None)
            if entry is None:
                raise StepError(f"{args.change}'s workflow log has no seq {args.seq}")
            for shown in denial_report(path.parent, entry):
                print(shown)
        elif args.kind == "round":
            line = note_round(path, parse_sections(args.sections), args.by, args.after)
            print(json.dumps(line, ensure_ascii=False))
        else:
            line = note_orchestrator(path, args.decision, args.reason, by=args.by,
                                     resolves=args.resolves, reads=args.reads,
                                     next_step=args.next_step, kind=args.kind)
            print(json.dumps(line, ensure_ascii=False))
    except StepError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
