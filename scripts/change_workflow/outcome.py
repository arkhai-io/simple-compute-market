"""The outcome a step ends with, checked against its schema.

A step's outcome conforms to `.agents/change-outcome.schema.json`: `finished`,
`question`, `returned`, `blocked`, or `stopped`, each with the step's `message` to
the owner. The scripts run on the standard library alone, without a JSON Schema
package, so the check understands exactly the keywords the schema uses.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from change_workflow.common import ROOT, StepError
from change_workflow.graph import TargetError, node_of

SCHEMA = ROOT / ".agents" / "change-outcome.schema.json"


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
    when the run ends, logging an outcome that misses one as `stopped`.
    """
    return {key: value for key, value in schema.items() if key not in ("allOf", "anyOf", "oneOf")}


def outcome_problems(outcome: Any, schema: dict[str, Any] | None = None) -> list[str]:
    """Why `outcome` is not a step outcome; empty when it is.

    The schema holds a target's shape; whether it names a node of the workflow
    graph, a review with a kind the graph knows say, is the graph's to answer.
    """
    problems = schema_problems(outcome, schema if schema is not None else load_schema())
    target = outcome.get("next") if isinstance(outcome, dict) else None
    if isinstance(target, dict) and not any(p.startswith("outcome.next") for p in problems):
        try:
            node_of(target)
        except TargetError as exc:
            problems.append(f"outcome.next names no node: {exc}")
    return problems
