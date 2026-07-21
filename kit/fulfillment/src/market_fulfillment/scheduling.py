"""Policy contract for selecting among eligible settlement candidates.

See ``openspec/specs/fulfillment/spec.md#scheduling-and-assignment``.
"""

from __future__ import annotations

from typing import Protocol, Sequence

from .settlement_types import SettlementCandidate, SettlementRequirement


class SettlementSchedulingPolicy(Protocol):
    """Select one eligible concrete candidate without owning orchestration."""

    def select(
        self,
        *,
        requirement: SettlementRequirement,
        candidates: Sequence[SettlementCandidate],
    ) -> SettlementCandidate: ...
