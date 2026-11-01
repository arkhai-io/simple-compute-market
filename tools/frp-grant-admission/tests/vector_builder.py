"""Writes the published test vector, `vector/frp-grant-1.json`, from the cases below.

A case is added or changed here, never in the JSON: `tests/unit/test_vector.py` fails
while the committed file differs from what this module writes. Regenerate it from the
tool's directory with

    uv run python -m tests.vector_builder

Every key is one of RFC 8032's published test keys (`tests/rfc8032.py`): their private
keys are public, so they must never be used on any network.
"""

from __future__ import annotations

import base64
import json
import math
import sys
from pathlib import Path
from typing import Any

from frp_grant_admission.config import parse_config, thumbprint
from tests.rfc8032 import TEST_1, TEST_2, TEST_3, Rfc8032Key

VECTOR = Path(__file__).resolve().parents[1] / "vector" / "frp-grant-1.json"
SPECIFICATION = "frp-grant 1.0"

# 2027-01-01T00:00:00Z: the clock every case is replayed at unless it states another.
NOW = 1798761600
EXP = NOW + 3600
IAT = NOW - 60
AUDIENCE = "relay-1"
PORT = 6101
OTHER_ISSUERS_PORT = 6201
NO_ISSUERS_PORT = 6300

CONFIGURATION = f"""\
# RFC 8032 test keys only: never use them on any network.
listen = "127.0.0.1:7300"

[[issuers]]
name = "issuer-a"
audience = "{AUDIENCE}"
ports = {{ start = 6100, end = 6199 }}
keys = [
  {{ public_key = "{TEST_1.spki_base64}" }},  # RFC 8032 TEST 1
  {{ public_key = "{TEST_2.spki_base64}" }},  # RFC 8032 TEST 2
]

[[issuers]]
name = "issuer-b"
audience = "{AUDIENCE}"
ports = {{ start = 6200, end = 6249 }}
keys = [
  {{ public_key = "{TEST_3.spki_base64}" }},  # RFC 8032 TEST 3
]
"""


def jcs(value: Any) -> bytes:
    """RFC 8785 (JCS) serialization of the values the vector uses.

    For ASCII member names, strings with no lone surrogate, booleans, null, integers
    whose magnitude is at most 2^53, and non-integral floats whose shortest form has no
    exponent, JCS is JSON with sorted members and no whitespace, which `json.dumps`
    writes. With `ensure_ascii=False` it writes strings as JCS does: every character
    literally as UTF-8 but `"`, `\\`, and the control characters, those as `\\b \\t \\n
    \\f \\r` or else lowercase `\\u00xx`. Member names stay ASCII because JCS sorts them
    by UTF-16 code units and `json.dumps` by code points, which order differently
    beyond the Basic Multilingual Plane. Anything else is refused rather than serialized
    in a form JCS would write differently — such as `5.0`, which JCS writes as `5`.
    """
    _check_jcs_subset(value)
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def _check_jcs_subset(value: Any) -> None:
    if isinstance(value, dict):
        for name, member in value.items():
            if not isinstance(name, str) or not name.isascii():
                raise ValueError(f"member name {name!r} is outside the subset jcs() writes")
            _check_jcs_subset(member)
    elif isinstance(value, list):
        for member in value:
            _check_jcs_subset(member)
    elif isinstance(value, bool) or value is None:
        return
    elif isinstance(value, str):
        if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
            raise ValueError(f"string {value!r} is outside the subset jcs() writes")
    elif isinstance(value, int):
        if abs(value) > 2**53:
            raise ValueError(f"integer {value} is outside the subset jcs() writes")
    elif isinstance(value, float):
        if not math.isfinite(value) or value.is_integer() or "e" in repr(value):
            raise ValueError(f"number {value!r} is outside the subset jcs() writes")
    else:
        raise ValueError(f"{type(value).__name__} is not JSON")


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def sign(header: dict[str, Any], claims: dict[str, Any], key: Rfc8032Key = TEST_1) -> str:
    """A token as a conforming signer writes it: JCS segments, unpadded base64url."""
    signing_input = f"{b64url(jcs(header))}.{b64url(jcs(claims))}"
    signature = key.private_key.sign(signing_input.encode("ascii"))
    return f"{signing_input}.{b64url(signature)}"


