"""VM-owned HTTP models for hosted settlement lifecycle routes."""

from __future__ import annotations

from typing import Any

from market_hosted_settlement import FundingProfile
from market_identity import Identity
from pydantic import BaseModel


class SettlementPublicResponse(BaseModel):
    """Public VM projection of one hosted settlement obligation."""

    settlement_ref: str | None = None
    obligation_ref: str
    funding_authorization_ref: str | None = None
    funding_profile: FundingProfile
    payer_principal: Identity
    claimant_principal: Identity
    status: str
    funding_reason: str | None = None
    funding_deadline_unix: int | None = None
    action: dict[str, Any] | None = None
    action_kind: str | None = None
    action_expires_at_unix: int | None = None
    # The buyer's guarantee is that fulfillment is anchored to the condition the
    # authority evaluates, so both halves of that binding are public: the
    # authority's immutable anchor, and the portable evidence reference the
    # seller published against it.
    condition_anchor: str | None = None
    fulfillment_ref: str | None = None
    receipt: dict[str, Any] | None = None
