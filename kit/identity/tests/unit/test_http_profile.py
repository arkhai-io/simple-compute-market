from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

import http_sf
import httpx
import pytest
from http_message_signatures import (
    HTTPMessageSigner,
    HTTPMessageVerifier,
    HTTPSignatureAlgorithm,
    HTTPSignatureKeyResolver,
    InvalidSignature,
    PreparedSignature,
)
from starlette.requests import Request

from market_identity import (
    Ed25519Signer,
    Eip191Signer,
    Identity,
    IdentityScheme,
    MarketRequest,
    RequestBinding,
    Signer,
    TrustedIdentitySet,
    VerificationCode,
    VerifiedRequest,
    build_public_request,
    encode_query,
    get_identity_verifier,
    is_public_request,
    principal_text,
    sign_market_request,
    sign_market_response,
    stated_request_binding,
    verify_market_request,
    verify_market_response,
)
from market_identity.wire import (
    CONTENT_DIGEST,
    MARKET_AUDIENCE,
    MARKET_OPERATION,
    MARKET_REQUEST_ID,
    MARKET_REQUEST_ORIGIN,
    MARKET_RESOURCE,
    MARKET_ROLE,
    REQUEST_PROFILE,
    RESPONSE_PROFILE,
    SIGNATURE,
    SIGNATURE_INPUT,
)

VECTORS = json.loads((Path(__file__).parent / "vectors" / "market_v3.json").read_text())

# The authority the requests are addressed to, and another: deterministic
# development keys, never for a public network.
AUTHORITY = Ed25519Signer(bytes(range(32, 64)))
OTHER_AUTHORITY = Ed25519Signer(bytes(range(64, 96)))
CREATED = 1_795_000_000
REQUEST = MarketRequest(
    method="POST",
    role="storefront",
    operation="capacity_reserve",
    resource="pool-gpu-a100",
    request_id="0f6c2b1e7d4a4c1e9a523e8b6d0f1a77",
    origin=CREATED,
)
BODY = b'{"quantity":1}'
RESPONSE_BODY = b'{"reservation_id":"r-1"}'
DELIVERY_TARGET = "https://receiver.example/hooks/market"


def _audience(*signers: Signer) -> TrustedIdentitySet:
    return TrustedIdentitySet(identities=tuple(signer.identity for signer in signers))


def _signed(signer: Signer, *, created: int = CREATED, request: MarketRequest = REQUEST,
            body: bytes = BODY) -> dict[str, str]:
    return sign_market_request(
        signer=signer, request=request, body=body, created=created,
        audience=_audience(AUTHORITY),
    ).headers


def _verify(headers: dict[str, str], *, method: str = "POST", body: bytes = BODY, query: str = ""):
    return verify_market_request(method=method, headers=headers, body=body, query=query)


def _response_headers(signer: Signer, *, status: int = 201, created: int = CREATED + 1) -> dict[str, str]:
    return sign_market_response(
        signer=signer, status=status, body=RESPONSE_BODY, request=REQUEST.binding, created=created
    ).headers


def _verify_response(headers: dict[str, str], signer: Signer, *, status: int = 201,
                     body: bytes = RESPONSE_BODY, request: RequestBinding = REQUEST.binding,
                     expected: TrustedIdentitySet | None = None, now: int = CREATED + 1):
    return verify_market_response(
        status=status, headers=headers, body=body, request=request,
        expected_principals=expected or _audience(signer), now=now, max_skew=300,
    )


def _with(headers: dict[str, str], name: str, value: str) -> dict[str, str]:
    return {**headers, name: value}


def _scheme(signer: Signer) -> str:
    return signer.identity.scheme.value


def _other_of_scheme(signer: Signer) -> Signer:
    """Another deterministic development key under the same scheme as ``signer``,
    never for a public network."""

    return OTHER_AUTHORITY if _scheme(signer) == "ed25519" else Eip191Signer(bytes(range(96, 128)))


def test_request_and_response_signatures_are_byte_identical_to_the_vectors(signer: Signer) -> None:
    vector = VECTORS[_scheme(signer)]
    assert _signed(signer) == vector["request_headers"]
    assert _response_headers(signer) == vector["response_headers"]


def test_a_signed_request_verifies_and_states_its_fields(signer: Signer) -> None:
    result = _verify(_signed(signer))

    assert result.code == VerificationCode.VERIFIED and result.verified
    verified = result.request
    assert isinstance(verified, VerifiedRequest)
    assert verified.principal == signer.identity
    assert verified.created == CREATED
    assert verified.binding == REQUEST.binding
    assert (verified.role, verified.origin) == (REQUEST.role, REQUEST.origin)
    assert verified.audience == (AUTHORITY.identity,)
    assert verified.addressed_to(AUTHORITY.identity)
    assert not verified.addressed_to(OTHER_AUTHORITY.identity)
    assert verified.target_uri is None


def test_a_vector_request_verifies_without_resigning(signer: Signer) -> None:
    assert _verify(VECTORS[_scheme(signer)]["request_headers"]).verified


def test_a_query_vector_is_byte_identical_and_verifies_against_its_query(signer: Signer) -> None:
    vector = VECTORS[_scheme(signer)]
    signed = sign_market_request(
        signer=signer, request=READ, body=b"", created=CREATED, query=vector["query"],
        audience=_audience(AUTHORITY),
    ).headers
    assert signed == vector["query_request_headers"]
    assert _verify(signed, method="GET", body=b"", query=vector["query"]).verified


@pytest.mark.parametrize(
    "field",
    [MARKET_ROLE, MARKET_OPERATION, MARKET_RESOURCE, MARKET_REQUEST_ID, MARKET_REQUEST_ORIGIN],
)
def test_every_covered_market_field_change_invalidates_the_proof(signer: Signer, field: str) -> None:
    headers = _signed(signer)
    changed = {
        MARKET_ROLE: "buyer",
        MARKET_OPERATION: "capacity_release",
        MARKET_RESOURCE: "pool-gpu-h100",
        MARKET_REQUEST_ID: "0f6c2b1e7d4a4c1e9a523e8b6d0f1a78",
        MARKET_REQUEST_ORIGIN: str(CREATED - 1),
    }[field]
    assert _verify(_with(headers, field, changed)).code == VerificationCode.INVALID_PROOF


