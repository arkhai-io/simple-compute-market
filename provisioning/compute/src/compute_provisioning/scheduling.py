"""Replaceable policy contracts for capacity settlement scheduling."""

from __future__ import annotations

from typing import Protocol, Sequence

from .physical_settlement import SettlementCandidate, SettlementRequirement


class SettlementSchedulingPolicy(Protocol):
    """Select one eligible concrete candidate without owning orchestration."""

    def select(
        self,
        *,
        requirement: SettlementRequirement,
        candidates: Sequence[SettlementCandidate],
    ) -> SettlementCandidate: ...
