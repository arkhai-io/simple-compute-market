"""HTTP request/response models for the deal-servicing endpoints."""

from __future__ import annotations

from typing import Any

from market_identity import Identity
from pydantic import BaseModel, ConfigDict, Field


class DealHeartbeatRequest(BaseModel):
    """One body-bound liveness attestation from the recorded buyer principal."""
    model_config = ConfigDict(extra="forbid")


    buyer_principal: Identity
    seller_principal: Identity
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Schema-tagged attestation payload. Opaque to core.",
    )


class DealHeartbeatResponse(BaseModel):
    deal_ref: str
    buyer_principal: Identity
    seller_principal: Identity
    sent_at_unix: float
    heartbeat_count: int = Field(
        description="Total heartbeats recorded for this deal so far.",
    )
    next_expected_by_unix: float | None = Field(
        default=None,
        description=(
            "Hint for the next expected heartbeat. Advisory; lifecycle policy owns gating."
        ),
    )
