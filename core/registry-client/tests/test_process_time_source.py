"""The registry client signs and judges freshness by the process time source."""

from __future__ import annotations

from collections.abc import Iterator

import injected_time
import pytest
from injected_time import InjectedTime
from market_identity import TrustedIdentitySet, verify_market_request
from market_identity.fixtures.messages import build_signed_response, development_authority, development_signer

from registry_client.auth import SignedRegistryRequest, sign_registry_request, verify_registry_response

#: An instant the wall clock has left behind by far more than the signing skew,
#: so a read of the wall clock anywhere on the path fails the response's skew.
INSTANT = 1_794_822_300

_SELLER = development_signer("ed25519")
_REGISTRY = development_authority("ed25519")
_REGISTRIES = TrustedIdentitySet(identities=(_REGISTRY.identity,))
_BODY = b'{"listing_id":"listing"}'


@pytest.fixture(autouse=True)
def source() -> Iterator[InjectedTime]:
    before = injected_time.installed()
    held = InjectedTime(start=INSTANT)
    injected_time.install(held)
    yield held
    injected_time.install(before)


def _request() -> SignedRegistryRequest:
    return sign_registry_request(
        signer=_SELLER, role="seller", method="POST", path="/listings", body=_BODY, audience=_REGISTRIES
    )


def test_a_signed_request_carries_the_source_s_instant_as_its_signing_time_and_origin() -> None:
    signed = _request()
    request = verify_market_request(method="POST", headers=signed.headers, body=_BODY).request

    assert request is not None
    assert (request.created, request.origin) == (INSTANT, INSTANT)


def test_a_response_signed_at_the_source_s_instant_verifies() -> None:
    signed = _request()
    answer = build_signed_response(signer=_REGISTRY, request=signed.binding, body=b"{}", created=INSTANT)

    verify_registry_response(
        status=200, headers=answer.headers, body=answer.body, binding=signed.binding, expected_registries=_REGISTRIES
    )


def test_a_response_past_the_skew_from_the_source_is_refused(source: InjectedTime) -> None:
    signed = _request()
    answer = build_signed_response(signer=_REGISTRY, request=signed.binding, body=b"{}", created=INSTANT)
    source.set(INSTANT + 301)

    with pytest.raises(ValueError, match="timestamp_skew"):
        verify_registry_response(
            status=200, headers=answer.headers, body=answer.body, binding=signed.binding,
            expected_registries=_REGISTRIES,
        )
