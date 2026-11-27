from __future__ import annotations

from market_identity import ExactRetry, RequestRecord, ResponseRecord
from market_identity import exact_retry, wire
from market_identity.wire import RecordField, RefusalCode


def test_the_wire_module_exports_exactly_the_profiles_names() -> None:
    assert set(wire.__all__) == {
        "REQUEST_PROFILE",
        "RESPONSE_PROFILE",
        "SIGNATURE_LABEL",
        "MARKET_ROLE",
        "MARKET_OPERATION",
        "MARKET_RESOURCE",
        "MARKET_AUDIENCE",
        "MARKET_REQUEST_ID",
        "MARKET_REQUEST_ORIGIN",
        "CONTENT_DIGEST",
        "SIGNATURE_INPUT",
        "SIGNATURE",
        "RecordField",
        "RefusalCode",
    }


def test_the_covered_fields_and_tags_are_the_profiles() -> None:
    assert (wire.REQUEST_PROFILE, wire.RESPONSE_PROFILE) == (
        "arkhai.market-request-signature.v3",
        "arkhai.market-response-signature.v3",
    )
    assert {
        wire.MARKET_ROLE,
        wire.MARKET_OPERATION,
        wire.MARKET_RESOURCE,
        wire.MARKET_AUDIENCE,
        wire.MARKET_REQUEST_ID,
        wire.MARKET_REQUEST_ORIGIN,
        wire.CONTENT_DIGEST,
    } == {
        "Market-Role",
        "Market-Operation",
        "Market-Resource",
        "Market-Audience",
        "Market-Request-ID",
        "Market-Request-Origin",
        "Content-Digest",
    }


def test_the_refusal_codes_are_exactly_the_profiles() -> None:
    assert {code.value for code in RefusalCode} == {
        "operation_not_served",
        "operation_mismatch",
        "audience_mismatch",
        "unsupported_protocol",
        "exact_retry_expired",
        "exact_retry_outcome_unknown",
        "admission_unavailable",
    }


def test_the_record_field_names_are_exactly_the_records() -> None:
    assert [field.value for field in RecordField] == [
        "protocol",
        "principal",
        "role",
        "method",
        "operation",
        "resource",
        "request_id",
        "timestamp",
        "origin",
        "audience",
        "proof",
        "status",
    ]
    assert set(RequestRecord.model_fields) == {field.value for field in RecordField} - {"status"}
    assert set(ResponseRecord.model_fields) == {field.value for field in RecordField} - {
        "role",
        "origin",
        "audience",
    }


def test_exact_retry_declares_rerun_or_recorded_and_nothing_else() -> None:
    assert ExactRetry is exact_retry.ExactRetry
    assert [(member.name, member.value) for member in ExactRetry] == [
        ("RERUN", "rerun"),
        ("RECORDED", "recorded"),
    ]
    assert ExactRetry("recorded") is ExactRetry.RECORDED
