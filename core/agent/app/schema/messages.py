"""Agent-to-agent message envelope.

Every inter-agent message — negotiation and settlement alike — is wrapped
in a small envelope so the receiver can dispatch it without parsing the
payload first. The envelope is transport-agnostic but today rides over
plain HTTP POST JSON.

    {
      "schema_id": "arkhai.compute_negotiation.v1",
      "message_id": "msg_<uuid>",
      "sender": "http://seller.example/",        # agent URL or ERC-8004 ID
      "payload": { ...event-specific fields... }
    }

The `schema_id` pins the payload shape. Receivers reject unknown schemas
with HTTP 415 so agents running different versions don't silently drop
messages. A freeform-LLM haggling mode, for example, would ship as a new
schema (`arkhai.freeform_negotiation.v1`) whose payload is a plain text
turn — the transport stays identical.

Today only two schemas exist:

  arkhai.compute_negotiation.v1
    make_offer, counter_offer (NegotiationEvent), accept_offer, exit
  arkhai.compute_settlement.v1
    receive_compute_obligation_fulfillment, fulfillment_failed,
    arbitration_complete
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field, field_validator


SCHEMA_COMPUTE_NEGOTIATION_V1 = "arkhai.compute_negotiation.v1"
SCHEMA_COMPUTE_SETTLEMENT_V1 = "arkhai.compute_settlement.v1"


# Which event_type values each schema may carry. Receivers reject
# mismatches so a NegotiationEvent sent to /settlement/fulfilled is a
# clear 400, not a silent misroute.
SCHEMA_EVENT_TYPES: dict[str, set[str]] = {
    SCHEMA_COMPUTE_NEGOTIATION_V1: {
        "make_offer",
        "accept_offer",
        "negotiation",  # NegotiationEvent covers counter + exit
    },
    SCHEMA_COMPUTE_SETTLEMENT_V1: {
        "receive_compute_obligation_fulfillment",
        "fulfillment_failed",
        "arbitration_complete",
    },
}

SUPPORTED_SCHEMAS = frozenset(SCHEMA_EVENT_TYPES.keys())


class MessageEnvelope(BaseModel):
    """Wire format for agent-to-agent messages.

    `payload` is deliberately free-form (dict[str, Any]) because the
    domain event classes (MakeOfferEvent, AcceptOfferEvent, etc.) already
    own their validation. We only enforce the envelope's own invariants
    here: schema_id is known, payload is a dict.
    """

    schema_id: str = Field(description="Version tag pinning payload shape")
    message_id: str = Field(
        default_factory=lambda: f"msg_{uuid.uuid4()}",
        description="Unique per-message ID; lets receivers dedupe retries.",
    )
    sender: str = Field(
        default="",
        description="Sender's agent URL or ERC-8004 canonical ID. Informational.",
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Event-specific fields; shape determined by schema_id.",
    )

    @field_validator("schema_id")
    @classmethod
    def _known_schema(cls, v: str) -> str:
        if v not in SUPPORTED_SCHEMAS:
            raise ValueError(
                f"Unknown schema_id {v!r}; supported: {sorted(SUPPORTED_SCHEMAS)}"
            )
        return v


class EnvelopeError(Exception):
    """Raised when an inbound envelope fails validation.

    `status_code` lets the route handler pick 4xx flavor without each
    handler needing its own mapping table.
    """

    def __init__(self, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def parse_envelope(body: Any, *, expected_schema: str) -> MessageEnvelope:
    """Validate a raw JSON body into a MessageEnvelope.

    Raises EnvelopeError on any mismatch. Callers catch and translate to
    JSONResponse(status_code=exc.status_code).
    """
    if not isinstance(body, dict):
        raise EnvelopeError("Request body must be a JSON object")

    schema_id = body.get("schema_id")
    if not isinstance(schema_id, str) or not schema_id.strip():
        raise EnvelopeError("Envelope missing required 'schema_id'")
    if schema_id not in SUPPORTED_SCHEMAS:
        raise EnvelopeError(
            f"Unsupported schema_id {schema_id!r}; supported: {sorted(SUPPORTED_SCHEMAS)}",
            status_code=415,
        )
    if schema_id != expected_schema:
        raise EnvelopeError(
            f"Route expects schema {expected_schema!r}, got {schema_id!r}",
            status_code=400,
        )

    payload = body.get("payload")
    if not isinstance(payload, dict):
        raise EnvelopeError("Envelope 'payload' must be a JSON object")

    # event_type is how _parse_domain_event picks the concrete event class.
    # We verify it's consistent with the declared schema so a typo in the
    # payload doesn't get dispatched to the wrong handler path.
    event_type = payload.get("event_type")
    allowed_types = SCHEMA_EVENT_TYPES[schema_id]
    if event_type is not None and event_type not in allowed_types:
        raise EnvelopeError(
            f"event_type {event_type!r} not allowed under schema {schema_id!r}; "
            f"expected one of {sorted(allowed_types)}",
            status_code=400,
        )

    try:
        return MessageEnvelope(**body)
    except Exception as exc:
        raise EnvelopeError(f"Malformed envelope: {exc}") from exc


def build_envelope(
    *,
    schema_id: str,
    payload: dict[str, Any],
    sender: str = "",
    message_id: str | None = None,
) -> dict[str, Any]:
    """Construct a wire-ready envelope dict.

    Used by the outbound HTTP dispatcher. Returns a plain dict (not a
    Pydantic model) because callers hand the result straight to
    `json.dumps` or aiohttp's `json=` parameter.
    """
    if schema_id not in SUPPORTED_SCHEMAS:
        raise ValueError(
            f"Unknown schema_id {schema_id!r}; supported: {sorted(SUPPORTED_SCHEMAS)}"
        )
    return {
        "schema_id": schema_id,
        "message_id": message_id or f"msg_{uuid.uuid4()}",
        "sender": sender,
        "payload": payload,
    }
