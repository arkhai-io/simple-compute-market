"""Executor-neutral contracts for capacity settlement scheduling."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PhysicalSettlementError(Exception):
    """Base error for settlement scheduling failures."""


class SettlementEntityNotFoundError(PhysicalSettlementError):
    """A referenced allocation, agreement, pool, or resource does not exist."""


class SettlementRequestMismatchError(PhysicalSettlementError):
    """Existing entities do not correspond to the supplied request."""


class CapacityReservationExpiredError(PhysicalSettlementError):
    """The referenced capacity reservation has expired."""


class NoEligibleSettlementResourceError(PhysicalSettlementError):
    """No enabled resource can satisfy the validated reservation."""


class PhysicalSettlementRequest(BaseModel):
    """Request to create or retrieve one Capacity Settlement Assignment."""

    allocation_id: str = Field(description="Capacity Reservation identifier and idempotency key.")
    agreement_id: str = Field(description="Agreement served by this settlement.")
    market: str = Field(description="Market domain identity, for example 'vms'.")
    requirements: dict[str, Any] = Field(default_factory=dict)
    resource_id: str | None = Field(
        default=None,
        description=(
            "Optional exact resource constraint. Explicit selection bypasses policy "
            "choice, never eligibility validation."
        ),
    )


class SettlementRequirement(BaseModel):
    """Generic capacity shape used to evaluate concrete candidates."""

    resource_kind: str
    units: int = Field(gt=0)
    attributes: dict[str, Any] = Field(default_factory=dict)


class SettlementCandidate(BaseModel):
    """One concrete resource eligible for physical settlement evaluation."""

    resource_id: str
    pool_id: str
    resource_kind: str
    available_units: int
    enabled: bool = True
    provider: str
    attributes: dict[str, Any] = Field(default_factory=dict)


class SettlementResource(BaseModel):
    """The selected physical resource in a Capacity Settlement Assignment."""

    settlement_resource_id: str
    pool_id: str
    resource_kind: str
    provider: str
    attributes: dict[str, Any] = Field(default_factory=dict)


class CapacitySettlementAssignment(BaseModel):
    """Idempotent allocation-to-resource scheduling decision."""

    allocation_id: str
    agreement_id: str
    resource: SettlementResource
