"""Registry-client v2 signer and body-binding contracts."""

from __future__ import annotations

import pytest
from market_identity import (
    Ed25519Signer,
    Eip191Signer,
    TrustedIdentitySet,
    VerificationCode,
    verify_request,
)

from registry_client.auth import authenticate_request, authentication_headers
from registry_client.client import SyncRegistryClient


@pytest.mark.parametrize(
    "signer",
    [
        Eip191Signer(bytes.fromhex("11" * 32)),
        Ed25519Signer(bytes.fromhex("22" * 32)),
    ],
)
def test_both_schemes_emit_the_same_v2_header_contract(signer) -> None:
    body = {"listing_id": "listing", "offer_resource": {"region": "us"}}
    authenticated = authenticate_request(
        signer=signer,
        role="seller",
        method="POST",
        operation="listing.publish",
        resource="listings",
        body=body,
        request_id="request-one",
        timestamp=123,
    )
    headers = authentication_headers(authenticated)
    assert headers["X-Market-Signature-Version"] == (
        "arkhai.market-request-signature.v2"
    )
    assert headers["X-Market-Identity-Scheme"] == signer.identity.scheme.value
    assert headers["X-Market-Identity-Identifier"] == signer.identity.identifier
    assert headers["X-Market-Request-ID"] == "request-one"
    assert "signature" not in body


def test_signature_is_bound_to_exact_body() -> None:
    signer = Ed25519Signer(bytes.fromhex("33" * 32))
    body = {"listing_id": "listing", "status": "open"}
    authenticated = authenticate_request(
        signer=signer,
        role="seller",
        method="POST",
        operation="listing.publish",
        resource="listings",
        body=body,
    )
    result = verify_request(
        authenticated,
        body={**body, "status": "closed"},
        now=authenticated.timestamp,
        max_skew=300,
        expected_role="seller",
        expected_method="POST",
        expected_operation="listing.publish",
        expected_resource="listings",
        expected_principals=TrustedIdentitySet(identities=(signer.identity,)),
    )
    assert result.code == VerificationCode.BODY_HASH_MISMATCH


def test_client_requires_signer_role_authority_and_trust_set() -> None:
    with pytest.raises(TypeError):
        SyncRegistryClient("http://unreachable.invalid")
