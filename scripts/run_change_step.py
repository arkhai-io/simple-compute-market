#!/usr/bin/env python3
"""Run a step of an OpenSpec change unattended, and keep the change's workflow log.

`run` starts the step's skill as a headless Claude Code session (`claude -p`),
held to the step's permissions in `scripts/change_steps.toml` under the `dontAsk`
permission mode, told to end its turn with an outcome matching the outcome schema,
and streaming its events. `resume` continues the last session with the owner's
answer, optionally granting a rule for that one run. Either way the run's event
stream is kept as `reviews/transcripts/NN-<step>.jsonl`, with a progress file of
its tool calls beside it, and its outcome is appended to the workflow log. A run
that crashes, ends without an outcome, or ends with one the schema rejects is
logged `stopped` by the wrapper itself, and a `stopped` line's denials are always
the run's own record of denied tools, never the step's account of them.

A step's outcome conforms to `scripts/change_outcome.schema.json`: `finished`,
`question`, `returned`, `blocked`, or `stopped`, each with the step's `message` to
the owner. `record_outcome` appends one as a line of the change's
`reviews/workflow.jsonl`, with a sequence number, the time, the step, and the
run's session and commit. `note` appends the orchestrating session's own lines: a
`round` line recording the implementation round the owner agreed, and an
`orchestrator` line recording a routing or recovery decision it made itself. This
module is the log's only writer.

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
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from find_change import ChangeNotFound, change_directory  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = Path(__file__).resolve().parent / "change_outcome.schema.json"
STEP_TABLE = Path(__file__).resolve().parent / "change_steps.toml"
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
    "outcome; the owner's answer resumes this session. If a tool call is denied, end with a "
    "`stopped` outcome naming it, and never work around the denial or ask about it as a "
    "question.")


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


def note_round(path: Path, sections: Any, by: str, clock: Clock = _utc_now) -> Entry:
    """Record the implementation round the owner agreed: its sessions, each a list
    of the sections that session implements, in order."""
    if not _section_ids(sections):
        raise StepError("a round names one or more sessions, each a non-empty list of "
                        f"sections; got {sections!r}")
    if not by:
        raise StepError("a round names who agreed it")
    return append_entry(path, {"step": ORCHESTRATOR, "outcome": "round",
                               "sections": sections, "by": by}, clock)


def note_orchestrator(path: Path, decision: str, reason: str,
                      clock: Clock = _utc_now) -> Entry:
    """Record a routing or recovery decision the orchestrating session made itself."""
    if not decision or not reason:
        raise StepError("an orchestrator line names its decision and its reason")
    return append_entry(path, {"step": ORCHESTRATOR, "outcome": ORCHESTRATOR,
                               "decision": decision, "reason": reason}, clock)


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


def next_transcript(reviews: Path, step: str) -> Path:
    """Claim `reviews/transcripts/NN-<step>.jsonl`, numbered after every record.

    The number follows every numbered file in `reviews/` and its transcripts, as a
    review record's does, and the create is exclusive, so no run overwrites
    another's transcript.
    """
    transcripts = reviews / TRANSCRIPTS
    transcripts.mkdir(parents=True, exist_ok=True)
    while True:
        numbers = [int(entry.name.split("-", 1)[0])
                   for directory in (reviews, transcripts)
                   for entry in directory.iterdir()
                   if entry.name.split("-", 1)[0].isascii()
                   and entry.name.split("-", 1)[0].isdigit() and "-" in entry.name]
        path = transcripts / f"{max(numbers, default=0) + 1:02d}-{step}.jsonl"
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
    given = tool.get("input") if isinstance(tool.get("input"), dict) else {}
    for key in ("command", "file_path", "path", "pattern", "skill", "description", "prompt"):
        if isinstance(given.get(key), str):
            summary = " ".join(given[key].split())
            return summary if len(summary) <= 120 else summary[:119] + "…"
    return ""


class Stream:
    """The run's event stream: written whole to the transcript, its tool calls to
    the progress file, and read for the run's session and its final result."""

    def __init__(self, transcript: Path, progress: Path, clock: Clock = _utc_now,
                 echo: Callable[[str], None] | None = None) -> None:
        self.transcript = transcript
        self.progress = progress
        self.clock = clock
        self.echo = echo
        self.session: str | None = None
        self.result: dict[str, Any] | None = None

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


