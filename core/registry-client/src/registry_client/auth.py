"""Versioned, body-bound authentication for every registry request and response."""

from __future__ import annotations

import time
import uuid
from typing import Any

from market_identity import (
    EMPTY_BODY,
    AuthenticatedRequest,
    Identity,
    RequestEnvelope,
    Signer,
    TrustedIdentitySet,
    VerificationCode,
    canonical_body_hash,
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


def authenticate_request(
    *,
    signer: Signer,
    role: str,
    method: str,
    operation: str,
    resource: str,
    body: Any = EMPTY_BODY,
    request_id: str | None = None,
    timestamp: int | None = None,
) -> AuthenticatedRequest:
    """Build and sign one canonical registry request."""

    envelope = RequestEnvelope(
        role=role,
        principal=signer.identity,
        method=method,
        operation=operation,
        resource=resource,
        request_id=request_id or uuid.uuid4().hex,
        timestamp=int(time.time()) if timestamp is None else timestamp,
        body_hash=canonical_body_hash(body),
    )
    return sign_request(signer=signer, envelope=envelope)


def authentication_headers(request: AuthenticatedRequest) -> dict[str, str]:
    """Map an authenticated request to the registry's flat HTTP headers."""

    return {
        "Content-Type": "application/json",
        SIGNATURE_VERSION_HEADER: request.protocol,
        IDENTITY_SCHEME_HEADER: request.principal.scheme.value,
        IDENTITY_IDENTIFIER_HEADER: request.principal.identifier,
        ROLE_HEADER: request.role,
        REQUEST_ID_HEADER: request.request_id,
        TIMESTAMP_HEADER: str(request.timestamp),
        SIGNATURE_HEADER: request.proof.value,
    }

def verify_authenticated_response(
    *,
    headers: Any,
    expected_registries: TrustedIdentitySet,
    request: AuthenticatedRequest,
    status: int,
    body: Any = EMPTY_BODY,
    now: int | None = None,
) -> None:
    """Verify a registry response against its public authority pin and request."""
    try:
        timestamp: int | str = int(headers[TIMESTAMP_HEADER])
    except (KeyError, TypeError, ValueError):
        timestamp = headers.get(TIMESTAMP_HEADER, "")


    scheme = headers.get(IDENTITY_SCHEME_HEADER, "")
    envelope = {
        "protocol": headers.get(SIGNATURE_VERSION_HEADER, ""),
        "role": headers.get(ROLE_HEADER, ""),
        "principal": {
            "scheme": scheme,
            "identifier": headers.get(IDENTITY_IDENTIFIER_HEADER, ""),
        },
        "method": request.method,
        "operation": request.operation,
        "resource": request.resource,
        "request_id": headers.get(REQUEST_ID_HEADER, ""),
        "timestamp": timestamp,
        "status": status,
        "body_hash": canonical_body_hash(body),
        "proof": {
            "scheme": scheme,
            "value": headers.get(SIGNATURE_HEADER, ""),
        },
    }
    result = verify_response(
        envelope,
        body=body,
        now=int(time.time()) if now is None else now,
        max_skew=300,
        expected_role="registry",
        expected_method=request.method,
        expected_operation=request.operation,
        expected_principals=expected_registries,
        expected_resource=request.resource,
        expected_request_id=request.request_id,
    )
    if result.code != VerificationCode.VERIFIED:
        raise ValueError(f"invalid registry response: {result.code.value}")


class RegistryClientError(Exception):
    """Raised when the Registry API returns a non-2xx status code."""

    def __init__(self, method: str, url: str, status_code: int, body: str) -> None:
        self.method = method
        self.url = url
        self.status_code = status_code
        self.body = body
        super().__init__(f"{method} {url} → HTTP {status_code}\n{body}")
