from __future__ import annotations

import time
from typing import Any

from market_identity import (
    Ed25519Signer,
    ResponseEnvelope,
    TrustedIdentitySet,
    canonical_body_hash,
    sign_response,
)

BUYER_SIGNER = Ed25519Signer(b"\x31" * 32)
SELLER_SIGNER = Ed25519Signer(b"\x32" * 32)
SELLER_TRUST = TrustedIdentitySet(identities=(SELLER_SIGNER.identity,))


def seller_principals() -> TrustedIdentitySet:
    return SELLER_TRUST


def signed_response_headers(
    request: Any,
    body: dict[str, Any],
    *,
    status: int = 200,
) -> dict[str, str]:
    request_headers = {key.lower(): value for key, value in request.header_items()}
    url = request.full_url.rstrip("/")
    if url.endswith("/negotiate/new"):
        operation = "negotiate_new"
        resource = str(body.get("listing_id") or "")
        if request.data:
            import json

            resource = str(json.loads(request.data.decode("utf-8"))["listing_id"])
    elif url.endswith("/status") and "/settle/" in url:
        operation = "settle_status"
        resource = url.rsplit("/", 2)[-2]
    elif "/settle/" in url:
        operation = "settle_escrow"
        resource = url.rsplit("/", 1)[-1]
    else:
        operation = "negotiate_continue"
        resource = url.rsplit("/", 1)[-1]
    timestamp = int(time.time())
    signed = sign_response(
        signer=SELLER_SIGNER,
        envelope=ResponseEnvelope(
            role="seller",
            principal=SELLER_SIGNER.identity,
            method=request.get_method(),
            operation=operation,
            resource=resource,
            request_id=request_headers["x-market-request-id"],
            timestamp=timestamp,
            status=status,
            body_hash=canonical_body_hash(body),
        ),
    )
    return {
        "X-Market-Signature-Version": signed.protocol,
        "X-Market-Identity-Scheme": signed.principal.scheme.value,
        "X-Market-Identity-Identifier": signed.principal.identifier,
        "X-Market-Role": signed.role,
        "X-Market-Request-ID": signed.request_id,
        "X-Market-Timestamp": str(signed.timestamp),
        "X-Market-Signature": signed.proof.value,
    }
