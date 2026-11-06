"""Composition-owned rate contract selection, independent of offer contents.

This gate admits new offers and acceptances only. Accepted-deal continuation must
not use offer eligibility to decide whether existing work is still serviced.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from market_core.schemas import SettlementOption


class RateServicingUnavailable(ValueError):
    """The selected rate contract is withdrawn; the buyer must refetch."""


@dataclass(frozen=True)
class RateServicingDeclaration:
    mechanism: str
    contract_revision: str
    publication: Literal["published", "proposed"]
    lane_identity: str | None = None

    def __post_init__(self) -> None:
        if not self.mechanism.strip() or not self.contract_revision.strip():
            raise ValueError("rate servicing requires a mechanism and contract revision")
        if self.publication not in {"published", "proposed"}:
            raise ValueError("rate servicing contract must be published or proposed")
        if self.publication == "proposed" and not (self.lane_identity or "").strip():
            raise ValueError("proposed rate servicing requires a stable test lane identity")
        if self.publication == "published" and self.lane_identity is not None:
            raise ValueError("published rate servicing is not a proposed test lane")


@dataclass(frozen=True)
class RateServicing:
    """Select current declarations against adapter-owned required revisions.

    Composition supplies both mappings, never a listing or request. A proposed
    declaration is usable only when its lane exactly matches the explicit opt-in.
    Consumers share this object so withdrawal is checked again at acceptance.
    """

    required_contracts: Mapping[str, str] = field(default_factory=dict)
    declarations: Mapping[str, RateServicingDeclaration] = field(default_factory=dict)
    proposed_lane: str | None = None

    def select(self, mechanism: str) -> RateServicingDeclaration:
        expected = self.required_contracts.get(mechanism)
        declared = self.declarations.get(mechanism)
        if (
            not expected or declared is None
            or declared.mechanism != mechanism
            or declared.contract_revision != expected
            or (declared.publication == "proposed" and (
                not self.proposed_lane or declared.lane_identity != self.proposed_lane
            ))
        ):
            raise RateServicingUnavailable(
                "settlement_option_withdrawn_refetch: compatible rate servicing "
                f"is undeclared for {mechanism!r}"
            )
        return declared

    def require_option(self, option: SettlementOption | Mapping[str, Any]) -> None:
        selected = SettlementOption.model_validate(option)
        # Either rate marker requires servicing even if the other is malformed
        # or absent. The mechanism codec still owns period parsing and support;
        # an unreadable rate must never slip through as an ordinary once option.
        if "period" in selected.settlement or "reserve_ahead_seconds" in selected.settlement:
            self.select(selected.settlement_schema)
