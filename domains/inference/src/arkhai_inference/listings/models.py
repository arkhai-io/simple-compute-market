"""Inference listing resource schema.

The listing's ``listing_resource`` is a model card: one served model at one
seller. ``model_id`` is seller-asserted; ``identity.derive_model_id`` is the
convention sellers of the same weights should share. ``resource_id`` names the
quota resource the listing derives from — seller-internal bookkeeping the
reconciler and quota guard key on; buyers ignore it.
"""

from __future__ import annotations

import json
from typing import Any, Literal, get_args

from market_core.schemas import OptionalUint256Amount, Uint256Amount
from market_identity import CanonicalizationError, Identity, canonical_json
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

INFERENCE_KIND = "inference.v1"
INFERENCE_OFFERING_MODE = "inference"
OPENAI_V1_API_STYLE = "openai.v1"

Quantization = Literal["none", "fp16", "bf16", "fp8", "int8", "int4", "awq", "gptq"]
Provenance = Literal["self-hosted", "resold"]

QUANTIZATIONS: tuple[str, ...] = get_args(Quantization)

_MODEL_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,254}$"

#: The largest base-unit amount a settlement mechanism can carry; every card
#: amount and derived charge stays within it.
MAX_BASE_UNIT_AMOUNT = 2**256 - 1
_SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"


class InferenceRateCard(BaseModel):
    """Prices in base units of ``asset``, the one asset the listing settles in.

    Every settlement option and escrow token on the listing must identify
    ``asset``, so a rate bound compared against the card is compared within
    one asset. Amounts are uint256-domain: Python integers in memory and
    decimal-digit strings on the wire, because a card on an 18-decimal asset
    exceeds the integer range canonical JSON carries, and both the published
    listing and the usage evidence that pins the card are signed canonically.
    ``model_dump`` therefore yields the string form in both modes; arithmetic
    reads the attributes.
    """

    model_config = ConfigDict(extra="forbid")

    asset: str = Field(min_length=1)
    prompt_credits_per_million: Uint256Amount
    completion_credits_per_million: Uint256Amount
    request_credits: Uint256Amount = 0
    cached_prompt_credits_per_million: OptionalUint256Amount = None
    image_credits_per_unit: OptionalUint256Amount = None

    @field_validator("asset")
    @classmethod
    def _non_blank_asset(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("rate_card.asset must be non-empty")
        return value

    @model_validator(mode="after")
    def _within_uint256(self) -> "InferenceRateCard":
        for name in (
            "prompt_credits_per_million",
            "completion_credits_per_million",
            "request_credits",
            "cached_prompt_credits_per_million",
            "image_credits_per_unit",
        ):
            value = getattr(self, name)
            if value is not None and value > MAX_BASE_UNIT_AMOUNT:
                raise ValueError(f"rate_card.{name} exceeds uint256")
        return self


class InferenceArchitecture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    modality: str = Field(min_length=1)
    tokenizer: str | None = None
    instruct_type: str | None = None


class InferenceEndpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str = Field(min_length=1)
    openapi_url: str | None = None
    api_style: Literal["openai.v1"] = OPENAI_V1_API_STYLE


class AttestationEnvelope(BaseModel):
    """Opaque, unverified in this version; a proof format is a later ``kind``."""

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(min_length=1)
    schema_version: StrictInt = Field(ge=1)
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("payload")
    @classmethod
    def _canonical_payload(cls, value: dict[str, Any]) -> dict[str, Any]:
        # The card is signed canonically, so a payload that cannot be is
        # refused here rather than when the listing is signed.
        try:
            canonical_json(value)
        except CanonicalizationError as exc:
            raise ValueError("attestation.payload must be canonical JSON") from exc
        return value


class InferenceModelCard(BaseModel):
    """``listing_resource`` payload for an inference listing."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["inference.v1"] = INFERENCE_KIND
    model_id: str = Field(pattern=_MODEL_ID_PATTERN)
    artifact_ref: str = Field(min_length=1)
    artifact_digest: str | None = Field(default=None, pattern=_SHA256_PATTERN)
    display_name: str | None = None
    model_owner: Identity | None = None
    provenance: Provenance
    served_model_name: str = Field(min_length=1)
    model_family: str | None = None
    context_length: int = Field(gt=0)
    max_completion_tokens: int | None = Field(default=None, gt=0)
    quantization: Quantization
    architecture: InferenceArchitecture
    supported_parameters: list[str]
    endpoint: InferenceEndpoint
    rate_card: InferenceRateCard
    attestation: AttestationEnvelope | None = None
    capacity_site_id: str = Field(min_length=1)
    resource_id: str | None = Field(default=None, min_length=1)
    offering_mode: Literal["inference"] = INFERENCE_OFFERING_MODE

    @field_validator("served_model_name", "artifact_ref", "capacity_site_id", "resource_id")
    @classmethod
    def _non_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must be non-empty")
        return value

    @field_validator("supported_parameters")
    @classmethod
    def _non_blank_parameters(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value):
            raise ValueError("supported_parameters entries must be non-empty")
        return value


def accepted_terms(card: InferenceModelCard) -> dict[str, Any]:
    """The terms a buyer accepts with ``card``: its rate card and attestation, as plain JSON.

    Storefront and gateway both build them here so the pinned and current terms agree.
    """
    return {
        "rate_card": card.rate_card.model_dump(mode="json"),
        "attestation": None if card.attestation is None else card.attestation.model_dump(mode="json"),
    }


def coerce_resource_dict(value: Any) -> dict[str, Any]:
    """Best-effort dict view of a listing_resource (SQLite stores JSON text)."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}
