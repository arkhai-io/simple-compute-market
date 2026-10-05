"""Who a job acts for, and how a repeated submission is recognized.

A fulfillment provider submits each job it dispatches with a ``JobActionRequest``:
the capacity reservation the job serves, the caller's opaque deal reference, the
offering mode and action, and the idempotency key. It is the job authority's own
correlation and idempotency record, never a request any route accepts. The job's
content is the parameters submitted beside it, which the engine persists and
compares: a repeated identity with the same parameters returns the job already
recorded, and one with different parameters is refused.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class JobActionRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    capacity_reservation_id: str = Field(min_length=1)
    deal_ref: dict[str, Any]
    offering_mode: str = Field(min_length=1)
    action_kind: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)


__all__ = ["JobActionRequest"]
