"""Validated durable settlement inputs, separate from physical progress."""

from typing import Any, Literal

from arkhai_bare_metal import BareMetalTerms
from pydantic import BaseModel, ConfigDict, Field


class DeliveryInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    site_id: str = Field(min_length=1)
    physical_resource_id: str = Field(min_length=1)
    pool_id: str | None = None
    terms: BareMetalTerms


class EvidencePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["bare_metal.settlement-evidence.v1"] = (
        "bare_metal.settlement-evidence.v1"
    )
    schema_version: Literal[1] = 1
    agreement_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source: dict[str, Any] = Field(default_factory=dict)
    delivery: DeliveryInput | None = None
