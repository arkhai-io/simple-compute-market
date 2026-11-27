"""Retained signed messages verify offline, version 2 and version 3 alike.

Every case under both schemes. A record is stored as JSON and verified from what
was kept alone; no verifier takes an instant, so none judges freshness.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from market_identity import (
    Ed25519Signer,
    Eip191Signer,
    MarketRequest,
    RequestEvidence,
    ResponseEvidence,
    Signer,
    TrustedIdentitySet,
    VerificationCode,
    principal_text,
    sign_market_request,
    sign_market_response,
    verify_request_evidence,
    verify_response_evidence,
)

VECTORS = Path(__file__).parent / "vectors"
REQUEST_V2 = json.loads((VECTORS / "market_request_v2.json").read_text())
RESPONSE_V2 = json.loads((VECTORS / "market_response_v2.json").read_text())
REQUEST_V2_TARGETLESS = json.loads((VECTORS / "market_request_v2_targetless.json").read_text())
# The body both version 2 vectors were signed over, by its canonical JSON hash.
V2_BODY = b'{"accepted": true}'

# Deterministic development keys, never for a public network.
AUTHORITY = Ed25519Signer(bytes(range(32, 64)))
STRANGER = Eip191Signer(bytes(range(96, 128)))
ED25519_STRANGER = Ed25519Signer(bytes(range(64, 96)))


def _stranger_of_scheme(signer: Signer) -> Signer:
    """Another party under ``signer``'s scheme, so its proof parses and only the
    signature tells them apart."""

    return STRANGER if signer.identity.scheme.value == "eip191" else ED25519_STRANGER
SIGNED_AT = 1_795_000_000
PUBLISH = MarketRequest(
    method="POST", role="seller", operation="listing.publish",
    request_id="0f6c2b1e7d4a4c1e9a523e8b6d0f1a77", origin=SIGNED_AT,
)
UPDATE = PUBLISH.model_copy(update={"operation": "listing.update", "resource": "list-7f3a"})
BODY = b'{"listing_id":"list-7f3a","price":"3"}'
ACK_BODY = b'{"ended":true}'


def _trusted(*signers: Signer) -> TrustedIdentitySet:
    return TrustedIdentitySet(identities=tuple(s.identity for s in signers))


def _stored_request(signer: Signer, request: MarketRequest = PUBLISH, query: str = "") -> dict:
    record = sign_market_request(
        signer=signer, request=request, body=BODY, created=SIGNED_AT, query=query, audience=_trusted(AUTHORITY)
    ).record
    assert record is not None
    return json.loads(record.model_dump_json())


def _stored_response(signer: Signer, request: MarketRequest = UPDATE) -> dict:
    record = sign_market_response(
        signer=signer, status=200, body=ACK_BODY, request=request.binding, created=SIGNED_AT + 5
    ).record
    return json.loads(record.model_dump_json())


def test_a_publication_verifies_long_after_it_was_signed(signer: Signer) -> None:
    assert _stored_request(signer)["query"] == "?"
    stored = json.dumps(_stored_request(signer))
    # Read back days later: nothing here reads a clock, and no window applies.
    result = verify_request_evidence(
        json.loads(stored), body=BODY, trusted=_trusted(signer),
        expected_role="seller", expected_operation="listing.publish", expected_resource=None,
    )

    assert result.verified and result.evidence == RequestEvidence(
        principal=signer.identity, timestamp=SIGNED_AT, operation="listing.publish",
        resource=None, request_id=PUBLISH.request_id, role="seller",
    )


ALTERED_REQUEST = [
    ("role", lambda: "buyer"),
    ("method", lambda: "PUT"),
    ("operation", lambda: "listing.update"),
    ("resource", lambda: "list-7f3a"),
    ("request_id", lambda: "another-request"),
    ("timestamp", lambda: SIGNED_AT + 1),
    ("origin", lambda: SIGNED_AT - 1),
    ("audience", lambda: [principal_text(STRANGER.identity)]),
    ("query", lambda: "?status=open"),
]


@pytest.mark.parametrize(("field", "value"), ALTERED_REQUEST, ids=[f for f, _ in ALTERED_REQUEST])
def test_an_altered_request_record_fails(signer: Signer, field: str, value) -> None:
    altered = {**_stored_request(signer), field: value()}
    result = verify_request_evidence(altered, body=BODY, trusted=_trusted(signer, STRANGER))
    assert not result.verified and result.evidence is None


def test_a_record_naming_another_principal_of_its_scheme_fails_its_proof(signer: Signer) -> None:
    stranger = _stranger_of_scheme(signer)
    trusted = _trusted(signer, stranger)
    request = {**_stored_request(signer), "principal": principal_text(stranger.identity)}
    response = {**_stored_response(signer), "principal": principal_text(stranger.identity)}
    assert verify_request_evidence(request, body=BODY, trusted=trusted).code == VerificationCode.INVALID_PROOF
    assert verify_response_evidence(response, body=ACK_BODY, trusted=trusted).code == VerificationCode.INVALID_PROOF


def test_a_response_record_with_another_proof_fails(signer: Signer) -> None:
    other = _stored_response(signer, UPDATE.model_copy(update={"request_id": "r-2"}))["proof"]
    altered = {**_stored_response(signer), "proof": other}
    assert verify_response_evidence(altered, body=ACK_BODY, trusted=_trusted(signer)).code == (
        VerificationCode.INVALID_PROOF
    )


def test_a_request_records_removed_resource_or_altered_proof_or_body_fails(signer: Signer) -> None:
    targeted = _stored_request(signer, UPDATE)
    removed = {k: v for k, v in targeted.items() if k != "resource"}
    other_proof = _stored_request(signer, PUBLISH.model_copy(update={"request_id": "r-2"}))["proof"]
    for altered, body in ((removed, BODY), ({**targeted, "proof": other_proof}, BODY), (targeted, BODY + b" ")):
        assert not verify_request_evidence(altered, body=body, trusted=_trusted(signer)).verified
    assert verify_request_evidence(targeted, body=BODY, trusted=_trusted(signer)).verified


ALTERED_RESPONSE = [
    ("status", lambda: 201),
    ("timestamp", lambda: SIGNED_AT),
    ("method", lambda: "PUT"),
    ("operation", lambda: "listing.publish"),
    ("resource", lambda: "list-0000"),
    ("request_id", lambda: "another-request"),
]


@pytest.mark.parametrize(("field", "value"), ALTERED_RESPONSE, ids=[f for f, _ in ALTERED_RESPONSE])
def test_an_altered_response_record_fails(signer: Signer, field: str, value) -> None:
    altered = {**_stored_response(signer), field: value()}
    assert not verify_response_evidence(altered, body=ACK_BODY, trusted=_trusted(signer, STRANGER)).verified
    assert not verify_response_evidence(_stored_response(signer), body=b"{}", trusted=_trusted(signer)).verified


def test_an_end_acknowledgement_verifies_by_the_seller_alone_with_no_role(signer: Signer) -> None:
    result = verify_response_evidence(
        _stored_response(signer), body=ACK_BODY, trusted=_trusted(signer),
        expected_operation="listing.update", expected_resource="list-7f3a",
    )

    assert result.verified and result.evidence == ResponseEvidence(
        principal=signer.identity, timestamp=SIGNED_AT + 5, operation="listing.update",
        resource="list-7f3a", request_id=UPDATE.request_id, status=200,
    )
    other = verify_response_evidence(_stored_response(signer), body=ACK_BODY, trusted=_trusted(STRANGER))
    assert other.code == VerificationCode.WRONG_PRINCIPAL


def test_an_untrusted_principal_or_an_unexpected_value_is_refused(signer: Signer) -> None:
    stored = _stored_request(signer, UPDATE)
    assert verify_request_evidence(stored, body=BODY, trusted=_trusted(STRANGER)).code == (
        VerificationCode.WRONG_PRINCIPAL
    )
    for expectation in (
        {"expected_role": "buyer"},
        {"expected_operation": "listing.publish"},
        {"expected_resource": None},
        {"expected_resource": "list-0000"},
    ):
        result = verify_request_evidence(stored, body=BODY, trusted=_trusted(signer), **expectation)
        assert result.code == VerificationCode.CONTEXT_MISMATCH


def test_a_response_from_an_untrusted_principal_or_unexpected_is_refused(signer: Signer) -> None:
    stored = _stored_response(signer)
    for expectation in (
        {"expected_operation": "listing.publish"},
        {"expected_resource": None},
        {"expected_resource": "list-0000"},
    ):
        result = verify_response_evidence(stored, body=ACK_BODY, trusted=_trusted(signer), **expectation)
        assert result.code == VerificationCode.CONTEXT_MISMATCH
    unknown = {**stored, "protocol": "arkhai.market-response-signature.v4"}
    assert verify_response_evidence(unknown, body=ACK_BODY, trusted=_trusted(signer)).code == (
        VerificationCode.UNSUPPORTED_VERSION
    )
    assert verify_response_evidence({**stored, "status": 99}, body=ACK_BODY, trusted=_trusted(signer)).code == (
        VerificationCode.MALFORMED_ENVELOPE
    )


def test_a_record_under_an_unknown_protocol_or_malformed_is_refused(signer: Signer) -> None:
    stored = _stored_request(signer)
    unknown = {**stored, "protocol": "arkhai.market-request-signature.v4"}
    assert verify_request_evidence(unknown, body=BODY, trusted=_trusted(signer)).code == (
        VerificationCode.UNSUPPORTED_VERSION
    )
    assert verify_request_evidence({**stored, "proof": "x"}, body=BODY, trusted=_trusted(signer)).code == (
        VerificationCode.MALFORMED_ENVELOPE
    )


@pytest.mark.parametrize("scheme", sorted(REQUEST_V2))
def test_version_2_and_version_3_requests_verify_alike_into_one_view(scheme: str, signer: Signer) -> None:
    captured = REQUEST_V2[scheme]
    principal = TrustedIdentitySet.model_validate({"identities": [captured["principal"]]})
    v2 = verify_request_evidence(
        captured, body=V2_BODY, trusted=principal, expected_role="buyer",
        expected_operation="negotiation.advance", expected_resource="negotiation/thread-17",
    )
    v3 = verify_request_evidence(_stored_request(signer), body=BODY, trusted=_trusted(signer))

    assert v2.verified and v3.verified
    assert isinstance(v2.evidence, RequestEvidence) and isinstance(v3.evidence, RequestEvidence)
    assert v2.evidence == RequestEvidence(
        principal=principal.identities[0], timestamp=captured["timestamp"], operation=captured["operation"],
        resource=captured["resource"], request_id=captured["request_id"], role="buyer",
    )
    assert not verify_request_evidence(captured, body=b'{"accepted": false}', trusted=principal).verified
    assert not verify_request_evidence({**captured, "role": "seller"}, body=V2_BODY, trusted=principal).verified


@pytest.mark.parametrize("scheme", sorted(RESPONSE_V2))
def test_version_2_and_version_3_responses_verify_alike_into_one_view(scheme: str, signer: Signer) -> None:
    captured = RESPONSE_V2[scheme]
    principal = TrustedIdentitySet.model_validate({"identities": [captured["principal"]]})
    # The version 2 response signs the role "storefront", which is not read.
    v2 = verify_response_evidence(
        captured, body=V2_BODY, trusted=principal,
        expected_operation="negotiation.advance", expected_resource="negotiation/thread-17",
    )
    v3 = verify_response_evidence(_stored_response(signer), body=ACK_BODY, trusted=_trusted(signer))

    assert v2.verified and v3.verified
    assert isinstance(v2.evidence, ResponseEvidence) and isinstance(v3.evidence, ResponseEvidence)
    assert v2.evidence == ResponseEvidence(
        principal=principal.identities[0], timestamp=captured["timestamp"], operation=captured["operation"],
        resource=captured["resource"], request_id=captured["request_id"], status=captured["status"],
    )
    assert not verify_response_evidence({**captured, "status": 201}, body=V2_BODY, trusted=principal).verified
    assert not verify_response_evidence(captured, body=b'{"accepted": false}', trusted=principal).verified


@pytest.mark.parametrize("scheme", sorted(REQUEST_V2_TARGETLESS))
def test_a_version_2_empty_resource_reads_as_none(scheme: str) -> None:
    captured = REQUEST_V2_TARGETLESS[scheme]
    assert captured["resource"] == ""
    principal = TrustedIdentitySet.model_validate({"identities": [captured["principal"]]})

    result = verify_request_evidence(captured, body=V2_BODY, trusted=principal, expected_resource=None)
    assert result.verified and result.evidence is not None and result.evidence.resource is None


def test_a_record_with_a_query_verifies_and_fails_once_its_query_is_altered(signer: Signer) -> None:
    stored = _stored_request(signer, UPDATE, query="?limit=50&offset=0&status=open")
    assert verify_request_evidence(stored, body=BODY, trusted=_trusted(signer)).verified
    altered = {**stored, "query": "?limit=50&offset=0&status=closed"}
    assert verify_request_evidence(altered, body=BODY, trusted=_trusted(signer)).code == (
        VerificationCode.INVALID_PROOF
    )
