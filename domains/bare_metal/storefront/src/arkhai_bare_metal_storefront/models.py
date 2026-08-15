"""Bare-metal-owned HTTP carriers that must not imply VM fulfillment."""

from __future__ import annotations
from datetime import datetime

from typing import Literal

from arkhai_bare_metal import (
    BareMetalAcceptedHostedBinding,
    BareMetalAccessResult,
    BareMetalLeaseReadyEvidence,
    BareMetalLeaseReadyResult,
    BareMetalReceipt,
)
from market_identity import Identity
from pydantic import BaseModel, ConfigDict, Field, model_validator

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


class BareMetalHostedLifecycle(BaseModel):
    """Durable hosted-to-physical state under one accepted seller binding."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    accepted_binding: BareMetalAcceptedHostedBinding
    accepted_binding_digest: str
    fulfillment_identity: str
    physical_state: PhysicalState = "accepted"
    financial_state: FinancialState = "pending"
    recovery_state: RecoveryState = "none"
    teardown_state: TeardownState = "not_started"
    capacity_reservation_id: str | None = None
    settlement_resource_id: str | None = None
    fulfillment_id: str | None = None
    public_result: BareMetalLeaseReadyResult | None = None
    public_result_digest: str | None = None
    portable_evidence: BareMetalLeaseReadyEvidence | None = None
    portable_evidence_digest: str | None = None
    portable_evidence_ref: str | None = None
    failure_reason: str | None = None

    @model_validator(mode="after")
    def _validate_lifecycle(self) -> "BareMetalHostedLifecycle":
        if self.accepted_binding_digest != self.accepted_binding.binding_digest:
            raise ValueError("accepted hosted binding digest does not match")
        if self.public_result is None:
            if self.public_result_digest is not None:
                raise ValueError("public result digest requires its result")
        elif self.public_result_digest != self.public_result.result_digest:
            raise ValueError("public result digest does not match")
        evidence_values = (
            self.portable_evidence,
            self.portable_evidence_digest,
            self.portable_evidence_ref,
        )
        if any(value is not None for value in evidence_values):
            if any(value is None for value in evidence_values):
                raise ValueError(
                    "portable evidence payload, digest, and ref are atomic"
                )
            assert self.portable_evidence is not None
            if self.portable_evidence_digest != self.portable_evidence.evidence_digest:
                raise ValueError("portable evidence digest does not match")
            if self.portable_evidence.fulfillment_identity != self.fulfillment_identity:
                raise ValueError("portable evidence changes fulfillment identity")
        return self


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
