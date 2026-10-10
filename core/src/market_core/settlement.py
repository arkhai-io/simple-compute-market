"""Dependency-light settlement composition and evidence carriers.

Stages and evidence payloads belong to the composing domain. Neither carrier
requires a mechanism API, actor sequence, or financial status vocabulary.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Generic, TypeVar

StageT = TypeVar("StageT")


def _identity(value: str, name: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{name} must be a non-empty, trimmed string")


@dataclass(frozen=True, init=False)
class SettlementStageTable(Mapping[str, StageT], Generic[StageT]):
    """An immutable role declaration; entry values are opaque to core.

    Iterable pairs permit duplicate detection before a mapping would erase it.
    The table copies its input, but does not freeze domain-owned stage objects.
    """

    _entries: Mapping[str, StageT] = field(repr=False)

    def __init__(
        self,
        entries: Mapping[str, StageT] | Iterable[tuple[str, StageT]],
    ) -> None:
        copied: dict[str, StageT] = {}
        pairs = entries.items() if isinstance(entries, Mapping) else entries
        for mechanism, stage in pairs:
            _identity(mechanism, "mechanism")
            if mechanism in copied:
                raise ValueError(f"duplicate settlement mechanism: {mechanism}")
            if stage is None:
                raise ValueError(f"settlement mechanism {mechanism} has no stage")
            copied[mechanism] = stage
        object.__setattr__(self, "_entries", MappingProxyType(copied))

    def __getitem__(self, mechanism: str) -> StageT:
        return self._entries[mechanism]

    def __iter__(self) -> Iterator[str]:
        return iter(self._entries)

    def __len__(self) -> int:
        return len(self._entries)


@dataclass(frozen=True)
class SettlementEvidence:
    """Secret-free domain evidence, not a core delivery authorization.

    Status and payload interpretation belong to the domain. Pending evidence
    may have no reference. The payload mapping is copied; its values stay
    opaque, just as stage objects do in a role table.
    """

    negotiation_id: str
    mechanism: str
    settlement_ref: str | None
    status: str
    evidence: Mapping[str, Any] = field(repr=False)

    def __post_init__(self) -> None:
        _identity(self.negotiation_id, "negotiation_id")
        _identity(self.mechanism, "mechanism")
        _identity(self.status, "status")
        if self.settlement_ref is not None:
            _identity(self.settlement_ref, "settlement_ref")
        if not isinstance(self.evidence, Mapping):
            raise ValueError("evidence must be a mapping")
        object.__setattr__(self, "evidence", MappingProxyType(dict(self.evidence)))

    def validate_identity(
        self,
        *,
        negotiation_id: str,
        mechanism: str,
        settlement_ref: str | None = None,
    ) -> None:
        """Refuse retargeting accepted state or an established reference."""
        if self.negotiation_id != negotiation_id or self.mechanism != mechanism:
            raise ValueError("settlement evidence changed its accepted identity")
        if settlement_ref is not None and self.settlement_ref != settlement_ref:
            raise ValueError("settlement evidence changed its established reference")

    def to_dict(self) -> dict[str, Any]:
        return {
            "negotiation_id": self.negotiation_id,
            "mechanism": self.mechanism,
            "settlement_ref": self.settlement_ref,
            "status": self.status,
            "evidence": dict(self.evidence),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SettlementEvidence:
        return cls(**dict(value))
