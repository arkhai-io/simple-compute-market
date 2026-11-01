"""The published vector, replayed through the plugin's own verifier.

These tests read `vector/frp-grant-1.json` as any signer or verifier elsewhere reads
it: from its own data, not from the builder's helpers, apart from the two tests of
the builder itself — that the committed file equals its output, and that its JCS
writes RFC 8785's own example.
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
from tests.vector_builder import VECTOR, jcs, render

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
    # The vector's members have ASCII names and hold strings, integers, and lists, for
    # which RFC 8785 is JSON with sorted members and no whitespace, every character of
    # a string written as UTF-8 but `"`, `\`, and the control characters.
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


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


def test_a_signing_case_holds_strings_jcs_writes_unlike_ascii_json() -> None:
    strings = [
        value
        for case in VECTOR_DATA["signing"]
        for value in case["claims"].values()
        if isinstance(value, str)
    ]

    assert any(any(0x80 <= ord(c) <= 0xFFFF for c in value) for value in strings)
    assert any(any(ord(c) > 0xFFFF for c in value) for value in strings)
    assert any(any(ord(c) < 0x20 for c in value) for value in strings)


def test_the_builders_jcs_writes_rfc_8785s_string_example() -> None:
    # RFC 8785's own example of string serialization, an oracle outside this code: the
    # euro sign, `$`, U+000F, a line feed, `A'B`, a quotation mark, two backslashes, a
    # quotation mark, and `/` serialize as the bytes below — the euro sign literally,
    # U+000F in lowercase hex, `/` unescaped.
    parsed = "€$\x0f\nA'B\"\\\\\"/"

    assert jcs(parsed) == r'''"€$\u000f\nA'B\"\\\\\"/"'''.encode("utf-8")


def test_the_thumbprint_case_matches_the_derivation() -> None:
    case = VECTOR_DATA["thumbprint"]
    public_key = parse_public_key(case["public_key_spki_base64"])

    assert public_key is not None
    assert thumbprint(public_key) == case["kid"] == TEST_1_THUMBPRINT
