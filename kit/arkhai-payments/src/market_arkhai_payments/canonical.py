"""Canonical hashes for opaque agreements and payments mandates."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

import rfc8785
from pydantic import BaseModel, RootModel

from market_arkhai_payments.errors import PaymentsError


class CanonicalizationError(PaymentsError, ValueError):
    """An input is not a JSON object representable under RFC 8785."""


def wire_json(model: BaseModel) -> Any:
    """Return a wire model as the JSON the service exchanges.

    An optional property without a value is omitted, and a required property keeps
    its null, as a part's `maxHoldExtension` may. `exclude_none` alone would drop that
    null and change the mandate's transaction ID. Opaque JSON, such as an attached
    Agreement, is returned whole, nulls included.
    """

    return _wire(model, model.model_dump(mode="json", by_alias=True))


def _wire(value: Any, dumped: Any) -> Any:
    if isinstance(value, RootModel):
        return _wire(value.root, dumped)
    if isinstance(value, BaseModel):
        wire = {}
        for name, field in type(value).model_fields.items():
            key = field.serialization_alias or field.alias or name
            item = getattr(value, name)
            if item is None and not field.is_required():
                continue
            wire[key] = _wire(item, dumped[key])
        return wire
    if isinstance(value, (list, tuple)):
        return [_wire(item, entry) for item, entry in zip(value, dumped, strict=True)]
    if isinstance(value, dict):
        return {
            key: _wire(item, entry)
            for (_, item), (key, entry) in zip(value.items(), dumped.items(), strict=True)
        }
    return dumped


def jcs_bytes(value: Any) -> bytes:
    """Serialize a JSON value using RFC 8785 without lossy Python defaults."""

    if isinstance(value, BaseModel):
        value = wire_json(value)
    try:
        return bytes(rfc8785.dumps(value))
    except (TypeError, ValueError) as exc:
        raise CanonicalizationError("value is not canonicalizable JSON") from exc


def jcs_sha256(value: Any) -> str:
    """Return lowercase SHA-256 of an RFC 8785 JSON serialization."""

    return hashlib.sha256(jcs_bytes(value)).hexdigest()


def agreement_hash(agreement_json: Mapping[str, Any]) -> str:
    """Hash the accepted Agreement object without interpreting its vocabulary."""

    if not isinstance(agreement_json, Mapping):
        raise CanonicalizationError("agreement must be a JSON object")
    return jcs_sha256(dict(agreement_json))
