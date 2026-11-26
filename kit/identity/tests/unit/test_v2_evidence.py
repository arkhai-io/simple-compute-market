"""Version 2 signed responses retained as evidence verify through the readers alone.

The vectors were captured from version 2 signing, so these tests import no signing
function: they hold the evidence readers to bytes already on record.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from market_identity import (
    AuthenticatedResponse,
    TrustedIdentitySet,
    VerificationCode,
    verify_response,
)

VECTORS = json.loads((Path(__file__).parent / "vectors" / "market_response_v2.json").read_text())
EVIDENCE_BODY = {"accepted": True}


def _verify(captured: dict, **changes):
    response = AuthenticatedResponse.model_validate({**captured, **changes})
    return verify_response(
        response,
        body=EVIDENCE_BODY,
        now=captured["timestamp"],
        max_skew=300,
        expected_role=captured["role"],
        expected_principals=TrustedIdentitySet(identities=(response.principal,)),
        expected_method=captured["method"],
        expected_operation=captured["operation"],
        expected_resource=captured["resource"],
        expected_request_id=captured["request_id"],
    )


@pytest.mark.parametrize("scheme", sorted(VECTORS))
def test_a_captured_version_2_response_verifies_as_evidence(scheme: str) -> None:
    assert _verify(VECTORS[scheme]).code == VerificationCode.VERIFIED


@pytest.mark.parametrize("scheme", sorted(VECTORS))
def test_a_changed_version_2_response_does_not(scheme: str) -> None:
    assert _verify(VECTORS[scheme], status=201).code == VerificationCode.INVALID_PROOF
