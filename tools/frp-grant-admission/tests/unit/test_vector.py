"""The published vector, replayed through the plugin's own verifier.

These tests read `vector/frp-grant-1.json` as any signer or verifier elsewhere reads
it: from its own data, not from the builder's helpers, apart from the one test that
holds the committed file equal to the builder's output.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from frp_grant_admission.config import parse_config, parse_public_key, thumbprint
from frp_grant_admission.grant import check_grant
from frp_grant_admission.reasons import Reason
from tests.rfc8032 import TEST_1_THUMBPRINT
from tests.vector_builder import VECTOR, render

# The refusals the grant check itself returns; the rest are decided from the request
# before a grant is read.
GRANT_REASONS = {
    Reason.GRANT_MALFORMED,
    Reason.GRANT_TYPE_UNSUPPORTED,
    Reason.KEY_UNKNOWN,
    Reason.SIGNATURE_INVALID,
    Reason.CLAIM_MISSING,
    Reason.AUDIENCE_MISMATCH,
    Reason.GRANT_EXPIRED,
    Reason.GRANT_NOT_YET_VALID,
    Reason.PORT_MISMATCH,
    Reason.PORT_OUTSIDE_RANGE,
}


def _vector() -> dict[str, Any]:
    return json.loads(VECTOR.read_text(encoding="utf-8"))


VECTOR_DATA = _vector() if VECTOR.exists() else {"verification": [], "signing": [], "keys": []}


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _jcs(value: Any) -> bytes:
    # The vector's values are ASCII strings, integers, and lists, for which RFC 8785
    # is JSON with sorted members and no whitespace.
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def test_the_committed_vector_is_the_builders_output(tmp_path: Path) -> None:
    expected = render()
    committed = VECTOR.read_text(encoding="utf-8") if VECTOR.exists() else None
    if committed != expected:
        written = tmp_path / VECTOR.name
        written.write_text(expected, encoding="utf-8")
        pytest.fail(
            f"{VECTOR} differs from what tests/vector_builder.py writes; regenerate it "
            f"with `uv run python -m tests.vector_builder` (the builder's output is at {written})"
        )


def test_the_vector_states_its_specification_and_warns_of_its_keys() -> None:
    assert VECTOR_DATA["specification"] == "frp-grant 1.0"
    assert "never use them on any network" in VECTOR_DATA["warning"]
    assert "never use them on any network" in VECTOR_DATA["configuration"]


@pytest.mark.parametrize("key", VECTOR_DATA["keys"], ids=lambda key: key["name"])
def test_each_key_entry_is_consistent(key: dict[str, str]) -> None:
    private_key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(key["seed"]))
    public_key = parse_public_key(key["public_key_spki_base64"])

    assert public_key is not None
    assert private_key.public_key().public_bytes_raw().hex() == key["public_key"]
    assert public_key.public_bytes_raw().hex() == key["public_key"]
    assert thumbprint(public_key) == key["kid"]


@pytest.mark.parametrize(
    "case", VECTOR_DATA["verification"], ids=lambda case: case["name"]
)
def test_each_verification_case_returns_its_verdict_and_reason(case: dict[str, Any]) -> None:
    config = parse_config(VECTOR_DATA["configuration"])
    assert case["proxy_type"] == "tcp"

    result = check_grant(case["token"], config, case["remote_port"], case["time"])

    assert ("admit" if result.admitted else "refuse") == case["verdict"]
    assert (result.reason.code if result.reason else None) == case["reason"]


def test_the_verification_cases_cover_every_reason_the_grant_check_returns() -> None:
    covered = {case["reason"] for case in VECTOR_DATA["verification"]}

    assert covered - {None} == {reason.code for reason in GRANT_REASONS}
    assert None in covered


@pytest.mark.parametrize("case", VECTOR_DATA["signing"], ids=lambda case: case["name"])
def test_each_signing_case_is_reproduced_byte_for_byte(case: dict[str, Any]) -> None:
    key = next(key for key in VECTOR_DATA["keys"] if key["name"] == case["key"])
    private_key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(key["seed"]))

    signing_input = f"{_b64url(_jcs(case['header']))}.{_b64url(_jcs(case['claims']))}"
    token = f"{signing_input}.{_b64url(private_key.sign(signing_input.encode('ascii')))}"

    assert token == case["token"]


def test_the_signing_cases_hold_every_claim_and_only_the_required_ones() -> None:
    claim_sets = [set(case["claims"]) for case in VECTOR_DATA["signing"]]

    assert {"aud", "port", "exp", "nbf", "iat", "sub", "jti"} in claim_sets
    assert {"aud", "port", "exp"} in claim_sets


def test_the_thumbprint_case_matches_the_derivation() -> None:
    case = VECTOR_DATA["thumbprint"]
    public_key = parse_public_key(case["public_key_spki_base64"])

    assert public_key is not None
    assert thumbprint(public_key) == case["kid"] == TEST_1_THUMBPRINT
