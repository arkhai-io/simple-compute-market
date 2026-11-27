"""The authority's wire models; each class docstring enters the served OpenAPI document."""

from __future__ import annotations

from functools import cache
from typing import Any, Literal

from market_identity import Identity
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    create_model,
    model_serializer,
)

from arkhai_api.issuance import (
    ACCEPTED_TERMS_FIELDS,
    DIGEST_PATTERN,
    RESULT_SCHEMA_PATTERN,
    RequestCharge,
    IssuanceRequest,
    IssuanceResult,
    KeyDisposition,
    issuance_request_model,
    issuance_result_model,
    omit_unset,
)
from arkhai_api.labels import IssuanceLabel

__all__ = [
    "AdjustRequest",
    "ConsumeBatchItem",
    "ConsumeBatchRequest",
    "ConsumeBatchResponse",
    "ConsumeOutcome",
    "ConsumeRefusal",
    "ConsumeRequest",
    "GrantListResponse",
    "IssuanceLabel",
    "IssuanceRequest",
    "IssuanceResponse",
    "IssuanceResult",
    "KeyDisposition",
    "KeyListResponse",
    "UsageListResponse",
    "VerifyRequest",
    "VerifyResponse",
    "issuance_request_model",
    "issuance_response_model",
    "issuance_result_model",
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


# A caller's expected key scope, sent with verify, consume, and each batched
# consume; a request that names neither is the unscoped request and is
# answered as one.
_SCOPE_FIELDS = ("service", "resource_id")


class ConsumeRequest(BaseModel):
    amount: int = Field(ge=1)
    idempotency_key: str | None = None
    service: str | None = Field(default=None, min_length=1, max_length=255)
    resource_id: str | None = Field(default=None, min_length=1, max_length=255)

    # Unannotated: a return annotation would replace the published serialisation schema.
    @model_serializer(mode="wrap")
    def _omit_unset_scope(self, handler: SerializerFunctionWrapHandler):
        return omit_unset(handler(self), _SCOPE_FIELDS)


class ConsumeBatchItem(BaseModel):
    key_id: str = Field(min_length=1)
    amount: int = Field(ge=1)
    idempotency_key: str | None = None
    service: str | None = Field(default=None, min_length=1, max_length=255)
    resource_id: str | None = Field(default=None, min_length=1, max_length=255)

    @model_serializer(mode="wrap")
    def _omit_unset_scope(self, handler: SerializerFunctionWrapHandler):
        return omit_unset(handler(self), _SCOPE_FIELDS)


class ConsumeBatchRequest(BaseModel):
    items: list[ConsumeBatchItem]


class ConsumeBatchResponse(BaseModel):
    results: list[dict[str, Any]]


class ConsumeOutcome(BaseModel):
    """One consumption's outcome: an accepted charge, a duplicate of one, or a refusal's reason."""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    balance: int
    consumed: int = 0
    duplicate: bool = False
    reason: str | None = None


class ConsumeRefusal(BaseModel):
    """The body of a refused consume; ``error`` is one of `CONSUME_REFUSALS`."""

    model_config = ConfigDict(extra="forbid")

    error: str
    balance: int


class VerifyRequest(BaseModel):
    secret: str = Field(min_length=1)
    service: str | None = Field(default=None, min_length=1, max_length=255)
    resource_id: str | None = Field(default=None, min_length=1, max_length=255)

    @model_serializer(mode="wrap")
    def _omit_unset_scope(self, handler: SerializerFunctionWrapHandler):
        return omit_unset(handler(self), _SCOPE_FIELDS)


class VerifyResponse(BaseModel):
    """A key's verification; a pinned key's accepted terms, digest, and charge, omitted when unpinned."""

    model_config = ConfigDict(extra="forbid")

    valid: bool
    status: str | None
    balance: int
    accepted_terms: dict[str, Any] | None = None
    terms_digest: str | None = Field(default=None, pattern=DIGEST_PATTERN)
    request_charge: RequestCharge | None = None

    @model_serializer(mode="wrap")
    def _omit_unset_terms(self, handler: SerializerFunctionWrapHandler):
        return omit_unset(handler(self), ACCEPTED_TERMS_FIELDS)


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
