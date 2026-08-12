"""VM-owned HTTP models for hosted settlement lifecycle routes."""

from __future__ import annotations

from typing import Any

from market_identity import Identity
from pydantic import BaseModel, ConfigDict, Field


class SettlementStartRequest(BaseModel):
    """Start one accepted hosted obligation for its durable parties."""

    model_config = ConfigDict(extra="forbid")

    negotiation_id: str = Field(min_length=1)
    obligation_ref: str = Field(pattern=r"^[0-9a-f]{64}$")
    payer_principal: Identity
    claimant_principal: Identity


class SettlementPublicResponse(BaseModel):
    """Public VM projection of one hosted settlement obligation."""

    settlement_ref: str | None = None
    payer_principal: Identity
    claimant_principal: Identity
    obligation_ref: str
    status: str
    action: dict[str, Any] | None = None
    action_kind: str | None = None
    action_expires_at_unix: int | None = None
