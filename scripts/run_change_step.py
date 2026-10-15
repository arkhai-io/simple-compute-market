#!/usr/bin/env python3
"""Keep an OpenSpec change's workflow log of step outcomes and orchestrator notes.

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
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from find_change import ChangeNotFound, change_directory  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = Path(__file__).resolve().parent / "change_outcome.schema.json"
LOG = "workflow.jsonl"
STEPS = ("design", "plan", "review", "triage", "implement", "validate", "closeout",
         "archive-cleanup")
ORCHESTRATOR = "orchestrator"

Clock = Callable[[], datetime]
Entry = dict[str, Any]


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


def parse_sections(text: str) -> list[list[int | str]]:
    """`1,2;3` as `[[1, 2], [3]]`: sessions separated by `;`, sections by `,`."""
    return [[int(section) if section.isascii() and section.isdigit() else section
             for section in (part.strip() for part in session.split(",")) if section]
            for session in text.split(";") if session.strip()]


def main(argv: Sequence[str] | None = None, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
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
    try:
        path = log_path(root, args.change)
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
