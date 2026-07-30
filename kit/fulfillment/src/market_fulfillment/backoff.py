"""Deterministic exponential backoff with injectable jitter."""
from __future__ import annotations

from dataclasses import dataclass, field
from random import Random


@dataclass(frozen=True)
class Backoff:
    """Computes a claim-lease length that grows with ``attempt_count``.

    ``attempt_count`` is expected to already reflect the current claim
    (i.e. incremented by ``SettlementRepository.claim_pending`` before this
    is called) -- ``attempt_count=1`` is the first claim and returns
    approximately ``initial_seconds``.
    """

    initial_seconds: float
    multiplier: float
    max_seconds: float
    jitter_fraction: float = 0.0
    random_source: Random = field(default_factory=Random)

    def delay_seconds(self, attempt_count: int) -> float:
        attempt_index = max(0, attempt_count - 1)
        base = min(
            self.initial_seconds * (self.multiplier**attempt_index),
            self.max_seconds,
        )
        if self.jitter_fraction <= 0:
            return float(base)
        factor = 1.0 + self.jitter_fraction * ((2.0 * self.random_source.random()) - 1.0)
        return max(0.0, float(base) * factor)
