"""Mechanism-neutral records; financial and dispute authority references are opaque.

Instants are nonnegative Unix seconds. Exact signed bodies travel as base64,
not parsed JSON, so exporting evidence never reconstructs signed bytes.
"""

from __future__ import annotations

from typing import Annotated, Literal

from market_identity import AuthenticatedRequest, AuthenticatedResponse, Identity
from pydantic import Base64Bytes, BaseModel, ConfigDict, Field, JsonValue, model_validator

Reference = Annotated[str, Field(min_length=1)]
Instant = Annotated[int, Field(strict=True, ge=0)]
Amount = Annotated[str, Field(pattern=r"^(0|[1-9][0-9]*)$")]
CommandKind = Literal["start", "stop", "reverse", "dispute", "delivery_end", "append"]
PaymentEventKind = Literal["start", "stop", "collect", "reverse", "award", "return", "extend", "lift"]
DisputeEventKind = Literal["filed", "appended", "ruled", "closed"]
LifecycleState = Literal["unstarted", "running", "ending", "ended", "repair_required"]


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LifecycleCommand(WireModel):
    negotiation_id: Reference
    kind: CommandKind
    operation_key: Reference
    at: Instant | None = None
    payload: dict[str, JsonValue] = Field(default_factory=dict)


class EvidenceItem(WireModel):
    evidence_id: Reference
    kind: Reference
    classification: Literal["seller_assertion", "buyer_observation", "independent"]
    recorded_at: Instant
    body: Base64Bytes
    headers: dict[str, str] = Field(default_factory=dict)
    context: dict[str, JsonValue] = Field(default_factory=dict)


class PaymentEvent(WireModel):
    negotiation_id: Reference
    commitment_ref: Reference
    part: Reference
    kind: PaymentEventKind
    actor: Reference
    at: Instant
    amount: Amount | None = None
    cause: str
    case_ref: Reference | None = None
    extension_ref: Reference | None = None
    sequence: Annotated[int, Field(strict=True, ge=0)]
    authority_record_ref: Reference

    @model_validator(mode="after")
    def required_effect_fields(self) -> PaymentEvent:
        if self.kind in {"extend", "lift"} and (self.extension_ref is None or self.case_ref is None):
            raise ValueError("extend and lift require extension_ref and case_ref")
        if self.kind in {"collect", "reverse", "award", "return"} and self.amount is None:
            raise ValueError("money movement requires an amount")
        return self


class PartEffect(WireModel):
    effect_id: Reference
    kind: Literal["reverse", "award", "stop"]
    part: Reference
    amount: Amount | None = None
    at: Instant | None = None
    settles_through: Literal["started_period", "last_boundary", "stop"] | None = None
    applied: bool

    @model_validator(mode="after")
    def required_effect_fields(self) -> PartEffect:
        if self.kind == "stop" and (self.at is None or self.settles_through is None):
            raise ValueError("a stop effect requires its instant and treatment")
        if self.kind in {"reverse", "award"} and self.amount is None:
            raise ValueError("a money effect requires an amount")
        return self


class DeliveryEndEffect(WireModel):
    effect_id: Reference
    kind: Literal["delivery_end"]
    at: Instant
    applied: bool


Effect = Annotated[PartEffect | DeliveryEndEffect, Field(discriminator="kind")]


class DisputeEvent(WireModel):
    negotiation_id: Reference
    commitment_ref: Reference
    case_ref: Reference
    kind: DisputeEventKind
    actor: Reference
    at: Instant
    items: list[EvidenceItem] = Field(default_factory=list)
    outcome: list[Effect] = Field(default_factory=list)
    sequence: Annotated[int, Field(strict=True, ge=0)]
    record_ref: Reference


class PartHold(WireModel):
    part: Reference
    status: Literal["held", "not_held"]
    reason: str
    extension_ref: Reference | None = None

    @model_validator(mode="after")
    def held_has_extension(self) -> PartHold:
        if self.status == "held" and self.extension_ref is None:
            raise ValueError("a held part requires its extension reference")
        return self


class FilingAnswer(WireModel):
    case_ref: Reference
    parts: list[PartHold]
    record_ref: Reference


class CasePayload(WireModel):
    negotiation_id: Reference
    commitment_ref: Reference
    agreement: Base64Bytes
    items: list[EvidenceItem]
    request: dict[str, JsonValue]


class CaseRecord(WireModel):
    case_ref: Reference
    state: DisputeEventKind
    record_ref: Reference
    outcome: list[Effect] = Field(default_factory=list)


