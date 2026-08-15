"""Bare-metal-owned HTTP carriers that must not imply VM fulfillment."""

from __future__ import annotations

from typing import Literal

from market_identity import Identity
from pydantic import BaseModel, ConfigDict, Field
from arkhai_bare_metal import BareMetalAccessResult, BareMetalReceipt


class BareMetalHealthResponse(BaseModel):
    """Public-safe readiness and identity projection for this storefront."""

    status: str
    checks: dict[str, str] = Field(default_factory=dict)
    paused: bool | None = None
    principal: Identity
    sites: list[dict[str, object]] = Field(default_factory=list)
    resource_count: int | None = None


class BareMetalFulfillRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    negotiation_id: str = Field(min_length=1)
    escrow_uid: str = Field(min_length=1)
    buyer_principal: Identity


class BareMetalFulfillmentResponse(BaseModel):
    negotiation_id: str
    escrow_uid: str
    site_id: str
    capacity_reservation_id: str | None = None
    settlement_resource_id: str | None = None
    fulfillment_id: str | None = None
    state: str
    failure_reason: str | None = None


class BareMetalFulfillmentResultResponse(BaseModel):
    negotiation_id: str
    receipt: BareMetalReceipt
    result: BareMetalAccessResult


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
    fulfillment_available: Literal[True] = True


class BareMetalSettleStatusResponse(BaseModel):
    escrow_uid: str
    negotiation_id: str
    status: str
    buyer_principal: Identity
    seller_principal: Identity
    fulfillment_available: Literal[True] = True
