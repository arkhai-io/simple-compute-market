"""Bare-metal-owned HTTP carriers that must not imply VM fulfillment."""

from __future__ import annotations

from typing import Literal

from market_identity import Identity
from pydantic import BaseModel, ConfigDict, Field


class BareMetalHealthResponse(BaseModel):
    """Public-safe readiness and identity projection for this storefront."""

    status: str
    checks: dict[str, str] = Field(default_factory=dict)
    paused: bool | None = None
    principal: Identity
    resource_count: int | None = None


class BareMetalSettleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    negotiation_id: str
    buyer_principal: Identity
    buyer_evm_address: str


class BareMetalSettleResponse(BaseModel):
    escrow_uid: str
    negotiation_id: str
    buyer_principal: Identity
    seller_principal: Identity
    status: Literal["settlement_verified"] = "settlement_verified"
    fulfillment_available: Literal[False] = False


class BareMetalSettleStatusResponse(BaseModel):
    escrow_uid: str
    negotiation_id: str
    status: str
    buyer_principal: Identity
    seller_principal: Identity
    fulfillment_available: Literal[False] = False
