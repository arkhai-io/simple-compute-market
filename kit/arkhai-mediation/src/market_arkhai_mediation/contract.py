"""Installed baseline bytes, validation and publication metadata."""

import hashlib
from importlib.resources import files
import json
from typing import Any

from jsonschema import Draft202012Validator
from pydantic import BaseModel

INTERFACE = "arkhai.mediation.v1"


def resource_bytes(name: str) -> bytes:
    if name not in {"mediation.schema.json", "mediation.vectors.json", "publication.json"}:
        raise ValueError("unknown mediation resource")
    return files("market_arkhai_mediation").joinpath("contract_data", name).read_bytes()


def publication() -> dict[str, Any]:
    metadata = json.loads(resource_bytes("publication.json"))
    for name, entry in metadata["files"].items():
        if hashlib.sha256(resource_bytes(name)).hexdigest() != entry["sha256"]:
            raise ValueError("mediation resource hash mismatch")
    return metadata


def schema() -> dict[str, Any]:
    return json.loads(resource_bytes("mediation.schema.json"))


def vectors() -> dict[str, Any]:
    return json.loads(resource_bytes("mediation.vectors.json"))


def wire(value: BaseModel) -> dict[str, Any]:
    """Retain present nulls and omit absent fields in signed/hashed JSON."""
    return value.model_dump(mode="json", by_alias=True, exclude_unset=True)


def validate(name: str, value: Any) -> Any:
    document = schema()
    if name not in document["$defs"]:
        raise ValueError("unknown mediation model")
    Draft202012Validator({**document, "$ref": "#/$defs/" + name}).validate(value)
    return value
