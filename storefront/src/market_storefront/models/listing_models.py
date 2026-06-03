"""HTTP request/response models for the Listings controller.

Domain types (ComputeResource, TokenResource, Listing) live in domain_models.py.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ---------------------------------------------------------------------------
# Request models
# listing_id is in the URL path for all lifecycle operations.
# ---------------------------------------------------------------------------

class CreateListingRequest(BaseModel):
    """Body for POST /api/v1/listings/create."""
    offer: dict[str, Any] = Field(description="Offered compute resource dict")
    accepted_escrows: list[dict[str, Any]] = Field(
        description=(
            "List of escrow shapes the seller will accept for this listing. "
            "Each entry: {chain_name, escrow_address, literal_fields, rates}. "
            "Must be non-empty."
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


class RefundRequest(BaseModel):
    """Body for POST /api/v1/listings/{listing_id}/refund.
    listing_id is in the path; this body contains the payment details only.

    ``buyer_address`` defaults to the listing's recorded buyer (the
    storefront DB knows it once a deal closes); pass explicitly to
    override. ``token`` (when given) is a 0x contract address. ``amount``
    is a non-negative decimal-digit string in base units (uint256-safe);
    Python int is accepted too for in-process callers. Human-decimal
    scaling is a client concern — the storefront expects already-scaled
    base-unit values.
    """
    buyer_address: str | None = None
    amount: str | int | None = None
    token: str | None = None


class ClaimRequest(BaseModel):
    """Body for POST /api/v1/listings/{listing_id}/claim."""
    escrow_uid: str
    fulfillment_uid: str


class ReclaimRequest(BaseModel):
    """Body for POST /api/v1/listings/{listing_id}/reclaim."""
    escrow_uid: str


class ArbitrateRequest(BaseModel):
    """Body for POST /api/v1/listings/{listing_id}/arbitrate."""
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
    offer_resource: Any = None    # dict or JSON string from SQLite
    accepted_escrows: list[dict[str, Any]] | None = None
    max_duration_seconds: int | None = None
    seller: str | None = None
    model_config = ConfigDict(extra="allow")


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
    fulfillment_uid: str | None = None
    collect_result: str | None = None


class ReclaimResponse(BaseModel):
    """Response for POST /api/v1/listings/{listing_id}/reclaim."""
    status: str
    listing_id: str
    escrow_uid: str | None = None
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
    buyer_address: str = Field(
        default="",
        description="Buyer wallet address (used for logging/context only; not auth-checked)",
    )


class EvaluateNegotiateResponse(BaseModel):
    """Response for POST /api/v1/admin/listings/{listing_id}/evaluate-negotiate.

    Returns what the configured negotiation strategy *would* decide for a
    buyer's opening proposal at this listing — without creating any negotiation
    thread or writing to the database.
    """
    listing_id: str
    our_reference_amount: int        # Seller's absolute reference (per-hour × duration / 3600)
    their_proposed_amount: int       # Echoed back from the request's proposal.fields.amount
    direction: str                   # "maximize" (seller always maximises amount)
    strategy: str                    # e.g. "bisection" or "rl"
    decision: str                    # "accept" | "counter" | "exit"
    decision_amount: int | None = None
    decision_proposal: dict[str, Any] | None = None
    decision_reason: str | None = None
    would_negotiate: bool            # True when decision != "exit"
