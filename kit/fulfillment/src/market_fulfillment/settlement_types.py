"""Domain-neutral physical settlement request and resource carriers.

The provisioning boundary is capacity-reservation-centric. Commercial agreement
identity remains with the storefront, while normalized multidimensional
requirements cross into fulfillment.
See ``openspec/specs/fulfillment/spec.md#physical-settlement-request``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field, field_validator


class PhysicalSettlementError(Exception):
    """Base error for settlement scheduling failures."""


class SettlementEntityNotFoundError(PhysicalSettlementError):
    """A referenced capacity reservation, pool, or resource does not exist."""


class SettlementRequestMismatchError(PhysicalSettlementError):
    """Existing entities do not correspond to the supplied request."""


class CapacityReservationExpiredError(PhysicalSettlementError):
    """The referenced capacity reservation has expired."""


class NoEligibleSettlementResourceError(PhysicalSettlementError):
    """No enabled resource can satisfy the validated reservation."""


class PhysicalSettlementRequest(BaseModel):
    """Request to create or retrieve one Capacity Settlement Assignment."""

    capacity_reservation_id: str = Field(
        description="Capacity Reservation identifier and idempotency key."
    )
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
    """Generic capacity shape used to evaluate concrete candidates.

    ``dimensions`` At least one positive dimension is required.
    """

    resource_kind: str
    dimensions: dict[str, Decimal] = Field(default_factory=dict)
    attributes: dict[str, Any] = Field(default_factory=dict)

    @field_validator("dimensions")
    @classmethod
    def _dimensions_positive_and_nonempty(cls, value: dict[str, Decimal]) -> dict[str, Decimal]:
        if not value:
            raise ValueError("dimensions must declare at least one quantity")
        for key, amount in value.items():
            # NaN/Infinity parse cleanly through pydantic's Decimal
            # coercion but raise InvalidOperation on comparison.
            if not amount.is_finite():
                raise ValueError(f"dimensions[{key}] must be a finite number, got {amount}")
            if amount <= 0:
                raise ValueError(f"dimensions[{key}] must be > 0, got {amount}")
        return value


class SettlementCandidate(BaseModel):
    """One concrete resource eligible for physical settlement evaluation.

    ``available`` A dimension a candidate never mentions is treated
    as unavailable (zero), matching the ledger's hard fit rule.
    """

    resource_id: str
    pool_id: str
    resource_kind: str
    available: dict[str, Decimal] = Field(default_factory=dict)
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
    # The reservation's own committed dimensions (see SettlementRequirement
    # .dimensions), carried forward from scheduling so a provider can
    # derive request-shape fields (VM GPU/CPU/RAM/disk, for example) from
    # what was actually reserved rather than trusting a second,
    # independently-computed copy the caller supplies alongside the
    # fulfillment request. Opaque to this kit -- dimension keys and units
    # are entirely domain-defined.
    dimensions: dict[str, Any] = Field(default_factory=dict)
