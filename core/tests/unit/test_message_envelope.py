"""Unit tests for the agent-to-agent message envelope.

Covers `parse_envelope` (inbound validation) and `build_envelope`
(outbound construction). The envelope is the thin layer between HTTP
and the domain event — most of the real validation lives in the domain
event classes themselves, so these tests focus on what the envelope
alone is responsible for: schema_id discipline and shape.
"""

from __future__ import annotations

import pytest

from core.agent.app.schema.messages import (
    SCHEMA_COMPUTE_NEGOTIATION_V1,
    SCHEMA_COMPUTE_SETTLEMENT_V1,
    SUPPORTED_SCHEMAS,
    EnvelopeError,
    MessageEnvelope,
    build_envelope,
    parse_envelope,
)


# ---------------------------------------------------------------------------
# parse_envelope
# ---------------------------------------------------------------------------


def test_parse_happy_path():
    body = {
        "schema_id": SCHEMA_COMPUTE_NEGOTIATION_V1,
        "message_id": "msg_abc",
        "sender": "http://alice:8000/",
        "payload": {"event_type": "make_offer", "offer": {"order_id": "o1"}},
    }
    env = parse_envelope(body, expected_schema=SCHEMA_COMPUTE_NEGOTIATION_V1)
    assert isinstance(env, MessageEnvelope)
    assert env.schema_id == SCHEMA_COMPUTE_NEGOTIATION_V1
    assert env.message_id == "msg_abc"
    assert env.payload["event_type"] == "make_offer"


def test_parse_rejects_non_object_body():
    with pytest.raises(EnvelopeError, match="must be a JSON object"):
        parse_envelope(["not", "a", "dict"], expected_schema=SCHEMA_COMPUTE_NEGOTIATION_V1)


def test_parse_missing_schema_id_is_400():
    with pytest.raises(EnvelopeError) as exc:
        parse_envelope({"payload": {}}, expected_schema=SCHEMA_COMPUTE_NEGOTIATION_V1)
    assert exc.value.status_code == 400
    assert "schema_id" in str(exc.value)


def test_parse_unknown_schema_is_415():
    with pytest.raises(EnvelopeError) as exc:
        parse_envelope(
            {"schema_id": "arkhai.unknown.v9000", "payload": {"event_type": "make_offer"}},
            expected_schema=SCHEMA_COMPUTE_NEGOTIATION_V1,
        )
    assert exc.value.status_code == 415


def test_parse_wrong_schema_for_route_is_400():
    # Sent to a negotiation route with a settlement schema → 400 (route mismatch)
    with pytest.raises(EnvelopeError) as exc:
        parse_envelope(
            {"schema_id": SCHEMA_COMPUTE_SETTLEMENT_V1,
             "payload": {"event_type": "receive_compute_obligation_fulfillment"}},
            expected_schema=SCHEMA_COMPUTE_NEGOTIATION_V1,
        )
    assert exc.value.status_code == 400
    assert "Route expects" in str(exc.value)


def test_parse_rejects_non_dict_payload():
    with pytest.raises(EnvelopeError, match="payload"):
        parse_envelope(
            {"schema_id": SCHEMA_COMPUTE_NEGOTIATION_V1, "payload": "not a dict"},
            expected_schema=SCHEMA_COMPUTE_NEGOTIATION_V1,
        )


def test_parse_rejects_event_type_not_in_schema():
    # make_offer belongs to the negotiation schema; receive_fulfillment doesn't.
    with pytest.raises(EnvelopeError) as exc:
        parse_envelope(
            {
                "schema_id": SCHEMA_COMPUTE_NEGOTIATION_V1,
                "payload": {"event_type": "receive_compute_obligation_fulfillment"},
            },
            expected_schema=SCHEMA_COMPUTE_NEGOTIATION_V1,
        )
    assert exc.value.status_code == 400
    assert "not allowed" in str(exc.value)


def test_parse_omitting_event_type_is_allowed():
    # Receivers will inject event_type from the route path if omitted.
    env = parse_envelope(
        {"schema_id": SCHEMA_COMPUTE_NEGOTIATION_V1, "payload": {"offer": {}}},
        expected_schema=SCHEMA_COMPUTE_NEGOTIATION_V1,
    )
    assert "event_type" not in env.payload


@pytest.mark.parametrize("schema", sorted(SUPPORTED_SCHEMAS))
def test_supported_schemas_parse(schema):
    # Each advertised schema must round-trip through parse_envelope.
    body = {"schema_id": schema, "payload": {}}
    env = parse_envelope(body, expected_schema=schema)
    assert env.schema_id == schema


# ---------------------------------------------------------------------------
# build_envelope
# ---------------------------------------------------------------------------


def test_build_produces_complete_dict():
    env = build_envelope(
        schema_id=SCHEMA_COMPUTE_NEGOTIATION_V1,
        payload={"event_type": "make_offer"},
        sender="http://seller:8001/",
    )
    assert env["schema_id"] == SCHEMA_COMPUTE_NEGOTIATION_V1
    assert env["sender"] == "http://seller:8001/"
    assert env["payload"] == {"event_type": "make_offer"}
    assert env["message_id"].startswith("msg_")


def test_build_respects_explicit_message_id():
    env = build_envelope(
        schema_id=SCHEMA_COMPUTE_NEGOTIATION_V1,
        payload={},
        message_id="my-custom-id",
    )
    assert env["message_id"] == "my-custom-id"


def test_build_rejects_unknown_schema():
    with pytest.raises(ValueError, match="Unknown schema_id"):
        build_envelope(schema_id="arkhai.phantom.v1", payload={})


def test_build_and_parse_roundtrip():
    env_dict = build_envelope(
        schema_id=SCHEMA_COMPUTE_SETTLEMENT_V1,
        payload={"event_type": "fulfillment_failed", "escrow_uid": "0xabc", "reason": "no vm"},
        sender="http://seller:8001/",
    )
    parsed = parse_envelope(env_dict, expected_schema=SCHEMA_COMPUTE_SETTLEMENT_V1)
    assert parsed.payload["escrow_uid"] == "0xabc"
    assert parsed.sender == "http://seller:8001/"