def test_an_audience_change_invalidates_the_proof(signer: Signer) -> None:
    headers = _signed(signer)
    widened = sign_market_request(
        signer=signer, request=REQUEST, body=BODY, created=CREATED,
        audience=_audience(AUTHORITY, OTHER_AUTHORITY),
    ).headers[MARKET_AUDIENCE]
    assert _verify(_with(headers, MARKET_AUDIENCE, widened)).code == VerificationCode.INVALID_PROOF


def test_a_method_change_invalidates_the_proof(signer: Signer) -> None:
    assert _verify(_signed(signer), method="PUT").code == VerificationCode.INVALID_PROOF


def test_a_created_change_invalidates_the_proof(signer: Signer) -> None:
    headers = _signed(signer)
    moved = headers[SIGNATURE_INPUT].replace(f"created={CREATED}", f"created={CREATED + 1}")
    assert _verify(_with(headers, SIGNATURE_INPUT, moved)).code == VerificationCode.INVALID_PROOF


def test_a_body_change_fails_its_signed_digest(signer: Signer) -> None:
    assert _verify(_signed(signer), body=b'{"quantity":2}').code == VerificationCode.BODY_HASH_MISMATCH


def test_a_digest_replaced_with_the_new_bodys_invalidates_the_proof(signer: Signer) -> None:
    headers = _signed(signer)
    other = _signed(signer, body=b'{"quantity":2}')[CONTENT_DIGEST]
    result = _verify(_with(headers, CONTENT_DIGEST, other), body=b'{"quantity":2}')
    assert result.code == VerificationCode.INVALID_PROOF


def test_another_principals_keyid_invalidates_the_proof(signer: Signer) -> None:
    headers = _signed(signer)
    other = _other_of_scheme(signer)
    swapped = headers[SIGNATURE_INPUT].replace(
        f"{_scheme(signer)}:{signer.identity.identifier}", principal_text(other.identity),
    )
    assert _verify(_with(headers, SIGNATURE_INPUT, swapped)).code == VerificationCode.INVALID_PROOF


def test_a_keyid_of_another_scheme_than_its_proof_is_malformed(signer: Signer) -> None:
    # A deterministic development key, never for a public network.
    other = Eip191Signer(bytes(range(96, 128))) if _scheme(signer) == "ed25519" else OTHER_AUTHORITY
    headers = _signed(signer)
    swapped = headers[SIGNATURE_INPUT].replace(
        f"{_scheme(signer)}:{signer.identity.identifier}", principal_text(other.identity),
    )
    assert _verify(_with(headers, SIGNATURE_INPUT, swapped)).code == VerificationCode.MALFORMED_ENVELOPE


def test_a_request_with_no_profile_signature_is_an_unsupported_version(signer: Signer) -> None:
    headers = _signed(signer)
    unsigned = {k: v for k, v in headers.items() if k not in {SIGNATURE, SIGNATURE_INPUT}}
    assert _verify(unsigned).code == VerificationCode.UNSUPPORTED_VERSION
    retagged = _with(headers, SIGNATURE_INPUT, headers[SIGNATURE_INPUT].replace(
        "arkhai.market-request-signature.v3", "arkhai.market-request-signature.v4"))
    assert _verify(retagged).code == VerificationCode.UNSUPPORTED_VERSION
    version_2 = {
        "X-Market-Signature-Version": "arkhai.market-request-signature.v2",
        "X-Market-Request-ID": REQUEST.request_id,
        "X-Market-Signature": "e30",
    }
    assert _verify(version_2).code == VerificationCode.UNSUPPORTED_VERSION


@pytest.mark.parametrize(
    "rewrite",
    [
        pytest.param(lambda v: v.replace(";tag=", ';alg="ed25519";tag='), id="alg-stated"),
        pytest.param(lambda v: v.replace(";tag=", ";expires=1795000300;tag="), id="expires-stated"),
        pytest.param(lambda v: v.replace(' "market-audience"', ""), id="audience-uncovered"),
        pytest.param(lambda v: v.replace(' "@query"', ""), id="query-uncovered"),
        pytest.param(lambda v: v.replace(' "content-digest"', ""), id="digest-uncovered"),
        pytest.param(lambda v: v.replace(' "content-digest"', ' "content-digest" "content-type"'),
                     id="extra-coverage"),
        pytest.param(lambda v: v + ", second=" + v.split("=", 1)[1], id="two-signatures"),
        pytest.param(lambda v: "market=(", id="unparseable"),
    ],
)
def test_a_signature_outside_the_profiles_shape_is_malformed(signer: Signer, rewrite) -> None:
    headers = _signed(signer)
    assert _verify(_with(headers, SIGNATURE_INPUT, rewrite(headers[SIGNATURE_INPUT]))).code == (
        VerificationCode.MALFORMED_ENVELOPE
    )


def test_an_unknown_scheme_in_the_keyid_is_classified(signer: Signer) -> None:
    headers = _signed(signer)
    unknown = headers[SIGNATURE_INPUT].replace(f'keyid="{_scheme(signer)}:', 'keyid="rsa:')
    assert _verify(_with(headers, SIGNATURE_INPUT, unknown)).code == VerificationCode.UNKNOWN_SCHEME


@pytest.mark.parametrize(
    ("field", "value"),
    [
        (MARKET_AUDIENCE, '"ed25519:not-a-token"'),
        (MARKET_AUDIENCE, "rsa:abc"),
        (MARKET_REQUEST_ORIGIN, "-5"),
        (MARKET_ROLE, "two words"),
    ],
)
def test_a_malformed_covered_field_is_malformed(signer: Signer, field: str, value: str) -> None:
    assert _verify(_with(_signed(signer), field, value)).code == VerificationCode.MALFORMED_ENVELOPE


def test_a_missing_covered_field_is_malformed(signer: Signer) -> None:
    headers = {k: v for k, v in _signed(signer).items() if k != MARKET_RESOURCE}
    assert _verify(headers).code == VerificationCode.MALFORMED_ENVELOPE


def test_a_retry_resigned_later_keeps_its_request_hash_and_a_changed_origin_does_not(
    signer: Signer,
) -> None:
    first = _verify(_signed(signer)).request
    retry = _verify(_signed(signer, created=CREATED + 120)).request
    changed_origin = _verify(_signed(
        signer, request=REQUEST.model_copy(update={"origin": CREATED - 1}))).request
    changed_body = _verify(_signed(signer, body=b'{"quantity":2}'), body=b'{"quantity":2}').request
    assert first is not None and retry is not None
    assert changed_origin is not None and changed_body is not None
    assert retry.created != first.created
    assert retry.request_hash == first.request_hash
    assert changed_origin.request_hash != first.request_hash
    assert changed_body.request_hash != first.request_hash


