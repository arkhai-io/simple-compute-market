"""Installed, explicitly selected payments contract resources."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from importlib.resources import files
import json
from types import ModuleType
from typing import Any

from market_arkhai_payments import models


@dataclass(frozen=True)
class PaymentsContract:
    """One coherent publication, never a union of independently selected resources."""

    selection: str
    schema_bytes: bytes
    vector_bytes: bytes
    models: ModuleType

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            "selection": self.selection,
            "published": True,
            "schema_id": json.loads(self.schema_bytes)["$id"],
            "schema_sha256": hashlib.sha256(self.schema_bytes).hexdigest(),
            "vectors_sha256": hashlib.sha256(self.vector_bytes).hexdigest(),
        }

    def vectors(self) -> dict[str, Any]:
        return dict(json.loads(self.vector_bytes))


def get_contract(selection: str = "published") -> PaymentsContract:
    """Load the selected contract from a wheel; unavailable candidates refuse."""

    if selection != "published":
        raise ValueError(f"payments contract resources unavailable: {selection}")
    resources = files("market_arkhai_payments").joinpath("contract_data")
    return PaymentsContract(
        selection=selection,
        schema_bytes=resources.joinpath("schema/payments.schema.json").read_bytes(),
        vector_bytes=resources.joinpath("test-vectors/payments.json").read_bytes(),
        models=models,
    )
