"""The producer fixture's messages verify, and its records verify as evidence.

Consumers' tests draw their signed version 3 messages from
``market_identity.fixtures.messages``; this holds every one to the verifiers.
"""

from __future__ import annotations

import json

import pytest

from market_identity import (
    TrustedIdentitySet,
    verify_market_request,
    verify_market_response,
    verify_request_evidence,
    verify_response_evidence,
)
from market_identity.fixtures.messages import (
    CREATED,
    READ_QUERY,
    SCHEMES,
    build_market_request,
    build_signed_request,
    build_signed_response,
    development_authority,
    development_signer,
    validate_request_record,
    validate_response_record,
)


@pytest.fixture(params=SCHEMES)
def scheme(request: pytest.FixtureRequest) -> str:
    return str(request.param)


@pytest.fixture(params=["targeted", "targetless"])
def fields(request: pytest.FixtureRequest) -> dict:
    return {} if request.param == "targeted" else {"operation": "listing.publish", "resource": None}


@pytest.fixture(params=["", READ_QUERY], ids=["no-query", "query"])
def query(request: pytest.FixtureRequest) -> str:
    return str(request.param)


def test_every_fixture_request_verifies_live_and_as_evidence(scheme: str, fields: dict, query: str) -> None:
    message = build_signed_request(scheme=scheme, query=query, **fields)
    live = verify_market_request(
        method=message.method, headers=message.headers, body=message.body, query=message.query
    )

    assert message.query == query
    assert live.verified and live.request is not None
    assert live.request.record == message.record
    assert message.record.query == (query or "?")
    assert live.request.addressed_to(development_authority(scheme).identity)
    evidence = verify_request_evidence(
        json.loads(message.record.model_dump_json()), body=message.body,
        trusted=TrustedIdentitySet(identities=(message.signer.identity,)),
    )
    assert evidence.verified
    validate_request_record(json.loads(message.record.model_dump_json()), resource=not fields)


def test_every_fixture_response_verifies_live_and_as_evidence(scheme: str, fields: dict) -> None:
    binding = build_market_request(**fields).binding
    message = build_signed_response(scheme=scheme, request=binding, status=409)
    trusted = TrustedIdentitySet(identities=(message.signer.identity,))
    live = verify_market_response(
        status=message.status, headers=message.headers, body=message.body, request=binding,
        expected_principals=trusted, now=CREATED, max_skew=300,
    )

    assert live.verified and live.record == message.record
    assert verify_response_evidence(json.loads(message.record.model_dump_json()), body=message.body, trusted=trusted).verified
    validate_response_record(json.loads(message.record.model_dump_json()), resource=not fields)


def test_development_signers_are_distinct_and_deterministic(scheme: str) -> None:
    assert development_signer(scheme).identity == development_signer(scheme).identity
    assert development_signer(scheme).identity != development_authority(scheme).identity
    with pytest.raises(ValueError):
        development_signer("rsa")


def test_a_request_signed_by_another_signer_and_audience(scheme: str) -> None:
    caller = development_signer(scheme, index=2)
    audience = TrustedIdentitySet(identities=(development_signer(scheme, index=3).identity,))
    message = build_signed_request(scheme=scheme, signer=caller, audience=audience, role="seller")
    assert message.record.principal.endswith(caller.identity.identifier)
    assert message.record.role == "seller"
    assert len(message.record.audience) == 1


def test_the_validators_refuse_a_record_naming_a_resource_it_should_not(scheme: str) -> None:
    request = build_signed_request(scheme=scheme)
    response = build_signed_response(scheme=scheme)
    with pytest.raises(AssertionError):
        validate_request_record(json.loads(request.record.model_dump_json()), resource=False)
    with pytest.raises(AssertionError):
        validate_response_record(json.loads(response.record.model_dump_json()), resource=False)