def test_the_request_hash_ignores_where_the_request_is_addressed(signer: Signer) -> None:
    narrow = _verify(_signed(signer)).request
    wide = _verify(sign_market_request(
        signer=signer, request=REQUEST, body=BODY, created=CREATED,
        audience=_audience(AUTHORITY, OTHER_AUTHORITY),
    ).headers).request
    assert narrow is not None and wide is not None
    assert wide.request_hash == narrow.request_hash


def test_freshness_bounds_created_both_ways_and_the_origin_from_above(signer: Signer) -> None:
    verified = _verify(_signed(signer)).request
    assert verified is not None
    assert verified.fresh(now=CREATED + 300, max_skew=300)
    assert verified.fresh(now=CREATED - 300, max_skew=300)
    assert not verified.fresh(now=CREATED + 301, max_skew=300)
    assert not verified.fresh(now=CREATED - 301, max_skew=300)

    retry = _verify(_signed(
        signer, created=CREATED + 7200, request=REQUEST.model_copy(update={"origin": CREATED}),
    )).request
    assert retry is not None and retry.fresh(now=CREATED + 7200, max_skew=300)

    ahead = _verify(_signed(
        signer, created=CREATED, request=REQUEST.model_copy(update={"origin": CREATED + 301}),
    )).request
    assert ahead is not None and not ahead.fresh(now=CREATED, max_skew=300)


def test_a_delivery_binds_its_target_and_fails_at_another_endpoint(signer: Signer) -> None:
    signed = sign_market_request(
        signer=signer, request=REQUEST, body=BODY, created=CREATED, target_uri=DELIVERY_TARGET,
    )
    assert signed.record is None
    headers = signed.headers
    assert MARKET_AUDIENCE not in headers
    delivered = verify_market_request(
        method="POST", headers=headers, body=BODY, target_uri=DELIVERY_TARGET)
    assert delivered.verified and delivered.request is not None
    assert delivered.request.target_uri == DELIVERY_TARGET
    assert delivered.request.audience is None
    assert delivered.request.record is None

    elsewhere = verify_market_request(
        method="POST", headers=headers, body=BODY, target_uri="https://other.example/hooks/market")
    assert elsewhere.code == VerificationCode.INVALID_PROOF
    assert _verify(headers).code == VerificationCode.MALFORMED_ENVELOPE


def test_a_request_binds_exactly_one_of_audience_or_target(signer: Signer) -> None:
    with pytest.raises(ValueError, match="exactly one"):
        sign_market_request(signer=signer, request=REQUEST, body=BODY, created=CREATED)
    with pytest.raises(ValueError, match="exactly one"):
        sign_market_request(
            signer=signer, request=REQUEST, body=BODY, created=CREATED,
            audience=_audience(AUTHORITY), target_uri=DELIVERY_TARGET,
        )


def test_a_request_read_through_starlette_verifies(signer: Signer) -> None:
    headers = _signed(signer)
    scope = {
        "type": "http",
        "method": "POST",
        "scheme": "http",
        "server": ("site.example", 80),
        "path": "/api/v1/capacity/reservations",
        "raw_path": b"/api/v1/capacity/reservations",
        "query_string": b"",
        "headers": [(name.lower().encode(), value.encode()) for name, value in headers.items()],
    }

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": BODY, "more_body": False}

    async def read() -> tuple[Request, bytes]:
        request = Request(scope, receive)
        return request, await request.body()

    request, body = asyncio.run(read())
    result = verify_market_request(method=request.method, headers=request.headers, body=body)
    assert result.verified and result.request is not None
    assert result.request.binding == REQUEST.binding


def test_a_response_verifies_against_its_request_and_authority(signer: Signer) -> None:
    result = _verify_response(_response_headers(signer), signer)
    assert result.code == VerificationCode.VERIFIED and result.verified
    assert result.principal == signer.identity and result.created == CREATED + 1


def test_a_response_signed_for_a_verified_request_binds_it(signer: Signer) -> None:
    verified = _verify(_signed(signer)).request
    assert verified is not None
    headers = sign_market_response(
        signer=AUTHORITY, status=201, body=RESPONSE_BODY, request=verified.binding,
        created=CREATED + 1,
    ).headers
    assert _verify_response(headers, AUTHORITY).verified


@pytest.mark.parametrize(
    "binding",
    [
        REQUEST.binding.model_copy(update={"method": "PUT"}),
        REQUEST.binding.model_copy(update={"operation": "capacity_release"}),
        REQUEST.binding.model_copy(update={"resource": "pool-gpu-h100"}),
        REQUEST.binding.model_copy(update={"request_id": "another-request"}),
    ],
    ids=["method", "operation", "resource", "request_id"],
)
def test_a_response_fails_against_any_other_request(signer: Signer, binding: RequestBinding) -> None:
    result = _verify_response(_response_headers(signer), signer, request=binding)
    assert result.code == VerificationCode.INVALID_PROOF


def test_a_response_fails_against_its_request_without_the_resource(signer: Signer) -> None:
    binding = REQUEST.binding.model_copy(update={"resource": None})
    result = _verify_response(_response_headers(signer), signer, request=binding)
    assert result.code == VerificationCode.MALFORMED_ENVELOPE


def test_a_response_with_another_status_or_body_fails(signer: Signer) -> None:
    headers = _response_headers(signer)
    assert _verify_response(headers, signer, status=200).code == VerificationCode.INVALID_PROOF
    assert _verify_response(headers, signer, body=b"{}").code == VerificationCode.BODY_HASH_MISMATCH


def test_a_response_from_an_unexpected_authority_is_refused(signer: Signer) -> None:
    result = _verify_response(_response_headers(signer), signer, expected=_audience(OTHER_AUTHORITY))
    assert result.code == VerificationCode.WRONG_PRINCIPAL


def test_a_response_from_either_principal_of_an_overlap_verifies(
    ed25519_signer: Ed25519Signer, eip191_signer: Eip191Signer,
) -> None:
    overlap = _audience(ed25519_signer, eip191_signer)
    for authority in (ed25519_signer, eip191_signer):
        assert _verify_response(_response_headers(authority), authority, expected=overlap).verified


