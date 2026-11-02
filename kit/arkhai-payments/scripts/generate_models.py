#!/usr/bin/env python3
"""Generate the payments wire models from the vendored JSON Schema."""

from __future__ import annotations

import argparse
import ast
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schema" / "payments.schema.json"
OUTPUT = ROOT / "src" / "market_arkhai_payments" / "models.py"
HEADER = (
    "# Generated from schema/payments.schema.json, checked by\n"
    "# scripts/generate_models.py; do not edit.\n"
    "# Contract identity and update procedure: schema/SOURCE.md.\n\n"
)

# Required nullable durations affect canonical mandate identity. Refuse a publication
# that changes their presence or union shape rather than silently dropping nulls.
REQUIRED_NULLABLE = (("OncePart", "maxHoldExtension"), ("RatePart", "maxHoldExtension"))
PUBLISHED_FORM = {"anyOf": [{"$ref": "#/$defs/Duration"}, {"type": "null"}]}


def normalized(schema: dict[str, Any]) -> dict[str, Any]:
    """Check required nulls and inline string constraints for hashable map keys."""

    for definition, field in REQUIRED_NULLABLE:
        target = schema["$defs"][definition]
        if field not in target.get("required", []):
            raise SystemExit(f"{definition}.{field} is no longer required; review the publication")
        if target["properties"][field] != PUBLISHED_FORM:
            raise SystemExit(f"{definition}.{field} changed its published form; review the publication")
    result = copy.deepcopy(schema)
    available = result["$defs"]["Balance"]["properties"]["available"]
    if available.get("propertyNames") != {"$ref": "#/$defs/Asset"}:
        raise SystemExit("Balance.available propertyNames changed; review map-key generation")
    # Pydantic RootModel keys are unhashable. Inline the identical string schema so
    # code generation constrains plain string keys instead of constructing Asset.
    available["propertyNames"] = copy.deepcopy(result["$defs"]["Asset"])
    return result


def render(destination: Path) -> None:
    executable = shutil.which("datamodel-codegen")
    if executable is None:
        raise SystemExit("datamodel-codegen is missing; run `uv sync --dev` first")
    schema = normalized(json.loads(SCHEMA.read_text(encoding="utf-8")))
    with tempfile.TemporaryDirectory(prefix="arkhai-payments-schema-") as temporary:
        # The generator names its input file in the output, so the normalized copy
        # keeps the vendored file's name.
        source = Path(temporary) / SCHEMA.name
        source.write_text(json.dumps(schema, indent=2, ensure_ascii=False), encoding="utf-8")
        _generate(executable, source, destination)
    generated = destination.read_text(encoding="utf-8")
    destination.write_text(HEADER + annotated_keys(generated, schema), encoding="utf-8")


def annotated_keys(generated: str, schema: dict[str, Any]) -> str:
    """Express the generator's constrained dictionary key in typing-valid syntax."""

    calls = [
        node for node in ast.walk(ast.parse(generated))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "constr"
    ]
    if len(calls) != 1:
        raise SystemExit("expected one constrained balance key; review generator output")
    call = calls[0]
    pattern = schema["$defs"]["Asset"]["pattern"]
    if call.args or len(call.keywords) != 1 or call.keywords[0].arg != "pattern":
        raise SystemExit("balance key constraints changed; review generator output")
    if ast.literal_eval(call.keywords[0].value) != pattern:
        raise SystemExit("balance key pattern changed; review generator output")
    lines = generated.splitlines(keepends=True)
    assert call.end_lineno is not None and call.end_col_offset is not None
    start = sum(map(len, lines[:call.lineno - 1])) + call.col_offset
    end = sum(map(len, lines[:call.end_lineno - 1])) + call.end_col_offset
    replacement = f"Annotated[str, Field(pattern={pattern!r})]"
    return (generated[:start] + replacement + generated[end:]).replace(
        "RootModel, constr", "RootModel"
    )


def _generate(executable: str, source: Path, destination: Path) -> None:
    subprocess.run(
        [
            executable,
            "--input",
            str(source),
            "--input-file-type",
            "jsonschema",
            "--output-model-type",
            "pydantic_v2.BaseModel",
            "--use-annotated",
            "--field-constraints",
            "--target-python-version",
            "3.10",
            "--formatters",
            "builtin",
            "--disable-timestamp",
            # A publication may state a constant as a one-value enum,
            # which constrains exactly what `const` does; typing it as a literal keeps
            # comparisons with plain wire values, such as an identity's scheme, exact.
            "--enum-field-as-literal",
            "one",
            "--output",
            str(destination),
        ],
        check=True,
        cwd=ROOT,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail if generated models are stale")
    args = parser.parse_args()
    if args.check:
        with tempfile.TemporaryDirectory(prefix="arkhai-payments-models-") as temporary:
            candidate = Path(temporary) / "models.py"
            render(candidate)
            if candidate.read_bytes() != OUTPUT.read_bytes():
                print("models.py is stale; run `python scripts/generate_models.py`", file=sys.stderr)
                return 1
        print("generated payments models are current")
        return 0
    render(OUTPUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
