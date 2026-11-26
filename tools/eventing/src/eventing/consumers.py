"""Consumers: each event delivered at least once to each of a consumer's destinations.

A named consumer holds a durable position — the highest sequence it has read — and,
for each of its destinations, a state (`active`, `parked` or `retired`) and one
delivery row per event selected for it: `pending`, `delivered` or `abandoned`, with
its attempt count and last error. A cycle does three things, each in its own
transactions:

1. **Registers** the consumer and its configured destinations. A new consumer, and a
   destination added to an existing one, start at the current position: neither
   receives an event recorded before it. A stored destination absent from the
   configuration is retired: each delivery still pending to it is abandoned to the finally sink, and
   nothing more is selected for it.
2. **Reads** every event past the position, in sequence order, writes a pending
   delivery for each destination its selection names that is not retired, and
   advances the position. The recorder's sequence allocation means no event can later
   commit below the position.
3. **Delivers**, destination by destination, each pending delivery in sequence order,
   outside any transaction, then records the outcome. A delivery that fails is retried
   after a backoff, and the destination's later events wait behind it; another
   destination is not held up. A delivery whose outcome was never recorded — the
   process stopped after delivering — is delivered again under the same event `id`,
   so a destination sees each event at least once.

A destination parks itself by raising `ParkDestination`, or is parked explicitly;
nothing is delivered to it until it is resumed, and resuming delivers, in order, the
pending events still retained. A consumer's retry policy may bound a delivery's
retries by a maximum age: a delivery that fails once older than that is abandoned,
keeping its last error, and the event is handed to the finally sink.

Retries are scheduled, and a delivery's age measured, in the time of the world the
consumer's clock reads, not on the monotonic clock: the schedule is stored and
outlives the process. Where that time is held, a retry comes due only when it is
moved forward.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

from sqlalchemy import ColumnElement, CursorResult, and_, func, insert, select, update
from sqlalchemy.orm import Session, sessionmaker

from eventing import schema
from eventing.envelope import Envelope

ACTIVE = "active"
PARKED = "parked"
RETIRED = "retired"

PENDING = "pending"
DELIVERED = "delivered"
ABANDONED = "abandoned"

RETIRED_ERROR = "destination retired: not configured"


class ParkDestination(Exception):
    """Raised by a destination that must receive nothing more until it is resumed —
    a receiver answering that it does not support the delivery, say. The message is
    the reason, kept as the delivery's last error and the destination's state reason."""


class Destination(Protocol):
    """Where a consumer delivers. `deliver` returns once the event is delivered, and
    raises to fail the attempt, or `ParkDestination` to park the destination."""

    def deliver(self, envelope: Envelope) -> None: ...


class FinallySink(Protocol):
    """Where an abandoned delivery's event goes."""

    def abandoned(
        self, *, consumer: str, destination: str, envelope: Envelope, last_error: str | None
    ) -> None: ...


class LogFinallySink:
    """The default finally sink: the event and its last error, logged as a warning."""

    def __init__(self, log: logging.Logger | None = None) -> None:
        self._log = log or logging.getLogger("eventing.finally")

    def abandoned(
        self, *, consumer: str, destination: str, envelope: Envelope, last_error: str | None
    ) -> None:
        self._log.warning(
            "delivery abandoned: consumer=%s destination=%s event=%s last_error=%s envelope=%s",
            consumer, destination, envelope.id, last_error, envelope.to_json(),
        )


@dataclass(frozen=True)
class RetryPolicy:
    """How a consumer retries a failed delivery: a backoff doubling from `initial`
    to at most `maximum`, and an optional `max_age` past which a failing delivery is
    abandoned. With no `max_age`, a delivery is retried without limit."""

    initial: timedelta = timedelta(seconds=10)
    maximum: timedelta = timedelta(hours=1)
    max_age: timedelta | None = None

    def delay(self, attempts: int) -> timedelta:
        """The wait before the attempt after `attempts` failed ones."""
        delay: timedelta = min(self.initial * (2 ** max(attempts - 1, 0)), self.maximum)
        return delay


