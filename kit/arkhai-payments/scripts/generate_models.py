#!/usr/bin/env python3
"""Generate the payments wire models from the vendored JSON Schema."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schema" / "payments.schema.json"
OUTPUT = ROOT / "src" / "market_arkhai_payments" / "models.py"
RESOURCE_INPUTS = (SCHEMA, ROOT / "test-vectors" / "payments.json")
RESOURCE_ROOT = OUTPUT.parent / "contract_data"
HEADER = (
    "# Generated from schema/payments.schema.json; do not edit.\n"
    "# Contract identity and update procedure: schema/SOURCE.md.\n\n"
)


def render(destination: Path) -> None:
    executable = shutil.which("datamodel-codegen")
    if executable is None:
        raise SystemExit("datamodel-codegen is missing; run `uv sync --dev` first")
    subprocess.run(
        [
            executable,
            "--input",
            str(SCHEMA),
            "--input-file-type",
            "jsonschema",
            "--output-model-type",
            "pydantic_v2.BaseModel",
            "--base-class",
            "market_arkhai_payments.wire.WireModel",
            "--use-annotated",
            "--field-constraints",
            "--target-python-version",
            "3.10",
            "--formatters",
            "builtin",
            "--disable-timestamp",
            "--output",
            str(destination),
        ],
        check=True,
        cwd=ROOT,
    )
    generated = destination.read_text(encoding="utf-8")
    destination.write_text(HEADER + generated, encoding="utf-8")


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
        for source in RESOURCE_INPUTS:
            resource = RESOURCE_ROOT / source.relative_to(ROOT)
            if not resource.is_file() or resource.read_bytes() != source.read_bytes():
                print(f"{resource.relative_to(ROOT)} is stale; run `make generate-models`",
                      file=sys.stderr)
                return 1
        print("generated payments models and resources are current")
        return 0
    render(OUTPUT)
    for source in RESOURCE_INPUTS:
        resource = RESOURCE_ROOT / source.relative_to(ROOT)
        resource.parent.mkdir(parents=True, exist_ok=True)
        resource.write_bytes(source.read_bytes())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
