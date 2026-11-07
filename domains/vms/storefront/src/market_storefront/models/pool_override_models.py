"""The VM market's storefront pool override terms.

A pool override's ``terms`` are opaque to the pool-override kit; for the VM
offering mode they are these. Each is optional: an unset term states nothing,
and the next precedence tier supplies it.
"""

from __future__ import annotations

from typing import Any

from arkhai_vms_listings.pricing_resolution import family_rate_terms_problems
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator


class VmPoolOverrideTerms(BaseModel):
    """What a VM override may say about a pool's commercial terms.

    ``pricing`` states family rates in the pool pricing hint's nesting —
    ``{"gpu": {"<model>": {"rates": [...]}}, "cpu": {"rates": [...]}}`` — and
    nothing else. ``min_price`` and ``token`` are not terms, so a write stating
    them is refused; a stored override that still carries them is reported
    by derivation and otherwise read as if they were absent.
    """

    model_config = ConfigDict(extra="forbid")

    sla: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    max_duration_seconds: StrictInt | None = Field(default=None, gt=0)
    pricing: dict[str, Any] | None = None

    @field_validator("pricing")
    @classmethod
    def _family_rates_are_readable(
        cls, value: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        if value is None:
            return None
        problems = family_rate_terms_problems(value)
        if problems:
            raise ValueError("; ".join(problems))
        return value
