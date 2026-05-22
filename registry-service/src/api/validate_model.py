"""Pydantic models for POST /api/v1/listings/validate-publish."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ValidatePublishRequest(BaseModel):
    """Body for POST /api/v1/listings/validate-publish.

    Mirrors the non-auth fields of POST /agents/{agent_id}/listings so
    tests can pass the same listing payload they constructed locally.
    No agent_id or signature is required — this endpoint never writes.
    """

    listing_id: str = Field(description="Listing ID to validate")
    seller: str = Field(
        default="",
        description="Seller agent-card URL. Required by listing_shape v2+.",
    )
    offer_resource: dict[str, Any] = Field(
        default_factory=dict, description="Offered resource dict"
    )
    accepted_escrows: list[dict[str, Any]] = Field(
        default_factory=list,
        description="List of escrow tuples the seller will accept",
    )
    max_duration_seconds: int | None = Field(
        default=None, description="Optional lease duration ceiling in seconds"
    )


class ValidatePublishResponse(BaseModel):
    """Result of POST /api/v1/listings/validate-publish.

    ``valid`` is True when all structural checks pass — the payload
    would be accepted by POST /agents/{agent_id}/listings (ignoring
    auth and agent registration, which are environment concerns).
    When ``valid`` is False, ``errors`` lists the specific problems.
    """

    valid: bool
    listing_id: str
    offer_resource_type: str | None = None   # "compute" | "token" | "unknown"
    accepted_escrows_count: int = 0
    errors: list[str] = Field(default_factory=list)
