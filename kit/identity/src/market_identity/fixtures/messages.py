"""Contract fixtures for version 3 signed messages and their evidence records.

A consumer's test never frames or signs a protocol message itself: it draws one
from here, signed by the same functions the profile's verifier checks against and
pinned by the identity kit's published vectors. Each boundary is a pair:

- ``build_*()`` -- a signed message, with defaults for every value, so a test
  overrides only what it cares about;
- ``validate_*()`` -- asserts a record real code produced keeps the record's shape.

Usage in a consumer test::

    from market_identity.fixtures.messages import READ_QUERY, build_signed_request

    message = build_signed_request(
        scheme="eip191", method="GET", operation="listing.list", resource=None,
        body=b"", query=READ_QUERY,
    )
    client.get(path + message.query, headers=message.headers)

The keys are derived from fixed labels and are well-known development values,
never for a public network.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from market_identity.http_profile import (
    MarketRequest,
    RequestBinding,
    sign_market_request,
    sign_market_response,
)
from market_identity.models import TrustedIdentitySet
from market_identity.records import RequestRecord, ResponseRecord
from market_identity.registry import Signer
from market_identity.schemes import Ed25519Signer, Eip191Signer
from market_identity.wire import RecordField

#: The schemes a fixture message is signed under.
SCHEMES = ("ed25519", "eip191")

#: The signing instant of every fixture message unless a test gives another.
CREATED = 1_795_000_000
REQUEST_BODY = b'{"quantity":1}'
#: A read's query suffix, as :func:`market_identity.http_profile.encode_query`
#: builds it, for a fixture request that carries a query.
READ_QUERY = "?limit=50&offset=0&status=open"
RESPONSE_BODY = b'{"accepted":true}'

_CALLER = 0
_AUTHORITY = 1
_REQUEST_DEFAULTS: dict[str, Any] = {
    "method": "POST",
    "role": "storefront",
    "operation": "capacity_reserve",
    "resource": "pool-gpu-a100",
    "request_id": "0f6c2b1e7d4a4c1e9a523e8b6d0f1a77",
}


def development_signer(scheme: str = "ed25519", *, index: int = _CALLER) -> Signer:
    """A well-known development signer under ``scheme``: index 0 signs as the
    caller, index 1 as the authority, and any other index as another party."""

    key = hashlib.sha256(f"arkhai.market development {scheme} key {index}".encode()).digest()
    if scheme == "ed25519":
        return Ed25519Signer(key)
    if scheme == "eip191":
        return Eip191Signer(key)
    raise ValueError(f"no development signer under {scheme!r}; known: {SCHEMES}")


def development_authority(scheme: str = "ed25519") -> Signer:
    """The authority a fixture request is addressed to, and that signs its answer."""

    return development_signer(scheme, index=_AUTHORITY)


@dataclass(frozen=True)
class FixtureRequest:
    """A signed request as sent: its method, query suffix, headers and body, and its
    record. ``query`` is appended to the request's path as it is."""

    request: MarketRequest
    query: str
    headers: dict[str, str]
    body: bytes
    record: RequestRecord
    signer: Signer

    @property
    def method(self) -> str:
        return self.request.method


@dataclass(frozen=True)
class FixtureResponse:
    """A signed response as sent: its status, headers and body, and its record."""

    binding: RequestBinding
    status: int
    headers: dict[str, str]
    body: bytes
    record: ResponseRecord
    signer: Signer


def build_market_request(**overrides: Any) -> MarketRequest:
    """The semantic fields of a fixture request; ``resource=None`` is an operation
    with no target."""

    values = {**_REQUEST_DEFAULTS, "origin": CREATED, **overrides}
    return MarketRequest(**values)


def build_signed_request(
    *,
    scheme: str = "ed25519",
    signer: Signer | None = None,
    audience: TrustedIdentitySet | None = None,
    body: bytes = REQUEST_BODY,
    created: int = CREATED,
    query: str = "",
    **fields: Any,
) -> FixtureRequest:
    """A version 3 request, signed under ``scheme`` by the development caller or by
    ``signer``, addressed to the development authority or to ``audience``, and sent
    with the query suffix ``query`` -- by default none, so it covers ``?``.

    Any field of :func:`build_market_request` may be given.
    """

    request = build_market_request(**({"origin": created} | fields))
    caller = signer or development_signer(scheme)
    addressed = audience or TrustedIdentitySet(identities=(development_authority(scheme).identity,))
    signed = sign_market_request(
        signer=caller, request=request, body=body, created=created, query=query, audience=addressed
    )
    assert signed.record is not None
    return FixtureRequest(
        request=request, query=query, headers=signed.headers, body=body, record=signed.record, signer=caller
    )


def build_signed_response(
    *,
    scheme: str = "ed25519",
    signer: Signer | None = None,
    request: RequestBinding | None = None,
    status: int = 200,
    body: bytes = RESPONSE_BODY,
    created: int = CREATED + 1,
) -> FixtureResponse:
    """A version 3 response to ``request`` -- by default the fixture request's
    binding -- signed under ``scheme`` by the development authority or by
    ``signer``."""

    binding = request if request is not None else build_market_request().binding
    authority = signer or development_authority(scheme)
    signed = sign_market_response(signer=authority, status=status, body=body, request=binding, created=created)
    return FixtureResponse(
        binding=binding, status=status, headers=signed.headers, body=body, record=signed.record, signer=authority
    )


def validate_request_record(document: Mapping[str, Any], *, resource: bool) -> RequestRecord:
    """Assert ``document`` is a request record as kept, naming a resource exactly
    when ``resource`` says its operation has a target."""

    record = RequestRecord.model_validate(dict(document))
    assert (RecordField.RESOURCE.value in document) is resource, "a record names a resource exactly when its operation has a target"
    assert set(document) <= {field.value for field in RecordField} - {RecordField.STATUS.value}
    return record


def validate_response_record(document: Mapping[str, Any], *, resource: bool) -> ResponseRecord:
    """Assert ``document`` is a response record as kept, naming the answered
    request's resource exactly when ``resource`` says its operation has a target."""

    record = ResponseRecord.model_validate(dict(document))
    assert (RecordField.RESOURCE.value in document) is resource, "a record names a resource exactly when its operation has a target"
    excluded = {
        RecordField.ROLE.value,
        RecordField.QUERY.value,
        RecordField.ORIGIN.value,
        RecordField.AUDIENCE.value,
    }
    assert set(document) <= {field.value for field in RecordField} - excluded
    return record
