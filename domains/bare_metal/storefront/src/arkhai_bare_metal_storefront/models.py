"""Bare-metal-owned HTTP carriers that must not imply VM fulfillment."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from arkhai_bare_metal import (
    BareMetalResult,
    BareMetalReceipt,
)
from core_storefront.models.system_models import ProjectionFamilyStatus
from market_identity import Identity
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

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
    # Reported per site and outside ``checks``: one site's projection being
    # unavailable is not a storefront-wide degradation.
    site_projections: dict[str, dict[str, ProjectionFamilyStatus]] | None = None
    # Each stored pool override's address and state; administrator status only.
    pool_overrides: list[dict[str, str]] | None = None
    # Storefront policies disclosed to anyone before they commit data, keyed by
    # policy. ``introduction_retention`` is present only while contact exchange
    # is enabled.
    disclosures: dict[str, dict[str, object]] = Field(default_factory=dict)
    # Settlement obligations waiting for an operator, each counted once;
    # administrator status only.
    settlement_manual_required: int | None = None
    # The storefront-to-provisioning contract version this storefront speaks,
    # from its installed contract wheel; administrator status only.
    provisioning_contract_version: str | None = None


class BareMetalFulfillmentResponse(BaseModel):
    negotiation_id: str
    escrow_uid: str
    site_id: str
    capacity_reservation_id: str | None = None
    settlement_resource_id: str | None = None
    fulfillment_id: str | None = None
    state: str
    failure_reason: str | None = None
    # The digest of the deal's lease-ready evidence once it is stored, which
    # is what an Alkahest delivery publishes on chain; the buyer resolves the
    # evidence by it through the evidence route.
    evidence_digest: str | None = Field(
        default=None,
        validation_alias=AliasChoices("evidence_digest", "lease_ready_evidence_digest"),
    )


class BareMetalFulfillmentResultResponse(BaseModel):
    negotiation_id: str
    receipt: BareMetalReceipt
    result: BareMetalResult


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


class BareMetalVerifyEscrowRequest(BaseModel):
    """An administrator's dry-run check of an escrow against a listing's terms."""

    model_config = ConfigDict(extra="forbid")

    seller_wallet: str = Field(min_length=1)
    # Base units in the uint256 domain, as a decimal-digit string.
    agreed_price: str = Field(pattern=r"^[0-9]+$")
    agreed_duration_seconds: int = Field(gt=0)
    listing_id: str = Field(min_length=1)
    chain_name: str = Field(default="anvil", min_length=1)


class BareMetalVerifyEscrowResponse(BaseModel):
    escrow_uid: str
    valid: bool
    reason: str | None = None


class BareMetalEvaluateSettleRequest(BaseModel):
    """An administrator's preview of the fulfillment settlement would start."""

    model_config = ConfigDict(extra="forbid")

    listing_id: str = Field(min_length=1)
    ssh_public_key: str = ""
    duration_seconds: int = Field(default=3600, gt=0)
    negotiation_id: str | None = None


class BareMetalEvaluateSettleResponse(BaseModel):
    escrow_uid: str
    would_submit: bool
    reason: str | None = None
    host_id: str | None = None
    site_id: str | None = None
    physical_resource_id: str | None = None
    required_attributes: dict[str, object] | None = None
    duration_seconds: int | None = None


class BareMetalSettleWaitResponse(BaseModel):
    ready: bool
    status: str
    elapsed_ms: int
    fulfillment_state: str | None = None


class BareMetalReserveCapacityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required_attributes: dict[str, object] = Field(default_factory=dict)
    listing_id: str | None = None
    escrow_uid: str | None = None


class BareMetalCapacityReleasedEvent(BaseModel):
    """A site's report that a reservation's capacity is free again."""

    model_config = ConfigDict(extra="forbid")

    capacity_reservation_id: str = Field(min_length=1)
    site_id: str = Field(min_length=1)
    resource_id: str | None = None
    provider_lease_id: str | None = None
    released_at: str | None = None


class BareMetalCapacityEventResponse(BaseModel):
    capacity_reservation_id: str
    state: str