def test_a_response_outside_the_skew_is_refused(signer: Signer) -> None:
    headers = _response_headers(signer)
    assert _verify_response(headers, signer, now=CREATED + 301).verified
    assert _verify_response(headers, signer, now=CREATED + 302).code == VerificationCode.TIMESTAMP_SKEW


def test_an_unsigned_response_is_not_under_the_profile(signer: Signer) -> None:
    assert _verify_response({}, signer).code == VerificationCode.UNSUPPORTED_VERSION
    request_signature = _signed(signer)
    assert _verify_response(request_signature, signer).code == VerificationCode.UNSUPPORTED_VERSION


def test_a_stated_request_identity_is_read_without_verifying() -> None:
    headers = {
        MARKET_OPERATION: "capacity_reserve",
        MARKET_RESOURCE: "pool-gpu-a100",
        MARKET_REQUEST_ID: "0f6c2b1e7d4a4c1e9a523e8b6d0f1a77",
    }
    assert stated_request_binding(method="post", headers=headers) == REQUEST.binding
    for missing in (MARKET_OPERATION, MARKET_REQUEST_ID):
        assert stated_request_binding(
            method="POST", headers={k: v for k, v in headers.items() if k != missing}) is None
    targetless = {k: v for k, v in headers.items() if k != MARKET_RESOURCE}
    stated = stated_request_binding(method="POST", headers=targetless)
    assert stated is not None and stated.resource is None


def test_a_stated_identity_is_taken_as_stated_unless_no_signature_can_hold_it() -> None:
    headers = {
        MARKET_OPERATION: "not a token",
        MARKET_RESOURCE: "",
        MARKET_REQUEST_ID: "x" * 300,
    }
    stated = stated_request_binding(method="POST", headers=headers)
    assert stated is not None
    assert (stated.operation, stated.resource, stated.request_id) == ("not a token", "", "x" * 300)
    assert stated_request_binding(
        method="POST", headers=_with(headers, MARKET_OPERATION, "réserve")) is None


def test_a_refusal_over_long_stated_values_is_signed_and_verifies(signer: Signer) -> None:
    stated = stated_request_binding(method="POST", headers={
        MARKET_OPERATION: "o" * 200, MARKET_RESOURCE: "r" * 2000, MARKET_REQUEST_ID: "i" * 300})
    assert stated is not None
    signed = sign_market_response(signer=signer, status=401, body=b"{}", request=stated, created=CREATED)
    assert signed.record.operation == "o" * 200
    result = verify_market_response(
        status=401, headers=signed.headers, body=b"{}", request=stated,
        expected_principals=_audience(signer), now=CREATED, max_skew=300,
    )
    assert result.verified and result.record == signed.record


def test_a_refusal_signed_over_a_stated_identity_verifies_against_it(signer: Signer) -> None:
    stated = stated_request_binding(method="POST", headers={
        MARKET_OPERATION: "not a token", MARKET_RESOURCE: "r", MARKET_REQUEST_ID: "id with spaces"})
    assert stated is not None
    headers = sign_market_response(
        signer=signer, status=400, body=b'{"code":"unsupported_protocol"}', request=stated,
        created=CREATED,
    ).headers
    result = verify_market_response(
        status=400, headers=headers, body=b'{"code":"unsupported_protocol"}', request=stated,
        expected_principals=_audience(signer), now=CREATED, max_skew=300,
    )
    assert result.verified


def test_a_profile_signature_input_without_its_signature_is_malformed(signer: Signer) -> None:
    headers = {k: v for k, v in _signed(signer).items() if k != SIGNATURE}
    assert _verify(headers).code == VerificationCode.MALFORMED_ENVELOPE


def test_a_vector_response_verifies_without_resigning(signer: Signer) -> None:
    assert _verify_response(VECTORS[_scheme(signer)]["response_headers"], signer).verified


def test_a_response_created_change_invalidates_the_proof(signer: Signer) -> None:
    headers = _response_headers(signer)
    moved = headers[SIGNATURE_INPUT].replace(f"created={CREATED + 1}", f"created={CREATED + 2}")
    result = _verify_response(_with(headers, SIGNATURE_INPUT, moved), signer)
    assert result.code == VerificationCode.INVALID_PROOF


def test_a_response_digest_replaced_with_the_new_bodys_invalidates_the_proof(signer: Signer) -> None:
    headers = _response_headers(signer)
    other = sign_market_response(
        signer=signer, status=201, body=b"{}", request=REQUEST.binding, created=CREATED + 1,
    ).headers[CONTENT_DIGEST]
    result = _verify_response(_with(headers, CONTENT_DIGEST, other), signer, body=b"{}")
    assert result.code == VerificationCode.INVALID_PROOF


def test_a_response_keyid_swapped_to_another_expected_principal_fails(signer: Signer) -> None:
    headers = _response_headers(signer)
    other = _other_of_scheme(signer)
    swapped = headers[SIGNATURE_INPUT].replace(
        f"{_scheme(signer)}:{signer.identity.identifier}", principal_text(other.identity),
    )
    result = _verify_response(
        _with(headers, SIGNATURE_INPUT, swapped), signer,
        expected=_audience(signer, other),
    )
    assert result.code == VerificationCode.INVALID_PROOF


def test_a_repeated_covered_field_line_is_malformed_through_starlette(signer: Signer) -> None:
    headers = _signed(signer)
    raw = [(name.encode(), value.encode()) for name, value in headers.items()]
    raw.append((b"market-role", b"buyer"))
    request = Request({
        "type": "http", "method": "POST", "scheme": "http", "server": ("site.example", 80),
        "path": "/", "raw_path": b"/", "query_string": b"", "headers": raw,
    })
    result = verify_market_request(method=request.method, headers=request.headers, body=BODY)
    assert result.code == VerificationCode.MALFORMED_ENVELOPE


@pytest.mark.parametrize(
    "rewrite",
    [
        pytest.param(lambda v: re.sub(r'keyid="[^"]*"', "keyid=5", v), id="keyid-not-text"),
        pytest.param(lambda v: 'market="x";' + v.split(";", 1)[1], id="member-not-a-list"),
        pytest.param(lambda v: v.replace("created=1795000000", "created=-1"), id="negative-created"),
    ],
)
def test_signature_parameters_outside_their_types_are_malformed(signer: Signer, rewrite) -> None:
    headers = _signed(signer)
    assert _verify(_with(headers, SIGNATURE_INPUT, rewrite(headers[SIGNATURE_INPUT]))).code == (
        VerificationCode.MALFORMED_ENVELOPE
    )