@dataclass
class CycleReport:
    """What one consumer cycle did."""

    read: int = 0
    selected: int = 0
    delivered: int = 0
    failed: int = 0
    parked: list[str] = field(default_factory=list)
    abandoned: int = 0
    retired: list[str] = field(default_factory=list)


def _all(destinations: Collection[str]) -> Callable[[Envelope], Collection[str]]:
    return lambda envelope: destinations


class Consumer:
    """One named consumer over one store.

    `select` names the destinations an event goes to; by default, every configured
    destination. `clock` reads the time of the world as an aware datetime, against
    which retries are scheduled and a delivery's age is measured.
    """

    def __init__(
        self,
        name: str,
        *,
        session_factory: sessionmaker[Session],
        destinations: Mapping[str, Destination],
        clock: Callable[[], datetime],
        retry: RetryPolicy | None = None,
        select: Callable[[Envelope], Collection[str]] | None = None,
        finally_sink: FinallySink | None = None,
        batch_size: int = 100,
    ) -> None:
        self.name = name
        self._sessions = session_factory
        self._destinations = dict(destinations)
        self._clock = clock
        self._retry = retry or RetryPolicy()
        self._select = select or _all(tuple(self._destinations))
        self._finally = finally_sink or LogFinallySink()
        self._batch_size = batch_size

    def run_cycle(self) -> CycleReport:
        """Register, read past the position, and deliver what is due."""
        report = CycleReport()
        self.register(report)
        self.read(report)
        self.deliver(report)
        return report

    def register(self, report: CycleReport | None = None) -> None:
        """Record the consumer and its configured destinations, retiring each stored
        destination absent from the configuration."""
        report = report if report is not None else CycleReport()
        now = schema.to_stored(self._clock())
        with self._sessions.begin() as session:
            position = self._position(session, now)
            stored: dict[str, str] = {
                row.name: row.state
                for row in session.execute(
                    select(schema.destinations.c.name, schema.destinations.c.state).where(
                        schema.destinations.c.consumer == self.name
                    )
                )
            }
            for name in sorted(self._destinations):
                if name not in stored:
                    session.execute(
                        insert(schema.destinations).values(
                            consumer=self.name, name=name, state=ACTIVE,
                            added_at_position=position, added_at=now, state_changed_at=now,
                        )
                    )
                elif stored[name] == RETIRED:
                    # Configured again after retirement: a new destination, starting
                    # at the current position.
                    session.execute(
                        update(schema.destinations)
                        .where(self._destination(name))
                        .values(state=ACTIVE, added_at_position=position,
                                added_at=now, state_changed_at=now, state_reason=None)
                    )
            for name in sorted(set(stored) - set(self._destinations)):
                if stored[name] != RETIRED:
                    report.abandoned += self._retire(session, name, now)
                    report.retired.append(name)

    def read(self, report: CycleReport | None = None) -> None:
        """Write a pending delivery of each event past the position for each
        destination selected for it, advancing the position past every event read."""
        report = report if report is not None else CycleReport()
        while True:
            with self._sessions.begin() as session:
                now = schema.to_stored(self._clock())
                position = self._position(session, now)
                receiving: set[str] = set(
                    session.execute(
                        select(schema.destinations.c.name).where(
                            schema.destinations.c.consumer == self.name,
                            schema.destinations.c.state != RETIRED,
                        )
                    ).scalars()
                )
                rows = session.execute(
                    select(schema.events.c.sequence, schema.events.c.envelope)
                    .where(schema.events.c.sequence > position)
                    .order_by(schema.events.c.sequence)
                    .limit(self._batch_size)
                ).all()
                if not rows:
                    return
                for sequence, raw in rows:
                    chosen = receiving & set(self._select(Envelope.from_json(str(raw))))
                    for destination in sorted(chosen):
                        session.execute(
                            insert(schema.deliveries).values(
                                consumer=self.name, destination=destination,
                                event_sequence=sequence, state=PENDING, attempts=0,
                                created_at=now, next_attempt_at=now,
                            )
                        )
                    report.selected += len(chosen)
                report.read += len(rows)
                session.execute(
                    update(schema.consumers)
                    .where(schema.consumers.c.name == self.name)
                    .values(position=rows[-1][0])
                )

    def deliver(self, report: CycleReport | None = None) -> None:
        """Attempt each active destination's due deliveries, in sequence order."""
        report = report if report is not None else CycleReport()
        for name in sorted(self._destinations):
            self._deliver_to(name, report)

    def park(self, destination: str, reason: str) -> None:
        """Park `destination`: nothing is delivered to it until it is resumed."""
        with self._sessions.begin() as session:
            park_destination(session, self.name, destination, reason, self._clock())

    def resume(self, destination: str) -> None:
        """Resume `destination`, delivering, in order, its pending events still retained."""
        with self._sessions.begin() as session:
            resume_destination(session, self.name, destination, self._clock())

    def _deliver_to(self, name: str, report: CycleReport) -> None:
        destination = self._destinations[name]
        while True:
            now = self._clock()
            with self._sessions.begin() as session:
                state: str = session.execute(
                    select(schema.destinations.c.state).where(self._destination(name))
                ).scalar_one()
                if state != ACTIVE:
                    return
                due = session.execute(
                    select(
                        schema.deliveries.c.event_sequence,
                        schema.deliveries.c.attempts,
                        schema.deliveries.c.created_at,
                        schema.deliveries.c.next_attempt_at,
                        schema.events.c.envelope,
                    )
                    .join(schema.events,
                          schema.events.c.sequence == schema.deliveries.c.event_sequence)
                    .where(self._deliveries(name), schema.deliveries.c.state == PENDING)
                    .order_by(schema.deliveries.c.event_sequence)
                    .limit(1)
                ).first()
            # The head of the destination's queue holds the rest back until it is
            # delivered or abandoned, so the destination receives events in order.
            if due is None or schema.from_stored(due.next_attempt_at) > now:
                return
            envelope = Envelope.from_json(due.envelope)
            attempts = due.attempts + 1
            try:
                destination.deliver(envelope)
            except ParkDestination as parked:
                with self._sessions.begin() as session:
                    self._attempted(session, name, due.event_sequence, attempts, now,
                                    last_error=str(parked))
                    park_destination(session, self.name, name, str(parked), now)
                report.parked.append(name)
                return
            except Exception as error:  # a destination's failure is any exception
                last_error = f"{type(error).__name__}: {error}"
                age = now - schema.from_stored(due.created_at)
                with self._sessions.begin() as session:
                    if self._retry.max_age is not None and age >= self._retry.max_age:
                        self._attempted(session, name, due.event_sequence, attempts, now,
                                        last_error=last_error, state=ABANDONED)
                        self._finally.abandoned(consumer=self.name, destination=name,
                                                envelope=envelope, last_error=last_error)
                        report.abandoned += 1
                        continue
                    self._attempted(session, name, due.event_sequence, attempts, now,
                                    last_error=last_error,
                                    next_attempt_at=now + self._retry.delay(attempts))
                report.failed += 1
                return
            with self._sessions.begin() as session:
                self._attempted(session, name, due.event_sequence, attempts, now,
                                state=DELIVERED)
            report.delivered += 1

    def _attempted(
        self,
        session: Session,
        destination: str,
        sequence: int,
        attempts: int,
        now: datetime,
        *,
        last_error: str | None = None,
        state: str = PENDING,
        next_attempt_at: datetime | None = None,
    ) -> None:
        values: dict[str, object] = {
            "attempts": attempts,
            "last_attempted_at": schema.to_stored(now),
            "state": state,
        }
        if last_error is not None:
            values["last_error"] = last_error
        if state != PENDING:
            values["finished_at"] = schema.to_stored(now)
        if next_attempt_at is not None:
            values["next_attempt_at"] = schema.to_stored(next_attempt_at)
        session.execute(
            update(schema.deliveries)
            .where(self._deliveries(destination),
                   schema.deliveries.c.event_sequence == sequence)
            .values(**values)
        )

    def _position(self, session: Session, now: datetime) -> int:
        """The consumer's position, registering it at the last event if it is new."""
        position = session.execute(
            select(schema.consumers.c.position).where(schema.consumers.c.name == self.name)
        ).scalar_one_or_none()
        if position is not None:
            return int(position)
        latest: int | None = session.execute(select(func.max(schema.events.c.sequence))).scalar_one()
        position = int(latest or 0)
        session.execute(
            insert(schema.consumers).values(name=self.name, position=position, created_at=now)
        )
        return position

    def _retire(self, session: Session, name: str, now: datetime) -> int:
        pending = session.execute(
            select(schema.deliveries.c.event_sequence, schema.deliveries.c.last_error,
                   schema.events.c.envelope)
            .join(schema.events, schema.events.c.sequence == schema.deliveries.c.event_sequence)
            .where(self._deliveries(name), schema.deliveries.c.state == PENDING)
            .order_by(schema.deliveries.c.event_sequence)
        ).all()
        session.execute(
            update(schema.deliveries)
            .where(self._deliveries(name), schema.deliveries.c.state == PENDING)
            .values(state=ABANDONED, finished_at=now,
                    last_error=func.coalesce(schema.deliveries.c.last_error, RETIRED_ERROR))
        )
        session.execute(
            update(schema.destinations)
            .where(self._destination(name))
            .values(state=RETIRED, state_changed_at=now, state_reason=RETIRED_ERROR)
        )
        # Handed over inside the transaction: if the finally sink fails, the
        # retirement rolls back and is attempted again, so no event is lost.
        for row in pending:
            self._finally.abandoned(
                consumer=self.name, destination=name,
                envelope=Envelope.from_json(row.envelope),
                last_error=row.last_error or RETIRED_ERROR,
            )
        return len(pending)

    def _destination(self, name: str) -> ColumnElement[bool]:
        return and_(schema.destinations.c.consumer == self.name, schema.destinations.c.name == name)

    def _deliveries(self, destination: str) -> ColumnElement[bool]:
        return and_(schema.deliveries.c.consumer == self.name,
                    schema.deliveries.c.destination == destination)


