"""Reads of the stored events and their delivery state, and the framework-free
service a process binds behind its own administrator authentication.

`EventReader` reads events by kind, severity, subject and related reference, in
sequence order, and each destination's delivery state. `EventService` validates and
performs the reads and the resume of a parked destination, and shapes their answers
as JSON-ready dictionaries; the HTTP binding — paths, authentication, turning
`EventServiceError` into a response — is each process's own.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, sessionmaker

from eventing import schema
from eventing.consumers import ABANDONED, DELIVERED, PENDING, RETIRED, resume_destination
from eventing.envelope import Envelope, Reference, Severity, iso_utc

MAX_LIMIT = 500
INVALID_QUERY_STATUS = 422
UNKNOWN_DESTINATION_STATUS = 404
CONFLICT_STATUS = 409


@dataclass(frozen=True)
class DestinationStatus:
    """One destination of one consumer: its state, and its deliveries by state.

    `head_*` describe the earliest pending delivery, which holds the others back.
    """

    consumer: str
    destination: str
    state: str
    state_reason: str | None
    added_at_position: int
    consumer_position: int
    pending: int
    delivered: int
    abandoned: int
    head_sequence: int | None
    head_attempts: int | None
    head_last_error: str | None
    head_next_attempt_at: datetime | None


class EventReader:
    """Reads one store."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sessions = session_factory

    def events(
        self,
        *,
        kind: str | None = None,
        severity: Severity | None = None,
        subject: Reference | None = None,
        reference: Reference | None = None,
        after: int | None = None,
        limit: int = 100,
    ) -> list[Envelope]:
        """Events matching every filter given, in sequence order, past `after`.

        `reference` matches an event naming it among its related references.
        """
        e = schema.events
        query = select(e.c.envelope).order_by(e.c.sequence).limit(limit)
        if kind is not None:
            query = query.where(e.c.kind == kind)
        if severity is not None:
            query = query.where(e.c.severity_rank == severity.rank)
        if subject is not None:
            query = query.where(e.c.subject_type == subject.type, e.c.subject_id == subject.id)
        if reference is not None:
            r = schema.related
            query = query.where(
                e.c.sequence.in_(
                    select(r.c.event_sequence).where(r.c.type == reference.type,
                                                     r.c.id == reference.id)
                )
            )
        if after is not None:
            query = query.where(e.c.sequence > after)
        with self._sessions() as session:
            stored: list[str] = list(session.execute(query).scalars())
        return [Envelope.from_json(raw) for raw in stored]

    def destinations(self) -> list[DestinationStatus]:
        """Every destination of every consumer, by consumer and name."""
        d, ds, c = schema.deliveries, schema.destinations, schema.consumers
        counts = (
            select(
                d.c.consumer,
                d.c.destination,
                func.sum(case((d.c.state == PENDING, 1), else_=0)).label("pending"),
                func.sum(case((d.c.state == DELIVERED, 1), else_=0)).label("delivered"),
                func.sum(case((d.c.state == ABANDONED, 1), else_=0)).label("abandoned"),
                func.min(case((d.c.state == PENDING, d.c.event_sequence))).label("head"),
            )
            .group_by(d.c.consumer, d.c.destination)
            .subquery()
        )
        query = (
            select(ds, c.c.position, counts.c.pending, counts.c.delivered,
                   counts.c.abandoned, counts.c.head,
                   d.c.attempts, d.c.last_error, d.c.next_attempt_at)
            .join(c, c.c.name == ds.c.consumer)
            .outerjoin(counts, (counts.c.consumer == ds.c.consumer)
                       & (counts.c.destination == ds.c.name))
            .outerjoin(d, (d.c.consumer == ds.c.consumer) & (d.c.destination == ds.c.name)
                       & (d.c.event_sequence == counts.c.head))
            .order_by(ds.c.consumer, ds.c.name)
        )
        with self._sessions() as session:
            return [
                DestinationStatus(
                    consumer=row.consumer,
                    destination=row.name,
                    state=row.state,
                    state_reason=row.state_reason,
                    added_at_position=row.added_at_position,
                    consumer_position=row.position,
                    pending=int(row.pending or 0),
                    delivered=int(row.delivered or 0),
                    abandoned=int(row.abandoned or 0),
                    head_sequence=row.head,
                    head_attempts=row.attempts,
                    head_last_error=row.last_error,
                    head_next_attempt_at=(schema.from_stored(row.next_attempt_at)
                                          if row.next_attempt_at is not None else None),
                )
                for row in session.execute(query)
            ]


