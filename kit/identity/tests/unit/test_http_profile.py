from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import pytest
from starlette.requests import Request

from market_identity import (
    Ed25519Signer,
    Eip191Signer,
    MarketRequest,
    RequestBinding,
    Signer,
    TrustedIdentitySet,
    VerificationCode,
    VerifiedRequest,
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
    SIGNATURE,
    SIGNATURE_INPUT,
)

VECTORS = json.loads((Path(__file__).parent / "vectors" / "market_v3.json").read_text())

# The authority the requests are addressed to, a deterministic development key.
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
    )


def _verify(headers: dict[str, str], *, method: str = "POST", body: bytes = BODY):
    return verify_market_request(method=method, headers=headers, body=body)


def _response_headers(signer: Signer, *, status: int = 201, created: int = CREATED + 1) -> dict[str, str]:
    return sign_market_response(
        signer=signer, status=status, body=RESPONSE_BODY, request=REQUEST.binding, created=created
    )


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
    )[MARKET_AUDIENCE]
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
    swapped = headers[SIGNATURE_INPUT].replace(
        f"{_scheme(signer)}:{signer.identity.identifier}",
        f"ed25519:{OTHER_AUTHORITY.identity.identifier}",
    )
    assert _verify(_with(headers, SIGNATURE_INPUT, swapped)).code == VerificationCode.INVALID_PROOF


def test_a_request_with_no_profile_signature_is_an_unsupported_version(signer: Signer) -> None:
    headers = _signed(signer)
    unsigned = {k: v for k, v in headers.items() if k not in {SIGNATURE, SIGNATURE_INPUT}}
    assert _verify(unsigned).code == VerificationCode.UNSUPPORTED_VERSION
    retagged = _with(headers, SIGNATURE_INPUT, headers[SIGNATURE_INPUT].replace(
        "arkhai.market-request.v3", "arkhai.market-request.v4"))
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
    )).request
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
    headers = sign_market_request(
        signer=signer, request=REQUEST, body=BODY, created=CREATED, target_uri=DELIVERY_TARGET,
    )
    assert MARKET_AUDIENCE not in headers
    delivered = verify_market_request(
        method="POST", headers=headers, body=BODY, target_uri=DELIVERY_TARGET)
    assert delivered.verified and delivered.request is not None
    assert delivered.request.target_uri == DELIVERY_TARGET
    assert delivered.request.audience is None

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
    )
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
    for missing in headers:
        assert stated_request_binding(
            method="POST", headers={k: v for k, v in headers.items() if k != missing}) is None


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


def test_a_refusal_signed_over_a_stated_identity_verifies_against_it(signer: Signer) -> None:
    stated = stated_request_binding(method="POST", headers={
        MARKET_OPERATION: "not a token", MARKET_RESOURCE: "r", MARKET_REQUEST_ID: "id with spaces"})
    assert stated is not None
    headers = sign_market_response(
        signer=signer, status=400, body=b'{"code":"unsupported_protocol"}', request=stated,
        created=CREATED,
    )
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
    )[CONTENT_DIGEST]
    result = _verify_response(_with(headers, CONTENT_DIGEST, other), signer, body=b"{}")
    assert result.code == VerificationCode.INVALID_PROOF


def test_a_response_keyid_swapped_to_another_expected_principal_fails(signer: Signer) -> None:
    headers = _response_headers(signer)
    swapped = headers[SIGNATURE_INPUT].replace(
        f"{_scheme(signer)}:{signer.identity.identifier}",
        f"ed25519:{OTHER_AUTHORITY.identity.identifier}",
    )
    result = _verify_response(
        _with(headers, SIGNATURE_INPUT, swapped), signer,
        expected=_audience(signer, OTHER_AUTHORITY),
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


@pytest.mark.parametrize("resource", [" pool", "pool\t", "pool-é", "a\nb"])
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
