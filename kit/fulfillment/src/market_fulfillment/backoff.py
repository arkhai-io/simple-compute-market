"""Deterministic exponential backoff with injectable jitter."""
from __future__ import annotations

from dataclasses import dataclass
from random import Random


@dataclass(frozen=True)
class Backoff:
    initial_seconds: float
    multiplier: float
    max_seconds: float
    jitter_fraction: float = 0.0
    random_source: Random | None = None

    def delay_seconds(self, attempt_count: int) -> float:
        attempt_index = max(0, attempt_count - 1)
        base = min(
            self.initial_seconds * (self.multiplier ** attempt_index),
            self.max_seconds,
        )
        if self.jitter_fraction <= 0:
            return float(base)
        rng = self.random_source or Random()
        factor = 1.0 + self.jitter_fraction * ((2.0 * rng.random()) - 1.0)
        return max(0.0, float(base) * factor)
