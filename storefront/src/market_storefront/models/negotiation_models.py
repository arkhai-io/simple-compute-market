"""HTTP request/response models for the Negotiate and Negotiations controllers."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# /negotiate/new — buyer → seller to start a negotiation
# ---------------------------------------------------------------------------

class NegotiateNewRequest(BaseModel):
    listing_id: str
    buyer_address: str
    initial_price: int = Field(ge=0)
    duration_seconds: int = Field(gt=0)
    buyer_agent_url: str = ""


class NegotiateNewResponse(BaseModel):
    negotiation_id: str
    action: str
    price: int | None = None
    reason: str | None = None


# ---------------------------------------------------------------------------
# /negotiate/{neg_id} — buyer continues an existing negotiation
# ---------------------------------------------------------------------------

class NegotiateContinueRequest(BaseModel):
    action: Literal["counter", "accept", "exit"]
    buyer_address: str
    price: int | None = None
    reason: str | None = None


class NegotiateContinueResponse(BaseModel):
    action: str
    price: int | None = None
    reason: str | None = None


# ---------------------------------------------------------------------------
# /api/v1/listings/{id}/negotiations — admin read and control API
# ---------------------------------------------------------------------------

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

    model_config = {"extra": "allow"}


# ---------------------------------------------------------------------------
# Admin negotiation control
# ---------------------------------------------------------------------------

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
