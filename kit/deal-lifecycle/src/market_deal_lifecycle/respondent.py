"""Neutral respondent discovery and interface-owned response construction."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from market_deal_lifecycle_contracts.models import EvidenceItem, Instant, Reference, Rejected, WireModel
from market_identity import Signer
from pydantic import Field, JsonValue

from .adapters import DeliveryEndIntent, DisputeBinding


class RespondentCase(WireModel):
    case_ref: Reference
    agreement_ref: Reference
    commitment_ref: Reference
    filed_at: Instant
    filed_record_ref: Reference
    intent: DeliveryEndIntent | None = None


class RespondentPage(WireModel):
    cases: list[RespondentCase] = Field(default_factory=list)
    next_after: str
    has_more: bool


@runtime_checkable
class RespondentAdapter(Protocol):
    binding: DisputeBinding

    async def respondent(self, after: str = "", limit: int = 100) -> RespondentPage: ...

    def build_answer(
        self, case: RespondentCase, *, matching: bool, items: list[EvidenceItem], signer: Signer,
    ) -> dict[str, JsonValue] | Rejected:
        """Sign exact matching facts or package contesting evidence; never rule."""
        ...
