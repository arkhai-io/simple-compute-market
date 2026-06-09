"""HTTP request/response models for the Negotiate and Negotiations controllers."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from market_core.schemas import EscrowProposal, ProvisionTerms


class NegotiateNewRequest(BaseModel):
    """Round 0 of a negotiation.

    The buyer publishes two structured artifacts: ``provision_terms``
    (what they want delivered) and ``proposal`` (the on-chain escrow
    tuple, picked from the listing's ``accepted_escrows``). Scalar payment
    escrows carry the buyer's absolute opening bid in ``fields["amount"]``;
    amountless exact escrows may omit it. Both artifacts are validated
    against the listing's acceptance set on the seller side.
    """

    listing_id: str
    buyer_address: str
    provision_terms: ProvisionTerms
    proposal: EscrowProposal
    buyer_agent_url: str = ""


class NegotiateNewResponse(BaseModel):
    """Seller's round-0 response.

    ``proposal`` carries the seller's counter (when action="counter")
    or the agreed proposal echoed back (when action="accept"). For
    "exit" / "reject" it's absent. ``accepted_provision_terms`` and
    ``accepted_escrow_proposal`` echo back the buyer's round-0 ask
    after the seller validated it.
    """

    negotiation_id: str
    action: str
    proposal: dict[str, Any] | None = None
    reason: str | None = None
    accepted_provision_terms: ProvisionTerms | None = None
    accepted_escrow_proposal: EscrowProposal | None = None
    accepted_escrow_terms: list[dict[str, Any]] | None = None


class NegotiateContinueRequest(BaseModel):
    action: Literal["counter", "accept", "exit"]
    buyer_address: str
    proposal: dict[str, Any] | None = None
    reason: str | None = None


class NegotiateContinueResponse(BaseModel):
    action: str
    proposal: dict[str, Any] | None = None
    reason: str | None = None
    accepted_escrow_proposal: EscrowProposal | None = None
    accepted_escrow_terms: list[dict[str, Any]] | None = None


class NegotiationSummary(BaseModel):
    negotiation_id: str
    our_listing_id: str
    their_agent_id: str | None = None
    terminal_state: str | None = None
    agreed_amount: int | None = None
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
    proposed_amount: int | None = None
    model_config = {"extra": "allow"}


class NegotiationDetailResponse(BaseModel):
    negotiation_id: str
    our_listing_id: str
    their_agent_id: str | None = None
    terminal_state: str | None = None
    agreed_amount: int | None = None
    round_count: int = 0
    messages: list[dict[str, Any]] = Field(default_factory=list)
    stage_events: list[dict[str, Any]] = Field(default_factory=list)
    escrows: list[dict[str, Any]] = Field(default_factory=list)
    model_config = {"extra": "allow"}


class AdvanceRequest(BaseModel):
    action: Literal["counter", "accept", "exit"]
    proposal: dict[str, Any] | None = None
    reason: str | None = None


class ForceAcceptRequest(BaseModel):
    amount: int


class ForceAcceptResponse(BaseModel):
    action: str
    amount: int
    source: str = "admin_force_accept"


class AdvanceResponse(BaseModel):
    action: str
    proposal: dict[str, Any] | None = None
    reason: str | None = None
