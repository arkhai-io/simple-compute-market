"""How the provisioning service reaches a host, held without knowing the means.

A host's connection is an envelope: a ``kind`` naming the codec of the
implementation distribution that supports it, a payload ``version``, and the
payload itself. The host authority stores and returns envelopes; it never reads
a payload's fields. What a kind's payload contains, which of its fields are
secret, and how an executor uses it belong to that kind's codec.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Protocol


@dataclass(frozen=True)
class ConnectionEnvelope:
    kind: str
    version: int
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.kind or not self.kind.strip():
            raise ValueError("a connection kind must be non-empty")
        if self.version < 1:
            raise ValueError("a connection payload version must be positive")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


class ConnectionCodec(Protocol):
    """One connection kind, as the implementation distribution supporting it defines it.

    The host authority validates every payload of ``kind`` through its codec and
    encrypts at rest the fields ``secret_fields`` names for that payload, without
    itself knowing what any field means.
    """

    kind: str
    version: int

    def validate(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Return the canonical payload, or raise ``ValueError`` naming the problem."""

    def secret_fields(self, payload: Mapping[str, Any]) -> frozenset[str]:
        """The fields of this validated payload that are secret material."""


__all__ = ["ConnectionCodec", "ConnectionEnvelope"]
