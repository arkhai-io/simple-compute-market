"""The authority's wire models; each class docstring enters the served OpenAPI document."""

from __future__ import annotations

from functools import cache
from typing import Any, Literal

from market_identity import Identity
from pydantic import BaseModel, ConfigDict, Field, create_model

from arkhai_api.issuance import (
    RESULT_SCHEMA_PATTERN,
    IssuanceRequest,
    KeyDisposition,
    issuance_request_model,
)
from arkhai_api.labels import IssuanceLabel

__all__ = [
    "AdjustRequest",
    "ConsumeBatchItem",
    "ConsumeBatchRequest",
    "ConsumeBatchResponse",
    "ConsumeRequest",
    "GrantListResponse",
    "IssuanceRequest",
    "IssuanceResponse",
    "KeyDisposition",
    "KeyListResponse",
    "UsageListResponse",
    "VerifyRequest",
    "issuance_request_model",
    "issuance_response_model",
]


class IssuanceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema: str = Field(pattern=RESULT_SCHEMA_PATTERN)
    fulfillment_id: str
    grant_id: str
    negotiation_id: str
    owner: Identity
    service: str
    resource_id: str
    quantity: int
    key_mode: Literal["new", "existing"]
    key_id: str
    balance: int
    request_digest: str
    committed_at_unix: int
    capacity_reservation_id: str | None = None
    already_issued: bool = False
    secret: str | None = Field(default=None, repr=False)


@cache
def issuance_response_model(label: IssuanceLabel) -> type[IssuanceResponse]:
    schema = label.issuance_result_schema
    return create_model(
        "IssuanceResponse",
        __base__=IssuanceResponse,
        schema=(Literal[schema], schema),  # type: ignore[valid-type]
    )


class ConsumeRequest(BaseModel):
    amount: int = Field(ge=1)
    idempotency_key: str | None = None


class ConsumeBatchItem(BaseModel):
    key_id: str = Field(min_length=1)
    amount: int = Field(ge=1)
    idempotency_key: str | None = None


class ConsumeBatchRequest(BaseModel):
    items: list[ConsumeBatchItem]


class ConsumeBatchResponse(BaseModel):
    results: list[dict[str, Any]]


class VerifyRequest(BaseModel):
    secret: str = Field(min_length=1)


class AdjustRequest(BaseModel):
    delta: int
    reason: str | None = None


class KeyListResponse(BaseModel):
    keys: list[dict[str, Any]]
    total: int


class GrantListResponse(BaseModel):
    grants: list[dict[str, Any]]
    total: int


class UsageListResponse(BaseModel):
    events: list[dict[str, Any]]
    total: int
