"""Records of version 3 signed messages, kept as evidence beside their exact bodies.

A party that keeps a signed request or response as evidence keeps a record of the
message's signed values and its body bytes, never its headers: the profile accepts
one spelling of everything it signs, so the record rebuilds the exact signature
base, and it reads as data, naming who signed and when without parsing RFC 9421.
No digest is kept, since a verifier computes it from the body.

A record is for a message bound to an authority -- a request carrying
``Market-Audience``, and the response answering one. A delivery bound by
``@target-uri`` has none: its signature covers its endpoint's URL, which a
record does not hold.

Signing and verifying produce records (:mod:`market_identity.http_profile`), so
no party builds one; :mod:`market_identity.evidence` verifies one offline.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import (
    Field,
    SerializerFunctionWrapHandler,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_serializer,
    model_validator,
)

from market_identity.models import (
    _REQUEST_ID,
    _TOKEN,
    ContractModel,
    Identity,
    IdentityScheme,
    SignatureProof,
)
from market_identity.wire import REQUEST_PROFILE, RESPONSE_PROFILE, RecordField

MAX_RESOURCE_CHARACTERS = 1024

# RFC 3986's query grammar after its ``?``: unreserved and sub-delimiter characters,
# ``:``, ``@``, ``/``, ``?`` and percent escapes. The signature library parses every
# URL it reads to this grammar, so no verified request carries a query outside it.
_QUERY = re.compile(r"(?:[A-Za-z0-9._~!$&'()*+,;=:@/?-]|%[0-9A-Fa-f]{2})*")


def principal_text(identity: Identity) -> str:
    """The complete principal as the profile writes it: ``<scheme>:<identifier>``."""

    return f"{identity.scheme.value}:{identity.identifier}"


def principal_identity(text: str) -> Identity:
    """The principal ``text`` names, which must be written as the profile writes it."""

    scheme, separator, identifier = text.partition(":")
    if not separator:
        raise ValueError("a principal is written <scheme>:<identifier>")
    try:
        identity = Identity(scheme=IdentityScheme(scheme), identifier=identifier)
    except ValidationError as error:
        raise ValueError(f"{text!r} is not a marketplace principal") from error
    if principal_text(identity) != text:
        raise ValueError(f"{text!r} is not written as the profile writes its principal")
    return identity


def resource_is_signable(value: str) -> bool:
    """Whether a header field, and so a signature base, can hold ``value`` as it is."""

    return bool(value) and value.isascii() and value.isprintable() and value == value.strip(" \t")


def covered_query(query: str) -> str:
    """The ``@query`` a request with this query suffix covers.

    ``query`` is the request target's query suffix as sent: empty where the request
    has no query, or ``?`` and the query. RFC 9421 covers both an absent and an
    empty query as ``?`` alone. A query outside RFC 3986's grammar is refused.
    """

    if query and not query.startswith("?"):
        raise ValueError("a query suffix is empty or starts with '?'")
    if not _QUERY.fullmatch(query[1:]):
        raise ValueError("a query is RFC 3986 query characters and percent escapes")
    return query or "?"


def _method(value: str) -> str:
    if not value.isascii() or not value.isalpha() or value != value.upper():
        raise ValueError("method must be upper-case ASCII letters")
    return value


def _token(value: str, name: str) -> str:
    if not _TOKEN.fullmatch(value):
        raise ValueError(f"{name} must be a bounded ASCII token")
    return value


def _request_id(value: str) -> str:
    if not _REQUEST_ID.fullmatch(value):
        raise ValueError("request_id must be a bounded ASCII token")
    return value


def _resource(value: str | None) -> str | None:
    if value is not None and not resource_is_signable(value):
        raise ValueError("resource must be non-empty printable ASCII with no surrounding whitespace")
    return value


def _stated(value: str, name: str) -> str:
    # A response binds what its request stated, which a refusal signs as it was
    # sent, so it is held only to what a signature base can carry.
    if not value.isascii() or not value.isprintable() or value != value.strip(" \t"):
        raise ValueError(f"{name} must be printable ASCII with no surrounding whitespace")
    return value


def _proof_for(principal: str, proof: str) -> None:
    SignatureProof(scheme=principal_identity(principal).scheme, value=proof)


class RequestRecord(ContractModel):
    """The signed values of a version 3 request addressed to marketplace authorities."""

    protocol: Literal[REQUEST_PROFILE] = REQUEST_PROFILE
    principal: str = Field(min_length=1, max_length=256)
    role: str = Field(min_length=1, max_length=64)
    method: str = Field(min_length=1, max_length=32)
    #: The covered ``@query``, ``?`` where the request had no query. Unbounded
    #: beyond what a request target carries, since every verified request has one.
    query: str = Field(min_length=1)
    operation: str = Field(min_length=1, max_length=128)
    resource: str | None = Field(default=None, max_length=MAX_RESOURCE_CHARACTERS)
    request_id: str = Field(min_length=1, max_length=128)
    timestamp: int = Field(ge=0)
    origin: int = Field(ge=0, le=999_999_999_999_999)
    audience: tuple[str, ...] = Field(min_length=1)
    proof: str = Field(min_length=1, max_length=256)

    @field_validator("audience", mode="before")
    @classmethod
    def accept_wire_audience_array(cls, value: object) -> object:
        # A record decoded from JSON holds its audience as a list.
        return tuple(value) if isinstance(value, list) else value

    @field_validator("principal")
    @classmethod
    def validate_principal(cls, value: str) -> str:
        principal_identity(value)
        return value

    @field_validator("audience")
    @classmethod
    def validate_audience(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for member in value:
            principal_identity(member)
        return value

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str) -> str:
        return _token(value, "role")

    @field_validator("operation")
    @classmethod
    def validate_operation(cls, value: str) -> str:
        return _token(value, "operation")

    @field_validator("method")
    @classmethod
    def validate_method(cls, value: str) -> str:
        return _method(value)

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        # The covered value itself, never an empty suffix: one spelling of each
        # query, so a record rebuilds the signature base it was taken from.
        if covered_query(value) != value:
            raise ValueError("query is the covered @query value, '?' for no query")
        return value

    @field_validator("resource")
    @classmethod
    def validate_resource(cls, value: str | None) -> str | None:
        return _resource(value)

    @field_validator("request_id")
    @classmethod
    def validate_request_id(cls, value: str) -> str:
        return _request_id(value)

    @model_validator(mode="after")
    def validate_proof(self) -> RequestRecord:
        _proof_for(self.principal, self.proof)
        return self

    @model_serializer(mode="wrap")
    def omit_absent_resource(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        if self.resource is None:
            data.pop(RecordField.RESOURCE.value, None)
        return data

    @property
    def identity(self) -> Identity:
        """The principal that signed the request."""

        return principal_identity(self.principal)


class ResponseRecord(ContractModel):
    """The signed values of a version 3 response, and of the request it answers.

    The answered request's method, operation, resource and request ID are what
    the response's signature binds, which for a refusal of an unverified request
    are the values it stated.
    """

    protocol: Literal[RESPONSE_PROFILE] = RESPONSE_PROFILE
    principal: str = Field(min_length=1, max_length=256)
    status: int = Field(ge=100, le=599)
    timestamp: int = Field(ge=0)
    # Unbounded beyond what a header carries: a refusal binds what its request
    # stated, however long, and signing it must not fail for that.
    method: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    resource: str | None = None
    request_id: str = Field(min_length=1)
    proof: str = Field(min_length=1, max_length=256)

    @field_validator("principal")
    @classmethod
    def validate_principal(cls, value: str) -> str:
        principal_identity(value)
        return value

    @field_validator("method")
    @classmethod
    def validate_method(cls, value: str) -> str:
        return _method(value)

    @field_validator("operation", "request_id")
    @classmethod
    def validate_stated(cls, value: str, info: ValidationInfo) -> str:
        return _stated(value, str(info.field_name))

    @field_validator("resource")
    @classmethod
    def validate_resource(cls, value: str | None) -> str | None:
        return None if value is None else _stated(value, "resource")

    @model_validator(mode="after")
    def validate_proof(self) -> ResponseRecord:
        _proof_for(self.principal, self.proof)
        return self

    @model_serializer(mode="wrap")
    def omit_absent_resource(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        if self.resource is None:
            data.pop(RecordField.RESOURCE.value, None)
        return data

    @property
    def identity(self) -> Identity:
        """The principal that signed the response."""

        return principal_identity(self.principal)
