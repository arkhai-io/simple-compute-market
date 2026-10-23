"""Issuance: the authority's immutable command for one grant, its result, and their identities.

Every identity and digest takes the issuing domain's label, so two domains
digesting one request never agree and each authority accepts only its own.
"""

from __future__ import annotations

import hashlib
import re
from functools import cache
from typing import Literal, Self

from market_identity import Identity, canonical_json
from pydantic import BaseModel, ConfigDict, Field, create_model, model_validator

from arkhai_api.labels import IssuanceLabel

_SAFE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$")
REQUEST_SCHEMA_PATTERN = r"^arkhai\.[a-z0-9-]+\.issuance-request\.v1$"
RESULT_SCHEMA_PATTERN = r"^arkhai\.[a-z0-9-]+\.issuance-result\.v1$"
DIGEST_PATTERN = r"^sha256:[0-9a-f]{64}$"


class _IssuanceContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class KeyDisposition(_IssuanceContract):
    mode: Literal["new", "existing"]
    key_id: str | None = Field(default=None, min_length=1, max_length=255)

    @model_validator(mode="after")
    def validate_target(self) -> Self:
        if self.mode == "new" and self.key_id is not None:
            raise ValueError("new key target must not provide key_id")
        if self.mode == "existing" and self.key_id is None:
            raise ValueError("existing key target requires key_id")
        return self


def fulfillment_id(label: IssuanceLabel, negotiation_id: str) -> str:
    """The grant's identity, derived from the accepted negotiation alone."""

    if not isinstance(negotiation_id, str) or not _SAFE_REF.fullmatch(negotiation_id):
        raise ValueError("negotiation_id must be a safe opaque reference")
    digest = hashlib.sha256(
        canonical_json({"domain": label.name, "negotiation_id": negotiation_id, "version": 1})
    ).hexdigest()
    return f"{label.fulfillment_id_prefix}:{digest}"


class IssuanceRequest(_IssuanceContract):
    """Complete immutable command for one credits grant."""

    schema: str = Field(pattern=REQUEST_SCHEMA_PATTERN)
    fulfillment_id: str = Field(min_length=1, max_length=320)
    negotiation_id: str = Field(min_length=1, max_length=255)
    owner: Identity
    service: str = Field(min_length=1, max_length=255)
    resource_id: str = Field(min_length=1, max_length=255)
    quantity: int = Field(ge=1)
    key: KeyDisposition
    request_digest: str = Field(pattern=DIGEST_PATTERN)
    capacity_reservation_id: str | None = Field(default=None, min_length=1, max_length=255)


class IssuanceResult(_IssuanceContract):
    """The committed grant as its requester sees it; the bearer secret never serializes."""

    schema: str = Field(pattern=RESULT_SCHEMA_PATTERN)
    negotiation_id: str = Field(min_length=1, max_length=255)
    fulfillment_id: str = Field(min_length=1, max_length=320)
    grant_id: str = Field(min_length=1, max_length=320)
    owner: Identity
    service: str = Field(min_length=1, max_length=255)
    resource_id: str = Field(min_length=1, max_length=255)
    quantity: int = Field(ge=1)
    key_mode: Literal["new", "existing"]
    key_id: str = Field(min_length=1, max_length=255)
    balance: int = Field(ge=0)
    request_digest: str = Field(pattern=DIGEST_PATTERN)
    committed_at_unix: int = Field(ge=0)
    capacity_reservation_id: str | None = Field(default=None, max_length=255)
    already_issued: bool = False
    secret: str | None = Field(default=None, min_length=1, max_length=512, exclude=True, repr=False)

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if self.grant_id != self.fulfillment_id:
            raise ValueError("grant_id must equal fulfillment_id")
        if self.key_mode == "existing" and self.secret is not None:
            raise ValueError("existing-key top-up must not return a secret")
        if self.secret is not None and not self.secret.startswith(f"{self.key_id}."):
            raise ValueError("issued credential does not match key_id")
        return self


def _request_digest(
    label: IssuanceLabel,
    *,
    fulfillment_id: str,
    negotiation_id: str,
    owner: Identity,
    service: str,
    resource_id: str,
    quantity: int,
    key: KeyDisposition,
) -> str:
    payload = {
        "fulfillment_id": fulfillment_id,
        "key": key.model_dump(mode="json"),
        "negotiation_id": negotiation_id,
        "owner": owner.model_dump(mode="json"),
        "quantity": quantity,
        "resource_id": resource_id,
        "schema": label.issuance_request_schema,
        "service": service,
    }
    return "sha256:" + hashlib.sha256(canonical_json(payload)).hexdigest()


def issuance_request_digest(label: IssuanceLabel, request: IssuanceRequest) -> str:
    """Digest every authority-owned input of the request; the quota hint is transient and excluded."""

    return _request_digest(
        label,
        fulfillment_id=request.fulfillment_id,
        negotiation_id=request.negotiation_id,
        owner=request.owner,
        service=request.service,
        resource_id=request.resource_id,
        quantity=request.quantity,
        key=request.key,
    )


@cache
def issuance_request_model(label: IssuanceLabel) -> type[IssuanceRequest]:
    """``IssuanceRequest`` bound to one label: its schema literal, identity, and digest."""

    def holds_under_label(request: IssuanceRequest) -> IssuanceRequest:
        if request.fulfillment_id != fulfillment_id(label, request.negotiation_id):
            raise ValueError("fulfillment_id does not match negotiation_id")
        if request.request_digest != issuance_request_digest(label, request):
            raise ValueError("request_digest does not match issuance request")
        return request

    schema = label.issuance_request_schema
    return create_model(
        "IssuanceRequest",
        __base__=IssuanceRequest,
        __doc__=IssuanceRequest.__doc__,
        __validators__={"holds_under_label": model_validator(mode="after")(holds_under_label)},
        schema=(Literal[schema], schema),  # type: ignore[valid-type]
    )


@cache
def issuance_result_model(label: IssuanceLabel) -> type[IssuanceResult]:
    """``IssuanceResult`` bound to one label: its schema literal and identity."""

    def holds_under_label(result: IssuanceResult) -> IssuanceResult:
        if result.fulfillment_id != fulfillment_id(label, result.negotiation_id):
            raise ValueError("fulfillment_id does not match negotiation_id")
        return result

    schema = label.issuance_result_schema
    return create_model(
        "IssuanceResult",
        __base__=IssuanceResult,
        __validators__={"holds_under_label": model_validator(mode="after")(holds_under_label)},
        schema=(Literal[schema], schema),  # type: ignore[valid-type]
    )


def issuance_request(
    label: IssuanceLabel,
    *,
    negotiation_id: str,
    owner: Identity,
    service: str,
    resource_id: str,
    quantity: int,
    key: KeyDisposition,
    capacity_reservation_id: str | None = None,
) -> IssuanceRequest:
    """One grant's command under ``label``, its identity and digest computed from the inputs."""

    identity = fulfillment_id(label, negotiation_id)
    return issuance_request_model(label)(
        fulfillment_id=identity,
        negotiation_id=negotiation_id,
        owner=owner,
        service=service,
        resource_id=resource_id,
        quantity=quantity,
        key=key,
        request_digest=_request_digest(
            label,
            fulfillment_id=identity,
            negotiation_id=negotiation_id,
            owner=owner,
            service=service,
            resource_id=resource_id,
            quantity=quantity,
            key=key,
        ),
        capacity_reservation_id=capacity_reservation_id,
    )
