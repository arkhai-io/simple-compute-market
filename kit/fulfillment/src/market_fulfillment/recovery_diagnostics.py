"""Typed operator-facing fulfillment recovery diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class RecoveryStateDiagnostics:
    """Recovery health for one non-terminal fulfillment lifecycle state."""

    total: int
    actively_claimed: int
    expired_claims: int
    oldest_row_age_seconds: float | None
    max_attempt_count: int

    def as_log_fields(self) -> dict[str, int | float | None]:
        """Return stable primitive fields suitable for structured logging."""

        return {
            "total": self.total,
            "actively_claimed": self.actively_claimed,
            "expired_claims": self.expired_claims,
            "oldest_row_age_seconds": self.oldest_row_age_seconds,
            "max_attempt_count": self.max_attempt_count,
        }


@dataclass(frozen=True)
class RecoveryDiagnostics:
    """One complete fulfillment convergence diagnostics snapshot."""

    per_state: Mapping[str, RecoveryStateDiagnostics]
    failed_count: int
    teardown_failed_count: int

    def as_log_fields(self) -> dict[str, object]:
        """Return the stable operator-facing logging payload."""

        return {
            "per_state": {
                state: diagnostics.as_log_fields()
                for state, diagnostics in self.per_state.items()
            },
            "failed_count": self.failed_count,
            "teardown_failed_count": self.teardown_failed_count,
        }
