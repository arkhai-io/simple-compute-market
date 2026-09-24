"""The VM market's storefront pool override terms.

A pool override's ``terms`` are opaque to the pool-override kit; for the VM
offering mode they are these. Each is optional: an unset term states nothing,
and the next precedence tier supplies it.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr


class VmPoolOverrideTerms(BaseModel):
    """What a VM override may say about a pool's commercial terms."""

    model_config = ConfigDict(extra="forbid")

    sla: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    min_price: StrictStr | None = None
    token: StrictStr | None = None
    max_duration_seconds: StrictInt | None = Field(default=None, gt=0)
