"""HTTP request/response models for the Negotiate and Negotiations controllers."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from market_identity import Identity


from market_core.schemas import (
    EscrowProposal,
    ProvisionTerms,
    SettlementPlan,
    SettlementSelection,
)


class NegotiateNewRequest(BaseModel):
    """Round 0 of a negotiation.

    The buyer publishes two structured artifacts: ``provision_terms``
    (what they want delivered) and ``proposal`` (the on-chain escrow
    tuple, picked from the listing's ``accepted_escrows``). Scalar payment
    escrows carry the buyer's absolute opening bid in ``fields["amount"]``;
    amountless exact escrows may omit it. Both artifacts are validated
    against the listing's acceptance set on the seller side.
    """
    model_config = ConfigDict(extra="forbid")


    listing_id: str
    buyer_principal: Identity
    provision_terms: ProvisionTerms
    proposal: dict[str, Any] | None = None
    settlement_selection: SettlementSelection | None = None
    buyer_agent_url: str = ""


class NegotiateNewResponse(BaseModel):
    """Seller's round-0 response.

    ``proposal`` carries the seller's counter (when action="counter")
    or the agreed proposal echoed back (when action="accept"). For
    "exit" / "reject" it's absent. ``accepted_provision_terms`` and
    ``accepted_escrow_proposal`` echo back the buyer's round-0 ask
    after the seller validated it.

    ``settlement_plan`` is the negotiated outcome's canonical carrier
    (mechanism-neutral obligations); ``accepted_escrow_terms`` is its
    LEGACY flat-alkahest mirror, kept for buyers that predate the plan
    carrier and removed with the client-wheel wire bump.
    """

    negotiation_id: str
    buyer_principal: Identity
    seller_principal: Identity
    action: str
    proposal: dict[str, Any] | None = None
    reason: str | None = None
    accepted_provision_terms: ProvisionTerms | None = None
    accepted_escrow_proposal: EscrowProposal | None = None
    settlement_selection: SettlementSelection | None = None
    settlement_plan: SettlementPlan | None = None
    accepted_escrow_terms: list[dict[str, Any]] | None = None


class NegotiateContinueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["counter", "accept", "exit"]
    buyer_principal: Identity
    proposal: dict[str, Any] | None = None
    settlement_selection: SettlementSelection | None = None
    reason: str | None = None


class NegotiateContinueResponse(BaseModel):
    action: str
    buyer_principal: Identity
    seller_principal: Identity
    proposal: dict[str, Any] | None = None
    reason: str | None = None
    accepted_escrow_proposal: EscrowProposal | None = None
    settlement_plan: SettlementPlan | None = None
    settlement_selection: SettlementSelection | None = None
    accepted_escrow_terms: list[dict[str, Any]] | None = None


class NegotiationSummary(BaseModel):
    negotiation_id: str
    our_listing_id: str
    their_agent_id: str | None = None
    buyer_principal: Identity | None = None
    seller_principal: Identity | None = None
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
    sender_role: Literal["buyer", "seller", "admin", "service"]
    sender_principal: Identity
    action_taken: str
    proposed_amount: int | None = None
    model_config = {"extra": "allow"}


class NegotiationDetailResponse(BaseModel):
    negotiation_id: str
    our_listing_id: str
    their_agent_id: str | None = None
    buyer_principal: Identity | None = None
    seller_principal: Identity | None = None
    terminal_state: str | None = None
    agreed_amount: int | None = None
    round_count: int = 0
    messages: list[dict[str, Any]] = Field(default_factory=list)
    stage_events: list[dict[str, Any]] = Field(default_factory=list)
    escrows: list[dict[str, Any]] = Field(default_factory=list)
    model_config = {"extra": "allow"}


class AdvanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["counter", "accept", "exit"]
    proposal: dict[str, Any] | None = None
    reason: str | None = None


class ForceAcceptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: int


class ForceAcceptResponse(BaseModel):
    action: str
    amount: int
    source: str = "admin_force_accept"


class AdvanceResponse(BaseModel):
    action: str
    proposal: dict[str, Any] | None = None
    reason: str | None = None
