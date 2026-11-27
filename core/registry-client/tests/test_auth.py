"""Registry-client version 3 signing and response verification."""

from __future__ import annotations

import asyncio

import httpx
import injected_time
import pytest
from market_identity import (
    RequestBinding,
    TrustedIdentitySet,
    VerificationCode,
    verify_market_request,
)
from market_identity.fixtures.messages import (
    build_signed_response,
    development_authority,
    development_signer,
    validate_request_record,
)

from registry_client import RegistryClient, RegistryClientError, SyncRegistryClient
from registry_client.auth import request_route, sign_registry_request, verify_registry_response

_REGISTRY = development_authority("ed25519")
_REGISTRIES = TrustedIdentitySet(identities=(_REGISTRY.identity,))
_BODY = b'{"listing_id":"listing","listing_resource":{"region":"us"}}'


@pytest.mark.parametrize("scheme", ["ed25519", "eip191"])
def test_a_publication_is_signed_with_no_resource_and_addressed_to_the_registries(scheme: str) -> None:
    signer = development_signer(scheme)

    signed = sign_registry_request(
        signer=signer, role="seller", method="POST", path="/listings", body=_BODY, audience=_REGISTRIES,
        request_id="request-one", origin=123,
    )
    verification = verify_market_request(method="POST", headers=signed.headers, body=_BODY, query="")

    assert verification.code == VerificationCode.VERIFIED
    assert verification.request is not None
    assert verification.request.addressed_to(_REGISTRY.identity)
    assert (verification.request.operation, verification.request.resource) == ("listing.publish", None)
    assert (verification.request.request_id, verification.request.origin) == ("request-one", 123)
    assert "Market-Resource" not in signed.headers
    assert signed.record is not None
    validate_request_record(signed.record.model_dump(mode="json"), resource=False)


def test_the_signature_is_bound_to_the_exact_body() -> None:
    signed = sign_registry_request(
        signer=development_signer(), role="seller", method="POST", path="/listings", body=_BODY, audience=_REGISTRIES
    )

    verification = verify_market_request(
        method="POST", headers=signed.headers, body=_BODY.replace(b"us", b"eu"), query=""
    )

    assert verification.code == VerificationCode.BODY_HASH_MISMATCH


def test_a_read_sends_the_query_its_signature_covers() -> None:
    signed = sign_registry_request(
        signer=development_signer(), role="buyer", method="GET", path="/listings", body=b"", audience=_REGISTRIES,
        query=[("limit", "50"), ("filter_spec_etag", "abc"), ("region", "us east")],
    )

    assert signed.target == "/listings?limit=50&filter_spec_etag=abc&region=us%20east"
    query = signed.target[len("/listings"):]
    assert verify_market_request(method="GET", headers=signed.headers, body=b"", query=query).verified
    altered = query.replace("limit=50", "limit=51")
    assert verify_market_request(method="GET", headers=signed.headers, body=b"", query=altered).code == (
        VerificationCode.INVALID_PROOF
    )


@pytest.mark.parametrize(
    ("method", "path", "route"),
    [
        ("GET", "/listings", ("listing.list", None)),
        ("PUT", "/listings/l-1", ("listing.update", "l-1")),
        ("DELETE", "/listings/l-1", ("listing.delete", "l-1")),
        ("GET", "/filter-spec", ("filter.get", None)),
        ("GET", "/api/v1/system/health", ("health.read", None)),
        ("GET", "/api/v1/system/stats", ("system.stats.read", None)),
        ("POST", "/api/v1/listings/validate-publish", ("listing.validate", None)),
        ("GET", "/publishers", ("publisher.list", None)),
        ("GET", "/publishers/7", ("publisher.get", "7")),
        ("POST", "/publishers/7/identity-rotations", ("publisher.identity.rotate", "7")),
        ("GET", "/publishers/7/identity-rotations/n", ("publisher.identity.rotation.read", "7:n")),
        ("POST", "/publishers/7/identity-rotations/n/retire", ("publisher.identity.retire", "7:n")),
    ],
)
def test_each_route_binds_its_operation_and_its_target_where_it_has_one(
    method: str, path: str, route: tuple[str, str | None]
) -> None:
    assert request_route(method, path) == route


def test_an_answer_signed_by_another_principal_is_refused() -> None:
    signed = sign_registry_request(
        signer=development_signer(), role="buyer", method="GET", path="/filter-spec", body=b"", audience=_REGISTRIES
    )
    answer = build_signed_response(signer=development_signer(index=7), request=signed.binding, body=b"{}")

    with pytest.raises(ValueError, match="wrong_principal"):
        verify_registry_response(
            status=200, headers=answer.headers, body=answer.body, binding=signed.binding,
            expected_registries=_REGISTRIES,
        )


def test_the_client_requires_a_signer_a_role_an_authority_and_a_trust_set() -> None:
    with pytest.raises(TypeError):
        SyncRegistryClient("http://unreachable.invalid")  # type: ignore[call-arg]


class _Unreachable(httpx.BaseTransport, httpx.AsyncBaseTransport):
    """A transport that fails the test if any request reaches it."""

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"no request may be sent: {request.method} {request.url}")

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"no request may be sent: {request.method} {request.url}")


@pytest.mark.parametrize("url", ["http://registry.example", "ftp://registry.example"])
def test_a_bootstrap_given_a_url_not_https_is_refused_naming_the_scheme_before_sending(url: str) -> None:
    scheme = url.partition(":")[0]

    with pytest.raises(ValueError, match=f"over https, not {scheme}"):
        SyncRegistryClient.bootstrap_registry_descriptor(url, transport=_Unreachable())


def test_the_async_bootstrap_refuses_plain_http_before_sending() -> None:
    with pytest.raises(ValueError, match="over https, not http"):
        asyncio.run(RegistryClient.bootstrap_registry_descriptor("http://registry.example", transport=_Unreachable()))


def test_a_refusal_raises_with_the_registry_s_status() -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        binding = RequestBinding(
            method="GET", operation="filter.get", request_id=request.headers["Market-Request-ID"]
        )
        signed = build_signed_response(
            signer=_REGISTRY, request=binding, status=403, body=b'{"detail":"no"}', created=injected_time.now()
        )
        return httpx.Response(signed.status, headers=signed.headers, content=signed.body)

    client = SyncRegistryClient(
        "http://registry.test", signer=development_signer(), caller_role="buyer",
        expected_registries=_REGISTRIES, registry_authority="test-registry",
        transport=httpx.MockTransport(answer),
    )

    with pytest.raises(RegistryClientError) as refused:
        client.get_filter_spec()
    assert refused.value.status_code == 403