def sign_padded(header: dict[str, Any], claims: dict[str, Any]) -> str:
    """A token whose segments carry base64 padding, signed over the padded segments."""

    def padded(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).decode("ascii")

    signing_input = f"{padded(jcs(header))}.{padded(jcs(claims))}"
    signature = TEST_1.private_key.sign(signing_input.encode("ascii"))
    return f"{signing_input}.{padded(signature)}"


def kid(key: Rfc8032Key) -> str:
    return thumbprint(key.private_key.public_key())


def header(key: Rfc8032Key = TEST_1, **changes: Any) -> dict[str, Any]:
    """The header a conforming signer writes; a value of `None` removes that member."""
    members: dict[str, Any] = {"alg": "EdDSA", "kid": kid(key), "typ": "frp-grant+jwt"}
    members.update(changes)
    return {name: value for name, value in members.items() if value is not None}


def claims(**changes: Any) -> dict[str, Any]:
    """A grant for `PORT` with every claim; a value of `None` removes that claim."""
    members: dict[str, Any] = {
        "aud": AUDIENCE,
        "port": PORT,
        "exp": EXP,
        "iat": IAT,
        "sub": "host-1",
        "jti": "grant-0001",
    }
    members.update(changes)
    return {name: value for name, value in members.items() if value is not None}


def forged(header_members: dict[str, Any], claim_members: dict[str, Any]) -> str:
    """A token naming TEST 1's key but signed with TEST 2's, a key of the same issuer."""
    return sign(header_members, claim_members, key=TEST_2)


def admit(name: str, token: str, *, time: int = NOW, remote_port: int = PORT) -> dict[str, Any]:
    return _case(name, token, time, remote_port, "admit", None)


def refuse(
    name: str, token: str, reason: str, *, time: int = NOW, remote_port: int = PORT
) -> dict[str, Any]:
    return _case(name, token, time, remote_port, "refuse", reason)


def _case(
    name: str, token: str, time: int, remote_port: int, verdict: str, reason: str | None
) -> dict[str, Any]:
    return {
        "name": name,
        "time": time,
        "proxy_type": "tcp",
        "remote_port": remote_port,
        "token": token,
        "verdict": verdict,
        "reason": reason,
    }


def verification_cases() -> list[dict[str, Any]]:
    return [
        admit("valid", sign(header(), claims())),
        admit("a second key of the same issuer", sign(header(TEST_2), claims(), key=TEST_2)),
        admit("only the required claims", sign(header(), claims(iat=None, sub=None, jti=None))),
        admit("a padded token", sign_padded(header(), claims())),
        admit("an unknown claim is ignored", sign(header(), claims(region="eu-1"))),
        admit("one second before exp", sign(header(), claims()), time=EXP - 1),
        admit("iat equal to the clock", sign(header(), claims(iat=NOW))),
        admit("nbf equal to the clock", sign(header(), claims(nbf=NOW))),
        refuse("exactly at exp", sign(header(), claims()), "grant_expired", time=EXP),
        refuse("after exp", sign(header(), claims()), "grant_expired", time=EXP + 3600),
        refuse(
            "iat one second ahead", sign(header(), claims(iat=NOW + 1)), "grant_not_yet_valid"
        ),
        refuse(
            "nbf one second ahead", sign(header(), claims(nbf=NOW + 1)), "grant_not_yet_valid"
        ),
        refuse("the wrong port", sign(header(), claims(port=PORT + 1)), "port_mismatch"),
        refuse("port as a string", sign(header(), claims(port=str(PORT))), "port_mismatch"),
        refuse("port as true", sign(header(), claims(port=True)), "port_mismatch"),
        refuse(
            "outside every issuer's range",
            sign(header(), claims(port=NO_ISSUERS_PORT)),
            "port_outside_range",
            remote_port=NO_ISSUERS_PORT,
        ),
        refuse(
            "inside the other issuer's range",
            sign(header(), claims(port=OTHER_ISSUERS_PORT)),
            "port_outside_range",
            remote_port=OTHER_ISSUERS_PORT,
        ),
        refuse("the wrong audience", sign(header(), claims(aud="relay-2")), "audience_mismatch"),
        refuse(
            "aud as a list", sign(header(), claims(aud=[AUDIENCE])), "audience_mismatch"
        ),
        refuse("a forged signature", forged(header(), claims()), "signature_invalid"),
        refuse(
            "alg none",
            f"{b64url(jcs(header(alg='none')))}.{b64url(jcs(claims()))}.",
            "signature_invalid",
        ),
        refuse(
            "an unknown kid", sign(header(kid="not-a-configured-key"), claims()), "key_unknown"
        ),
        refuse("no kid", sign(header(kid=None), claims()), "key_unknown"),
        refuse("typ JWT", sign(header(typ="JWT"), claims()), "grant_type_unsupported"),
        refuse("typ absent", sign(header(typ=None), claims()), "grant_type_unsupported"),
        refuse(
            "crit on a correctly signed grant",
            sign(header(crit=["b64"], b64=True), claims()),
            "grant_malformed",
        ),
        refuse(
            "crit on a forged grant",
            forged(header(crit=["x-unsupported"]), claims()),
            "grant_malformed",
        ),
        refuse("no exp", sign(header(), claims(exp=None)), "claim_missing"),
        refuse("no aud", sign(header(), claims(aud=None)), "claim_missing"),
        refuse("no port", sign(header(), claims(port=None)), "claim_missing"),
        refuse("exp as a string", sign(header(), claims(exp=str(EXP))), "grant_malformed"),
        refuse("exp as a float", sign(header(), claims(exp=EXP + 0.5)), "grant_malformed"),
        refuse("exp as true", sign(header(), claims(exp=True)), "grant_malformed"),
        refuse("iat as a string", sign(header(), claims(iat=str(IAT))), "grant_malformed"),
        refuse("jti as an integer", sign(header(), claims(jti=1)), "grant_malformed"),
        refuse("sub as an object", sign(header(), claims(sub={"host": 1})), "grant_malformed"),
        refuse("not a JWT", "not-a-jwt", "grant_malformed"),
        refuse(
            "claims that are not an object",
            sign_raw_claims(header(), b"[]"),
            "grant_malformed",
        ),
    ]


