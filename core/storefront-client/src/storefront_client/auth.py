"""HTTP mapping for the marketplace identity v2 request/response contract."""

from __future__ import annotations

import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from market_identity import (
    EMPTY_BODY,
    RESPONSE_PROTOCOL,
    AuthenticatedResponse,
    Identity,
    RequestEnvelope,
    SignatureProof,
    Signer,
    TrustedIdentitySet,
    VerificationCode,
    canonical_body_hash,
    canonical_json,
    sign_request,
    verify_response,
)

SIGNATURE_VERSION_HEADER = "X-Market-Signature-Version"
IDENTITY_SCHEME_HEADER = "X-Market-Identity-Scheme"
IDENTITY_IDENTIFIER_HEADER = "X-Market-Identity-Identifier"
ROLE_HEADER = "X-Market-Role"
REQUEST_ID_HEADER = "X-Market-Request-ID"
TIMESTAMP_HEADER = "X-Market-Timestamp"
SIGNATURE_HEADER = "X-Market-Signature"
AUTH_HEADERS = frozenset(
    {
        SIGNATURE_VERSION_HEADER,
        IDENTITY_SCHEME_HEADER,
        IDENTITY_IDENTIFIER_HEADER,
        ROLE_HEADER,
        REQUEST_ID_HEADER,
        TIMESTAMP_HEADER,
        SIGNATURE_HEADER,
    }
)
LEGACY_AUTH_HEADERS = frozenset(
    {
        "X-Signature",
        "X-Timestamp",
        "X-Identity-Scheme",
        "X-Identity",
    }
)
DEFAULT_MAX_RESPONSE_SKEW = 300


class StorefrontAuthenticationError(ValueError):
    """The peer did not satisfy the marketplace identity v2 contract."""


@dataclass(frozen=True)
class SignedRequest:
    """Canonical body bytes and transport headers for one signed request."""

    method: str
    operation: str
    resource: str
    role: str
    request_id: str
    timestamp: int
    body: Any
    content: bytes | None
    headers: dict[str, str]


def build_authenticated_request(
    *,
    signer: Signer,
    role: str,
    method: str,
    operation: str,
    resource: str,
    body: Any = EMPTY_BODY,
    request_id: str | None = None,
    timestamp: int | None = None,
) -> SignedRequest:
    """Build a scheme-neutral v2 request from one injected signer.

    The principal and proof scheme are taken exclusively from ``signer``. JSON
    requests are serialized once to RFC 8785 bytes, and those exact bytes are
    sent by both clients.
    """

    if not isinstance(signer, Signer):
        raise TypeError("signer must implement market_identity.Signer")
    if not isinstance(signer.identity, Identity):
        raise TypeError("signer.identity must be a market_identity.Identity")
    normalized_request_id = uuid.uuid4().hex if request_id is None else request_id
    normalized_timestamp = int(time.time()) if timestamp is None else timestamp
    content = None if body is EMPTY_BODY else canonical_json(body)
    authenticated = sign_request(
        signer=signer,
        envelope=RequestEnvelope(
            role=role,
            principal=signer.identity,
            method=method,
            operation=operation,
            resource=resource,
            request_id=normalized_request_id,
            timestamp=normalized_timestamp,
            body_hash=canonical_body_hash(body),
        ),
    )
    headers = {
        "Accept": "application/json",
        SIGNATURE_VERSION_HEADER: authenticated.protocol,
        IDENTITY_SCHEME_HEADER: authenticated.principal.scheme.value,
        IDENTITY_IDENTIFIER_HEADER: authenticated.principal.identifier,
        ROLE_HEADER: authenticated.role,
        REQUEST_ID_HEADER: authenticated.request_id,
        TIMESTAMP_HEADER: str(authenticated.timestamp),
        SIGNATURE_HEADER: authenticated.proof.value,
    }
    if content is not None:
        headers["Content-Type"] = "application/json"
    return SignedRequest(
        method=authenticated.method,
        operation=authenticated.operation,
        resource=authenticated.resource,
        role=authenticated.role,
        request_id=authenticated.request_id,
        timestamp=authenticated.timestamp,
        body=body,
        content=content,
        headers=headers,
    )


def verify_authenticated_response(
    *,
    headers: Mapping[str, str],
    expected_publishers: TrustedIdentitySet,
    request: SignedRequest,
    status: int,
    body: Any = EMPTY_BODY,
    now: int | None = None,
    max_skew: int = DEFAULT_MAX_RESPONSE_SKEW,
) -> None:
    """Verify one response against an exact trusted publisher set."""
    if not isinstance(expected_publishers, TrustedIdentitySet):
        raise TypeError(
            "expected_publishers must be a market_identity.TrustedIdentitySet"
        )


    # Which of these fails says what happened: a response with none of the
    # headers was never an acknowledgement, and one missing a single header is
    # a protocol fault. The status is carried into either, because an error
    # answer and an unsigned acknowledgement are the same shape from here.
    try:
        protocol = _required_header(headers, SIGNATURE_VERSION_HEADER)
        if protocol != RESPONSE_PROTOCOL:
            raise StorefrontAuthenticationError(
                "unsupported marketplace response signature version"
            )
        scheme = _required_header(headers, IDENTITY_SCHEME_HEADER)
        principal = Identity(
            scheme=scheme,
            identifier=_required_header(headers, IDENTITY_IDENTIFIER_HEADER),
        )
        authenticated = AuthenticatedResponse(
            protocol=protocol,
            role=_required_header(headers, ROLE_HEADER),
            principal=principal,
            method=request.method,
            operation=request.operation,
            resource=request.resource,
            request_id=_required_header(headers, REQUEST_ID_HEADER),
            timestamp=int(_required_header(headers, TIMESTAMP_HEADER)),
            status=status,
            body_hash=canonical_body_hash(body),
            proof=SignatureProof(
                scheme=scheme,
                value=_required_header(headers, SIGNATURE_HEADER),
            ),
        )
    except StorefrontAuthenticationError as exc:
        raise StorefrontAuthenticationError(f"HTTP {status}: {exc}") from exc
    except (TypeError, ValueError) as exc:
        raise StorefrontAuthenticationError(
            f"HTTP {status}: unreadable marketplace response authentication"
        ) from exc
    result = verify_response(
        authenticated,
        body=body,
        now=int(time.time()) if now is None else now,
        max_skew=max_skew,
        expected_role="seller",
        expected_principals=expected_publishers,
        expected_method=request.method,
        expected_operation=request.operation,
        expected_resource=request.resource,
        expected_request_id=request.request_id,
    )
    if result.code != VerificationCode.VERIFIED:
        raise StorefrontAuthenticationError(
            f"marketplace response authentication failed: {result.code.value}"
        )


def response_has_authentication(headers: Mapping[str, str]) -> bool:
    """Return whether any v2 or rejected legacy authentication header is present."""

    lower = {str(key).lower() for key in headers}
    return any(
        name.lower() in lower for name in AUTH_HEADERS | LEGACY_AUTH_HEADERS
    )


def _required_header(headers: Mapping[str, str], name: str) -> str:
    value = headers.get(name)
    if value is None:
        lowered = name.lower()
        for key, candidate in headers.items():
            if str(key).lower() == lowered:
                value = candidate
                break
    if not isinstance(value, str) or not value:
        raise StorefrontAuthenticationError(f"missing {name} header")
    return value
