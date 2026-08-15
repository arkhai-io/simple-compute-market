"""Behavioral coverage for the marketplace identity v2 client contract."""

from __future__ import annotations

import inspect

import pytest
from market_identity import (
    AuthenticatedRequest,
    Ed25519Signer,
    Eip191Signer,
    Identity,
    ResponseEnvelope,
    SignatureProof,
    VerificationCode,
    TrustedIdentitySet,
    canonical_body_hash,
    canonical_json,
    sign_response,
    verify_request,
)

from storefront_client import (
    StorefrontAuthenticationError,
    SyncStorefrontClient,
    build_authenticated_request,
    verify_authenticated_response,
)
from storefront_client.auth import (
    IDENTITY_IDENTIFIER_HEADER,
    IDENTITY_SCHEME_HEADER,
    REQUEST_ID_HEADER,
    ROLE_HEADER,
    SIGNATURE_HEADER,
    SIGNATURE_VERSION_HEADER,
    TIMESTAMP_HEADER,
)

_EIP_PRIVATE_KEY = (
    "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a"
)


def _signers():
    return [Ed25519Signer(bytes(range(32))), Eip191Signer(_EIP_PRIVATE_KEY)]


def _authenticated(request):
    scheme = request.headers[IDENTITY_SCHEME_HEADER]
    return AuthenticatedRequest(
        protocol=request.headers[SIGNATURE_VERSION_HEADER],
        role=request.headers[ROLE_HEADER],
        principal=Identity(
            scheme=scheme,
            identifier=request.headers[IDENTITY_IDENTIFIER_HEADER],
        ),
        method=request.method,
        operation=request.operation,
        resource=request.resource,
        request_id=request.headers[REQUEST_ID_HEADER],
        timestamp=int(request.headers[TIMESTAMP_HEADER]),
        body_hash=canonical_body_hash(request.body),
        proof=SignatureProof(
            scheme=scheme,
            value=request.headers[SIGNATURE_HEADER],
        ),
    )


def _response_headers(*, signer, request, body, status=200):
    authenticated = sign_response(
        signer=signer,
        envelope=ResponseEnvelope(
            role="seller",
            principal=signer.identity,
            method=request.method,
            operation=request.operation,
            resource=request.resource,
            request_id=request.request_id,
            timestamp=1_000,
            status=status,
            body_hash=canonical_body_hash(body),
        ),
    )
    return {
        SIGNATURE_VERSION_HEADER: authenticated.protocol,
        IDENTITY_SCHEME_HEADER: authenticated.principal.scheme.value,
        IDENTITY_IDENTIFIER_HEADER: authenticated.principal.identifier,
        ROLE_HEADER: authenticated.role,
        REQUEST_ID_HEADER: authenticated.request_id,
        TIMESTAMP_HEADER: str(authenticated.timestamp),
        SIGNATURE_HEADER: authenticated.proof.value,
    }


@pytest.mark.parametrize("signer", _signers())
def test_both_signer_schemes_use_one_body_bound_contract(signer):
    body = {"listing_id": "listing-1", "nested": {"amount": 7}}
    request = build_authenticated_request(
        signer=signer,
        role="buyer",
        method="post",
        operation="negotiate_new",
        resource="listing-1",
        body=body,
        request_id="request-1",
        timestamp=1_000,
    )

    assert request.content == canonical_json(body)
    assert request.headers[IDENTITY_SCHEME_HEADER] == signer.identity.scheme.value
    assert request.headers[IDENTITY_IDENTIFIER_HEADER] == signer.identity.identifier
    assert request.headers[ROLE_HEADER] == "buyer"
    assert request.headers[REQUEST_ID_HEADER] == "request-1"
    result = verify_request(
        _authenticated(request),
        body=body,
        now=1_000,
        max_skew=0,
        expected_role="buyer",
        expected_method="POST",
        expected_operation="negotiate_new",
        expected_resource="listing-1",
        expected_principals=TrustedIdentitySet(
            identities=(signer.identity,)
        ),
    )
    assert result.code == VerificationCode.VERIFIED


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("role", "seller"),
        ("method", "PATCH"),
        ("operation", "negotiate_continue"),
        ("resource", "listing-2"),
        ("request_id", "request-2"),
    ],
)
def test_signed_request_context_mutations_fail_closed(field, value):
    signer = Ed25519Signer(bytes(range(32)))
    body = {"amount": 7}
    request = build_authenticated_request(
        signer=signer,
        role="buyer",
        method="POST",
        operation="negotiate_new",
        resource="listing-1",
        body=body,
        request_id="request-1",
        timestamp=1_000,
    )
    envelope = _authenticated(request).model_copy(update={field: value})

    result = verify_request(
        envelope,
        body=body,
        now=1_000,
        max_skew=0,
        expected_role="buyer",
        expected_method="POST",
        expected_operation="negotiate_new",
        expected_resource="listing-1",
        expected_principals=TrustedIdentitySet(
            identities=(signer.identity,)
        ),
    )
    assert not result.verified


def test_signed_request_body_mutation_fails_closed():
    signer = Ed25519Signer(bytes(range(32)))
    original = {"amount": 7, "nested": {"region": "us"}}
    request = build_authenticated_request(
        signer=signer,
        role="buyer",
        method="POST",
        operation="negotiate_new",
        resource="listing-1",
        body=original,
        request_id="request-1",
        timestamp=1_000,
    )

    result = verify_request(
        _authenticated(request),
        body={"amount": 8, "nested": {"region": "us"}},
        now=1_000,
        max_skew=0,
        expected_role="buyer",
        expected_method="POST",
        expected_operation="negotiate_new",
        expected_resource="listing-1",
        expected_principals=TrustedIdentitySet(
            identities=(signer.identity,)
        ),
    )
    assert result.code == VerificationCode.BODY_HASH_MISMATCH