class Accepted(WireModel):
    status: Literal["accepted"] = "accepted"
    records: list[PaymentEvent | DisputeEvent] = Field(default_factory=list)
    filing: FilingAnswer | None = None


class Rejected(WireModel):
    status: Literal["rejected"] = "rejected"
    reason: Reference


class Pending(WireModel):
    status: Literal["pending"] = "pending"
    reason: Reference


class Unknown(WireModel):
    status: Literal["unknown"] = "unknown"
    reason: Reference


LifecycleOutcome = Annotated[Accepted | Rejected | Pending | Unknown, Field(discriminator="status")]


class FilingProgress(WireModel):
    intent_ref: Reference
    outcome: LifecycleOutcome


class CommitMessage(WireModel):
    kind: Literal["commit"] = "commit"
    negotiation_id: Reference
    operation_key: Reference
    commitment_ref: Reference
    payload: dict[str, JsonValue] = Field(default_factory=dict)


class HintMessage(WireModel):
    kind: Literal["hint"] = "hint"
    negotiation_id: Reference
    operation_key: Reference
    payload: dict[str, JsonValue] = Field(default_factory=dict)


class EndDeliveryMessage(WireModel):
    """Surrender at durable receipt, never at a buyer-supplied instant."""

    kind: Literal["end_delivery"] = "end_delivery"
    negotiation_id: Reference
    operation_key: Reference


PeerMessage = Annotated[CommitMessage | HintMessage | EndDeliveryMessage, Field(discriminator="kind")]


class OpenExtension(WireModel):
    part: Reference
    extension_ref: Reference
    case_ref: Reference
    until: Instant | None


class AuthorityView(WireModel):
    outcome: LifecycleOutcome
    # None means the adapter cannot supply a complete payout observation.
    # Completed parts use their first verified completion observation, not a forecast.
    payouts: dict[str, Instant | None] | None = None
    state: LifecycleState | None = None
    events: list[PaymentEvent] = Field(default_factory=list)
    disputes: list[DisputeEvent] = Field(default_factory=list)
    cases: list[CaseRecord] = Field(default_factory=list)
    extensions: list[OpenExtension] = Field(default_factory=list)
    deadline: Instant | None = None


class RecordedEnd(WireModel):
    ended_at: Instant
    actor: Identity
    cause: Reference
    source: Reference
    evidence_refs: list[str] = Field(default_factory=list)


class DeliveryView(WireModel):
    recorded_end: RecordedEnd | None = None
    progress: Literal["unstarted", "active", "end_recorded", "tearing_down", "released", "repair_required"]
    site_reports: list[EvidenceItem] = Field(default_factory=list)


class EndDeliveryAcknowledgement(WireModel):
    negotiation_id: Reference
    operation_key: Reference
    receipt_at: Instant
    selected_end: RecordedEnd
    delivery: DeliveryView
    # The selected dispute adapter owns validation and the claim's canonical frame.
    signed_delivery_end_claim: dict[str, JsonValue] | None = None

    @model_validator(mode="after")
    def selected_end_matches_delivery(self) -> EndDeliveryAcknowledgement:
        if self.delivery.recorded_end != self.selected_end:
            raise ValueError("acknowledgement must return its selected end in the delivery view")
        if self.selected_end.ended_at > self.receipt_at:
            raise ValueError("selected end cannot be later than surrender receipt")
        return self


class SignedEndDeliveryReceipt(WireModel):
    request: AuthenticatedRequest
    request_body: Base64Bytes
    response: AuthenticatedResponse
    response_body: Base64Bytes


class LifecycleRead(WireModel):
    negotiation_id: Reference
    commitment_ref: Reference | None = None
    authority: AuthorityView
    delivery: DeliveryView
    filings: list[FilingProgress] = Field(default_factory=list)


class DealSummary(WireModel):
    negotiation_id: Reference
    commitment_ref: Reference
    domain: Reference
    mechanism: Reference
    entitlements: dict[str, JsonValue]
    state: LifecycleState
    deadline: Instant | None = None
    has_open_extension: bool
    open_cases: list[Reference]
    filings: list[FilingProgress] = Field(default_factory=list)


class DealPage(WireModel):
    deals: list[DealSummary]
    continuation: str | None = None


class ListDealsRequest(WireModel):
    limit: Annotated[int, Field(strict=True, ge=1, le=100)] = 50
    continuation: str | None = None


class SubmitResponse(WireModel):
    outcome: LifecycleOutcome
