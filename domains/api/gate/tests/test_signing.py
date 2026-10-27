"""A response the gate cannot establish as its authority's is refused under the deployment's label."""

from __future__ import annotations

import time

import pytest
from market_identity import (
    EMPTY_BODY,
    Ed25519Signer,
    ResponseEnvelope,
    canonical_body_hash,
    sign_response,
)

from arkhai_api_gate.signing import (
    AUTHORITY_RESPONSE_ROLE,
    AuthoritySigning,
    ResponseAuthenticationError,
    build_trusted_authorities,
)

# Development seeds, 32 bytes each; never used on any network.
GATE = Ed25519Signer(b"gate-test-gated-app-seed-32byte!")
AUTHORITY = Ed25519Signer(b"gate-test-authority-seed-32byte!")
IMPOSTOR = Ed25519Signer(b"gate-test-impostor-seed-32bytes!")
LABEL = "test-authority"


def _signing() -> AuthoritySigning:
    return AuthoritySigning(
        authority_label=LABEL,
        signer=GATE,
        expected_authorities=build_trusted_authorities([AUTHORITY.identity.model_dump(mode="json")]),
    )


def _headers(signer: Ed25519Signer, call, status: int) -> dict[str, str]:
    signed = sign_response(
        signer=signer,
        envelope=ResponseEnvelope(
            role=AUTHORITY_RESPONSE_ROLE,
            principal=signer.identity,
            method=call.method,
            operation=call.operation,
            resource=call.resource,
            request_id=call.request_id,
            timestamp=int(time.time()),
            status=status,
            body_hash=canonical_body_hash(EMPTY_BODY),
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


def _call(signing: AuthoritySigning):
    return signing.sign(method="POST", operation="credits_key_verify", resource="ak_x", body={"secret": "s"})


def test_a_response_from_the_trusted_authority_verifies():
    signing = _signing()
    call = _call(signing)

    signing.verify(call, headers=_headers(AUTHORITY, call, 200), status=200)


def test_a_response_without_authentication_names_the_deployments_authority():
    signing = _signing()

    with pytest.raises(ResponseAuthenticationError, match=rf"^HTTP 200: missing or malformed {LABEL} response authentication$"):
        signing.verify(_call(signing), headers={}, status=200)


def test_a_response_signed_by_an_untrusted_key_names_the_deployments_authority():
    signing = _signing()
    call = _call(signing)

    with pytest.raises(ResponseAuthenticationError, match=rf"^HTTP 402: {LABEL} response authentication failed: "):
        signing.verify(call, headers=_headers(IMPOSTOR, call, 402), status=402)
