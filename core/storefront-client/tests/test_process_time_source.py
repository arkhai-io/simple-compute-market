"""The client signs and judges freshness by the process time source."""

from collections.abc import Iterator

import injected_time
import pytest
from injected_time import InjectedTime
from market_identity import (
    Ed25519Signer,
    ResponseEnvelope,
    TrustedIdentitySet,
    canonical_body_hash,
    sign_response,
)

from storefront_client.auth import (
    IDENTITY_IDENTIFIER_HEADER,
    IDENTITY_SCHEME_HEADER,
    REQUEST_ID_HEADER,
    ROLE_HEADER,
    SIGNATURE_HEADER,
    SIGNATURE_VERSION_HEADER,
    TIMESTAMP_HEADER,
    SignedRequest,
    StorefrontAuthenticationError,
    build_authenticated_request,
    verify_authenticated_response,
)

#: An instant the wall clock has left behind by far more than the signing skew,
#: so a read of the wall clock anywhere on the path fails the response's skew.
INSTANT = 1_794_822_300

_BUYER = Ed25519Signer(bytes(range(32)))
_SELLER = Ed25519Signer(bytes(range(1, 33)))
_BODY = {"status": "ok"}


@pytest.fixture(autouse=True)
def _source() -> Iterator[InjectedTime]:
    before = injected_time.installed()
    source = InjectedTime(start=INSTANT)
    injected_time.install(source)
    yield source
    injected_time.install(before)


def _request() -> SignedRequest:
    return build_authenticated_request(
        signer=_BUYER, role="buyer", method="POST", operation="negotiate_new",
        resource="listing-1", body={"amount": "7"},
    )


def _response_headers(request: SignedRequest, *, timestamp: int) -> dict[str, str]:
    signed = sign_response(
        signer=_SELLER,
        envelope=ResponseEnvelope(
            role="seller", principal=_SELLER.identity, method=request.method,
            operation=request.operation, resource=request.resource,
            request_id=request.request_id, timestamp=timestamp, status=200,
            body_hash=canonical_body_hash(_BODY),
        ),
    )
    return {
        SIGNATURE_VERSION_HEADER: signed.protocol,
        IDENTITY_SCHEME_HEADER: signed.principal.scheme.value,
        IDENTITY_IDENTIFIER_HEADER: signed.principal.identifier,
        ROLE_HEADER: signed.role,
        REQUEST_ID_HEADER: signed.request_id,
        TIMESTAMP_HEADER: str(signed.timestamp),
        SIGNATURE_HEADER: signed.proof.value,
    }


def test_a_signed_request_carries_the_source_s_instant() -> None:
    request = _request()

    assert request.timestamp == INSTANT
    assert request.headers[TIMESTAMP_HEADER] == str(INSTANT)


def test_a_response_stamped_at_the_source_s_instant_verifies() -> None:
    request = _request()

    verify_authenticated_response(
        headers=_response_headers(request, timestamp=INSTANT),
        expected_publishers=TrustedIdentitySet(identities=(_SELLER.identity,)),
        request=request, status=200, body=_BODY,
    )


def test_a_response_past_the_skew_from_the_source_is_refused(
    _source: InjectedTime,
) -> None:
    request = _request()
    _source.set(INSTANT + 301)

    with pytest.raises(StorefrontAuthenticationError, match="timestamp_skew"):
        verify_authenticated_response(
            headers=_response_headers(request, timestamp=INSTANT),
            expected_publishers=TrustedIdentitySet(identities=(_SELLER.identity,)),
            request=request, status=200, body=_BODY,
        )