def run_outcome(status: int, result: dict[str, Any] | None,
                schema: dict[str, Any]) -> Entry:
    """The outcome to log for a run that exited with `status` and ended with `result`.

    The step's own outcome when it gave a valid one; otherwise a `stopped` the
    wrapper writes, its message the reason. A `stopped` outcome's denials are
    replaced with the run's record of them, whatever the step said.
    """
    denials = (result or {}).get("permission_denials")
    denials = denials if isinstance(denials, list) else []
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
    elif outcome["outcome"] == "stopped":
        return {**outcome, "denials": denials}
    elif denials:
        # A run denied a tool ends stopped, naming the denial; a step that carried
        # on past one may have worked around it.
        return {"outcome": "stopped", "message": outcome["message"],
                "reason": f"the run was denied {len(denials)} tool call(s) but ended "
                          f"{outcome['outcome']}",
                "denials": denials}
    else:
        return outcome
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

    def resume(self, change: str, answer: str, granted: Sequence[str] = ()) -> Entry:
        """Resume the last step session with the owner's answer.

        A granted rule applies to this run alone: it is passed on this command line
        and noted on this run's log line, never added to the step table, so the
        step's next run is held to its table again.
        """
        if not answer:
            raise StepError("a resumed step needs the owner's answer")
        steps = load_steps(self.steps_path)
        log = log_path(self.root, change)
        previous = last_run(log, list(steps))
        if previous is None:
            raise StepError(f"{change} has no step session in its workflow log to resume")
        if not previous.get("session"):
            raise StepError(f"{change}'s last {previous['step']} run (seq {previous['seq']}) "
                            "recorded no session to resume; run the step again")
        step = previous["step"]
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
            outcome = run_outcome(status, stream.result, schema)
        except BaseException as exc:
            # A run that could not start, or was interrupted, still ends with a
            # line, so the log never shows its previous outcome as the latest.
            failure, status = exc, None
            reason = (f"the run did not finish: {type(exc).__name__}"
                      + (f": {exc}" if str(exc) else ""))
            outcome = {"outcome": "stopped", "message": reason, "reason": reason,
                       "denials": run_outcome(1, stream.result, schema)["denials"]}
        extra = {**(extra or {}), "exit_status": status,
                 "transcript": transcript.relative_to(log.parent).as_posix()}
        line = record_outcome(log, step, outcome, session=stream.session or session,
                              commit=self.head(self.root), extra=extra, schema=schema,
                              clock=self.clock)
        if failure is not None and not isinstance(failure, Exception):
            raise failure
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
    resume = commands.add_parser("resume", help="resume the last step with the owner's answer")
    resume.add_argument("change")
    resume.add_argument("--answer", required=True)
    resume.add_argument("--allow", action="append", default=[],
                        help="a permission rule granted for this run alone")
    log = commands.add_parser("log", help="print the last lines of the change's workflow log")
    log.add_argument("change")
    log.add_argument("--last", type=int, default=10)
    note = commands.add_parser("note", help="append an orchestrator line to the workflow log")
    note.add_argument("change")
    kinds = note.add_subparsers(dest="kind", required=True)
    round_ = kinds.add_parser("round", help="the implementation round the owner agreed")
    round_.add_argument("--sections", required=True,
                        help="sessions separated by ';', each a ','-separated list of sections")
    round_.add_argument("--by", default="owner")
    decision = kinds.add_parser(ORCHESTRATOR, help="a routing or recovery decision")
    decision.add_argument("--decision", required=True)
    decision.add_argument("--reason", required=True)
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
        if args.command == "resume":
            line = wrapper.resume(args.change, args.answer, args.allow)
            print(json.dumps(line, ensure_ascii=False))
            return 1 if line["outcome"] == "stopped" else 0
        if args.command == "log":
            for entry in last_entries(path, args.last):
                print(json.dumps(entry, ensure_ascii=False))
        elif args.kind == "round":
            line = note_round(path, parse_sections(args.sections), args.by)
            print(json.dumps(line, ensure_ascii=False))
        else:
            line = note_orchestrator(path, args.decision, args.reason)
            print(json.dumps(line, ensure_ascii=False))
    except StepError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
