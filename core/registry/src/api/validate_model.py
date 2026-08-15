"""Pydantic models for POST /api/v1/listings/validate-publish."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ValidatePublishRequest(BaseModel):
    """Body for POST /api/v1/listings/validate-publish.

    Carries the same listing fields as POST /listings. The route authenticates
    the complete normalized model as a canonical v2 marketplace request before
    performing its read-only schema check.
    """

    listing_id: str = Field(description="Listing ID to validate")
    storefront_url: str = Field(
        default="",
        description="Publisher's storefront URL. Required by listing_shape v4+.",
    )
    offer_resource: dict[str, Any] = Field(
        default_factory=dict, description="Offered resource dict"
    )
    accepted_escrows: list[dict[str, Any]] = Field(
        default_factory=list,
        description="List of escrow tuples the seller will accept",
    )
    settlement_options: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Mechanism-neutral settlement choices",
    )
    demands: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Listing-level arbiter demands",
    )
    max_duration_seconds: int | None = Field(
        default=None, description="Optional lease duration ceiling in seconds"
    )


class ValidatePublishResponse(BaseModel):
    """Result of POST /api/v1/listings/validate-publish.

    ``valid`` is True when all structural checks pass — the normalized payload
    would be accepted by POST /listings after the caller separately satisfies
    publisher ownership.
    When ``valid`` is False, ``errors`` lists the specific problems.
    """

    valid: bool
    listing_id: str
    offer_resource_type: str | None = None   # "compute" | "token" | "unknown"
    accepted_escrows_count: int = 0
    settlement_options_count: int = 0
    errors: list[str] = Field(default_factory=list)
