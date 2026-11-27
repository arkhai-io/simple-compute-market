"""Common HTTP framing for the registry's v2 marketplace proofs."""

from collections.abc import Mapping
import json
from typing import Any

import injected_time
from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse
from market_identity import EMPTY_BODY, ResponseEnvelope, Signer, canonical_body_hash, sign_response


SIGNATURE_VERSION_HEADER = "X-Market-Signature-Version"
IDENTITY_SCHEME_HEADER = "X-Market-Identity-Scheme"
IDENTITY_IDENTIFIER_HEADER = "X-Market-Identity-Identifier"
ROLE_HEADER = "X-Market-Role"
REQUEST_ID_HEADER = "X-Market-Request-ID"
TIMESTAMP_HEADER = "X-Market-Timestamp"
SIGNATURE_HEADER = "X-Market-Signature"

def request_signature_fields(
    headers: Mapping[str, str], *, method: str, operation: str, resource: str, body: Any
) -> dict[str, Any]:
    """Reconstruct the envelope from wire data and route-owned context."""
    try:
        timestamp: int | str = int(headers[TIMESTAMP_HEADER])
    except (KeyError, TypeError, ValueError):
        timestamp = headers.get(TIMESTAMP_HEADER, "")
    scheme = headers.get(IDENTITY_SCHEME_HEADER, "")
    return {
        "protocol": headers.get(SIGNATURE_VERSION_HEADER, ""),
        "role": headers.get(ROLE_HEADER, ""),
        "principal": {"scheme": scheme, "identifier": headers.get(IDENTITY_IDENTIFIER_HEADER, "")},
        "method": method,
        "operation": operation,
        "resource": resource,
        "request_id": headers.get(REQUEST_ID_HEADER, ""),
        "timestamp": timestamp,
        "body_hash": canonical_body_hash(body),
        "proof": {"scheme": scheme, "value": headers.get(SIGNATURE_HEADER, "")},
    }


def wire_body(raw: bytes) -> Any:
    """The body as the caller sent it, for signature verification.

    A proof binds the bytes the caller hashed. Verifying against a value
    re-serialized from a typed model instead compares a different document:
    every field the model defaults or coerces is present in the server's view
    and absent from the caller's, so a payload that omits an optional field
    fails with a context mismatch that names nothing about the cause. Routes
    that parse into a model keep the model for validation and pass this for
    authentication.
    """
    if not raw:
        return EMPTY_BODY
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return raw.decode("utf-8", errors="replace")


def registry_authority_signer(request: Request) -> Signer:
    signer = getattr(request.app.state, "registry_authority_signer", None)
    if signer is None:
        raise HTTPException(status_code=503, detail="Registry authority unavailable")
    return signer


def signed_context_response(
    *, method: str, operation: str, resource: str, request_id: str,
    signer: Signer, status: int, body: Any,
) -> Response:
    response_body: Any = EMPTY_BODY if status == 204 else body
    envelope = ResponseEnvelope(
        role="registry",
        principal=signer.identity,
        method=method,
        operation=operation,
        resource=resource,
        request_id=request_id,
        timestamp=injected_time.now(),
        status=status,
        body_hash=canonical_body_hash(response_body),
    )
    signed = sign_response(signer=signer, envelope=envelope)
    headers = {
        SIGNATURE_VERSION_HEADER: signed.protocol,
        IDENTITY_SCHEME_HEADER: signed.principal.scheme.value,
        IDENTITY_IDENTIFIER_HEADER: signed.principal.identifier,
        ROLE_HEADER: signed.role,
        REQUEST_ID_HEADER: signed.request_id,
        TIMESTAMP_HEADER: str(signed.timestamp),
        SIGNATURE_HEADER: signed.proof.value,
    }
    if status == 204:
        return Response(status_code=status, headers=headers)
    return JSONResponse(status_code=status, content=body, headers=headers)
