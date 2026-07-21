"""Replaceable policy contracts for capacity settlement scheduling.

Moved from ``provisioning/compute/src/compute_provisioning/scheduling.py``
(design.md, pools-7-storefront-fulfillment-cutover, "Shared package
boundary"; tasks.md 1.4).
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
