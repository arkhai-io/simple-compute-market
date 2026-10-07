"""Bare-metal-owned HTTP carriers that must not imply VM fulfillment."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from arkhai_bare_metal import (
    BareMetalAccessResult,
    BareMetalReceipt,
)
from market_identity import Identity
from pydantic import BaseModel, ConfigDict, Field

PhysicalState = Literal[
    "accepted",
    "funded",
    "capacity_reserved",
    "capacity_committed",
    "scheduled",
    "fulfillment_pending",
    "access_ready",
    "evidence_published",
    "physical_failed",
]
FinancialState = Literal[
    "pending",
    "collection_unknown",
    "collected",
    "collection_blocked",
    "reclaimed",
    "manual_review",
]
RecoveryState = Literal[
    "none",
    "funding_returned",
    "reclaim_pending",
    "reclaimed",
    "loss_manual",
    "manual_review",
]
TeardownState = Literal[
    "not_started",
    "pending",
    "tearing_down",
    "failed",
    "torn_down",
    "released",
]


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
    escrow_uid: str | None = Field(default=None, min_length=1)
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


class BareMetalAccessDeliveryResponse(BaseModel):
    """Transient buyer-authorized SSH coordinates; never durable market state."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    negotiation_id: str = Field(min_length=1)
    method: Literal["ssh"] = "ssh"
    host: str = Field(min_length=1)
    port: int = Field(ge=1, le=65535)
    username: str = Field(min_length=1)
    expires_at: datetime | None = None


class BareMetalSettleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    negotiation_id: str
    buyer_principal: Identity
    buyer_evm_address: str | None = None


class BareMetalSettleResponse(BaseModel):
    escrow_uid: str
    negotiation_id: str
    buyer_principal: Identity
    seller_principal: Identity
    obligation_ref: str | None = None
    status: Literal["settlement_verified"] = "settlement_verified"
    fulfillment_available: Literal[True] = True


class BareMetalSettleStatusResponse(BaseModel):
    escrow_uid: str
    negotiation_id: str
    status: str
    buyer_principal: Identity
    seller_principal: Identity
    obligation_ref: str | None = None
    fulfillment_available: Literal[True] = True
