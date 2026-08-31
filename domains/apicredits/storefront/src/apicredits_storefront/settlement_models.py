"""Strict API-credit models for legacy Alkahest and shared hosted routes."""

from __future__ import annotations

from typing import Any, Literal

from core_storefront.models.settle_models import SettleRequest
from market_identity import Identity
from pydantic import BaseModel, ConfigDict, Field


class ApiCreditsSettleRequest(SettleRequest):
    """Strict EVM settlement input for API-credit issuance."""

    buyer_evm_address: str
    chain_name: str


class ApiCreditsHostedSettlementResponse(BaseModel):
    """Authenticated provider-free projection of one hosted credit purchase."""

    model_config = ConfigDict(extra="forbid")

    settlement_ref: str
    obligation_ref: str
    funding_authorization_ref: str
    funding_profile: Literal[
        "card.v1",
        "us_bank_transfer.v1",
        "us_ach_debit.v1",
    ]
    payer_principal: Identity
    claimant_principal: Identity
    status: str
    funding_reason: str | None = None
    funding_deadline_unix: int | None = None
    action: dict[str, Any] | None = None
    action_kind: str | None = None
    action_expires_at_unix: int | None = None
    receipt: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    tenant_credentials: dict[str, Any] | None = Field(default=None, repr=False)
