"""Inbound HTTP routes for agent-to-agent messages.

Exposes six POST endpoints covering every inter-agent message that used
to ride over A2A:

    POST /negotiation/offer      — seller broadcasting a new order
    POST /negotiation/counter    — either side counter-proposing a price
    POST /negotiation/accept     — buyer committing to a deal (with escrow)
    POST /negotiation/exit       — either side abandoning the thread
    POST /settlement/fulfilled   — seller delivered; buyer should record it
    POST /settlement/failed      — seller's provisioning broke; reopen orders
    POST /settlement/arbitrated  — arbitration decisions posted

Each handler:
  1. Parses + validates the {schema_id, payload, ...} envelope.
  2. Hydrates the payload into the right DomainEvent subclass.
  3. Drives it through the reactive pipeline via root_agent._process_event_with_pipeline().
  4. Returns a small ack body to the caller.

Authentication is deliberately omitted for this first pass — the legacy
A2A channel was also unauthenticated between agents. Because escrow
release is gated on-chain by RecipientArbiter, a hostile message can't
move funds; it can only confuse local state. A signed header scheme
(verifier fetches sender's /.well-known/agent-wallet.json) is a
follow-up.
"""

from __future__ import annotations

import logging
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from core.agent.app.schema.messages import (
    SCHEMA_COMPUTE_NEGOTIATION_V1,
    SCHEMA_COMPUTE_SETTLEMENT_V1,
    EnvelopeError,
    parse_envelope,
)

logger = logging.getLogger(__name__)


def _error(status: int, message: str, **extra: Any) -> JSONResponse:
    body = {"error": message}
    body.update(extra)
    return JSONResponse(body, status_code=status)


async def _ingest(request: Request, *, expected_schema: str, expected_event_type: str) -> JSONResponse:
    """Shared inbound path.

    `expected_event_type` guards against a correctly-schema'd message
    being posted to the wrong route (e.g. an accept_offer body at
    /negotiation/exit). Receivers dispatch by HTTP path, so silent
    misroutes would be subtle; this check surfaces them as 400 instead.
    """
    # Imports deferred so importing this module doesn't bootstrap the
    # full TraderAgent (root_agent) before the agent module itself is
    # ready — unit tests import parse_envelope without spinning up the
    # whole pipeline.
    from core.agent.app.agent import root_agent, _parse_domain_event

    try:
        body = await request.json()
    except Exception as exc:
        return _error(400, f"Invalid JSON: {exc}")

    try:
        envelope = parse_envelope(body, expected_schema=expected_schema)
    except EnvelopeError as exc:
        return _error(exc.status_code, str(exc))

    payload = dict(envelope.payload)

    # Make sure the payload declares the event_type we expect. If
    # unspecified, inject it — some outbound builders don't bother
    # repeating event_type inside payload since the path already implies it.
    declared = payload.get("event_type")
    if declared is None:
        payload["event_type"] = expected_event_type
    elif declared != expected_event_type:
        return _error(
            400,
            f"event_type {declared!r} does not match route expectation "
            f"{expected_event_type!r}",
        )

    try:
        domain_event = _parse_domain_event(payload)
    except Exception as exc:
        logger.warning("[MSG] Failed to parse domain event from %s: %s", request.url.path, exc)
        return _error(400, f"Invalid payload for schema {expected_schema!r}: {exc}")

    try:
        outcome_message = await root_agent._process_event_with_pipeline(
            domain_event, ctx=None,
        )
    except Exception as exc:
        logger.error("[MSG] Pipeline error for %s: %s", request.url.path, exc, exc_info=True)
        return _error(500, f"Pipeline error: {exc}")

    return JSONResponse({
        "status": "received",
        "event_id": domain_event.event_id,
        "schema_id": envelope.schema_id,
        "message": outcome_message or "processed",
    })


# ---------------------------------------------------------------------------
# Negotiation routes (schema: arkhai.compute_negotiation.v1)
# ---------------------------------------------------------------------------


