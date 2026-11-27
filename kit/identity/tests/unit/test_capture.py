"""The client-side capture seam hands a sink a version 3 record and its exact body.

Every case under both schemes. The sink runs only once the body is the one signed.
"""

from __future__ import annotations

import pytest

from market_identity import (
    CapturedEnvelope,
    TrustedIdentitySet,
    capture_envelope,
    verify_request_evidence,
    verify_response_evidence,
)
from market_identity.fixtures.messages import SCHEMES, build_signed_request, build_signed_response

VERIFIED_AT = 1_795_000_010


@pytest.fixture(params=SCHEMES)
def scheme(request: pytest.FixtureRequest) -> str:
    return str(request.param)


def _trusting(signer) -> TrustedIdentitySet:
    return TrustedIdentitySet(identities=(signer.identity,))


def test_a_captured_response_record_reaches_the_sink_and_verifies(scheme: str) -> None:
    response = build_signed_response(scheme=scheme)
    sink: list[CapturedEnvelope] = []

    capture_envelope(
        sink.append, envelope=response.record, raw_body=response.body, verified_at=VERIFIED_AT,
        expected_principals=_trusting(response.signer),
    )

    (captured,) = sink
    assert (captured.envelope, captured.body, dict(captured.headers)) == (response.record, response.body, {})
    assert captured.verified_at == VERIFIED_AT
    assert verify_response_evidence(captured.envelope, body=captured.body, trusted=captured.expected_principals).verified


def test_a_captured_request_record_reaches_the_sink_and_verifies(scheme: str) -> None:
    request = build_signed_request(scheme=scheme, resource=None, operation="listing.publish")
    sink: list[CapturedEnvelope] = []

    capture_envelope(
        sink.append, envelope=request.record, raw_body=request.body, verified_at=VERIFIED_AT,
        expected_principals=_trusting(request.signer),
    )

    (captured,) = sink
    assert verify_request_evidence(captured.envelope, body=captured.body, trusted=captured.expected_principals).verified


def test_a_body_other_than_the_signed_one_is_refused_before_the_sink_runs(scheme: str) -> None:
    response = build_signed_response(scheme=scheme)
    sink: list[CapturedEnvelope] = []

    with pytest.raises(ValueError, match="differs from what was signed"):
        capture_envelope(
            sink.append, envelope=response.record, raw_body=response.body + b" ", verified_at=VERIFIED_AT,
            expected_principals=_trusting(response.signer),
        )
    assert sink == []


def test_a_record_verified_against_other_principals_is_refused(scheme: str) -> None:
    response = build_signed_response(scheme=scheme)
    stranger = build_signed_request(scheme=scheme).signer
    sink: list[CapturedEnvelope] = []
    with pytest.raises(ValueError, match="wrong_principal"):
        capture_envelope(
            sink.append, envelope=response.record, raw_body=response.body,
            verified_at=VERIFIED_AT, expected_principals=_trusting(stranger),
        )
    assert sink == []


def test_a_captured_record_carries_no_headers(scheme: str) -> None:
    response = build_signed_response(scheme=scheme)
    with pytest.raises(ValueError, match="no headers"):
        capture_envelope(
            lambda captured: None, envelope=response.record, raw_body=response.body,
            headers=response.headers, verified_at=VERIFIED_AT, expected_principals=_trusting(response.signer),
        )
