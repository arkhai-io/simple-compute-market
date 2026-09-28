"""Pydantic models for the credits-service HTTP surface."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Literal, Optional, Self

from market_identity import Identity, canonical_json
from pydantic import BaseModel, ConfigDict, Field, model_validator

ISSUANCE_REQUEST_SCHEMA = "arkhai.api-credits.issuance-request.v1"
ISSUANCE_RESULT_SCHEMA = "arkhai.api-credits.issuance-result.v1"
_SAFE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$")


def derive_credit_fulfillment_id(obligation_ref: str) -> str:
    if not isinstance(obligation_ref, str) or not _SAFE_REF.fullmatch(obligation_ref):
        raise ValueError("obligation_ref must be a safe opaque reference")
    digest = hashlib.sha256(
        canonical_json(
            {
                "domain": "api-credits",
                "obligation_ref": obligation_ref,
                "version": 1,
            }
        )
    ).hexdigest()
    return f"api-credit-fulfillment.v1:{digest}"


def issuance_request_digest(
    *,
    fulfillment_id: str,
    obligation_ref: str,
    mechanism: str,
    owner: Identity,
    service: str,
    resource_id: str,
    quantity: int,
    key: "KeyDisposition",
) -> str:
    payload = {
        "fulfillment_id": fulfillment_id,
        "key": key.model_dump(mode="json"),
        "mechanism": mechanism,
        "obligation_ref": obligation_ref,
        "owner": owner.model_dump(mode="json"),
        "quantity": quantity,
        "resource_id": resource_id,
        "schema": ISSUANCE_REQUEST_SCHEMA,
        "service": service,
    }
    return "sha256:" + hashlib.sha256(canonical_json(payload)).hexdigest()


LEGACY_ISSUANCE_SERVICE = "api-credits"
LEGACY_ISSUANCE_RESOURCE_ID = "legacy:unattributed"
LEGACY_ISSUANCE_SCHEMA = "arkhai.api-credits.legacy-issuance.v1"


def legacy_issuance_request_digest(
    *,
    fulfillment_id: str,
    obligation_ref: str,
    key_id: str,
    key_mode: str,
    owner: Identity | None,
    quantity: int,
) -> str:
    """Identify exactly one migration-authored legacy placeholder command."""

    payload = {
        "fulfillment_id": fulfillment_id,
        "key": {
            "key_id": key_id if key_mode == "existing" else None,
            "mode": key_mode,
        },
        "mechanism": "alkahest.v1",
        "obligation_ref": obligation_ref,
        "owner": owner.model_dump(mode="json") if owner is not None else None,
        "quantity": quantity,
        "resource_id": LEGACY_ISSUANCE_RESOURCE_ID,
        "schema": LEGACY_ISSUANCE_SCHEMA,
        "service": LEGACY_ISSUANCE_SERVICE,
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

    schema: Literal["arkhai.api-credits.issuance-request.v1"] = ISSUANCE_REQUEST_SCHEMA
    fulfillment_id: str = Field(min_length=1, max_length=320)
    obligation_ref: str = Field(min_length=1, max_length=255)
    mechanism: Literal["alkahest.v1", "fiat.stripe.v1"]
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
        if self.fulfillment_id != derive_credit_fulfillment_id(self.obligation_ref):
            raise ValueError("fulfillment_id does not match obligation_ref")
        expected = issuance_request_digest(
            fulfillment_id=self.fulfillment_id,
            obligation_ref=self.obligation_ref,
            mechanism=self.mechanism,
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

    schema: Literal["arkhai.api-credits.issuance-result.v1"] = ISSUANCE_RESULT_SCHEMA
    fulfillment_id: str
    grant_id: str
    obligation_ref: str
    mechanism: Literal["alkahest.v1", "fiat.stripe.v1"]
    owner: Optional[Identity]
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
