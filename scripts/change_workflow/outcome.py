"""The outcome a step ends with, checked against its schema.

A step's outcome conforms to `.agents/change-outcome.schema.json`: `finished`,
`question`, `returned`, `blocked`, or `stopped`, each with the step's `message` to
the owner. The scripts run on the standard library alone, without a JSON Schema
package, so the check understands exactly the keywords the schema uses.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

from .common import FORMAT, StepError, repository_root
from .graph import TargetError, node_of, review_phase

# The schema's place in the repository the command acts on.
SCHEMA = Path(".agents/change-outcome.schema.json")
# The schema's `$id` names the record-set format its outcomes belong to.
_SCHEMA_ID = re.compile(r":format:(\d+)$")
# A commit's full object name, SHA-1 or SHA-256, as `git rev-parse` prints it: an
# abbreviation could name another commit once the repository grows.
OBJECT_NAME = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")


def schema_format(schema: dict[str, Any]) -> int | None:
    """The record-set format the schema's `$id` states; None when it states none."""
    identifier = schema.get("$id")
    match = _SCHEMA_ID.search(identifier) if isinstance(identifier, str) else None
    return int(match.group(1)) if match else None


def load_schema(path: Path | None = None) -> dict[str, Any]:
    """The outcome schema at `path`, or the repository's own; refused when its `$id`
    states another format than the one this engine records, since its outcomes would
    be logged as lines of a format they do not belong to."""
    where = repository_root() / SCHEMA if path is None else path
    schema = json.loads(where.read_text("utf-8"))
    if (stated := schema_format(schema)) != FORMAT:
        raise StepError(f"{where} states format {stated} in its $id, and this engine records "
                        f"format {FORMAT}")
    return schema


_TYPES: dict[str, Callable[[Any], bool]] = {
    "object": lambda value: isinstance(value, dict),
    "array": lambda value: isinstance(value, list),
    "string": lambda value: isinstance(value, str),
    # JSON has no separate boolean among numbers; Python's bool is an int.
    "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
}
# Keywords that describe a schema rather than constrain a value.
_ANNOTATIONS = {"$schema", "$id", "title", "description"}


def schema_problems(value: Any, schema: dict[str, Any], path: str = "outcome") -> list[str]:
    """Why `value` does not conform to `schema`; empty when it does.

    Only the keywords the outcome schema uses are understood. Any other keyword
    raises, so a schema edit that this check cannot enforce fails loudly instead of
    being ignored: the scripts run on the standard library alone, without a JSON
    Schema package.
    """
    unknown = set(schema) - _ANNOTATIONS - {
        "type", "properties", "required", "additionalProperties", "enum", "const",
        "minLength", "minItems", "items", "allOf", "anyOf", "if", "then"}
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
    if "minItems" in schema and isinstance(value, list) and len(value) < schema["minItems"]:
        problems.append(f"{path} has fewer than {schema['minItems']} items")
    if "anyOf" in schema and all(found := [schema_problems(value, part, path)
                                           for part in schema["anyOf"]]):
        problems.append(f"{path} matches none of its allowed forms: "
                        + "; or ".join(", ".join(each) for each in found))
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
    when the run ends, logging an outcome that misses one as `stopped`. The `$id`
    constrains nothing a step writes: it names the format for the engine, and a tool's
    input schema is given only what the harness enforces.
    """
    return {key: value for key, value in schema.items()
            if key not in ("allOf", "anyOf", "oneOf", "$id")}


def outcome_problems(outcome: Any, schema: dict[str, Any] | None = None) -> list[str]:
    """Why `outcome` is not a step outcome; empty when it is.

    The schema holds a target's shape; whether it names a node of the workflow
    graph, a review with a kind the graph knows say, is the graph's to answer. It
    holds the landing record's shape too; that its commit is a full object name is
    checked here, since the schema's keywords include no pattern.
    """
    problems = schema_problems(outcome, schema if schema is not None else load_schema())
    target = outcome.get("next") if isinstance(outcome, dict) else None
    if isinstance(target, dict) and not any(p.startswith("outcome.next") for p in problems):
        try:
            node_of(target)
        except TargetError as exc:
            problems.append(f"outcome.next names no node: {exc}")
    landing = outcome.get("landing") if isinstance(outcome, dict) else None
    commit = landing.get("commit") if isinstance(landing, dict) else None
    if isinstance(commit, str) and commit and not OBJECT_NAME.fullmatch(commit):
        problems.append(f"outcome.landing.commit is {commit!r}, not a commit's full "
                        "hexadecimal object name")
    return problems


_RECORD_NAME = re.compile(r"^\d+-([a-z]+(?:-[a-z]+)*)$")


def triaged_problems(triaged: Any, reviews: Path) -> list[str]:
    """Why `triaged`, the records a triage's outcome names, does not name what it
    triaged; empty when it does.

    It is a non-empty list of distinct names, each a numbered record in `reviews` as
    its file is named without `.md`, `NN-<kind>`, with its triage file beside it, and
    at least one of them a review, `-external` included; the others may be the
    validation, the owner's notes, or the orchestrating session's observations
    triaged with it. Whether a record belongs to the triage the computation meant
    cannot be checked here: the triage file beside it is that triage's mark.
    """
    if triaged is None:
        return ["the triage names no records in triaged"]
    if not isinstance(triaged, list) or not triaged:
        return [f"triaged is not a non-empty list of records: {triaged!r}"]
    problems = []
    seen: set[str] = set()
    kinds = []
    for name in triaged:
        if not isinstance(name, str) or not (match := _RECORD_NAME.match(name)):
            problems.append(f"{name!r} is not a record's name, NN-<kind>")
            continue
        if name in seen:
            problems.append(f"{name} is named twice")
            continue
        seen.add(name)
        if not (reviews / f"{name}.md").is_file():
            problems.append(f"{name} is no record in reviews/")
        elif not (reviews / f"{name}.triage.md").is_file():
            problems.append(f"{name} has no triage file beside it")
        kinds.append(match.group(1))
    if not problems and not any(review_phase(kind.removesuffix("-external")) is not None
                                for kind in kinds):
        problems.append(f"{', '.join(triaged)} names no review")
    return problems


def triage_outcome_problems(outcome: Any, reviews: Path) -> list[str]:
    """Why a triage's outcome does not name what it triaged; empty when it does, or
    when it ends without an exit — a question, a block, or a stop — and so names
    nothing the next step is routed on."""
    if not isinstance(outcome, dict) or outcome.get("outcome") not in ("finished", "returned"):
        return []
    return triaged_problems(outcome.get("triaged"), reviews)