def test_response_verification_pins_publisher_and_body():
    buyer = Ed25519Signer(bytes(range(32)))
    publisher = Ed25519Signer(bytes(range(1, 33)))
    request = build_authenticated_request(
        signer=buyer,
        role="buyer",
        method="POST",
        operation="negotiate_new",
        resource="listing-1",
        body={"amount": 7},
        request_id="request-1",
        timestamp=1_000,
    )
    response_body = {"action": "accept", "amount": 7}
    headers = _response_headers(
        signer=publisher,
        request=request,
        body=response_body,
    )

    verify_authenticated_response(
        headers=headers,
        expected_publishers=TrustedIdentitySet(
            identities=(
                Ed25519Signer(bytes(range(2, 34))).identity,
                publisher.identity,
            )
        ),
        request=request,
        status=200,
        body=response_body,
        now=1_000,
        max_skew=0,
    )
    with pytest.raises(StorefrontAuthenticationError):
        verify_authenticated_response(
            headers=headers,
            expected_publishers=TrustedIdentitySet(
                identities=(publisher.identity,)
            ),
            request=request,
            status=200,
            body={"action": "reject", "amount": 7},
            now=1_000,
            max_skew=0,
        )
    with pytest.raises(StorefrontAuthenticationError):
        verify_authenticated_response(
            headers=headers,
            expected_publishers=TrustedIdentitySet(
                identities=(
                    Ed25519Signer(bytes(range(2, 34))).identity,
                )
            ),
            request=request,
            status=200,
            body=response_body,
            now=1_000,
            max_skew=0,
        )

@pytest.mark.parametrize(
    ("header", "value"),
    [
        (ROLE_HEADER, "buyer"),
        (REQUEST_ID_HEADER, "another-request"),
        (TIMESTAMP_HEADER, "1001"),
    ],
)
def test_response_context_mutations_fail_closed(header, value):
    buyer = Ed25519Signer(bytes(range(32)))
    publisher = Ed25519Signer(bytes(range(1, 33)))
    request = build_authenticated_request(
        signer=buyer,
        role="buyer",
        method="POST",
        operation="negotiate_new",
        resource="listing-1",
        body={"amount": 7},
        request_id="request-1",
        timestamp=1_000,
    )
    body = {"action": "accept"}
    headers = _response_headers(signer=publisher, request=request, body=body)
    headers[header] = value

    with pytest.raises(StorefrontAuthenticationError):
        verify_authenticated_response(
            headers=headers,
            expected_publishers=TrustedIdentitySet(
                identities=(publisher.identity,)
            ),
            request=request,
            status=200,
            body=body,
            now=1_000,
            max_skew=10,
        )


def test_legacy_and_unknown_response_protocols_fail_closed():
    buyer = Ed25519Signer(bytes(range(32)))
    publisher = Ed25519Signer(bytes(range(1, 33)))
    request = build_authenticated_request(
        signer=buyer,
        role="buyer",
        method="GET",
        operation="settle_status",
        resource="escrow-1",
        request_id="request-1",
        timestamp=1_000,
    )
    body = {"status": "ready"}
    headers = _response_headers(signer=publisher, request=request, body=body)

    for protocol in ("arkhai.market-response-signature.v1", "unknown"):
        mutated = dict(headers)
        mutated[SIGNATURE_VERSION_HEADER] = protocol
        with pytest.raises(StorefrontAuthenticationError):
            verify_authenticated_response(
                headers=mutated,
                expected_publishers=TrustedIdentitySet(
                    identities=(publisher.identity,)
                ),
                request=request,
                status=200,
                body=body,
                now=1_000,
                max_skew=0,
            )


def test_generic_client_has_no_private_key_or_identity_tag_configuration():
    parameters = inspect.signature(SyncStorefrontClient).parameters
    assert "private_key" not in parameters
    assert "identity_scheme" not in parameters
    assert "identity_identifier" not in parameters
    assert "expected_publisher" not in parameters


def test_client_rejects_missing_or_mismatched_signer_configuration():
    signer = Ed25519Signer(bytes(range(32)))
    with pytest.raises(ValueError, match="caller_role"):
        SyncStorefrontClient("http://test", signer=signer)
    with pytest.raises(ValueError, match="expected_publishers"):
        SyncStorefrontClient(
            "http://test",
            signer=signer,
            caller_role="buyer",
        )
    with pytest.raises(ValueError, match="requires signer"):
        SyncStorefrontClient(
            "http://test",
            expected_publishers=TrustedIdentitySet(
                identities=(signer.identity,)
            ),
        )
    with pytest.raises(TypeError, match="TrustedIdentitySet"):
        SyncStorefrontClient(
            "http://test",
            signer=signer,
            caller_role="buyer",
            expected_publishers=signer.identity,
        )
    with pytest.raises(ValueError, match="requires a configured signer"):
        with SyncStorefrontClient("http://test") as client:
            client.close_listing("listing-1")
    with pytest.raises(ValueError, match="requires caller_role='seller'"):
        with SyncStorefrontClient(
            "http://test",
            signer=signer,
            caller_role="buyer",
            expected_publishers=TrustedIdentitySet(
                identities=(signer.identity,)
            ),
        ) as client:
            client.close_listing("listing-1")


def test_seller_signer_and_publisher_pin_must_match():
    with pytest.raises(ValueError, match="in expected_publishers"):
        SyncStorefrontClient(
            "http://test",
            signer=Ed25519Signer(bytes(range(32))),
            caller_role="seller",
            expected_publishers=TrustedIdentitySet(
                identities=(
                    Ed25519Signer(bytes(range(1, 33))).identity,
                )
            ),
        )
