"""Deterministic round-robin settlement scheduling policy.

The policy is domain-neutral and pure: it orders and selects normalized
settlement candidates from explicit inputs, without importing VM, executor,
or provider-specific vocabulary and without any database access of its own.
See ``openspec/specs/fulfillment/spec.md#scheduling-and-assignment``.
"""

from __future__ import annotations

from .scheduling import SchedulingCursorState
from .settlement_types import NoEligibleSettlementResourceError, SettlementCandidate, SettlementRequirement


class DeterministicRoundRobinPolicy:
    """Round-robin across eligible pools, then resources within that pool.

    Stateless: every call takes the prior cursor as an argument and returns
    the next one rather than mutating instance attributes. This lets a
    single instance be shared safely across concurrent scheduling attempts
    for different fairness scopes (see ``SchedulingCursorState``) and lets
    the caller persist the returned cursor transactionally alongside the
    settlement record it accompanies.
    """

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
        cursor: SchedulingCursorState,
    ) -> tuple[SettlementCandidate, SchedulingCursorState]:
        del requirement
        by_pool: dict[str, list[SettlementCandidate]] = {}
        for candidate in candidates:
            by_pool.setdefault(candidate.pool_id, []).append(candidate)
        pool_id = self._next_after(sorted(by_pool), cursor.last_pool_id)
        resources = sorted(by_pool[pool_id], key=lambda item: item.resource_id)
        last_resource_by_pool = dict(cursor.last_resource_by_pool)
        resource_id = self._next_after(
            [item.resource_id for item in resources],
            last_resource_by_pool.get(pool_id),
        )
        selected = next(item for item in resources if item.resource_id == resource_id)
        last_resource_by_pool[pool_id] = resource_id
        updated_cursor = SchedulingCursorState(
            last_pool_id=pool_id,
            last_resource_by_pool=last_resource_by_pool,
        )
        return selected, updated_cursor
