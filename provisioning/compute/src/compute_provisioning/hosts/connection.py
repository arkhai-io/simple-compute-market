"""How the provisioning service reaches a host, held without knowing the means.

A host's connection is an envelope: a ``kind`` naming the codec of the
implementation distribution that supports it, a payload ``version``, ``public``
fields, and ``protected`` values. The host authority stores and returns
envelopes and never reads a field's meaning.

Connection secrets exist only as protected values: a scheme and its ciphertext.
A secret submitted with a connection is handed to the kind's codec, which turns
it into a protected value before anything is stored; the host authority never
encrypts, decrypts, returns, or logs secret material, and a protected value's
representation never shows its ciphertext. Only the codec decrypts, just in time
for execution.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Protocol


@dataclass(frozen=True)
class ProtectedValue:
    """A secret in the protected form its codec produced; opaque to everything else."""

    scheme: str
    ciphertext: str = field(repr=False)

    def __post_init__(self) -> None:
        if not self.scheme or not self.scheme.strip():
            raise ValueError("a protected value needs a scheme")
        if not self.ciphertext:
            raise ValueError("a protected value needs its ciphertext")

    def __str__(self) -> str:
        return f"<protected {self.scheme}>"

    def to_stored(self) -> dict[str, str]:
        """The form persisted with the host record."""
        return {"scheme": self.scheme, "ciphertext": self.ciphertext}

    @classmethod
    def from_stored(cls, stored: Mapping[str, Any]) -> "ProtectedValue":
        return cls(scheme=str(stored["scheme"]), ciphertext=str(stored["ciphertext"]))


@dataclass(frozen=True)
class ConnectionEnvelope:
    kind: str
    version: int
    public: Mapping[str, Any] = field(default_factory=dict)
    protected: Mapping[str, ProtectedValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.kind or not self.kind.strip():
            raise ValueError("a connection kind must be non-empty")
        if self.version < 1:
            raise ValueError("a connection payload version must be positive")
        for name, value in self.protected.items():
            if not isinstance(value, ProtectedValue):
                raise TypeError(f"protected value {name!r} is not a ProtectedValue")
        object.__setattr__(self, "public", MappingProxyType(dict(self.public)))
        object.__setattr__(self, "protected", MappingProxyType(dict(self.protected)))

    def stored_protected(self) -> dict[str, dict[str, str]]:
        return {name: value.to_stored() for name, value in self.protected.items()}

    def protected_schemes(self) -> dict[str, str]:
        """Each protected value's scheme, the most any read surface discloses."""
        return {name: value.scheme for name, value in self.protected.items()}


class ConnectionCodec(Protocol):
    """One connection kind, as the implementation distribution supporting it defines it."""

    kind: str
    version: int

    def build(
        self,
        public: Mapping[str, Any],
        secrets: Mapping[str, str],
        *,
        previous: ConnectionEnvelope | None = None,
    ) -> ConnectionEnvelope:
        """Validate submitted public fields and protect submitted secrets.

        ``previous`` is the connection being replaced, if any: a protected value
        the submission still needs and does not resubmit is carried forward from
        it. Raises ``ValueError`` naming the problem.
        """

    def validate(self, envelope: ConnectionEnvelope) -> ConnectionEnvelope:
        """Return the canonical form of a stored envelope, or raise ``ValueError``."""


class ConnectionCodecs:
    """The connection codecs a deployment supports, by kind."""

    def __init__(self, codecs: list[ConnectionCodec] | tuple[ConnectionCodec, ...]) -> None:
        by_kind: dict[str, ConnectionCodec] = {}
        for codec in codecs:
            if codec.kind in by_kind:
                raise ValueError(f"duplicate connection codec for kind {codec.kind!r}")
            by_kind[codec.kind] = codec
        self._codecs = by_kind

    def codec(self, kind: str) -> ConnectionCodec:
        try:
            return self._codecs[kind]
        except KeyError:
            raise ValueError(
                f"connection kind {kind!r} is not supported; supported: "
                f"{sorted(self._codecs)}"
            ) from None

    def build(
        self,
        kind: str,
        version: int,
        public: Mapping[str, Any],
        secrets: Mapping[str, str],
        *,
        previous: ConnectionEnvelope | None = None,
    ) -> ConnectionEnvelope:
        codec = self.codec(kind)
        if version != codec.version:
            raise ValueError(
                f"connection kind {kind!r} is at version {codec.version}, not {version}"
            )
        if previous is not None and previous.kind != kind:
            previous = None
        return codec.build(public, secrets, previous=previous)


__all__ = [
    "ConnectionCodec",
    "ConnectionCodecs",
    "ConnectionEnvelope",
    "ProtectedValue",
]
