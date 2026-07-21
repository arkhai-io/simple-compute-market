"""Deterministic round-robin policy for eligible settlement candidates.

Moved from ``provisioning/compute/service/src/compute_provisioning_service/
services/deterministic_round_robin_policy.py`` (design.md,
pools-7-storefront-fulfillment-cutover, "Shared package boundary";
tasks.md 1.4). Verified to contain zero VM-specific logic -- it only sorts
``pool_id``/``resource_id`` strings.
"""

from __future__ import annotations

from .settlement_types import NoEligibleSettlementResourceError, SettlementCandidate, SettlementRequirement


class DeterministicRoundRobinPolicy:
    """Round-robin across eligible pools, then resources within that pool."""

    def __init__(self) -> None:
        self._last_pool_id: str | None = None
        self._last_resource_by_pool: dict[str, str] = {}

    @staticmethod
    def _next_after(values: list[str], previous: str | None) -> str:
        if not values:
            raise NoEligibleSettlementResourceError("no eligible values")
        if previous not in values:
            return values[0]
        return values[(values.index(previous) + 1) % len(values)]

    def select(
        self,
        *,
        requirement: SettlementRequirement,
        candidates: list[SettlementCandidate],
    ) -> SettlementCandidate:
        del requirement
        by_pool: dict[str, list[SettlementCandidate]] = {}
        for candidate in candidates:
            by_pool.setdefault(candidate.pool_id, []).append(candidate)
        pool_id = self._next_after(sorted(by_pool), self._last_pool_id)
        resources = sorted(by_pool[pool_id], key=lambda item: item.resource_id)
        resource_id = self._next_after(
            [item.resource_id for item in resources],
            self._last_resource_by_pool.get(pool_id),
        )
        selected = next(item for item in resources if item.resource_id == resource_id)
        self._last_pool_id = pool_id
        self._last_resource_by_pool[pool_id] = resource_id
        return selected
