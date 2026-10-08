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
HEADER = (
    "# Generated from schema/payments.schema.json; do not edit.\n"
    "# Upstream: arkhai-io/arkhai-payments@f16b1ebdca4e0977dae45bebe7b57cce9c1a08c2\n\n"
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
        print("generated payments models are current")
        return 0
    render(OUTPUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
