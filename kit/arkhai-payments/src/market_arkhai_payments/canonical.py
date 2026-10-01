"""Canonical hashes for opaque agreements and payments mandates."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

import rfc8785
from pydantic import BaseModel

from market_arkhai_payments.errors import PaymentsError


class CanonicalizationError(PaymentsError, ValueError):
    """An input is not a JSON object representable under RFC 8785."""


def jcs_bytes(value: Any) -> bytes:
    """Serialize a JSON value using RFC 8785 without lossy Python defaults."""

    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json", by_alias=True, exclude_none=True)
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