def sign_raw_claims(header_members: dict[str, Any], raw_claims: bytes) -> str:
    signing_input = f"{b64url(jcs(header_members))}.{b64url(raw_claims)}"
    signature = TEST_1.private_key.sign(signing_input.encode("ascii"))
    return f"{signing_input}.{b64url(signature)}"


def signing_cases() -> list[dict[str, Any]]:
    every_claim = claims(nbf=IAT)
    required_only = claims(iat=None, sub=None, jti=None)
    # JCS writes `ô` and `€` literally, a character beyond the Basic Multilingual Plane
    # as its four UTF-8 bytes rather than a surrogate pair of escapes, and U+000F as
    # `\u000f` in lowercase; a serializer that escapes any of them otherwise fails here.
    beyond_ascii = claims(sub="hôte-€-1", jti="grant-\U0001f600-\x0f-0001")
    return [
        {
            "name": "every claim",
            "key": TEST_1.name,
            "header": header(),
            "claims": every_claim,
            "token": sign(header(), every_claim),
        },
        {
            "name": "only the required claims",
            "key": TEST_1.name,
            "header": header(),
            "claims": required_only,
            "token": sign(header(), required_only),
        },
        {
            "name": "non-ASCII and control characters",
            "key": TEST_1.name,
            "header": header(),
            "claims": beyond_ascii,
            "token": sign(header(), beyond_ascii),
        },
    ]


def _key_entry(key: Rfc8032Key) -> dict[str, str]:
    return {
        "name": key.name,
        "seed": key.seed_hex,
        "public_key": key.public_hex,
        "public_key_spki_base64": key.spki_base64,
        "kid": kid(key),
    }


def build() -> dict[str, Any]:
    parse_config(CONFIGURATION)
    return {
        "specification": SPECIFICATION,
        "warning": (
            "Every key here is a published RFC 8032 test key whose private key anyone can "
            "read. These are deterministic test values: never use them on any network."
        ),
        "keys": [_key_entry(TEST_1), _key_entry(TEST_2), _key_entry(TEST_3)],
        "configuration": CONFIGURATION,
        "verification": verification_cases(),
        "signing": signing_cases(),
        "thumbprint": {
            "public_key_spki_base64": TEST_1.spki_base64,
            "kid": kid(TEST_1),
        },
    }


def render() -> str:
    return json.dumps(build(), indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    VECTOR.parent.mkdir(exist_ok=True)
    VECTOR.write_text(render(), encoding="utf-8")
    print(f"wrote {VECTOR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
