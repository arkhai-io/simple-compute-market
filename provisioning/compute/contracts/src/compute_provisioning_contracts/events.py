"""The wire models of the provisioning service's operator event reads.

An administrator lists the events the service recorded
(``GET /api/v1/events``), reads each consumer destination's delivery state
(``GET /api/v1/events/deliveries``), resumes a parked destination
(``POST /api/v1/events/destinations/{name}/resume``), and drives the delivery
worker (``POST /api/v1/system/event-delivery/{run-cycle,pause,resume}``).

An event is read as its envelope. A reader ignores a field it does not know and
keeps ``extensions`` as given, so an envelope gaining an optional field reads
the same; ``details`` follow the event's ``kind_version``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

#: An attribute's value: routes and filters read attributes as scalar columns.
EventScalar = str | int | float | bool | None


class EventReference(BaseModel):
    """A typed reference to what an event concerns: ``{"type": "lease", "id": …}``."""

    model_config = ConfigDict(extra="ignore")

    type: str
    id: str


class EventSource(BaseModel):
    model_config = ConfigDict(extra="ignore")

    service: str
    instance: str


class OperatorEvent(BaseModel):
    """One recorded event's envelope."""

    model_config = ConfigDict(extra="ignore")

    envelope_version: int
    id: str
    kind: str
    kind_version: int
    data_schema: str
    source: EventSource
    sequence: int
    occurred_at: str
    severity: str
    subject: EventReference
    related: list[EventReference] = Field(default_factory=list)
    correlation_id: str | None = None
    causation_id: str | None = None
    attributes: dict[str, EventScalar] = Field(default_factory=dict)
    summary: str
    details: dict[str, Any] = Field(default_factory=dict)
    extensions: dict[str, Any] = Field(default_factory=dict)


class EventListResponse(BaseModel):
    """A page of events in sequence order; ``next_after`` reads the next page."""

    events: list[OperatorEvent]
    next_after: int | None = None


class EventDeliveryHead(BaseModel):
    """The oldest delivery still pending to a destination."""

    sequence: int
    attempts: int | None = None
    last_error: str | None = None
    next_attempt_at: str | None = None


class EventDestinationStatus(BaseModel):
    consumer: str
    destination: str
    state: str
    state_reason: str | None = None
    added_at_position: int
    consumer_position: int
    pending: int
    delivered: int
    abandoned: int
    head: EventDeliveryHead | None = None


class EventDeliveriesResponse(BaseModel):
    destinations: list[EventDestinationStatus]


class EventDestinationResumeResponse(BaseModel):
    consumer: str
    destination: str
    state: str


class EventDeliveryCycleResponse(BaseModel):
    """What one delivery worker cycle did: each consumer's delivery, then pruning."""

    consumers: dict[str, dict[str, Any]] = Field(default_factory=dict)
    pruned: dict[str, int] = Field(default_factory=dict)


__all__ = [
    "EventDeliveriesResponse",
    "EventDeliveryCycleResponse",
    "EventDeliveryHead",
    "EventDestinationResumeResponse",
    "EventDestinationStatus",
    "EventListResponse",
    "EventReference",
    "EventScalar",
    "EventSource",
    "OperatorEvent",
]
