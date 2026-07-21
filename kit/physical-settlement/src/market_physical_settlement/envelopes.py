"""Versioned payload envelopes for cross-domain generic dictionaries.

tasks.md 1.6: "Add versioned payload envelopes for prepared provider
create/teardown inputs, provider metadata, and ``SettlementResult``;
prohibit unversioned cross-domain generic dictionaries."

This module defines the shared envelope shape only. The concrete payload
kinds it wraps -- prepared provider create/teardown input (tasks.md 6.3/
6.4), provider metadata (6.6), and ``SettlementResult`` (8.2) -- are added
by the sections that need them; this section only establishes that no
generic ``dict[str, Any]`` crosses a domain or persistence boundary
without a schema version and a kind discriminator attached, so that a
later reader can tell what shape it is holding and whether it understands
that shape's version before trusting its contents.
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

PayloadT = TypeVar("PayloadT")


class VersionedEnvelope(BaseModel, Generic[PayloadT]):
    """Wraps a normalized, serializable payload with a schema version and
    kind discriminator.

    ``kind`` identifies the payload shape (e.g. ``"ansible_create_input"``,
    ``"settlement_result"``); ``schema_version`` is an integer a reader
    increments on any incompatible shape change to that ``kind``. A reader
    that does not recognize a ``(kind, schema_version)`` pair MUST refuse
    to interpret ``payload`` rather than guess at its shape -- this is what
    makes it safe to persist these durably (tasks.md 3.1) and dispatch
    them from a frozen snapshot on retry (design.md, "Provider input
    snapshot: prepare/dispatch split") without a later code change
    silently misreading an older row.
    """

    kind: str
    schema_version: int = Field(ge=1)
    payload: PayloadT

    model_config = {"frozen": True}


def envelope(kind: str, schema_version: int, payload: Any) -> VersionedEnvelope[Any]:
    """Convenience constructor mirroring ``VersionedEnvelope``'s fields."""
    return VersionedEnvelope(kind=kind, schema_version=schema_version, payload=payload)
