"""Executor-neutral physical-settlement scheduling shapes.

See openspec/changes/pools-2-physical-settlement-scheduler/design.md for
the design behind PhysicalSettlementScheduler.select_resource(...), which
consumes and returns these models.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator


class PhysicalSettlementRequest(BaseModel):
    """What the scheduler needs to bind an allocation to a settlement resource.

    Carries either fungible pool/capacity attributes (``pool_id``, or
    neither field for "any eligible pool") or an explicit ``resource_id``
    for a specific-resource opt-in listing — never both.
    """

    allocation_id: str = Field(description="Durable idempotency key for this binding.")
    agreement_id: str = Field(description="The market agreement/deal this settlement serves.")
    market: str = Field(description="Market domain identity, e.g. 'vms'.")
    terms: dict[str, Any] = Field(default_factory=dict)
    pool_id: str | None = Field(
        default=None,
        description="Restrict fungible selection to this pool. None means any eligible pool.",
    )
    resource_id: str | None = Field(
        default=None,
        description="Bind exactly this resource (specific-resource opt-in path).",
    )

    @model_validator(mode="after")
    def _pool_and_resource_are_mutually_exclusive(self) -> "PhysicalSettlementRequest":
        if self.pool_id is not None and self.resource_id is not None:
            raise ValueError(
                "pool_id and resource_id are mutually exclusive on a "
                "PhysicalSettlementRequest"
            )
        return self


class SettlementResource(BaseModel):
    """The durable selected physical resource for one allocation's settlement."""

    settlement_resource_id: str
    pool_id: str
    resource_kind: str
    provider: str
    attributes: dict[str, Any] = Field(default_factory=dict)
