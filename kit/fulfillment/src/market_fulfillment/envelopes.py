"""Versioned envelopes for generic payloads crossing durable boundaries."""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

PayloadT = TypeVar("PayloadT")


class VersionedEnvelope(BaseModel, Generic[PayloadT]):
    """Identify a payload schema before it crosses a domain or persistence boundary.

    Readers must recognize both ``kind`` and ``schema_version`` before
    interpreting the payload. This prevents retries or persisted records from
    being decoded according to a newer, incompatible provider schema.

    See ``openspec/specs/fulfillment/spec.md#versioned-envelopes``.
    """

    kind: str = Field(min_length=1)
    schema_version: int = Field(ge=1)
    payload: PayloadT

    model_config = {"frozen": True}


def envelope(kind: str, schema_version: int, payload: Any) -> VersionedEnvelope[Any]:
    """Construct an immutable versioned envelope."""

    return VersionedEnvelope(kind=kind, schema_version=schema_version, payload=payload)