async def _offer(request: Request) -> JSONResponse:
    return await _ingest(
        request,
        expected_schema=SCHEMA_COMPUTE_NEGOTIATION_V1,
        expected_event_type="make_offer",
    )


async def _counter(request: Request) -> JSONResponse:
    return await _ingest(
        request,
        expected_schema=SCHEMA_COMPUTE_NEGOTIATION_V1,
        expected_event_type="negotiation",
    )


async def _accept(request: Request) -> JSONResponse:
    return await _ingest(
        request,
        expected_schema=SCHEMA_COMPUTE_NEGOTIATION_V1,
        expected_event_type="accept_offer",
    )


async def _exit(request: Request) -> JSONResponse:
    # Exit is also a NegotiationEvent under the hood (message_type=exit).
    return await _ingest(
        request,
        expected_schema=SCHEMA_COMPUTE_NEGOTIATION_V1,
        expected_event_type="negotiation",
    )


# ---------------------------------------------------------------------------
# Settlement routes (schema: arkhai.compute_settlement.v1)
# ---------------------------------------------------------------------------


async def _fulfilled(request: Request) -> JSONResponse:
    return await _ingest(
        request,
        expected_schema=SCHEMA_COMPUTE_SETTLEMENT_V1,
        expected_event_type="receive_compute_obligation_fulfillment",
    )


async def _failed(request: Request) -> JSONResponse:
    return await _ingest(
        request,
        expected_schema=SCHEMA_COMPUTE_SETTLEMENT_V1,
        expected_event_type="fulfillment_failed",
    )


async def _arbitrated(request: Request) -> JSONResponse:
    return await _ingest(
        request,
        expected_schema=SCHEMA_COMPUTE_SETTLEMENT_V1,
        expected_event_type="arbitration_complete",
    )


NEGOTIATION_ROUTES = [
    Route("/negotiation/offer", _offer, methods=["POST"]),
    Route("/negotiation/counter", _counter, methods=["POST"]),
    Route("/negotiation/accept", _accept, methods=["POST"]),
    Route("/negotiation/exit", _exit, methods=["POST"]),
]

SETTLEMENT_ROUTES = [
    Route("/settlement/fulfilled", _fulfilled, methods=["POST"]),
    Route("/settlement/failed", _failed, methods=["POST"]),
    Route("/settlement/arbitrated", _arbitrated, methods=["POST"]),
]


def all_message_routes() -> list[Route]:
    """Return every inbound-message route for wiring into the Starlette app."""
    return NEGOTIATION_ROUTES + SETTLEMENT_ROUTES


# Outbound helper — keeps the schema+path pairing in one place so
# action_executor callsites don't hand-roll the mapping each time.
#
# (event_type → (schema_id, path)) — the canonical way for senders to
# pick the right endpoint for the event they're pushing.
OUTBOUND_ROUTING: dict[str, tuple[str, str]] = {
    "make_offer":                              (SCHEMA_COMPUTE_NEGOTIATION_V1, "/negotiation/offer"),
    "accept_offer":                            (SCHEMA_COMPUTE_NEGOTIATION_V1, "/negotiation/accept"),
    # NegotiationEvent covers both counter and exit; callers disambiguate
    # via message_type in the payload and pick the route accordingly.
    "negotiation.counter":                     (SCHEMA_COMPUTE_NEGOTIATION_V1, "/negotiation/counter"),
    "negotiation.exit":                        (SCHEMA_COMPUTE_NEGOTIATION_V1, "/negotiation/exit"),
    "receive_compute_obligation_fulfillment":  (SCHEMA_COMPUTE_SETTLEMENT_V1, "/settlement/fulfilled"),
    "fulfillment_failed":                      (SCHEMA_COMPUTE_SETTLEMENT_V1, "/settlement/failed"),
    "arbitration_complete":                    (SCHEMA_COMPUTE_SETTLEMENT_V1, "/settlement/arbitrated"),
}