@pytest.mark.parametrize("value", ["", "ed25519:abc;q=1", "?1"])
def test_an_audience_of_anything_but_principal_tokens_is_malformed(signer: Signer, value: str) -> None:
    assert _verify(_with(_signed(signer), MARKET_AUDIENCE, value)).code == (
        VerificationCode.MALFORMED_ENVELOPE
    )


@pytest.mark.parametrize("resource", ["", " pool", "pool\t", "pool-é", "a\nb"])
def test_a_resource_no_header_can_carry_is_refused(resource: str) -> None:
    with pytest.raises(ValueError):
        MarketRequest.model_validate({**REQUEST.model_dump(), "resource": resource})


@pytest.mark.parametrize("created", [-1, True, 1.5])
def test_signing_refuses_an_instant_that_is_not_a_whole_second(signer: Signer, created) -> None:
    with pytest.raises(ValueError, match="created"):
        _signed(signer, created=created)


@pytest.mark.parametrize("status", [99, 600, True])
def test_signing_refuses_a_status_outside_http(signer: Signer, status) -> None:
    with pytest.raises(ValueError, match="status"):
        sign_market_response(
            signer=signer, status=status, body=b"", request=REQUEST.binding, created=CREATED)


def test_a_negative_skew_is_refused(signer: Signer) -> None:
    verified = _verify(_signed(signer)).request
    assert verified is not None
    with pytest.raises(ValueError, match="max_skew"):
        verified.fresh(now=CREATED, max_skew=-1)
    with pytest.raises(ValueError, match="max_skew"):
        verify_market_response(
            status=201, headers=_response_headers(signer), body=RESPONSE_BODY,
            request=REQUEST.binding, expected_principals=_audience(signer), now=CREATED,
            max_skew=-1,
        )


# -- one accepted spelling ----------------------------------------------------------

TARGETLESS = REQUEST.model_copy(update={"operation": "listing.publish", "resource": None})
_COMPONENTS = [
    "@method", "@query", "market-role", "market-operation", "market-resource", "market-audience",
    "market-request-id", "market-request-origin", "content-digest",
]


class _OracleAlgorithm(HTTPSignatureAlgorithm):
    """RFC 9421 verification by a principal, through the public scheme registry."""

    algorithm_id = "oracle"

    def __init__(self, public_key: Identity | None = None, private_key: object = None) -> None:
        self._principal = public_key

    def sign(self, message: bytes) -> bytes:
        raise NotImplementedError

    def verify(self, signature: bytes, message: bytes) -> None:
        assert self._principal is not None
        if not get_identity_verifier(self._principal.scheme).verify_signature(self._principal, message, signature):
            raise InvalidSignature("signature does not verify")


class _OracleResolver(HTTPSignatureKeyResolver):
    def resolve_public_key(self, key_id: str) -> Identity:
        scheme, _, identifier = key_id.partition(":")
        return Identity(scheme=IdentityScheme(scheme), identifier=identifier)

    def resolve_private_key(self, key_id: str) -> None:
        raise KeyError(key_id)


class _Oracle(HTTPMessageVerifier):
    def validate_created_and_expires(self, sig_input, max_age=None) -> None:
        pass


@dataclass
class _Message:
    method: str
    url: str
    headers: dict[str, str]


@dataclass
class _ResponseMessage:
    status_code: int
    headers: dict[str, str]
    request: _Message


class _LibrarySigner(HTTPMessageSigner):
    """The library's own signer, signing whatever order and spelling a test gives.

    Its public ``sign`` writes the parameters in the profile's order, so a test
    asking for another builds the base through the library's base builder and
    attaches it with the library's ``apply``: no framing is the test's own.
    """

    def sign_as_given(
        self, signer: Signer, message: object, *, components: list[str], parameters: dict[str, object]
    ) -> None:
        base, params_node, _ = self._build_signature_base(
            message,
            covered_component_ids=self._parse_covered_component_ids(components),
            signature_params=dict(parameters),
        )
        prepared = PreparedSignature(base.encode(), str(params_node), "market", _OracleAlgorithm.algorithm_id)
        self.apply(message, prepared, signer.sign(base.encode()))


def _parameters(signer: Signer, order: list[str], *, created: int = CREATED, tag: str = REQUEST_PROFILE,
                keyid: str | None = None) -> dict[str, object]:
    values = {"created": created, "keyid": keyid or principal_text(signer.identity), "tag": tag}
    return {name: values[name] for name in order}


def _rfc_signed(
    signer: Signer, headers: dict[str, str], *, components: list[str], parameters: list[str],
    keyid: str | None = None, method: str = "POST", url: str = "https://market.invalid/",
) -> dict[str, str]:
    """``headers`` signed under RFC 9421 as given, by the library."""

    message = _Message(method, url, dict(headers))
    _LibrarySigner(signature_algorithm=_OracleAlgorithm).sign_as_given(
        signer, message, components=components, parameters=_parameters(signer, parameters, keyid=keyid),
    )
    return message.headers


def _rfc_signed_response(
    signer: Signer, headers: dict[str, str], *, components: list[str], parameters: list[str],
    keyid: str | None = None,
) -> dict[str, str]:
    """A response to ``REQUEST`` signed under RFC 9421 as given, by the library."""

    request_headers = {MARKET_OPERATION: REQUEST.operation, MARKET_RESOURCE: str(REQUEST.resource),
                       MARKET_REQUEST_ID: REQUEST.request_id}
    message = _ResponseMessage(201, dict(headers), _Message("POST", "https://market.invalid/", request_headers))
    serialized = [f'"{c}";req' if c in {"@method", *(n.lower() for n in request_headers)} else f'"{c}"'
                  for c in components]
    _LibrarySigner(signature_algorithm=_OracleAlgorithm).sign_as_given(
        signer, message, components=serialized,
        parameters=_parameters(signer, parameters, created=CREATED + 1, tag=RESPONSE_PROFILE, keyid=keyid),
    )
    return message.headers


def _rfc_verifies(headers: dict[str, str]) -> bool:
    return _oracle(_Message("POST", "https://market.invalid/", headers), REQUEST_PROFILE)


