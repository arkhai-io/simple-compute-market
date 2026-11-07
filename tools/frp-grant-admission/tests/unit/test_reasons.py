from __future__ import annotations

from frp_grant_admission.reasons import Reason

# The published codes. A code never changes meaning, so this list changes only by
# adding one.
CODES = [
    "malformed_request",
    "operation_not_supported",
    "proxy_type_not_allowed",
    "group_not_allowed",
    "port_invalid",
    "grant_missing",
    "grant_malformed",
    "grant_type_unsupported",
    "key_unknown",
    "signature_invalid",
    "claim_missing",
    "audience_mismatch",
    "grant_expired",
    "grant_not_yet_valid",
    "port_mismatch",
    "port_outside_range",
]


def test_the_reason_codes_are_the_published_ones() -> None:
    assert [reason.code for reason in Reason] == CODES


def test_each_reason_has_a_short_text_and_replies_with_code_and_text() -> None:
    for reason in Reason:
        assert reason.text and "\n" not in reason.text and len(reason.text) < 80
        assert reason.reply == f"{reason.code}: {reason.text}"
