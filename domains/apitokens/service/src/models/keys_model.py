"""Pydantic models for the tokens-service HTTP surface."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator


class IdentityRef(BaseModel):
    """Scheme-tagged identity, the same shape as the key ownership claim."""

    scheme: str = Field(min_length=1)
    id: str = Field(min_length=1)


class KeyDisposition(BaseModel):
    mode: str = Field(pattern="^(new|existing)$")
    key_id: Optional[str] = None

    @model_validator(mode="after")
    def _existing_needs_key_id(self) -> "KeyDisposition":
        if self.mode == "existing" and not self.key_id:
            raise ValueError("key.mode 'existing' requires key.key_id")
        return self


class IssuanceRequest(BaseModel):
    """Body for ``POST /api/v1/issuance`` — one deal's fulfillment."""

    escrow_uid: str = Field(min_length=1)
    quantity: int = Field(ge=1)
    key: KeyDisposition
    buyer: Optional[IdentityRef] = Field(
        default=None,
        description=(
            "The purchasing identity from the deal (wallet in v1). "
            "Existing-mode issuance re-checks the target key's ownership "
            "claim against it; new keys bind it as owner unless an "
            "explicit owner is given."
        ),
    )
    owner: Optional[IdentityRef] = Field(
        default=None,
        description="Explicit ownership claim for a new key (overrides buyer).",
    )
    allocation_id: Optional[str] = Field(
        default=None, description="The negotiation-time quota hold, if one was taken.",
    )
    resource_id: Optional[str] = Field(
        default=None,
        description="Quota resource to reserve against when no live hold exists.",
    )


class IssuanceResponse(BaseModel):
    key_id: str
    secret: Optional[str] = Field(
        default=None,
        description=(
            "Bearer secret — returned for new keys (and rotated on a "
            "retry that found the key unused); null for top-ups."
        ),
    )
    quantity: int
    balance: int
    allocation_id: Optional[str] = None
    already_issued: bool = False


class ConsumeRequest(BaseModel):
    amount: int = Field(ge=1)
    idempotency_key: Optional[str] = None


class ConsumeBatchItem(BaseModel):
    key_id: str = Field(min_length=1)
    amount: int = Field(ge=1)
    idempotency_key: Optional[str] = None


class ConsumeBatchRequest(BaseModel):
    items: list[ConsumeBatchItem]


class ConsumeBatchResponse(BaseModel):
    results: list[dict[str, Any]]


class VerifyRequest(BaseModel):
    secret: str = Field(min_length=1)


class AdjustRequest(BaseModel):
    delta: int
    reason: Optional[str] = None


class KeyListResponse(BaseModel):
    keys: list[dict[str, Any]]
    total: int


class GrantListResponse(BaseModel):
    grants: list[dict[str, Any]]
    total: int


class UsageListResponse(BaseModel):
    events: list[dict[str, Any]]
    total: int