def _rfc_verifies_response(headers: dict[str, str]) -> bool:
    request_headers = {MARKET_OPERATION: REQUEST.operation, MARKET_RESOURCE: str(REQUEST.resource),
                       MARKET_REQUEST_ID: REQUEST.request_id}
    message = _ResponseMessage(201, headers, _Message("POST", "https://market.invalid/", request_headers))
    return _oracle(message, RESPONSE_PROFILE)


def _oracle(message: object, tag: str) -> bool:
    try:
        _Oracle(signature_algorithm=_OracleAlgorithm, key_resolver=_OracleResolver()).verify(
            message, max_age=None, expect_tag=tag, expect_label="market",
        )
    except InvalidSignature:
        return False
    return True


def _unsigned(headers: dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in headers.items() if k not in {SIGNATURE, SIGNATURE_INPUT}}


def test_the_oracle_accepts_the_profiles_own_spelling(signer: Signer) -> None:
    resigned = _rfc_signed(signer, _unsigned(_signed(signer)), components=_COMPONENTS,
                           parameters=["created", "keyid", "tag"])
    assert _rfc_verifies(resigned)
    assert _verify(resigned).verified


def test_a_request_signing_its_parameters_in_another_order_is_malformed(signer: Signer) -> None:
    resigned = _rfc_signed(signer, _unsigned(_signed(signer)), components=_COMPONENTS,
                           parameters=["keyid", "created", "tag"])
    assert _rfc_verifies(resigned)
    assert _verify(resigned).code == VerificationCode.MALFORMED_ENVELOPE


def test_a_request_covering_its_components_in_another_order_is_malformed(signer: Signer) -> None:
    reordered = ["@method", "@query", "market-operation", "market-role", *_COMPONENTS[4:]]
    resigned = _rfc_signed(signer, _unsigned(_signed(signer)), components=reordered,
                           parameters=["created", "keyid", "tag"])
    assert _rfc_verifies(resigned)
    assert _verify(resigned).code == VerificationCode.MALFORMED_ENVELOPE


def test_an_audience_spelled_otherwise_is_malformed(signer: Signer) -> None:
    headers = _unsigned(sign_market_request(
        signer=signer, request=REQUEST, body=BODY, created=CREATED,
        audience=_audience(AUTHORITY, OTHER_AUTHORITY),
    ).headers)
    assert ", " in headers[MARKET_AUDIENCE]
    headers[MARKET_AUDIENCE] = headers[MARKET_AUDIENCE].replace(", ", ",")
    resigned = _rfc_signed(signer, headers, components=_COMPONENTS, parameters=["created", "keyid", "tag"])
    assert _rfc_verifies(resigned)
    assert _verify(resigned).code == VerificationCode.MALFORMED_ENVELOPE


@pytest.mark.parametrize(
    "rewrite",
    [
        pytest.param(lambda v: v + ", sha-512=:" + base64.b64encode(hashlib.sha512(BODY).digest()).decode() + ":",
                     id="a-second-member"),
        pytest.param(lambda v: v + ";p=1", id="a-parameter"),
        pytest.param(lambda v: v.replace("sha-256", "sha-512"), id="another-algorithm"),
    ],
)
def test_a_digest_spelled_otherwise_is_malformed(signer: Signer, rewrite) -> None:
    headers = _unsigned(_signed(signer))
    headers[CONTENT_DIGEST] = rewrite(headers[CONTENT_DIGEST])
    resigned = _rfc_signed(signer, headers, components=_COMPONENTS, parameters=["created", "keyid", "tag"])
    assert _rfc_verifies(resigned)
    assert _verify(resigned).code == VerificationCode.MALFORMED_ENVELOPE


_RESPONSE_COMPONENTS = ["@status", "content-digest", "@method", "market-operation", "market-resource",
                        "market-request-id"]


@pytest.mark.parametrize(
    ("components", "parameters", "digest_suffix"),
    [
        pytest.param(_RESPONSE_COMPONENTS, ["created", "keyid", "tag"], "", id="the-profiles-own"),
        pytest.param(_RESPONSE_COMPONENTS, ["tag", "keyid", "created"], "", id="parameters-reordered"),
        pytest.param(["content-digest", "@status", *_RESPONSE_COMPONENTS[2:]], ["created", "keyid", "tag"], "",
                     id="components-reordered"),
        pytest.param(_RESPONSE_COMPONENTS, ["created", "keyid", "tag"], ";p=1", id="digest-parameter"),
    ],
)
def test_a_response_spelled_otherwise_is_malformed(
    signer: Signer, components: list[str], parameters: list[str], digest_suffix: str
) -> None:
    headers = {CONTENT_DIGEST: _response_headers(signer)[CONTENT_DIGEST] + digest_suffix}
    resigned = _rfc_signed_response(signer, headers, components=components, parameters=parameters)
    assert _rfc_verifies_response(resigned)
    own = components == _RESPONSE_COMPONENTS and parameters == ["created", "keyid", "tag"] and not digest_suffix
    expected = VerificationCode.VERIFIED if own else VerificationCode.MALFORMED_ENVELOPE
    assert _verify_response(resigned, signer).code == expected


# -- an operation with no target ----------------------------------------------------


def _targetless_signed(signer: Signer) -> dict[str, str]:
    return _signed(signer, request=TARGETLESS)


def _targetless_response(signer: Signer) -> dict[str, str]:
    return sign_market_response(
        signer=signer, status=201, body=RESPONSE_BODY, request=TARGETLESS.binding, created=CREATED + 1
    ).headers


def test_a_targetless_request_and_its_response_sign_and_verify(signer: Signer) -> None:
    headers = _targetless_signed(signer)
    assert MARKET_RESOURCE not in headers
    assert '"market-resource"' not in headers[SIGNATURE_INPUT]
    verified = _verify(headers).request
    assert verified is not None and verified.resource is None
    assert verified.binding == TARGETLESS.binding

    response = _targetless_response(signer)
    assert "market-resource" not in response[SIGNATURE_INPUT]
    assert _verify_response(response, signer, request=TARGETLESS.binding).verified


def test_targetless_vectors_verify_without_resigning(signer: Signer) -> None:
    vector = VECTORS[_scheme(signer)]
    assert _targetless_signed(signer) == vector["targetless_request_headers"]
    assert _targetless_response(signer) == vector["targetless_response_headers"]
    assert _verify(vector["targetless_request_headers"]).verified
    assert _verify_response(vector["targetless_response_headers"], signer, request=TARGETLESS.binding).verified


