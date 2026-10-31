#!/usr/bin/env python3
"""Generate the payments wire models from the vendored JSON Schema."""

from __future__ import annotations

import argparse
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
    "# Generated from schema/payments.schema.json, normalized by\n"
    "# scripts/generate_models.py; do not edit.\n"
    "# Contract identity and update procedure: schema/SOURCE.md.\n\n"
)

# The service requires these properties and accepts null for them, but the published
# document states each as the intersection of `Duration` and a string-or-null type,
# which admits no null. Generation reads each as the union the service validates. The
# vendored schema stays as published; schema/SOURCE.md records the discrepancy.
REQUIRED_NULLABLE = (("OncePart", "maxHoldExtension"), ("RatePart", "maxHoldExtension"))
PUBLISHED_FORM = {"allOf": [{"$ref": "#/$defs/Duration"}, {"type": ["string", "null"]}]}
VALIDATED_FORM = {"anyOf": [{"$ref": "#/$defs/Duration"}, {"type": "null"}]}


def normalized(schema: dict[str, Any]) -> dict[str, Any]:
    """Return the schema generation reads, refusing a publication that has moved on.

    Only the properties in ``REQUIRED_NULLABLE`` change, and only while each is still
    required and still in its published form, so a corrected or reshaped publication
    stops generation rather than being reinterpreted.
    """

    result = copy.deepcopy(schema)
    for definition, field in REQUIRED_NULLABLE:
        target = result["$defs"][definition]
        if field not in target.get("required", []):
            raise SystemExit(f"{definition}.{field} is no longer required; review the normalization")
        if target["properties"][field] != PUBLISHED_FORM:
            raise SystemExit(f"{definition}.{field} changed its published form; review the normalization")
        target["properties"][field] = copy.deepcopy(VALIDATED_FORM)
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
    destination.write_text(HEADER + generated, encoding="utf-8")


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
            # The published OpenAPI document states a constant as a one-value enum,
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
