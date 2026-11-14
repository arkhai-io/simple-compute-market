"""The lifecycle read and list models exactly as release 0.1.0 shipped them.

A frozen copy, never edited: released clients validate a seller's read with
these models, which forbid unknown fields, so a test holds today's once-deal
reads to them.
"""

from __future__ import annotations

from typing import Annotated, Literal

from market_identity import Identity
from pydantic import Base64Bytes, BaseModel, ConfigDict, Field, JsonValue, model_validator

Reference = Annotated[str, Field(min_length=1)]
Instant = Annotated[int, Field(strict=True, ge=0)]
Amount = Annotated[str, Field(pattern=r"^(0|[1-9][0-9]*)$")]
PaymentEventKind = Literal["start", "stop", "collect", "reverse", "award", "return", "extend", "lift"]
DisputeEventKind = Literal["filed", "appended", "ruled", "closed"]
LifecycleState = Literal["unstarted", "running", "ending", "ended", "repair_required"]


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


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


class FilingAnswer(WireModel):
    case_ref: Reference
    parts: list[PartHold]
    record_ref: Reference


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


class OpenExtension(WireModel):
    part: Reference
    extension_ref: Reference
    case_ref: Reference
    until: Instant | None


class AuthorityView(WireModel):
    outcome: LifecycleOutcome
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
