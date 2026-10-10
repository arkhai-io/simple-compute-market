"""Pydantic models for the credits-service HTTP surface."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Final, Literal, Optional, Self

from market_identity import Identity, canonical_json
from pydantic import BaseModel, ConfigDict, Field, model_validator

ISSUANCE_REQUEST_SCHEMA: Final = "arkhai.api-credits.issuance-request.v1"
ISSUANCE_RESULT_SCHEMA: Final = "arkhai.api-credits.issuance-result.v1"
_SAFE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$")


def derive_credit_fulfillment_id(negotiation_id: str) -> str:
    if not isinstance(negotiation_id, str) or not _SAFE_REF.fullmatch(negotiation_id):
        raise ValueError("negotiation_id must be a safe opaque reference")
    digest = hashlib.sha256(
        canonical_json(
            {
                "domain": "api-credits",
                "negotiation_id": negotiation_id,
                "version": 1,
            }
        )
    ).hexdigest()
    return f"api-credit-fulfillment.v1:{digest}"


def issuance_request_digest(
    *,
    fulfillment_id: str,
    negotiation_id: str,
    owner: Identity,
    service: str,
    resource_id: str,
    quantity: int,
    key: "KeyDisposition",
) -> str:
    payload = {
        "fulfillment_id": fulfillment_id,
        "key": key.model_dump(mode="json"),
        "negotiation_id": negotiation_id,
        "owner": owner.model_dump(mode="json"),
        "quantity": quantity,
        "resource_id": resource_id,
        "schema": ISSUANCE_REQUEST_SCHEMA,
        "service": service,
    }
    return "sha256:" + hashlib.sha256(canonical_json(payload)).hexdigest()


class KeyDisposition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    mode: Literal["new", "existing"]
    key_id: Optional[str] = Field(default=None, min_length=1, max_length=255)

    @model_validator(mode="after")
    def validate_target(self) -> Self:
        if self.mode == "new" and self.key_id is not None:
            raise ValueError("new key target must not provide key_id")
        if self.mode == "existing" and self.key_id is None:
            raise ValueError("existing key target requires key_id")
        return self


class IssuanceRequest(BaseModel):
    """Complete immutable command for one credits grant."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    # The wire schema field shadows Pydantic's deprecated schema() method.
    schema: Literal["arkhai.api-credits.issuance-request.v1"] = ISSUANCE_REQUEST_SCHEMA  # type: ignore[assignment]
    fulfillment_id: str = Field(min_length=1, max_length=320)
    negotiation_id: str = Field(min_length=1, max_length=255)
    owner: Identity
    service: str = Field(min_length=1, max_length=255)
    resource_id: str = Field(min_length=1, max_length=255)
    quantity: int = Field(ge=1)
    key: KeyDisposition
    request_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    capacity_reservation_id: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=255,
    )

    @model_validator(mode="after")
    def validate_identity_and_digest(self) -> Self:
        if self.fulfillment_id != derive_credit_fulfillment_id(self.negotiation_id):
            raise ValueError("fulfillment_id does not match negotiation_id")
        expected = issuance_request_digest(
            fulfillment_id=self.fulfillment_id,
            negotiation_id=self.negotiation_id,
            owner=self.owner,
            service=self.service,
            resource_id=self.resource_id,
            quantity=self.quantity,
            key=self.key,
        )
        if self.request_digest != expected:
            raise ValueError("request_digest does not match issuance request")
        return self


class IssuanceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema: Literal["arkhai.api-credits.issuance-result.v1"] = ISSUANCE_RESULT_SCHEMA  # type: ignore[assignment]
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
    capacity_reservation_id: Optional[str] = None
    already_issued: bool = False
    secret: Optional[str] = Field(default=None, repr=False)


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