def test_adding_or_removing_the_resource_after_signing_fails(signer: Signer) -> None:
    added = _with(_targetless_signed(signer), MARKET_RESOURCE, "listings")
    removed = {k: v for k, v in _signed(signer).items() if k != MARKET_RESOURCE}
    assert _verify(added).code == VerificationCode.MALFORMED_ENVELOPE
    assert _verify(removed).code == VerificationCode.MALFORMED_ENVELOPE


def test_a_response_bound_with_the_other_coverage_list_fails(signer: Signer) -> None:
    with_resource = TARGETLESS.binding.model_copy(update={"resource": "listings"})
    assert _verify_response(_targetless_response(signer), signer, request=with_resource).code == (
        VerificationCode.MALFORMED_ENVELOPE
    )
    without = REQUEST.binding.model_copy(update={"resource": None})
    assert _verify_response(_response_headers(signer), signer, request=without).code == (
        VerificationCode.MALFORMED_ENVELOPE
    )


def test_the_request_hash_tells_an_absent_resource_from_a_present_one(signer: Signer) -> None:
    verified = _verify(_targetless_signed(signer)).request
    assert verified is not None
    named_absent = verified.model_copy(update={"resource": "absent"})
    assert verified.request_hash != named_absent.request_hash


# -- one spelling of a principal ----------------------------------------------------


def test_a_keyid_spelling_its_address_otherwise_is_malformed(eip191_signer: Eip191Signer) -> None:
    upper = "eip191:0x" + eip191_signer.identity.identifier[2:].upper()
    resigned = _rfc_signed(eip191_signer, _unsigned(_signed(eip191_signer)), components=_COMPONENTS,
                           parameters=["created", "keyid", "tag"], keyid=upper)
    assert _rfc_verifies(resigned)
    assert _verify(resigned).code == VerificationCode.MALFORMED_ENVELOPE


def test_a_response_keyid_spelling_its_address_otherwise_is_malformed(eip191_signer: Eip191Signer) -> None:
    upper = "eip191:0x" + eip191_signer.identity.identifier[2:].upper()
    headers = {CONTENT_DIGEST: _response_headers(eip191_signer)[CONTENT_DIGEST]}
    resigned = _rfc_signed_response(eip191_signer, headers, components=_RESPONSE_COMPONENTS,
                                    parameters=["created", "keyid", "tag"], keyid=upper)
    assert _rfc_verifies_response(resigned)
    assert _verify_response(resigned, eip191_signer).code == VerificationCode.MALFORMED_ENVELOPE


def test_an_audience_member_spelling_its_address_otherwise_is_malformed(
    signer: Signer, eip191_signer: Eip191Signer,
) -> None:
    headers = _unsigned(sign_market_request(
        signer=signer, request=REQUEST, body=BODY, created=CREATED,
        audience=_audience(eip191_signer),
    ).headers)
    identifier = eip191_signer.identity.identifier
    headers[MARKET_AUDIENCE] = headers[MARKET_AUDIENCE].replace(identifier, "0x" + identifier[2:].upper())
    resigned = _rfc_signed(signer, headers, components=_COMPONENTS, parameters=["created", "keyid", "tag"])
    assert _rfc_verifies(resigned)
    assert _verify(resigned).code == VerificationCode.MALFORMED_ENVELOPE


# -- the query -----------------------------------------------------------------------

READ = MarketRequest(
    method="GET", role="buyer", operation="listing.list", request_id="7c2d4b9e1a0f4e3d8c6b5a4f3e2d1c0b",
    origin=CREATED,
)
OPEN = "?limit=50&offset=0&status=open"


def _read(signer: Signer, query: str = OPEN, *, request: MarketRequest = READ) -> dict[str, str]:
    return sign_market_request(
        signer=signer, request=request, body=b"", created=CREATED, query=query, audience=_audience(AUTHORITY),
    ).headers


def _verify_read(headers: dict[str, str], query: str = OPEN):
    return verify_market_request(method="GET", headers=headers, body=b"", query=query)


def test_a_read_signed_for_its_query_verifies_against_that_raw_string(signer: Signer) -> None:
    headers = _read(signer)
    assert '"@method" "@query" "market-role"' in headers[SIGNATURE_INPUT]
    result = _verify_read(headers)
    assert result.verified and result.request is not None
    assert result.request.query == OPEN
    assert result.request.record is not None and result.request.record.query == OPEN


def test_a_read_whose_query_is_changed_in_transit_fails_as_an_invalid_proof(signer: Signer) -> None:
    result = _verify_read(_read(signer), "?limit=50&offset=0&status=closed")
    assert result.code == VerificationCode.INVALID_PROOF


def test_a_request_with_no_query_covers_a_bare_question_mark(signer: Signer) -> None:
    headers = _read(signer, "")
    for received in ("", "?"):
        result = _verify_read(headers, received)
        assert result.verified and result.request is not None and result.request.query == "?"
    assert _verify_read(headers, "?a=1").code == VerificationCode.INVALID_PROOF
    assert _verify_read(_read(signer, "?"), "").verified


def test_a_query_signed_with_percent_20_fails_against_the_same_query_spelled_with_plus(signer: Signer) -> None:
    headers = _read(signer, "?q=two%20words")
    assert _verify_read(headers, "?q=two%20words").verified
    assert _verify_read(headers, "?q=two+words").code == VerificationCode.INVALID_PROOF


def test_two_requests_differing_only_in_their_query_hash_differently(signer: Signer) -> None:
    first = _verify_read(_read(signer)).request
    resigned = _verify_read(sign_market_request(
        signer=signer, request=READ, body=b"", created=CREATED + 60, query=OPEN, audience=_audience(AUTHORITY),
    ).headers).request
    other = _verify_read(_read(signer, "?limit=50&offset=50&status=open"), "?limit=50&offset=50&status=open").request
    assert first is not None and resigned is not None and other is not None
    assert resigned.request_hash == first.request_hash
    assert other.request_hash != first.request_hash


def test_a_query_longer_than_one_framed_field_still_hashes(signer: Signer) -> None:
    long = "?q=" + "a" * 8000
    verified = _verify_read(_read(signer, long), long).request
    assert verified is not None and len(verified.request_hash) == 64


