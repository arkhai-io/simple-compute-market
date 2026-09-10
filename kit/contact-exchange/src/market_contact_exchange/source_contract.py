"""Strict public option shape for explicitly captured listing context."""

from __future__ import annotations

from typing import Literal

from market_core.schemas import derive_settlement_option_id
from market_identity import Identity
from pydantic import Field, field_validator, model_validator

from .delivery_contract import DeliveryPolicy, ObligationRef, StrictCarrier

CONTEXT_CONTRACT = "accepted-listing.v1"


class ContextOptionParams(StrictCarrier):
    profile: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9_.-]*$")
    channel: str = Field(min_length=1, max_length=128)
    terms: str = Field(min_length=1, max_length=4000)
    claimant_principal: Identity
    delivery_policy: DeliveryPolicy
    context_contract: Literal["accepted-listing.v1"]

    @field_validator("channel", "terms")
    @classmethod
    def public_scalars(cls, value: str) -> str:
        if not value.strip() or any(0xD800 <= ord(c) <= 0xDFFF for c in value):
            raise ValueError("nonblank scalar text required")
        return value

    @field_validator("channel")
    @classmethod
    def trimmed_channel(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("contact channel must be trimmed")
        return value


class ContextContactOption(StrictCarrier):
    option_id: ObligationRef
    mechanism: Literal["contact-exchange.v1"]
    asset: Literal["introduction"]
    rates: list[object] = Field(max_length=0)
    params: ContextOptionParams

    @model_validator(mode="after")
    def exact_option(self) -> ContextContactOption:
        expected = derive_settlement_option_id(
            mechanism=self.mechanism, asset=self.asset, rates=[],
            params=self.params.model_dump(mode="json"),
        )
        if self.option_id != expected:
            raise ValueError("invalid context option identity")
        return self
