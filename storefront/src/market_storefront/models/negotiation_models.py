"""HTTP request/response models for the Negotiate and Negotiations controllers."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from service.schemas import EscrowProposal, ProvisionTerms


class NegotiateNewRequest(BaseModel):
    """Round 0 of a negotiation.

    The buyer publishes the structured artifacts they're proposing:
    ``provision_terms`` (what they want the seller to deliver) and
    ``escrow_proposal`` (the on-chain escrow tuple they pick from the
    listing's ``accepted_escrows`` plus the ABI-defined ``fields``).
    Both are validated against the listing's acceptance set on the
    seller side.
    """

    listing_id: str
    buyer_address: str
    initial_price: int = Field(ge=0)
    provision_terms: ProvisionTerms
    escrow_proposal: EscrowProposal
    buyer_agent_url: str = ""


class NegotiateNewResponse(BaseModel):
    """Seller's round-0 response.

    ``accepted_provision_terms`` and ``accepted_escrow_proposal``
    echo back what the seller validated against its listing. They appear
    on every non-rejection response (counter, accept) so the buyer can
    use the seller-confirmed values rather than its local proposal —
    protects against accidental drift between sides.
    """

    negotiation_id: str
    action: str
    price: int | None = None
    reason: str | None = None
    accepted_provision_terms: ProvisionTerms | None = None
    accepted_escrow_proposal: EscrowProposal | None = None


class NegotiateContinueRequest(BaseModel):
    action: Literal["counter", "accept", "exit"]
    buyer_address: str
    price: int | None = None
    reason: str | None = None


class NegotiateContinueResponse(BaseModel):
    action: str
    price: int | None = None
    reason: str | None = None


class NegotiationSummary(BaseModel):
    negotiation_id: str
    our_listing_id: str
    their_agent_id: str | None = None
    terminal_state: str | None = None
    agreed_price: int | None = None
    round_count: int = 0
    created_at: str | None = None
    model_config = {"extra": "allow"}


class NegotiationListResponse(BaseModel):
    listing_id: str
    negotiations: list[dict[str, Any]]
    count: int
    limit: int
    offset: int


class NegotiationMessage(BaseModel):
    round: int
    sender: str
    action_taken: str
    proposed_price: int | None = None
    model_config = {"extra": "allow"}


class NegotiationDetailResponse(BaseModel):
    negotiation_id: str
    our_listing_id: str
    their_agent_id: str | None = None
    terminal_state: str | None = None
    agreed_price: int | None = None
    round_count: int = 0
    messages: list[dict[str, Any]] = Field(default_factory=list)
    stage_events: list[dict[str, Any]] = Field(default_factory=list)
    escrows: list[dict[str, Any]] = Field(default_factory=list)
    model_config = {"extra": "allow"}


class AdvanceRequest(BaseModel):
    action: Literal["counter", "accept", "exit"]
    price: int | None = None
    reason: str | None = None


class ForceAcceptRequest(BaseModel):
    price: int


class ForceAcceptResponse(BaseModel):
    action: str
    price: int
    source: str = "admin_force_accept"


class AdvanceResponse(BaseModel):
    action: str
    price: int | None = None
    reason: str | None = None