class EventServiceError(Exception):
    """A refused request: the HTTP status, a stable code and a detail."""

    def __init__(self, status_code: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.detail = detail


class EventService:
    """The event reads, the delivery status, and resuming a destination."""

    def __init__(self, session_factory: sessionmaker[Session], *, clock: Callable[[], datetime]) -> None:
        self._sessions = session_factory
        self._reader = EventReader(session_factory)
        self._clock = clock

    def list_events(
        self,
        *,
        kind: str | None = None,
        severity: str | None = None,
        subject: str | None = None,
        reference: str | None = None,
        after: int | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """`{"events": [<envelope>...], "next_after": <sequence or null>}`.

        `subject` and `reference` are `<type>:<id>`. `next_after` is the last
        event's sequence when the page is full, for reading the next page.
        """
        if not 1 <= limit <= MAX_LIMIT:
            raise EventServiceError(INVALID_QUERY_STATUS, "invalid_query",
                                    f"limit must be from 1 to {MAX_LIMIT}")
        try:
            wanted = Severity(severity) if severity is not None else None
        except ValueError:
            raise EventServiceError(
                INVALID_QUERY_STATUS, "invalid_query",
                f"severity must be one of {', '.join(s.value for s in Severity)}") from None
        events = self._reader.events(
            kind=kind, severity=wanted, subject=_reference("subject", subject),
            reference=_reference("reference", reference), after=after, limit=limit,
        )
        return {
            "events": [event.model_dump(mode="json") for event in events],
            "next_after": events[-1].sequence if len(events) == limit else None,
        }

    def deliveries(self) -> dict[str, Any]:
        """`{"destinations": [...]}`: every consumer's destinations and their state."""
        return {
            "destinations": [
                {
                    "consumer": status.consumer,
                    "destination": status.destination,
                    "state": status.state,
                    "state_reason": status.state_reason,
                    "added_at_position": status.added_at_position,
                    "consumer_position": status.consumer_position,
                    "pending": status.pending,
                    "delivered": status.delivered,
                    "abandoned": status.abandoned,
                    "head": None if status.head_sequence is None else {
                        "sequence": status.head_sequence,
                        "attempts": status.head_attempts,
                        "last_error": status.head_last_error,
                        "next_attempt_at": (iso_utc(status.head_next_attempt_at)
                                            if status.head_next_attempt_at else None),
                    },
                }
                for status in self._reader.destinations()
            ]
        }

    def resume(self, destination: str, *, consumer: str | None = None) -> dict[str, Any]:
        """Resume the parked destination named `destination` and answer its state.

        Without `consumer`, the name must be one consumer's alone. An active
        destination is answered as it is; a retired one, which no consumer still
        has, is refused.
        """
        matches = [
            status for status in self._reader.destinations()
            if status.destination == destination
            and (consumer is None or status.consumer == consumer)
        ]
        if not matches:
            raise EventServiceError(UNKNOWN_DESTINATION_STATUS, "unknown_destination",
                                    f"no destination {destination} is registered")
        if len(matches) > 1:
            raise EventServiceError(
                CONFLICT_STATUS, "ambiguous_destination",
                f"destination {destination} belongs to consumers "
                f"{', '.join(m.consumer for m in matches)}; name the consumer")
        match = matches[0]
        if match.state == RETIRED:
            raise EventServiceError(CONFLICT_STATUS, "destination_retired",
                                    f"destination {destination} is retired")
        with self._sessions.begin() as session:
            resume_destination(session, match.consumer, destination, self._clock())
        return {"consumer": match.consumer, "destination": destination, "state": "active"}


def _reference(name: str, value: str | None) -> Reference | None:
    if value is None:
        return None
    type_, separator, id_ = value.partition(":")
    if not separator or not type_ or not id_:
        raise EventServiceError(INVALID_QUERY_STATUS, "invalid_query",
                                f"{name} must be <type>:<id>")
    return Reference(type=type_, id=id_)
