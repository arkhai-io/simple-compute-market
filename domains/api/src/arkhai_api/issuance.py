"""Issuance: the authority's immutable command for one grant, its result, and their identities.

Every identity and digest takes the issuing domain's label, so two domains
digesting one request never agree and each authority accepts only its own.
"""

from __future__ import annotations

import hashlib
import re
from functools import cache
from typing import Annotated, Any, Literal, Self

from market_identity import Identity, canonical_json
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    TypeAdapter,
    create_model,
    model_serializer,
    model_validator,
)

from arkhai_api.labels import IssuanceLabel

_SAFE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$")
REQUEST_SCHEMA_PATTERN = r"^arkhai\.[a-z0-9-]+\.issuance-request\.v1$"
RESULT_SCHEMA_PATTERN = r"^arkhai\.[a-z0-9-]+\.issuance-result\.v1$"
DIGEST_PATTERN = r"^sha256:[0-9a-f]{64}$"
# The canonical JSON integer domain (RFC 8785), which the request digest
# carries the charge in; the authority's ledger admits it as well.
MAX_REQUEST_CHARGE = 2**53 - 1
# Optional terms fields are omitted when unset, never serialised as null, so an
# unpinned request serialises and digests exactly its base fields.
ACCEPTED_TERMS_FIELDS = ("accepted_terms", "terms_digest", "request_charge")
RequestCharge = Annotated[int, Field(strict=True, ge=1, le=MAX_REQUEST_CHARGE)]
_REQUEST_CHARGE = TypeAdapter(RequestCharge)


def accepted_terms_digest(accepted_terms: dict[str, Any]) -> str:
    """The digest that binds a grant to the canonical JSON of its accepted terms."""

    return "sha256:" + hashlib.sha256(canonical_json(accepted_terms)).hexdigest()


def omit_unset(data: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if key not in fields or value is not None}


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
    accepted_terms: dict[str, Any] | None = None
    terms_digest: str | None = Field(default=None, pattern=DIGEST_PATTERN)
    request_charge: RequestCharge | None = None

    @model_validator(mode="after")
    def validate_accepted_terms(self) -> Self:
        present = [getattr(self, name) is not None for name in ACCEPTED_TERMS_FIELDS]
        if any(present) and not all(present):
            raise ValueError("accepted_terms, terms_digest, and request_charge are set together")
        if self.accepted_terms is not None and self.terms_digest != accepted_terms_digest(
            self.accepted_terms
        ):
            raise ValueError("terms_digest does not match accepted_terms")
        return self

    # Unannotated: a return annotation would replace the published serialisation schema.
    @model_serializer(mode="wrap")
    def _omit_unset_terms(self, handler: SerializerFunctionWrapHandler):
        return omit_unset(handler(self), ACCEPTED_TERMS_FIELDS)


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
    terms_digest: str | None = None,
    request_charge: int | None = None,
) -> str:
    payload: dict[str, Any] = {
        "fulfillment_id": fulfillment_id,
        "key": key.model_dump(mode="json"),
        "negotiation_id": negotiation_id,
        "owner": owner.model_dump(mode="json"),
        "quantity": quantity,
        "resource_id": resource_id,
        "schema": label.issuance_request_schema,
        "service": service,
    }
    # The digest, not the payload, enters the request digest, so it does not
    # grow with the terms; an unpinned request digests the eight base keys.
    if terms_digest is not None:
        payload["terms_digest"] = terms_digest
    if request_charge is not None:
        payload["request_charge"] = request_charge
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
        terms_digest=request.terms_digest,
        request_charge=request.request_charge,
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
    accepted_terms: dict[str, Any] | None = None,
    terms_digest: str | None = None,
    request_charge: int | None = None,
) -> IssuanceRequest:
    """One grant's command under ``label``, its identity and digest computed from the inputs."""

    if request_charge is not None:
        # Refuse an out-of-domain charge before it reaches canonical JSON.
        _REQUEST_CHARGE.validate_python(request_charge)
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
            terms_digest=terms_digest,
            request_charge=request_charge,
        ),
        capacity_reservation_id=capacity_reservation_id,
        accepted_terms=accepted_terms,
        terms_digest=terms_digest,
        request_charge=request_charge,
    )
