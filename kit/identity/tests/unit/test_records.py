"""Signing and verifying produce a version 3 message's evidence record.

Every case under both schemes (conftest's ``signer``), for an operation with a
target and one without.
"""

from __future__ import annotations

import json

import pytest

from market_identity import (
    Ed25519Signer,
    MarketRequest,
    RequestRecord,
    ResponseRecord,
    Signer,
    TrustedIdentitySet,
    principal_text,
    sign_market_request,
    sign_market_response,
    verify_market_request,
    verify_market_response,
)

# A deterministic development key, never for a public network.
AUTHORITY = Ed25519Signer(bytes(range(32, 64)))
CREATED = 1_795_000_000
TARGETED = MarketRequest(
    method="POST", role="seller", operation="listing.update", resource="list-7f3a",
    request_id="0f6c2b1e7d4a4c1e9a523e8b6d0f1a77", origin=CREATED,
)
TARGETLESS = TARGETED.model_copy(update={"operation": "listing.publish", "resource": None})
BODY = b'{"listing_id":"list-7f3a"}'
RESPONSE_BODY = b'{"published":true}'


@pytest.fixture(params=["targeted", "targetless"])
def request_fields(request: pytest.FixtureRequest) -> MarketRequest:
    return TARGETED if request.param == "targeted" else TARGETLESS


def _audience() -> TrustedIdentitySet:
    return TrustedIdentitySet(identities=(AUTHORITY.identity,))


def test_the_request_record_from_signing_equals_the_one_from_verifying(
    signer: Signer, request_fields: MarketRequest
) -> None:
    signed = sign_market_request(signer=signer, request=request_fields, body=BODY, created=CREATED, audience=_audience())
    verified = verify_market_request(method="POST", headers=signed.headers, body=BODY).request

    assert verified is not None and signed.record is not None
    assert verified.record == signed.record
    assert signed.record.principal == principal_text(signer.identity)
    assert signed.record.timestamp == CREATED and signed.record.origin == CREATED
    assert signed.record.audience == (principal_text(AUTHORITY.identity),)
    assert signed.record.resource == request_fields.resource


def test_the_response_record_from_signing_equals_the_one_from_verifying(
    signer: Signer, request_fields: MarketRequest
) -> None:
    signed = sign_market_response(
        signer=signer, status=201, body=RESPONSE_BODY, request=request_fields.binding, created=CREATED + 1
    )
    verified = verify_market_response(
        status=201, headers=signed.headers, body=RESPONSE_BODY, request=request_fields.binding,
        expected_principals=TrustedIdentitySet(identities=(signer.identity,)), now=CREATED + 1, max_skew=300,
    )

    assert verified.verified and verified.record == signed.record
    assert (signed.record.status, signed.record.timestamp) == (201, CREATED + 1)
    assert signed.record.request_id == request_fields.request_id


def test_a_record_survives_a_json_round_trip(signer: Signer, request_fields: MarketRequest) -> None:
    request = sign_market_request(
        signer=signer, request=request_fields, body=BODY, created=CREATED, audience=_audience()
    ).record
    response = sign_market_response(
        signer=signer, status=200, body=RESPONSE_BODY, request=request_fields.binding, created=CREATED
    ).record
    assert request is not None

    assert RequestRecord.model_validate_json(request.model_dump_json()) == request
    assert RequestRecord.model_validate(json.loads(request.model_dump_json())) == request
    assert ResponseRecord.model_validate_json(response.model_dump_json()) == response
    assert ResponseRecord.model_validate(json.loads(response.model_dump_json())) == response


def test_a_targetless_record_has_no_resource_key(signer: Signer) -> None:
    request = sign_market_request(
        signer=signer, request=TARGETLESS, body=BODY, created=CREATED, audience=_audience()
    ).record
    response = sign_market_response(
        signer=signer, status=200, body=RESPONSE_BODY, request=TARGETLESS.binding, created=CREATED
    ).record
    assert request is not None

    for record in (request, response):
        assert "resource" not in record.model_dump()
        assert "resource" not in json.loads(record.model_dump_json())
    targeted = sign_market_request(
        signer=signer, request=TARGETED, body=BODY, created=CREATED, audience=_audience()
    ).record
    assert targeted is not None and targeted.model_dump()["resource"] == "list-7f3a"


def test_a_record_keeps_no_digest_or_header(signer: Signer) -> None:
    request = sign_market_request(
        signer=signer, request=TARGETED, body=BODY, created=CREATED, audience=_audience()
    ).record
    response = sign_market_response(
        signer=signer, status=200, body=RESPONSE_BODY, request=TARGETED.binding, created=CREATED
    ).record
    assert request is not None
    for record in (request, response):
        assert not {key for key in record.model_dump() if "digest" in key or "-" in key}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("principal", "ed25519:not-a-key"),
        ("principal", "EIP191:0x" + "ab" * 20),
        ("audience", []),
        ("audience", ["rsa:abc"]),
        ("proof", "not-a-proof"),
        ("method", "post"),
        ("resource", ""),
        ("role", "two words"),
    ],
)
def test_a_record_holding_what_no_signature_carries_is_refused(signer: Signer, field: str, value: object) -> None:
    record = sign_market_request(
        signer=signer, request=TARGETED, body=BODY, created=CREATED, audience=_audience()
    ).record
    assert record is not None
    with pytest.raises(ValueError):
        RequestRecord.model_validate({**json.loads(record.model_dump_json()), field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("principal", "ed25519:not-a-key"),
        ("proof", "not-a-proof"),
        ("method", "post"),
        ("status", 99),
        ("resource", " padded"),
        ("operation", "réserve"),
    ],
)
def test_a_response_record_holding_what_no_signature_carries_is_refused(
    signer: Signer, field: str, value: object
) -> None:
    record = sign_market_response(
        signer=signer, status=200, body=RESPONSE_BODY, request=TARGETED.binding, created=CREATED
    ).record
    with pytest.raises(ValueError):
        ResponseRecord.model_validate({**json.loads(record.model_dump_json()), field: value})


@pytest.mark.parametrize("query", ["?limit=50&offset=0&status=open", ""])
def test_a_record_carries_its_covered_query_through_a_json_round_trip(signer: Signer, query: str) -> None:
    signed = sign_market_request(
        signer=signer, request=TARGETLESS, body=BODY, created=CREATED, query=query, audience=_audience()
    )
    record = signed.record
    assert record is not None and record.query == (query or "?")
    stored = json.loads(record.model_dump_json())
    assert stored["query"] == (query or "?")
    assert list(stored)[:5] == ["protocol", "principal", "role", "method", "query"]
    assert RequestRecord.model_validate(stored) == record
    verified = verify_market_request(method="POST", headers=signed.headers, body=BODY, query=query).request
    assert verified is not None and verified.record == record


@pytest.mark.parametrize("query", ["", "limit=50", "?q=two words", "?q=%zz"])
def test_a_record_query_other_than_a_covered_value_is_refused(signer: Signer, query: str) -> None:
    record = sign_market_request(
        signer=signer, request=TARGETED, body=BODY, created=CREATED, audience=_audience()
    ).record
    assert record is not None
    with pytest.raises(ValueError):
        RequestRecord.model_validate({**json.loads(record.model_dump_json()), "query": query})


def test_a_request_record_requires_its_query(signer: Signer) -> None:
    record = sign_market_request(
        signer=signer, request=TARGETED, body=BODY, created=CREATED, audience=_audience()
    ).record
    assert record is not None
    stored = {k: v for k, v in json.loads(record.model_dump_json()).items() if k != "query"}
    with pytest.raises(ValueError):
        RequestRecord.model_validate(stored)