@pytest.mark.parametrize("query", ["limit=50", "?q=two words", "?q=é", "?q=%zz"])
def test_a_query_outside_the_suffix_grammar_is_refused_for_signing(signer: Signer, query: str) -> None:
    with pytest.raises(ValueError, match="query"):
        _read(signer, query)


def test_a_received_query_outside_rfc_3986_is_malformed(signer: Signer) -> None:
    assert _verify_read(_read(signer), '?status="open"').code == VerificationCode.MALFORMED_ENVELOPE
    # A URL parser would read what follows ``#`` as a fragment and cover only the
    # query before it, while the verified request would state the whole string.
    signed = _read(signer, "?limit=50")
    assert _verify_read(signed, "?limit=50").verified
    assert _verify_read(signed, "?limit=50#x").code == VerificationCode.MALFORMED_ENVELOPE
    with pytest.raises(ValueError, match="query"):
        _verify_read(_read(signer), "limit=50")


def test_the_oracle_agrees_on_a_base_covering_the_query(signer: Signer) -> None:
    headers = _read(signer)
    assert _oracle(_Message("GET", "https://market.invalid/" + OPEN, headers), REQUEST_PROFILE)
    assert not _oracle(
        _Message("GET", "https://market.invalid/?limit=50&offset=0&status=closed", headers), REQUEST_PROFILE
    )
    resigned = _rfc_signed(
        signer, _unsigned(headers), components=[c for c in _COMPONENTS if c != "market-resource"],
        parameters=["created", "keyid", "tag"], method="GET", url="https://market.invalid/" + OPEN,
    )
    assert _verify_read(resigned).verified


def test_a_delivery_covers_its_target_uris_query(signer: Signer) -> None:
    target = DELIVERY_TARGET + "?tenant=a"
    headers = sign_market_request(
        signer=signer, request=REQUEST, body=BODY, created=CREATED, target_uri=target,
    ).headers
    assert '"@method" "@query"' in headers[SIGNATURE_INPUT]
    delivered = verify_market_request(method="POST", headers=headers, body=BODY, target_uri=target)
    assert delivered.verified and delivered.request is not None and delivered.request.query == "?tenant=a"
    elsewhere = verify_market_request(
        method="POST", headers=headers, body=BODY, target_uri=DELIVERY_TARGET + "?tenant=b")
    assert elsewhere.code == VerificationCode.INVALID_PROOF
    with pytest.raises(ValueError, match="target URI"):
        sign_market_request(
            signer=signer, request=REQUEST, body=BODY, created=CREATED, target_uri=target, query="?x=1")
    with pytest.raises(ValueError, match="target URI"):
        verify_market_request(method="POST", headers=headers, body=BODY, target_uri=target, query="?x=1")


# -- the one query encoding -----------------------------------------------------------


def test_the_query_encoding_is_deterministic_and_empty_for_no_items() -> None:
    items = [("status", "open"), ("limit", "50")]
    assert encode_query(items) == encode_query(iter(items)) == "?status=open&limit=50"
    assert encode_query([]) == ""


def test_the_query_encoding_keeps_repeated_keys_in_order_and_escapes_reserved_characters() -> None:
    encoded = encode_query([
        ("tag", "b"), ("q", "two words"), ("tag", "a"), ("p&q", "x=y/z?#+~"), ("é", "ü"),
    ])
    assert encoded == "?tag=b&q=two%20words&tag=a&p%26q=x%3Dy%2Fz%3F%23%2B~&%C3%A9=%C3%BC"


def test_a_url_built_from_the_encoding_arrives_byte_identical_and_verifies(signer: Signer) -> None:
    query = encode_query([("status", "open now"), ("tag", "a+b"), ("tag", "é")])
    headers = _read(signer, query)
    received: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        received.append(request.url.query)
        return httpx.Response(200)

    with httpx.Client(transport=httpx.MockTransport(handler), base_url="https://registry.example") as client:
        client.get("/listings" + query, headers=headers)
    assert received == [query[1:].encode("ascii")]
    assert _verify_read(headers, "?" + received[0].decode("ascii")).verified


# -- the public request ---------------------------------------------------------------

DESCRIPTOR = "registry.descriptor.read"


def test_a_public_request_carries_only_its_request_identity() -> None:
    first = build_public_request(method="GET", operation=DESCRIPTOR)
    second = build_public_request(method="GET", operation=DESCRIPTOR)
    assert set(first.headers) == {MARKET_OPERATION, MARKET_REQUEST_ID}
    for absent in (SIGNATURE, SIGNATURE_INPUT, MARKET_AUDIENCE, MARKET_REQUEST_ORIGIN, CONTENT_DIGEST,
                   MARKET_RESOURCE, MARKET_ROLE):
        assert absent not in first.headers
    assert first.headers[MARKET_OPERATION] == DESCRIPTOR
    assert re.fullmatch(r"[0-9a-f]{32}", first.headers[MARKET_REQUEST_ID])
    assert first.headers[MARKET_REQUEST_ID] != second.headers[MARKET_REQUEST_ID]
    assert first.binding == RequestBinding(
        method="GET", operation=DESCRIPTOR, request_id=first.headers[MARKET_REQUEST_ID])


def test_a_public_answer_verifies_over_its_binding_and_no_other(signer: Signer) -> None:
    public = build_public_request(method="GET", operation=DESCRIPTOR)
    stated = stated_request_binding(method="GET", headers=public.headers)
    assert stated == public.binding
    answer = sign_market_response(signer=signer, status=200, body=b"{}", request=stated, created=CREATED)
    verify = lambda binding: verify_market_response(  # noqa: E731
        status=200, headers=answer.headers, body=b"{}", request=binding,
        expected_principals=_audience(signer), now=CREATED, max_skew=300,
    )
    assert verify(public.binding).verified
    replayed = build_public_request(method="GET", operation=DESCRIPTOR).binding
    assert verify(replayed).code == VerificationCode.INVALID_PROOF


def test_the_public_shape_check(signer: Signer) -> None:
    public = build_public_request(method="GET", operation=DESCRIPTOR).headers
    assert is_public_request(public)
    assert is_public_request({name.lower(): value for name, value in public.items()})
    assert not is_public_request(_signed(signer))
    assert not is_public_request({**public, SIGNATURE: "market=:AA==:"})
    assert not is_public_request({**public, SIGNATURE_INPUT: "market=()"})
    for missing in (MARKET_OPERATION, MARKET_REQUEST_ID):
        assert not is_public_request({k: v for k, v in public.items() if k != missing})
