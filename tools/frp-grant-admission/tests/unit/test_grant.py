"""What a grant's result carries beyond its verdict, and whose clock decides it.

Every verdict and reason a signer can produce is the published vector's
(`test_vector.py`); these tests cover the result's other fields, the clock the check
is given, and the size cap on what it reads.
"""

from __future__ import annotations

import time

from frp_grant_admission.config import parse_config
from frp_grant_admission.grant import MAX_GRANT_BYTES, check_grant
from frp_grant_admission.reasons import Reason
from tests.rfc8032 import TEST_1_THUMBPRINT, TEST_2
from tests.vector_builder import (
    CONFIGURATION,
    EXP,
    NOW,
    PORT,
    claims,
    forged,
    header,
    sign,
)

CONFIG = parse_config(CONFIGURATION)

# 2001-09-09 and 2100-01-01: far enough either side of any wall clock this suite runs
# under that a check reading the system clock could not pass both tests below.
LONG_AGO = 1_000_000_000
FAR_AHEAD = 4_102_444_800


def test_an_admitted_grant_carries_its_verified_claims_and_issuer() -> None:
    result = check_grant(sign(header(), claims()), CONFIG, PORT, NOW)

    assert result.admitted
    assert result.reason is None
    assert result.issuer == "issuer-a"
    assert (result.kid, result.sub, result.jti, result.exp) == (
        TEST_1_THUMBPRINT,
        "host-1",
        "grant-0001",
        EXP,
    )
    assert result.verified


def test_a_second_key_of_an_issuer_is_reported_by_its_own_kid() -> None:
    result = check_grant(sign(header(TEST_2), claims(), key=TEST_2), CONFIG, PORT, NOW)

    assert result.admitted
    assert result.kid == header(TEST_2)["kid"] != TEST_1_THUMBPRINT


def test_a_forged_grant_reports_the_claims_it_carried_as_unverified() -> None:
    result = check_grant(forged(header(), claims()), CONFIG, PORT, NOW)

    assert result.reason is Reason.SIGNATURE_INVALID
    assert result.issuer == "issuer-a"
    assert (result.kid, result.sub, result.jti, result.exp) == (
        TEST_1_THUMBPRINT,
        "host-1",
        "grant-0001",
        EXP,
    )
    assert not result.verified


def test_an_unknown_kid_names_no_issuer_and_is_unverified() -> None:
    result = check_grant(sign(header(kid="not-a-configured-key"), claims()), CONFIG, PORT, NOW)

    assert result.reason is Reason.KEY_UNKNOWN
    assert result.issuer is None
    assert result.kid == "not-a-configured-key"
    assert result.sub == "host-1"
    assert not result.verified


def test_a_malformed_grant_carries_no_claims() -> None:
    for grant in ("not-a-jwt", "a.b.c", "\ud800", sign(header(), claims(note="x" * 5000))):
        result = check_grant(grant, CONFIG, PORT, NOW)

        assert result.reason is Reason.GRANT_MALFORMED
        assert (result.issuer, result.kid, result.sub, result.jti, result.exp) == (None,) * 5
        assert not result.verified


def _grants_around(size: int) -> tuple[str, str]:
    """A valid grant of exactly `size` bytes, and the shortest valid grant over it.

    A filler claim sets the length. An unpadded base64url segment is never one
    character longer than a multiple of four, so some totals no filler reaches; the
    signature segment then carries its two padding characters, which the check
    accepts.
    """
    within: list[str] = []
    for length in range(size):
        token = sign(header(), claims(note="x" * length))
        if len(token) > size:
            exact = [t for t in within if len(t) == size]
            exact += [t + "==" for t in within if len(t) + 2 == size]
            assert exact, f"no filler length makes a grant exactly {size} bytes"
            return exact[0], token
        within.append(token)
    raise AssertionError(f"no filler length makes a grant over {size} bytes")


def test_a_grant_of_exactly_4_kib_is_read_and_one_byte_more_is_not() -> None:
    at_limit, over_limit = _grants_around(MAX_GRANT_BYTES)

    assert MAX_GRANT_BYTES == 4096
    assert len(at_limit.encode()) == MAX_GRANT_BYTES < len(over_limit.encode())
    assert check_grant(at_limit, CONFIG, PORT, NOW).admitted
    refused = check_grant(over_limit, CONFIG, PORT, NOW)
    assert refused.reason is Reason.GRANT_MALFORMED
    assert (refused.issuer, refused.kid, refused.sub, refused.jti, refused.exp) == (None,) * 5
    assert not refused.verified


def test_a_grant_refused_for_its_time_or_port_still_carries_verified_claims() -> None:
    expired = check_grant(sign(header(), claims()), CONFIG, PORT, EXP)
    wrong_port = check_grant(sign(header(), claims()), CONFIG, PORT + 1, NOW)
    port_as_text = check_grant(sign(header(), claims(port=str(PORT))), CONFIG, PORT, NOW)

    for result, reason in (
        (expired, Reason.GRANT_EXPIRED),
        (wrong_port, Reason.PORT_MISMATCH),
        (port_as_text, Reason.PORT_MISMATCH),
    ):
        assert result.reason is reason
        assert result.issuer == "issuer-a"
        assert (result.kid, result.sub, result.jti, result.exp) == (
            TEST_1_THUMBPRINT,
            "host-1",
            "grant-0001",
            EXP,
        )
        assert result.verified


def test_a_claim_of_the_wrong_type_leaves_the_claims_unverified() -> None:
    jti_as_number = check_grant(sign(header(), claims(jti=1)), CONFIG, PORT, NOW)
    exp_as_text = check_grant(sign(header(), claims(exp=str(EXP))), CONFIG, PORT, NOW)

    assert jti_as_number.reason is exp_as_text.reason is Reason.GRANT_MALFORMED
    assert (jti_as_number.issuer, jti_as_number.jti, jti_as_number.exp) == ("issuer-a", 1, EXP)
    assert (exp_as_text.kid, exp_as_text.exp) == (TEST_1_THUMBPRINT, str(EXP))
    assert not jti_as_number.verified
    assert not exp_as_text.verified

def test_expiry_is_judged_on_the_passed_clock_not_the_system_clock() -> None:
    assert LONG_AGO + 60 < time.time()
    grant = sign(header(), claims(iat=LONG_AGO - 60, exp=LONG_AGO + 60))

    assert check_grant(grant, CONFIG, PORT, LONG_AGO).admitted
    assert check_grant(grant, CONFIG, PORT, LONG_AGO + 60).reason is Reason.GRANT_EXPIRED


def test_iat_and_nbf_are_judged_on_the_passed_clock_not_the_system_clock() -> None:
    assert FAR_AHEAD > time.time()
    grant = sign(header(), claims(iat=FAR_AHEAD, nbf=FAR_AHEAD, exp=FAR_AHEAD + 3600))

    assert check_grant(grant, CONFIG, PORT, FAR_AHEAD).admitted
    assert check_grant(grant, CONFIG, PORT, FAR_AHEAD - 1).reason is Reason.GRANT_NOT_YET_VALID


def test_a_grant_signed_with_the_issuers_key_is_bound_to_that_issuers_range() -> None:
    result = check_grant(sign(header(), claims(port=6201)), CONFIG, 6201, NOW)

    assert result.reason is Reason.PORT_OUTSIDE_RANGE
    assert result.issuer == "issuer-a"
