"""HTTP request/response models for the Listings controller.

Domain types (ComputeResource, TokenResource, Listing) live in domain_models.py.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator
from market_identity import Identity


from market_core.schemas import EscrowDemand


# ---------------------------------------------------------------------------
# Request models
# listing_id is in the URL path for all lifecycle operations.
# ---------------------------------------------------------------------------

class CreateListingRequest(BaseModel):
    """Body for POST /api/v1/listings/create."""
    model_config = ConfigDict(extra="forbid")

    offer: dict[str, Any] = Field(description="Offered compute resource dict")
    accepted_escrows: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Mechanism-specific Alkahest settlement choices.",
    )
    settlement_options: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Mechanism-neutral settlement choices.",
    )
    settlement_config: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Schema-opaque settlement configuration interpreted by the "
            "storefront composition."
        ),
    )
    demands: list[EscrowDemand] = Field(
        default_factory=list,
        description=(
            "Listing-level arbiter demands, independent of accepted escrow "
            "obligation type."
        ),
    )
    max_duration_seconds: int | None = None
    paused: bool = Field(
        default=False,
        description=(
            "If true the listing is created paused and NOT published to the "
            "registry until POST /api/v1/listings/{id}/resume is called."
        ),
    )

    @model_validator(mode="after")
    def require_settlement_choice(self) -> "CreateListingRequest":
        if (
            not self.accepted_escrows
            and not self.settlement_options
            and self.settlement_config is None
        ):
            raise ValueError("at least one settlement choice is required")
        return self


class RefundRequest(BaseModel):
    """Explicit EVM refund inputs bound to the authenticated buyer principal."""
    model_config = ConfigDict(extra="forbid")


    buyer_principal: Identity
    buyer_evm_address: str
    amount: str | int | None = None
    token: str | None = None


class ClaimRequest(BaseModel):
    """Body for POST /api/v1/listings/{listing_id}/claim."""
    model_config = ConfigDict(extra="forbid")


    escrow_uid: str
    claimant_principal: Identity
    fulfillment_uid: str


class ReclaimRequest(BaseModel):
    """Body for POST /api/v1/listings/{listing_id}/reclaim."""
    model_config = ConfigDict(extra="forbid")


    escrow_uid: str
    payer_principal: Identity


class ArbitrateRequest(BaseModel):
    """Body for POST /api/v1/listings/{listing_id}/arbitrate."""
    model_config = ConfigDict(extra="forbid")


    escrow_uid: str | None = None
    fulfillment_uid: str | None = None
    decision: bool = True


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class ListingResponse(BaseModel):
    """Single listing — returned by GET /api/v1/listings/{id}."""

    listing_id: str
    status: str
    paused: bool = False
    offer_resource: Any = None  # dict or JSON string from SQLite
    accepted_escrows: list[dict[str, Any]] | None = None
    demands: list[dict[str, Any]] | None = None
    max_duration_seconds: int | None = None
    storefront_url: str
    seller_principal: Identity
    model_config = ConfigDict(extra="allow")

    @model_validator(mode="before")
    @classmethod
    def reject_legacy_seller_alias(cls, value: Any) -> Any:
        if isinstance(value, dict) and "seller" in value:
            raise ValueError("listing seller alias is not accepted")
        return value


class ListingListResponse(BaseModel):
    """Response for GET /api/v1/listings."""

    listings: list[dict[str, Any]]
    count: int
    limit: int
    offset: int
    total_after_filter: int | None = None


class PauseListingResponse(BaseModel):
    """Response for POST /api/v1/listings/{id}/pause and /resume."""

    listing_id: str
    paused: bool
    registry_status: str = ""
    message: str = ""


class CreateListingResponse(BaseModel):
    """Response for POST /api/v1/listings/create."""

    status: str
    listing_id: str | None = None
    root_agent_response: str = ""


class CloseListingResponse(BaseModel):
    """Response for POST /api/v1/listings/{listing_id}/close."""

    status: str
    listing_id: str
    root_agent_response: str = ""


class RefundResponse(BaseModel):
    """Response for POST /api/v1/listings/{listing_id}/refund."""

    status: str
    listing_id: str
    tx_hash: str | None = None
    from_address: str | None = None
    to_address: str | None = None
    token: dict[str, Any] | None = None
    amount_raw: int | None = None
    block_number: int | None = None


class ClaimResponse(BaseModel):
    """Response for POST /api/v1/listings/{listing_id}/claim."""

    status: str
    listing_id: str
    escrow_uid: str | None = None
    escrow_kind: str | None = None
    fulfillment_uid: str | None = None
    collect_result: str | None = None


class ReclaimResponse(BaseModel):
    """Response for POST /api/v1/listings/{listing_id}/reclaim."""

    status: str
    listing_id: str
    escrow_uid: str | None = None
    escrow_kind: str | None = None
    reclaim_result: str | None = None


class ArbitrateResponse(BaseModel):
    """Response for POST /api/v1/listings/{listing_id}/arbitrate."""

    status: str
    listing_id: str
    fulfillment_uid: str | None = None
    decision: bool = True
    decisions_count: int = 0
    note: str = ""


class EvaluateNegotiateRequest(BaseModel):
    """Body for POST /api/v1/admin/listings/{listing_id}/evaluate-negotiate."""

    proposal: dict[str, Any] = Field(
        description=(
            "The buyer's full EscrowProposal-shaped dict to evaluate, with "
            "``fields['amount']`` carrying the absolute opening amount in base "
            "units of the payment token."
        )
    )
    requested_duration_seconds: int | None = Field(
        default=None,
        description=(
            "Buyer's requested lease duration in seconds. Used to scale the "
            "seller's per-hour reference rate into an absolute amount. "
            "Defaults to 1 hour when omitted."
        ),
    )
    buyer_principal: Identity


class EvaluateNegotiateResponse(BaseModel):
    """Response for POST /api/v1/admin/listings/{listing_id}/evaluate-negotiate.

    Returns what the configured negotiation strategy *would* decide for a
    buyer's opening proposal at this listing — without creating any negotiation
    thread or writing to the database.
    """

    listing_id: str
    our_reference_amount: (
        int  # Seller's absolute reference (per-hour × duration / 3600)
    )
    their_proposed_amount: int  # Echoed back from the request's proposal.fields.amount
    direction: str  # "maximize" (seller always maximises amount)
    strategy: str  # e.g. "bisection" or "rl"
    decision: str  # "accept" | "counter" | "exit"
    decision_amount: int | None = None
    decision_proposal: dict[str, Any] | None = None
    decision_reason: str | None = None
    would_negotiate: bool  # True when decision != "exit"
