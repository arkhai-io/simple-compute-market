"""Generate transport models from the installed, published schema."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "market_arkhai_mediation"
ROOTS = (
    "DisputeAuthority", "Filing", "Append", "FilingAnswer", "AppendAnswer",
    "ReadAfter", "RecordPage", "CaseAnswer", "SignedRecordEntry",
    "DeliveryEndClaim", "SignedDeliveryEndClaim", "RespondentAfter", "RespondentPage",
)


def render(destination: Path) -> None:
    schema = json.loads((PACKAGE / "contract_data" / "mediation.schema.json").read_bytes())
    definitions = {}

    def include(value):
        if isinstance(value, dict):
            if "$ref" in value:
                name = value["$ref"].split("/")[-1]
                if name not in definitions:
                    definitions[name] = schema["$defs"][name]
                    include(definitions[name])
            for child in value.values():
                include(child)
        elif isinstance(value, list):
            for child in value:
                include(child)

    for name in ROOTS:
        include({"$ref": "#/$defs/" + name})
    # Mapping and compatibility advertisements remain schema-validated data.
    # This kit interprets only its own interface, not a payment mechanism.
    with tempfile.TemporaryDirectory() as temporary:
        source = Path(temporary) / "mediation.schema.json"
        source.write_text(json.dumps({"$defs": definitions}))
        subprocess.run([
            shutil.which("datamodel-codegen") or "datamodel-codegen",
            "--input", str(source), "--input-file-type", "jsonschema",
            "--output-model-type", "pydantic_v2.BaseModel", "--use-annotated",
            "--field-constraints", "--strict-types", "str", "int", "bool", "float",
            "--target-python-version", "3.12", "--formatters", "builtin",
            "--disable-timestamp", "--output", str(destination),
        ], check=True)
    generated = destination.read_text()
    destination.write_text(generated[generated.index("from __future__"):])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    output = PACKAGE / "models.py"
    if args.check:
        with tempfile.TemporaryDirectory() as temporary:
            candidate = Path(temporary) / "models.py"
            render(candidate)
            if candidate.read_bytes() != output.read_bytes():
                raise SystemExit("models.py is stale; run make generate-models")
    else:
        render(output)


if __name__ == "__main__":
    main()
