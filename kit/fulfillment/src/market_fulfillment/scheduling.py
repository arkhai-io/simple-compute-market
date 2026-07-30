"""Policy contract for selecting among eligible settlement candidates.

See ``openspec/specs/fulfillment/spec.md#scheduling-and-assignment``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Protocol, Sequence

from .settlement_types import SettlementCandidate, SettlementRequirement


@dataclass(frozen=True)
class SchedulingCursorState:
    """Immutable round-robin position for one fairness scope.

    A pure value carried into and out of ``SettlementSchedulingPolicy.select``.
    It has no database dependency: the caller (``PhysicalSettlementScheduler``)
    is responsible for reading it from and writing it back to durable storage
    inside its own transaction. Keeping this a plain value, rather than a
    database row, keeps the policy unit-testable without a session.
    """

    last_pool_id: str | None = None
    last_resource_by_pool: Mapping[str, str] = field(default_factory=dict)


class SettlementSchedulingPolicy(Protocol):
    """Select one eligible concrete candidate without owning orchestration.

    ``select`` is a pure function of its explicit inputs: it must not read or
    write a database, and it returns the fairness state it would like
    persisted rather than mutating instance state. The caller decides how
    and when that returned state is made durable.
    """

    def select(
        self,
        *,
        requirement: SettlementRequirement,
        candidates: Sequence[SettlementCandidate],
        cursor: SchedulingCursorState,
    ) -> tuple[SettlementCandidate, SchedulingCursorState]: ...