class UnknownDestination(LookupError):
    """No destination of that name is registered for the consumer."""


def park_destination(session: Session, consumer: str, destination: str, reason: str,
                     now: datetime) -> None:
    """Park `consumer`'s `destination` in `session`'s transaction."""
    result: CursorResult[tuple[()]] = session.execute(  # type: ignore[assignment]
        update(schema.destinations)
        .where(schema.destinations.c.consumer == consumer,
               schema.destinations.c.name == destination,
               schema.destinations.c.state != RETIRED)
        .values(state=PARKED, state_changed_at=schema.to_stored(now), state_reason=reason)
    )
    if result.rowcount == 0:
        raise UnknownDestination(f"consumer {consumer} has no destination {destination}")


def resume_destination(session: Session, consumer: str, destination: str, now: datetime) -> None:
    """Resume `consumer`'s parked `destination` in `session`'s transaction: its
    pending deliveries become due at once. Resuming an active destination changes
    nothing."""
    stored = schema.to_stored(now)
    result: CursorResult[tuple[()]] = session.execute(  # type: ignore[assignment]
        update(schema.destinations)
        .where(schema.destinations.c.consumer == consumer,
               schema.destinations.c.name == destination,
               schema.destinations.c.state == PARKED)
        .values(state=ACTIVE, state_changed_at=stored, state_reason=None)
    )
    if result.rowcount:
        session.execute(
            update(schema.deliveries)
            .where(schema.deliveries.c.consumer == consumer,
                   schema.deliveries.c.destination == destination,
                   schema.deliveries.c.state == PENDING)
            .values(next_attempt_at=stored)
        )
